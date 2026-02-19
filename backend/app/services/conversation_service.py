"""
ConversationService — state-machine-driven voice/text agent for form filling.

State Machine (backend is sole authority):
  WELCOME → SELECT_APPLICATION → FILLING_FORM → REVIEW → COMPLETE

Pre-submission Chat Mode (CHAT):
  Stateless — never reads/writes any Submission record.
  Handles greetings, help queries, and form selection.
  All form transitions remain deterministic and backend-authoritative.

AI responsibilities (strictly limited):
  ✓ Map natural language → structured field value
  ✓ Generate next question from field metadata
  ✓ Detect confirmation intent in REVIEW state
  ✓ Classify chat intent from keyword sets (no free LLM)

Backend responsibilities:
  ✓ Decide which field is next (current_field_index)
  ✓ Enforce all validation rules
  ✓ Persist every answer
  ✓ Control all state transitions
  ✗ AI must NOT invent fields, skip validation, or modify form structure
"""

import re
from dataclasses import dataclass, field
from typing import Optional
from sqlalchemy.orm import Session
from fastapi import HTTPException, status

from app.models import Form, FormField, SubmissionStatus, ConversationState, Submission
from app.services import form_service, submission_service
from app.schemas import (
    ConversationStartResponse,
    ConversationTurnResponse,
    FormListItem,
    SubmissionProgress,
    FormFieldOut,
)
from app.core.logging import get_logger

logger = get_logger()


# ---------------------------------------------------------------------------
# Chat-mode intent keyword sets
# ✗ AI must NOT add free-form responses — every reply comes from the maps below
# ---------------------------------------------------------------------------

SMALL_TALK_TRIGGERS: set[str] = {
    "hello", "hi", "hey", "howdy", "greetings",
    "good morning", "good afternoon", "good evening", "good day",
    "how are you", "how are you doing", "what's up", "whats up",
    "thanks", "thank you", "thank you very much", "cheers",
    "bye", "goodbye", "see you", "take care",
    "who are you", "what are you", "are you a bot", "are you human",
}

HELP_TRIGGERS: set[str] = {
    "help", "what can you do", "services", "available",
    "what do you offer", "options", "features", "assist", "support",
    "show me", "list", "menu", "what forms", "which forms",
    "what applications", "what can i apply for",
}

# Canned replies keyed by intent — no free generation allowed
_SMALL_TALK_REPLY = (
    "Hello! 👋 I'm the BankAI Assistant. I'm here to help you fill banking "
    "application forms using voice or text. Say 'help' to see what's available, "
    "or simply tell me which form you'd like to start!"
)

_HELP_REPLY_TEMPLATE = (
    "I can help you with the following banking applications:\n\n{form_list}\n\n"
    "Just say the name of the service you'd like — for example, "
    "'I want to open an account' or 'Aadhaar seeding'."
)

_OUT_OF_SCOPE_REPLY = (
    "I'm specialised in helping you with BankAI banking forms and applications. "
    "I'm unable to help with that question. Please ask about available forms, "
    "or say 'help' to see what I can do for you."
)


@dataclass
class ChatTurnResponse:
    """Response from handle_chat_turn — purely for the /chat endpoint."""
    message: str
    intent: str  # small_talk | help | form_selection | out_of_scope
    available_forms: list = field(default_factory=list)


# ---------------------------------------------------------------------------
# Intent keyword map  (form_code → trigger keywords)
# Extend this dict to add new form types — no code changes elsewhere needed.
# ---------------------------------------------------------------------------

INTENT_KEYWORDS: dict[str, list[str]] = {
    "account_opening": [
        "account", "open account", "new account", "savings", "saving",
        "bank account", "open a", "account opening",
    ],
    "aadhaar_seeding": [
        "aadhaar", "aadhar", "link aadhaar", "seed aadhaar", "aadhaar seeding",
        "link my aadhaar", "aadhaar link",
    ],
    "cheque_book_request": [
        "cheque", "check book", "chequebook", "cheque book", "checkbook",
        "new cheque", "request cheque",
    ],
}

