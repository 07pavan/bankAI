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
"""

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from pydantic import BaseModel, Field
from typing import Optional

from app.database import get_db
from app.core.security import get_current_user_id
from app.services import conversation_service
from app.schemas import FormListItem

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
# POST /next
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
      2. Validates and saves the answer (FILLING_FORM state)
      3. Advances to the next field or transitions to REVIEW / COMPLETE
      4. Returns the next question to ask (or a completion message)

    Status values:
      - "in_progress"  — more fields remain or awaiting review confirmation
      - "completed"    — all required fields answered, submission finalised
    """
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
