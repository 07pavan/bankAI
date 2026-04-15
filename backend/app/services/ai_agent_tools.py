"""
LangChain @tool-decorated functions for the BankAI LangGraph agent.

These tools are thin, safe wrappers around the existing service layer.
They do NOT duplicate business logic — every operation delegates to
form_service, submission_service, or kyc_service.

Security guarantees:
  - All string outputs pass through ``redact_pii`` before being returned
    to the LLM, ensuring no Aadhaar / PAN / phone / email reaches the API.
  - Field values are NEVER included in tool return strings.
  - Each tool acquires and releases its own DB session via ``SessionLocal``.

Every function returns a plain ``str`` summary that the LLM can reason
over without needing structured ORM objects or Pydantic models.
"""

from langchain_core.tools import tool

from app import database as app_db
from app.services import form_service, submission_service
from app.services import kyc_service as kyc_svc
from app.core.llm_redaction import redact_pii
from app.core.logging import get_logger

logger = get_logger()


# ---------------------------------------------------------------------------
# Helper — scoped DB session context manager
# ---------------------------------------------------------------------------

class _DBSession:
    """
    Lightweight context manager for a scoped DB session.
    Mirrors the ``get_db`` FastAPI dependency, but usable outside of
    a request lifecycle (i.e. inside a LangGraph node / tool call).
    """

    def __enter__(self):
        self.db = app_db.SessionLocal()
        return self.db

    def __exit__(self, exc_type, exc_val, exc_tb):
        if exc_type:
            self.db.rollback()
            logger.error(f"DB session error in agent tool: {exc_val}")
        self.db.close()
        return False  # Do not suppress exceptions


# ---------------------------------------------------------------------------
# Tool 1 — Available forms
# ---------------------------------------------------------------------------

@tool
def get_available_forms(user_id: int) -> str:
    """Retrieve all active banking application forms available for the user.

    Use this tool when the user asks what forms or services are available,
    or when you need to present the list of applications they can start.

    Args:
        user_id: The authenticated user's ID.

    Returns:
        A newline-separated list of available forms with their IDs,
        names, and descriptions. Returns a message if no forms are found.
    """
    logger.info(f"Tool[get_available_forms] called for user_id={user_id}")

    with _DBSession() as db:
        # Fetch all active banks, then all their active forms
        banks = form_service.get_active_banks(db)

        if not banks:
            return "No active banks found. There are no forms available at this time."

        lines: list[str] = []
        for bank in banks:
            try:
                forms = form_service.get_active_forms(bank.id, db)
            except ValueError:
                continue  # Bank became inactive between queries

            for f in forms:
                desc = f.description or "No description"
                lines.append(
                    f"• Form ID {f.id}: {f.name} (Bank: {bank.name}) — {desc}"
                )

        if not lines:
            return "No application forms are currently available."

        header = f"Available forms ({len(lines)} total):\n"
        result = header + "\n".join(lines)
        return redact_pii(result)


# ---------------------------------------------------------------------------
# Tool 2 — KYC status
# ---------------------------------------------------------------------------

@tool
def get_kyc_status(user_id: int) -> str:
    """Check the KYC verification status for a user.

    Use this tool when the user asks about their KYC status, identity
    verification, or whether their Aadhaar/PAN has been verified.

    Args:
        user_id: The authenticated user's ID.

    Returns:
        A summary of the user's KYC status including masked Aadhaar/PAN
        and verification state. All PII is masked before returning.
    """
    logger.info(f"Tool[get_kyc_status] called for user_id={user_id}")

    with _DBSession() as db:
        from app.models import KYCSubmission

        # Get the latest KYC submission for this user
        submission = (
            db.query(KYCSubmission)
            .filter(KYCSubmission.user_id == user_id)
            .order_by(KYCSubmission.created_at.desc())
            .first()
        )

        if not submission:
            return "No KYC submission found for this user."

        kyc_data = kyc_svc.get_kyc_status(submission.id, db)
        if not kyc_data:
            return "KYC submission record could not be retrieved."

        result = (
            f"KYC Status: {kyc_data['status']}\n"
            f"Aadhaar: {kyc_data['aadhaar_masked']}\n"
            f"PAN: {kyc_data['pan_masked']}\n"
            f"Selfie on file: {'Yes' if kyc_data['has_selfie'] else 'No'}\n"
            f"Submitted: {kyc_data['created_at']}"
        )
        # redact_pii is a safety net — kyc_service already returns masked data
        return redact_pii(result)