# Words that indicate user confirmation in REVIEW state
CONFIRMATION_WORDS = {"yes", "correct", "confirm", "ok", "okay", "right", "proceed", "submit", "done"}
REJECTION_WORDS = {"no", "wrong", "incorrect", "change", "edit", "modify", "back"}


# ---------------------------------------------------------------------------
# Public API — state dispatcher
# ---------------------------------------------------------------------------

def handle_conversation_turn(
    submission_id: int,
    user_id: int,
    message: str,
    db: Session,
) -> ConversationTurnResponse:
    """
    Main entry point for POST /api/v1/conversation/next.

    Dispatches to the correct state handler based on submission.conversation_state.
    The backend is the single source of truth for which state we are in.

    Args:
        submission_id: Active submission ID
        user_id: Authenticated user's ID
        message: Raw voice transcript from the frontend
        db: Database session

    Returns:
        ConversationTurnResponse with next_question (as agent_message), field_key, is_complete
    """
    sub = submission_service.get_submission(submission_id, user_id, db)
    state = sub.conversation_state

    logger.info(
        f"Conversation turn: submission={submission_id} state={state} "
        f"field_index={sub.current_field_index}"
    )

    if state == ConversationState.FILLING_FORM:
        return _handle_filling_form(sub, message, user_id, db)
    elif state == ConversationState.REVIEW:
        return _handle_review(sub, message, user_id, db)
    elif state == ConversationState.COMPLETE:
        return ConversationTurnResponse(
            submission_id=submission_id,
            agent_message="This application has already been submitted. Thank you!",
            is_complete=True,
        )
    else:
        # Fallback — treat unknown state as FILLING_FORM
        logger.warning(f"Unknown conversation state '{state}' for submission {submission_id}, defaulting to FILLING_FORM")
        return _handle_filling_form(sub, message, user_id, db)


# Legacy alias used by the old conversation endpoint — keeps backward compat
def handle_user_response(
    submission_id: int,
    user_id: int,
    text_input: str,
    db: Session,
) -> ConversationTurnResponse:
    return handle_conversation_turn(submission_id, user_id, text_input, db)


def start_conversation(user_id: int, bank_id: int, db: Session) -> ConversationStartResponse:
    """
    Begin a conversation session — returns available forms for the bank.
    Used by the WELCOME state before a submission exists.
    """
    try:
        forms = form_service.get_active_forms(bank_id, db)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))

    form_items = [FormListItem.model_validate(f) for f in forms]

    if not form_items:
        message = "Welcome to BankAI! No application forms are available right now. Please try again later."
    else:
        names = ", ".join(f.name for f in form_items)
        message = (
            f"Welcome to BankAI! I can help you apply for: {names}. "
            "Which one would you like to start?"
        )

    logger.info(f"Started conversation for user={user_id} bank={bank_id}")
    return ConversationStartResponse(message=message, available_forms=form_items)


def detect_application_intent(text_input: str, bank_id: int, db: Session) -> Optional[Form]:
    """
    Map a free-text utterance to a Form using keyword matching.
    Returns None if no intent is detected.
    Extend INTENT_KEYWORDS to support new form types without code changes.
    """
    normalised = text_input.lower().strip()

    for form_code, keywords in INTENT_KEYWORDS.items():
        for kw in keywords:
            if kw in normalised:
                form = (
                    db.query(Form)
                    .filter(
                        Form.bank_id == bank_id,
                        Form.code == form_code,
                        Form.is_active == True,
                    )
                    .first()
                )
                if form:
                    logger.info(f"Intent detected: form_code='{form_code}' from input (redacted)")
                    return form

    logger.info("No application intent detected from user input")
    return None


