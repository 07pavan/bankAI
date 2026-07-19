"""
LangChain @tool-decorated functions for the BankAI LangGraph agent.

These tools are thin, safe wrappers around the existing service layer.
They do NOT duplicate business logic — every operation delegates to
form_service, submission_service, or kyc_service.

Security guarantees:
  - All string outputs pass through ``redact_pii`` before being returned
    to the LLM, ensuring no Aadhaar / PAN / phone / email reaches the API.
  - Field values are NEVER included in tool return strings.
  - Each tool uses get_db() (Firestore client) — no SQLAlchemy sessions.

Every function returns a plain ``str`` summary that the LLM can reason
over without needing structured ORM objects or Pydantic models.
"""

from langchain_core.tools import tool

from app.database import get_db
from app.services import form_service, submission_service
from app.services import kyc_service as kyc_svc
from app.core.llm_redaction import redact_pii
from app.core.logging import get_logger

logger = get_logger()


# ---------------------------------------------------------------------------
# Tool 1 — Available forms
# ---------------------------------------------------------------------------

@tool
def get_available_forms(user_id: str) -> str:
    """Retrieve all active banking application forms available for the user.

    Use this tool when the user asks what forms or services are available,
    or when you need to present the list of applications they can start.

    Args:
        user_id: The authenticated user's ID (Firestore document ID string).

    Returns:
        A newline-separated list of available forms with their IDs,
        names, and descriptions. Returns a message if no forms are found.
    """
    logger.info(f"Tool[get_available_forms] called for user_id={user_id}")

    try:
        # Fetch all active banks from Firestore
        banks = form_service.get_active_banks()

        if not banks:
            return "No active banks found. There are no forms available at this time."

        lines: list[str] = []
        for bank in banks:
            try:
                forms = form_service.get_active_forms(bank["id"])
            except (ValueError, Exception):
                continue  # Bank became inactive between queries

            for f in forms:
                desc = f.get("description") or "No description"
                lines.append(
                    f"• Form ID {f['id']}: {f['name']} (Bank: {bank['name']}) — {desc}"
                )

        if not lines:
            return "No application forms are currently available."

        header = f"Available forms ({len(lines)} total):\n"
        result = header + "\n".join(lines)
        return redact_pii(result)

    except Exception as exc:
        logger.error(f"Tool[get_available_forms] failed: {exc}")
        return f"Could not retrieve forms: {str(exc)}"


# ---------------------------------------------------------------------------
# Tool 2 — KYC status
# ---------------------------------------------------------------------------

@tool
def get_kyc_status(user_id: str) -> str:
    """Check the KYC verification status for a user.

    Use this tool when the user asks about their KYC status, identity
    verification, or whether their Aadhaar/PAN has been verified.

    Args:
        user_id: The authenticated user's ID (Firestore document ID string).

    Returns:
        A summary of the user's KYC status. All PII is masked before returning.
    """
    logger.info(f"Tool[get_kyc_status] called for user_id={user_id}")

    try:
        db = get_db()
        from app.models import COLL_KYC_SUBMISSIONS

        # Get the latest KYC submission for this user from Firestore (sorted in memory to avoid index requirement)
        kyc_docs = (
            db.collection(COLL_KYC_SUBMISSIONS)
            .where("user_id", "==", user_id)
            .stream()
        )
        kyc_docs_list = list(kyc_docs)
        kyc_doc = None
        if kyc_docs_list:
            from datetime import datetime, timezone
            kyc_docs_list.sort(key=lambda d: d.to_dict().get("created_at") or datetime.min.replace(tzinfo=timezone.utc), reverse=True)
            kyc_doc = kyc_docs_list[0]

        if not kyc_doc:
            return "No KYC submission found for this user."

        kyc_data = {"id": kyc_doc.id, **kyc_doc.to_dict()}
        status = kyc_data.get("status", "unknown")
        created_at = kyc_data.get("created_at", "unknown")

        result = (
            f"KYC Status: {status}\n"
            f"Has Selfie: {'Yes' if kyc_data.get('selfie_path') else 'No'}\n"
            f"Submitted: {created_at}"
        )
        return redact_pii(result)

    except Exception as exc:
        logger.error(f"Tool[get_kyc_status] failed: {exc}")
        return f"Could not retrieve KYC status: {str(exc)}"


# ---------------------------------------------------------------------------
# Tool 3 — Answer a field
# ---------------------------------------------------------------------------

@tool
def answer_field(submission_id: str, field_key: str, value: str) -> str:
    """Save the user's answer for a specific form field.

    Use this tool after you have parsed and understood the user's response
    to a form question.  The backend enforces all validation rules — if the
    value is invalid, the tool returns the validation error message.

    IMPORTANT: After a successful save, call ``get_next_field`` to find
    the next unanswered field and ask the user about it.

    Args:
        submission_id: The active submission's ID (Firestore document ID string).
        field_key: The unique key of the field being answered
                   (e.g. 'full_name', 'dob', 'account_type').
        value: The user's answer as a string.  For select/radio fields
               pass the option *value* (not the label).

    Returns:
        A confirmation message on success, or a validation error message
        if the value was rejected by backend rules.
    """
    logger.info(
        f"Tool[answer_field] called: submission={submission_id} "
        f"field_key='{field_key}' (value redacted)"
    )

    try:
        submission_service.save_field_value(
            submission_id=submission_id,
            field_key=field_key,
            value=value,
        )
        # Advance the cursor to the next field
        submission_service.move_to_next_field(submission_id)

        return redact_pii(
            f"Field '{field_key}' saved successfully for submission {submission_id}."
        )
    except Exception as exc:
        detail = getattr(exc, "detail", str(exc))
        logger.warning(
            f"Tool[answer_field] validation error: submission={submission_id} "
            f"field_key='{field_key}' — {detail}"
        )
        return redact_pii(f"Error saving field '{field_key}': {detail}")