# ---------------------------------------------------------------------------
# Tool 3 — Answer a field
# ---------------------------------------------------------------------------

@tool
def answer_field(submission_id: int, field_key: str, value: str) -> str:
    """Save the user's answer for a specific form field.

    Use this tool after you have parsed and understood the user's response
    to a form question.  The backend enforces all validation rules — if the
    value is invalid, the tool returns the validation error message.

    IMPORTANT: After a successful save, call ``get_next_field`` to find
    the next unanswered field and ask the user about it.

    Args:
        submission_id: The active submission's ID.
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

    # Redact PII from the value before it reaches the LLM return string
    # (the raw value is still passed to the service for storage)
    with _DBSession() as db:
        try:
            submission_service.save_field_value(
                submission_id=submission_id,
                field_key=field_key,
                value=value,
                db=db,
            )
            # Advance the cursor to the next field
            submission_service.move_to_next_field(submission_id, db)

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
def get_current_submission_state(submission_id: int) -> str:
    """Get the full current state of a submission.

    Use this tool to understand where the user is in the form-filling
    process — how many fields are done, the overall status, and the
    conversation state.

    Args:
        submission_id: The submission's ID.

    Returns:
        A summary including status (draft/completed), conversation state,
        current field index, total fields, and a list of already-answered
        field keys (values are NOT included for security).
    """
    logger.info(f"Tool[get_current_submission_state] called: submission={submission_id}")

    with _DBSession() as db:
        from app.models import Submission

        sub = db.query(Submission).filter(Submission.id == submission_id).first()
        if not sub:
            return f"Submission {submission_id} not found."

        fields = form_service.get_ordered_active_fields(sub.form_id, db)
        total = len(fields)
        answered_keys = {d.field_key for d in sub.data}

        # Build the answered-fields list (keys only, never values)
        answered_list = ", ".join(sorted(answered_keys)) if answered_keys else "none"

        result = (
            f"Submission {sub.id}:\n"
            f"  Status: {sub.status}\n"
            f"  Conversation state: {sub.conversation_state}\n"
            f"  Progress: {sub.current_field_index}/{total} fields\n"
            f"  Answered fields: {answered_list}"
        )
        return redact_pii(result)


# ---------------------------------------------------------------------------
# Tool 5 — Next field
# ---------------------------------------------------------------------------

@tool
def get_next_field(submission_id: int) -> str:
    """Get the next unanswered field that the user should fill in.

    Use this tool after saving a field answer or when resuming a
    partially-completed form.  The response includes the field's label,
    type, and any validation constraints so you can ask the user a
    well-formed natural-language question.

    Args:
        submission_id: The submission's ID.

    Returns:
        A description of the next field including its key, label, type,
        whether it is required, and available options (for select/radio).
        Returns a completion message if all fields have been answered.
    """
    logger.info(f"Tool[get_next_field] called: submission={submission_id}")

    with _DBSession() as db:
        field = submission_service.get_current_field(submission_id, db)

        if field is None:
            return (
                f"All fields for submission {submission_id} have been answered. "
                "The form is ready for review."
            )

        # Build a rich description for the LLM to formulate a question
        lines = [
            f"Next field for submission {submission_id}:",
            f"  field_key: {field.field_key}",
            f"  label: {field.label}",
            f"  type: {field.field_type}",
            f"  required: {field.required}",
        ]

        # Validation hints
        rule = field.validation_rule or {}
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
        if field.options:
            opts = " | ".join(
                f"{opt['value']} ({opt['label']})" for opt in field.options
            )
            lines.append(f"  options: {opts}")

        result = "\n".join(lines)
        return redact_pii(result)


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