def handle_chat_turn(user_id: int, message: str, db: Session) -> "ChatTurnResponse":
    """
    Stateless pre-submission chat handler — does NOT touch any Submission record.

    Intent priority (descending):
      1. small_talk  — greetings, courtesies, "who are you"
      2. help        — queries about available services / forms
      3. form_selection — matches a known form via INTENT_KEYWORDS
      4. out_of_scope — anything else; politely redirected

    The function is READ-ONLY on the database (queries Bank/Form, never writes).
    All response texts are drawn from pre-defined constants — no free LLM output.

    Args:
        user_id: Authenticated user ID (for logging only)
        message:  Raw text/voice transcript from the frontend
        db:       Database session

    Returns:
        ChatTurnResponse with intent tag and canned reply
    """
    normalised = message.lower().strip()
    logger.info(f"Chat turn: user={user_id} (message content redacted)")

    # ── 1. Small-talk ─────────────────────────────────────────────────────────
    # Check exact match OR substring match for multi-word triggers
    if any(trigger in normalised for trigger in SMALL_TALK_TRIGGERS):
        logger.info(f"Chat intent=small_talk user={user_id}")
        return ChatTurnResponse(message=_SMALL_TALK_REPLY, intent="small_talk")

    # ── 2. Help / service listing ──────────────────────────────────────────────
    if any(trigger in normalised for trigger in HELP_TRIGGERS):
        forms = _get_all_active_forms(db)
        if forms:
            form_list = "\n".join(f"• {f.name}" for f in forms)
            reply = _HELP_REPLY_TEMPLATE.format(form_list=form_list)
        else:
            reply = "No banking forms are available right now. Please try again later."
        logger.info(f"Chat intent=help user={user_id}")
        return ChatTurnResponse(
            message=reply,
            intent="help",
            available_forms=[FormListItem.model_validate(f) for f in forms],
        )

    # ── 3. Form-selection intent ───────────────────────────────────────────────
    # Reuse existing keyword matching — find the first active bank's forms
    forms = _get_all_active_forms(db)
    matched_form = _detect_form_intent_from_all_banks(normalised, db)
    if matched_form:
        all_forms = _get_active_forms_for_bank(matched_form.bank_id, db)
        reply = (
            f"Great choice! I can help you with the **{matched_form.name}** application. "
            "Click 'Start' to begin — I'll guide you through each field with voice or text."
        )
        logger.info(f"Chat intent=form_selection user={user_id}")
        return ChatTurnResponse(
            message=reply,
            intent="form_selection",
            available_forms=[FormListItem.model_validate(f) for f in all_forms],
        )

    # ── 4. Out-of-scope guard ──────────────────────────────────────────────────
    logger.info(f"Chat intent=out_of_scope user={user_id}")
    return ChatTurnResponse(message=_OUT_OF_SCOPE_REPLY, intent="out_of_scope")


# ---------------------------------------------------------------------------
# Chat-mode DB helpers (read-only)
# ---------------------------------------------------------------------------

def _get_all_active_forms(db: Session) -> list:
    """Return all active forms across all active banks."""
    from app.models import Bank as BankModel
    return (
        db.query(Form)
        .join(BankModel, Form.bank_id == BankModel.id)
        .filter(Form.is_active == True, BankModel.is_active == True)
        .order_by(Form.id)
        .all()
    )


def _get_active_forms_for_bank(bank_id: int, db: Session) -> list:
    """Return all active forms for a specific bank."""
    return (
        db.query(Form)
        .filter(Form.bank_id == bank_id, Form.is_active == True)
        .order_by(Form.id)
        .all()
    )


def _detect_form_intent_from_all_banks(normalised: str, db: Session) -> Optional[Form]:
    """
    Run INTENT_KEYWORDS matching across all active banks.
    Returns the first matching active Form, or None.
    """
    from app.models import Bank as BankModel
    active_banks = db.query(BankModel).filter(BankModel.is_active == True).all()
    for bank in active_banks:
        for form_code, keywords in INTENT_KEYWORDS.items():
            for kw in keywords:
                if kw in normalised:
                    form = (
                        db.query(Form)
                        .filter(
                            Form.bank_id == bank.id,
                            Form.code == form_code,
                            Form.is_active == True,
                        )
                        .first()
                    )
                    if form:
                        return form
    return None




# ---------------------------------------------------------------------------
# State handlers (private)
# ---------------------------------------------------------------------------