# ---------------------------------------------------------------------------
# Tool 4 — Current submission state
# ---------------------------------------------------------------------------

@tool
def get_current_submission_state(submission_id: str) -> str:
    """Get the full current state of a submission.

    Use this tool to understand where the user is in the form-filling
    process — how many fields are done, the overall status, and the
    conversation state.  Also use it in REVIEW state to read back the
    answers to the user.

    Args:
        submission_id: The submission's ID (Firestore document ID string).

    Returns:
        A summary including status, conversation state, current field index,
        total fields, and a list of already-answered field keys with their
        values for review (values are shown so the LLM can read them back).
    """
    logger.info(f"Tool[get_current_submission_state] called: submission={submission_id}")

    try:
        db = get_db()
        from app.models import COLL_SUBMISSIONS, COLL_SUBMISSION_DATA

        sub_doc = db.collection(COLL_SUBMISSIONS).document(submission_id).get()
        if not sub_doc.exists:
            return f"Submission {submission_id} not found."

        sub = {"id": sub_doc.id, **sub_doc.to_dict()}

        # Get answered fields from sub-collection
        data_docs = (
            db.collection(COLL_SUBMISSIONS)
            .document(submission_id)
            .collection(COLL_SUBMISSION_DATA)
            .stream()
        )
        answered = {d.id: d.to_dict().get("value", "") for d in data_docs}

        # Get total field count
        form_id = sub.get("form_id", "")
        fields = form_service.get_ordered_active_fields(form_id) if form_id else []
        total = len(fields)

        # Build answered fields summary for review readback
        answered_summary = ""
        for field in fields:
            fk = field.get("field_key", "")
            if fk in answered:
                label = field.get("label", fk)
                answered_summary += f"\n  • {label}: {redact_pii(str(answered[fk]))}"

        result = (
            f"Submission {submission_id}:\n"
            f"  Status: {sub.get('status')}\n"
            f"  Conversation state: {sub.get('conversation_state')}\n"
            f"  Progress: {sub.get('current_field_index', 0)}/{total} fields\n"
            f"  Answered fields:{answered_summary if answered_summary else ' none'}"
        )
        return result

    except Exception as exc:
        logger.error(f"Tool[get_current_submission_state] failed: {exc}")
        return f"Could not retrieve submission state: {str(exc)}"


# ---------------------------------------------------------------------------
# Tool 5 — Next field
# ---------------------------------------------------------------------------

@tool
def get_next_field(submission_id: str) -> str:
    """Get the next unanswered field that the user should fill in.

    Use this tool after saving a field answer or when resuming a
    partially-completed form.  The response includes the field's label,
    type, and any validation constraints so you can ask the user a
    well-formed natural-language question.

    Args:
        submission_id: The submission's ID (Firestore document ID string).

    Returns:
        A description of the next field including its key, label, type,
        whether it is required, and available options (for select/radio).
        Returns a completion message if all fields have been answered.
    """
    logger.info(f"Tool[get_next_field] called: submission={submission_id}")

    try:
        field = submission_service.get_current_field(submission_id)

        if field is None:
            return (
                f"All fields for submission {submission_id} have been answered. "
                "The form is ready for review."
            )

        # Build a rich description for the LLM to formulate a question
        lines = [
            f"Next field for submission {submission_id}:",
            f"  field_key: {field.get('field_key')}",
            f"  label: {field.get('label')}",
            f"  type: {field.get('field_type')}",
            f"  required: {field.get('required', True)}",
        ]

        # Validation hints
        rule = field.get("validation_rule") or {}
        if rule:
            hints = []
            if "pattern" in rule:
                hints.append(f"pattern={rule['pattern']}")
            if "min" in rule:
                hints.append(f"min={rule['min']}")
            if "max" in rule:
                hints.append(f"max={rule['max']}")
            if "min_length" in rule:
                hints.append(f"min_length={rule['min_length']}")
            if "max_length" in rule:
                hints.append(f"max_length={rule['max_length']}")
            if hints:
                lines.append(f"  validation: {', '.join(hints)}")

        # Options for select / radio / checkbox
        options = field.get("options")
        if options:
            if isinstance(options[0], dict):
                opts = " | ".join(
                    f"{opt.get('value', opt)} ({opt.get('label', opt.get('value', opt))})"
                    for opt in options
                )
            else:
                opts = " | ".join(str(o) for o in options)
            lines.append(f"  options: {opts}")

        result = "\n".join(lines)
        return redact_pii(result)

    except Exception as exc:
        logger.error(f"Tool[get_next_field] failed: {exc}")
        return f"Could not retrieve next field: {str(exc)}"


# ---------------------------------------------------------------------------
# All tools — convenient list for LangGraph node binding
# ---------------------------------------------------------------------------

ALL_TOOLS = [
    get_available_forms,
    get_kyc_status,
    answer_field,
    get_current_submission_state,
    get_next_field,
]
