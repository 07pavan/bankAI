"""
Conversation API — voice/text agent for guided form filling + pre-submission chat mode.
All routes are JWT-protected.

Contracts:
  POST /api/v1/conversation/chat
    Body:    { "message": "<text or voice transcript>" }
    Response: { "message": "...", "intent": "small_talk|help|form_selection|out_of_scope",
                "available_forms": [...] }

  POST /api/v1/conversation/next
    Body:    { "submission_id": <int>, "message": "<voice transcript>" }
    Response: { "next_question": "...", "field_key": "...", "status": "in_progress|completed" }

LLM Integration:
  When LLM_API_KEY is configured (llm_settings.is_configured), the /next
  endpoint delegates to the LangGraph-based ai_agent_service.  Otherwise
  it falls back to the keyword-based conversation_service (zero-downtime
  backward compatibility).
"""

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from pydantic import BaseModel, Field
from typing import Optional

from app.database import get_db
from app.core.security import get_current_user_id
from app.core.logging import get_logger
from app.services import conversation_service
from app.services.ai_agent_service import (
    invoke_agent,
    get_last_agent_message,
    is_llm_available,
)
from app.models import Submission, ConversationState
from app.schemas import FormListItem

logger = get_logger()

router = APIRouter()


# ---------------------------------------------------------------------------
# POST /chat — stateless pre-submission chat mode
# ---------------------------------------------------------------------------

class ChatRequest(BaseModel):
    """Body for POST /conversation/chat — no submission_id required."""
    message: str = Field(..., min_length=1, description="User's text or voice transcript")


class ChatResponse(BaseModel):
    """Response from POST /conversation/chat."""
    message: str          # Canned agent reply
    intent: str           # small_talk | help | form_selection | out_of_scope
    available_forms: list[FormListItem] = []


@router.post("/chat", response_model=ChatResponse, summary="Pre-submission chat mode")
def conversation_chat(
    payload: ChatRequest,
    user_id: int = Depends(get_current_user_id),
    db: Session = Depends(get_db),
):
    """
    Stateless guarded chat handler — runs BEFORE any form submission exists.

    Handles:
      - Greetings / small talk (no DB access needed)
      - Help / service listing (reads active forms from DB)
      - Form-selection intent (detects which form the user wants)
      - Out-of-scope guard (anything unrelated to banking forms)

    This endpoint NEVER creates or modifies any Submission record.
    The existing /next endpoint handles all in-submission interaction.
    """
    result = conversation_service.handle_chat_turn(
        user_id=user_id,
        message=payload.message,
        db=db,
    )
    return ChatResponse(
        message=result.message,
        intent=result.intent,
        available_forms=[FormListItem.model_validate(f) for f in result.available_forms],
    )


# ---------------------------------------------------------------------------
# Request / Response models for /next
# ---------------------------------------------------------------------------

class ConversationNextRequest(BaseModel):
    """Body for POST /conversation/next."""
    submission_id: int
    message: str = Field(..., min_length=1)  # raw voice transcript; must be non-empty


class ConversationNextResponse(BaseModel):
    """Response from POST /conversation/next."""
    next_question: str          # The agent's next prompt (or completion message)
    field_key: Optional[str] = None  # Field that was just answered (None when complete)
    status: str                 # "in_progress" | "completed"


# ---------------------------------------------------------------------------
# POST /next — the main conversation turn endpoint
# ---------------------------------------------------------------------------

@router.post("/next", response_model=ConversationNextResponse)
def conversation_next(
    payload: ConversationNextRequest,
    user_id: int = Depends(get_current_user_id),
    db: Session = Depends(get_db),
):
    """
    Process one turn of the voice conversation.

    The frontend sends the user's voice transcript; this endpoint:
      1. Reads submission.conversation_state (backend is sole authority)
      2. Delegates to the LangGraph AI agent (if configured) or the
         keyword-based conversation_service (fallback)
      3. Syncs the agent's returned state back to the DB
      4. Returns the next question to ask (or a completion message)

    LLM Strategy:
      - If LLM_API_KEY is set → LangGraph agent (natural language)
      - If not → keyword-based conversation_service (zero-config)

    Status values:
      - "in_progress"  — more fields remain or awaiting review confirmation
      - "completed"    — all required fields answered, submission finalised

    Response format is backward-compatible regardless of which engine
    processes the turn.
    """
    # --- Fallback path: keyword-based conversation_service -----------------
    if not is_llm_available():
        logger.info(
            f"LLM not configured — using keyword fallback for "
            f"submission={payload.submission_id} user={user_id}"
        )
        turn = conversation_service.handle_conversation_turn(
            submission_id=payload.submission_id,
            user_id=user_id,
            message=payload.message,
            db=db,
        )
        return ConversationNextResponse(
            next_question=turn.agent_message,
            field_key=turn.field_key,
            status="completed" if turn.is_complete else "in_progress",
        )

    # --- LLM path: LangGraph AI agent -------------------------------------

    # 1. Load the submission to get current state (backend is authority)
    sub = db.query(Submission).filter(
        Submission.id == payload.submission_id,
        Submission.user_id == user_id,
    ).first()

    if not sub:
        return ConversationNextResponse(
            next_question="Submission not found or access denied.",
            field_key=None,
            status="in_progress",
        )

    logger.info(
        f"LLM agent turn: submission={sub.id} user={user_id} "
        f"state={sub.conversation_state} field_idx={sub.current_field_index}"
    )

    # 2. Invoke the LangGraph agent
    result = invoke_agent(
        user_id=user_id,
        user_message=payload.message,
        conversation_state=sub.conversation_state,
        submission_id=sub.id,
        current_field=None,  # Agent will call get_next_field
        form_id=sub.form_id,
        thread_id=f"submission_{sub.id}",
    )

    # 3. Extract the agent's text response
    agent_message = get_last_agent_message(result)
    if not agent_message:
        agent_message = "I'm processing your request. Could you please repeat that?"

    # 4. Determine completion and field_key from agent result
    new_conv_state = result.get("conversation_state", sub.conversation_state)
    is_complete = new_conv_state == ConversationState.COMPLETE
    field_key = result.get("current_field")

    # 5. Sync agent state back to DB (backend stays authoritative)
    state_changed = sub.conversation_state != new_conv_state

    if state_changed:
        sub.conversation_state = new_conv_state
        logger.info(
            f"DB sync: submission {sub.id} conversation_state "
            f"→ {new_conv_state}"
        )

    # If there was an error, log it but don't expose raw details
    if result.get("error"):
        logger.warning(
            f"Agent returned error for submission {sub.id}: "
            f"{result['error']}"
        )

    db.commit()
    db.refresh(sub)

    logger.info(
        f"Turn complete: submission={sub.id} state={sub.conversation_state} "
        f"is_complete={is_complete} field_key={field_key}"
    )

    # 6. Return backward-compatible response
    return ConversationNextResponse(
        next_question=agent_message,
        field_key=field_key,
        status="completed" if is_complete else "in_progress",
    )