def _handle_filling_form(
    sub: Submission,
    message: str,
    user_id: int,
    db: Session,
) -> ConversationTurnResponse:
    """
    FILLING_FORM state: validate + save the answer, advance to next field.
    When all fields are answered, transition to REVIEW state.
    """
    current_field = submission_service.get_current_field(sub.id, db)

    if current_field is None:
        # All fields answered — move to REVIEW
        return _transition_to_review(sub, db)

    # Parse and validate the answer (backend enforces all rules)
    parsed_value = _parse_and_validate(message, current_field)

    # Persist the answer (field_key logged, value never logged)
    submission_service.save_field_value(
        submission_id=sub.id,
        field_key=current_field.field_key,
        value=parsed_value,
        db=db,
    )
    logger.info(
        f"Field saved: submission={sub.id} field_key='{current_field.field_key}' "
        f"(value redacted for security)"
    )

    # Advance the cursor
    updated_sub = submission_service.move_to_next_field(sub.id, db)

    # Check if we just answered the last field
    next_field = submission_service.get_current_field(sub.id, db)
    if next_field is None:
        return _transition_to_review(updated_sub, db)

    agent_message = _build_field_prompt(
        confirmed_label=current_field.label,
        next_field=next_field,
    )

    return ConversationTurnResponse(
        submission_id=sub.id,
        field_key=current_field.field_key,
        agent_message=agent_message,
        is_complete=False,
        progress=_build_progress(updated_sub, db),
    )


def _handle_review(
    sub: Submission,
    message: str,
    user_id: int,
    db: Session,
) -> ConversationTurnResponse:
    """
    REVIEW state: read back all answers and wait for user confirmation.
    On confirmation → COMPLETE. On rejection → back to FILLING_FORM at index 0.
    """
    normalised = message.lower().strip()
    words = set(normalised.split())

    if words & CONFIRMATION_WORDS:
        # User confirmed — complete the submission
        return _transition_to_complete(sub, user_id, db)

    if words & REJECTION_WORDS:
        # User wants to change something — restart from field 0
        sub.conversation_state = ConversationState.FILLING_FORM
        sub.current_field_index = 0
        db.commit()
        db.refresh(sub)
        logger.info(f"Submission {sub.id} returned to FILLING_FORM from REVIEW (user requested changes)")

        first_field = submission_service.get_current_field(sub.id, db)
        prompt = f"No problem! Let's go through the form again. {_field_question(first_field)}" if first_field else "Let's start over."
        return ConversationTurnResponse(
            submission_id=sub.id,
            agent_message=prompt,
            is_complete=False,
            progress=_build_progress(sub, db),
        )

    # Ambiguous — re-read the summary and ask again
    summary = _build_review_summary(sub, db)
    return ConversationTurnResponse(
        submission_id=sub.id,
        agent_message=(
            f"{summary}\n\nPlease say 'confirm' to submit or 'change' to edit your answers."
        ),
        is_complete=False,
        progress=_build_progress(sub, db),
    )


def _transition_to_review(sub: Submission, db: Session) -> ConversationTurnResponse:
    """Move submission to REVIEW state and return the review summary."""
    sub.conversation_state = ConversationState.REVIEW
    db.commit()
    db.refresh(sub)
    logger.info(f"Submission {sub.id} transitioned to REVIEW state")

    summary = _build_review_summary(sub, db)
    return ConversationTurnResponse(
        submission_id=sub.id,
        agent_message=(
            f"Great! Here's a summary of your application:\n\n{summary}\n\n"
            "Say 'confirm' to submit or 'change' to edit."
        ),
        is_complete=False,
        progress=_build_progress(sub, db),
    )


def _transition_to_complete(sub: Submission, user_id: int, db: Session) -> ConversationTurnResponse:
    """Validate required fields and mark submission as COMPLETE."""
    completed = submission_service.complete_submission(sub.id, user_id, db)
    completed.conversation_state = ConversationState.COMPLETE
    db.commit()
    db.refresh(completed)
    logger.info(f"Submission {sub.id} completed by user={user_id} — state=COMPLETE")

    return ConversationTurnResponse(
        submission_id=sub.id,
        agent_message=(
            "Your application has been submitted successfully! "
            "Our team will review it and contact you shortly. Thank you!"
        ),
        is_complete=True,
        progress=_build_progress(completed, db),
    )


# ---------------------------------------------------------------------------
# Prompt builders (AI generates natural language from field metadata)
# ---------------------------------------------------------------------------

