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
from pydantic import BaseModel, Field
from typing import Optional
from google.cloud.firestore import Client

from app.database import get_db
from app.core.security import get_current_user_id
from app.core.logging import get_logger
from app.services import conversation_service
from app.services.ai_agent_service import is_llm_available
from app.models import ConversationState
from app.schemas import FormListItem

logger = get_logger()

router = APIRouter()


# ---------------------------------------------------------------------------
# GET /test — quick live test for the AI agent (no JWT required)
# ---------------------------------------------------------------------------

class TestResponse(BaseModel):
    """Response from GET /conversation/test."""
    reply: str
    conversation_state: str
    user_id: str
    thread_id: str
    llm_configured: bool
    error: Optional[str] = None


@router.get("/test", response_model=TestResponse, summary="Live AI agent test")
def conversation_test(
    message: str = "Hello, what can you help me with?",
    user_id: str = "1",
):
    """
    Quick test endpoint for the LangGraph AI agent.

    No JWT required — intended for development/demo use only.
    Calls invoke_agent() directly with the real LLM (no keyword fallback).

    Try it:
      GET /api/v1/conversation/test?message=hello&user_id=1
      GET /api/v1/conversation/test?message=what+forms+are+available
    """
    thread_id = f"user_{user_id}"

    if not is_llm_available():
        return TestResponse(
            reply="LLM is not configured. Set LLM_API_KEY in .env.",
            conversation_state="chat",
            user_id=user_id,
            thread_id=thread_id,
            llm_configured=False,
            error="LLM_API_KEY not set",
        )

    # Lazy import — only the /test endpoint needs these directly
    from app.services.ai_agent_service import invoke_agent, get_last_agent_message

    result = invoke_agent(
        user_id=user_id,
        user_message=message,
        conversation_state=ConversationState.CHAT,
        submission_id=None,
        thread_id=thread_id,
    )

    agent_reply = get_last_agent_message(result) or "No response from agent."
    error = result.get("error")

    logger.info(
        f"Test endpoint: user={user_id} thread={thread_id} "
        f"state={result.get('conversation_state', 'chat')} "
        f"error={error}"
    )

    return TestResponse(
        reply=agent_reply,
        conversation_state=result.get("conversation_state", "chat"),
        user_id=user_id,
        thread_id=thread_id,
        llm_configured=True,
        error=error,
    )


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
    user_id: str = Depends(get_current_user_id),
    db: Client = Depends(get_db),
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
    submission_id: str
    message: str = Field(..., min_length=1)  # raw voice transcript; must be non-empty


class ConversationNextResponse(BaseModel):
    """Response from POST /conversation/next."""
    next_question: str          # The agent's next prompt (or completion message)
    field_key: Optional[str] = None  # Field that was just answered (None when complete)
    status: str                 # "in_progress" | "completed"
    current_field_index: Optional[int] = None  # For frontend progress bar
    total_fields: Optional[int] = None         # For frontend progress bar
    conversation_state: Optional[str] = None    # Current state of the conversation


# ---------------------------------------------------------------------------
# POST /next — the main conversation turn endpoint
# ---------------------------------------------------------------------------

@router.post("/next", response_model=ConversationNextResponse)
def conversation_next(
    payload: ConversationNextRequest,
    user_id: str = Depends(get_current_user_id),
    db: Client = Depends(get_db),
):
    """
    Process one turn of the voice conversation.

    The frontend sends the user's voice transcript; this endpoint
    delegates to conversation_service.handle_conversation_turn() which
    uses a hybrid strategy:
      - If LLM is configured → tries the LangGraph AI agent first
      - If LLM fails or is disabled → keyword-based fallback (zero-config)

    The backend is the single source of truth for state transitions.
    The route never duplicates the LLM invocation logic — that lives
    exclusively in conversation_service.

    Status values:
      - "in_progress"  — more fields remain or awaiting review confirmation
      - "completed"    — all required fields answered, submission finalised
    """
    logger.info(
        f"Conversation turn: submission={payload.submission_id} "
        f"user={user_id} llm_available={is_llm_available()}"
    )

    turn = conversation_service.handle_conversation_turn(
        submission_id=payload.submission_id,
        user_id=user_id,
        message=payload.message,
        db=db,
    )

    # Extract progress fields if available
    current_idx = None
    total = None
    if turn.progress:
        current_idx = turn.progress.current_field_index
        total = turn.progress.total_fields

    # Load submission from DB to get the current conversation state
    from app.services import submission_service
    sub = submission_service.get_submission(payload.submission_id, user_id)
    conversation_state = sub.get("conversation_state")

    return ConversationNextResponse(
        next_question=turn.agent_message,
        field_key=turn.field_key,
        status="completed" if turn.is_complete else "in_progress",
        current_field_index=current_idx,
        total_fields=total,
        conversation_state=conversation_state,
    )


# ---------------------------------------------------------------------------
# POST /speak — proxy TTS to Deepgram API
# ---------------------------------------------------------------------------

from fastapi.responses import StreamingResponse
import httpx
from app.core.config import settings

class SpeakRequest(BaseModel):
    """Request body for TTS speak endpoint."""
    text: str


@router.post("/speak", summary="Synthesise speech using Deepgram TTS")
async def speak_text(
    payload: SpeakRequest,
    user_id: str = Depends(get_current_user_id),
):
    """
    Proxy Text-to-Speech requests to the Deepgram Aura TTS API.
    Streams back raw audio bytes (audio/mpeg) to avoid exposing keys on client side.
    """
    if not settings.DEEPGRAM_API_KEY:
        raise HTTPException(
            status_code=400,
            detail="Deepgram TTS is not configured. Falling back to browser voice."
        )

    text_to_speak = payload.text.strip()
    if not text_to_speak:
        raise HTTPException(status_code=400, detail="Text cannot be empty.")

    try:
        async with httpx.AsyncClient() as client:
            # Aura TTS API request (English female voice Aura-Asteria)
            url = "https://api.deepgram.com/v1/speak?model=aura-asteria-en"
            headers = {
                "Authorization": f"Token {settings.DEEPGRAM_API_KEY}",
                "Content-Type": "application/json",
            }
            body = {"text": text_to_speak}
            
            # Request audio stream from Deepgram
            response = await client.post(url, headers=headers, json=body, timeout=30.0)
            
            if response.status_code != 200:
                logger.error(f"Deepgram TTS failed: status={response.status_code} body={response.text}")
                raise HTTPException(
                    status_code=502,
                    detail=f"Deepgram TTS service error: {response.text[:200]}"
                )
            
            # Stream the audio response back to the client
            return StreamingResponse(
                response.iter_bytes(),
                media_type="audio/mpeg"
            )
            
    except httpx.RequestError as exc:
        logger.error(f"Failed to connect to Deepgram TTS: {exc}")
        raise HTTPException(
            status_code=502,
            detail="Failed to connect to Deepgram Text-to-Speech service."
        )