def _field_question(field: Optional[FormField]) -> str:
    """Generate a question prompt for a field."""
    if not field:
        return "All done!"

    if field.field_type in ("select", "radio") and field.options:
        choices = ", ".join(opt["label"] for opt in field.options)
        return f"{field.label}? Options: {choices}."

    if field.field_type == "date":
        return f"{field.label}? (Format: YYYY-MM-DD)"

    if field.field_type == "number":
        rule = field.validation_rule or {}
        hint = ""
        if "min" in rule and "max" in rule:
            hint = f" (between {rule['min']} and {rule['max']})"
        elif "min" in rule:
            hint = f" (minimum: {rule['min']})"
        return f"{field.label}?{hint}"

    return f"{field.label}?"


def _build_field_prompt(confirmed_label: str, next_field: FormField) -> str:
    """Confirmation of saved field + question for next field."""
    return f"Got it. Next: {_field_question(next_field)}"


def _build_review_summary(sub: Submission, db: Session) -> str:
    """
    Build a human-readable review of all answered fields.
    Field values ARE read back to the user here (this is intentional UX),
    but they are never written to logs.
    """
    from app.services.form_service import get_ordered_active_fields
    fields = get_ordered_active_fields(sub.form_id, db)
    answered = {d.field_key: d.value for d in sub.data}

    lines = []
    for field in fields:
        value = answered.get(field.field_key, "(not answered)")
        # For select/radio, show the label not the value key
        if field.options and value != "(not answered)":
            for opt in field.options:
                if opt["value"] == value:
                    value = opt["label"]
                    break
        lines.append(f"• {field.label}: {value}")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Validation (backend enforces all rules — AI cannot bypass)
# ---------------------------------------------------------------------------

def _parse_and_validate(text_input: str, field: FormField) -> str:
    """
    Validate raw text against the field's type and validation_rule.
    Returns the cleaned, normalised value string.
    Raises HTTPException 422 on any validation failure.
    Field values are never logged here.
    """
    value = text_input.strip()

    if not value:
        if field.required:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=f"'{field.label}' is required and cannot be empty",
            )
        return value

    rule = field.validation_rule or {}

    # ── Number validation ─────────────────────────────────────────────────────
    if field.field_type == "number":
        try:
            num = float(value)
        except ValueError:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=f"'{field.label}' must be a number",
            )
        if "min" in rule and num < rule["min"]:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=f"'{field.label}' must be at least {rule['min']}",
            )
        if "max" in rule and num > rule["max"]:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=f"'{field.label}' must be at most {rule['max']}",
            )

    # ── Select / Radio validation ─────────────────────────────────────────────
    elif field.field_type in ("select", "radio"):
        options = field.options or []
        valid_values = {opt["value"] for opt in options}
        valid_labels = {opt["label"].lower(): opt["value"] for opt in options}

        if value in valid_values:
            pass  # Already a valid value key
        elif value.lower() in valid_labels:
            value = valid_labels[value.lower()]  # Normalise label → value key
        else:
            choices = ", ".join(opt["label"] for opt in options)
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=f"'{field.label}' must be one of: {choices}",
            )

    # ── Pattern validation ────────────────────────────────────────────────────
    if "pattern" in rule:
        if not re.fullmatch(rule["pattern"], value):
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=f"'{field.label}' format is invalid",
            )

    # ── Length validation ─────────────────────────────────────────────────────
    if "min_length" in rule and len(value) < rule["min_length"]:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"'{field.label}' must be at least {rule['min_length']} characters",
        )
    if "max_length" in rule and len(value) > rule["max_length"]:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"'{field.label}' must be at most {rule['max_length']} characters",
        )

    return value


# ---------------------------------------------------------------------------
# Progress snapshot
# ---------------------------------------------------------------------------

def _build_progress(sub: Submission, db: Session) -> SubmissionProgress:
    from app.services.form_service import get_ordered_active_fields
    fields = get_ordered_active_fields(sub.form_id, db)
    total = len(fields)
    idx = sub.current_field_index

    current_field_out = None
    if idx < total:
        current_field_out = FormFieldOut.model_validate(fields[idx])

    return SubmissionProgress(
        submission_id=sub.id,
        current_field_index=idx,
        total_fields=total,
        status=sub.status,
        current_field=current_field_out,
    )
