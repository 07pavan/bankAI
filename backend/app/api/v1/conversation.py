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

from fastapi import APIRouter, Depends, HTTPException, status
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
        f"user={user_id} llm_available={is_llm_available()} "
        f"message={'__start__' if payload.message == '__start__' else '[user input]'}"
    )

    # ── __start__ special case ─────────────────────────────────────────────
    # The frontend sends "__start__" as the first turn after a submission is
    # created.  We only need to read the first field — no writes, no LLM call.
    # Bypassing handle_conversation_turn avoids the compound-query crash that
    # comes from trying to save "__start__" as a field value.
    if payload.message == "__start__":
        try:
            from app.services import submission_service, form_service
            sub = submission_service.get_submission(payload.submission_id, user_id)
            field = submission_service.get_current_field(payload.submission_id)
            total = len(form_service.get_ordered_active_fields(sub.get("form_id", "")))
            if field:
                question = (
                    f"Let's begin! {field.get('label', 'Please answer the first field')}. "
                )
                if field.get("field_type") in ("select", "radio") and field.get("options"):
                    opts = ", ".join(str(o) for o in field["options"])
                    question += f"Options: {opts}."
                elif field.get("field_type") == "number":
                    rule = field.get("validation_rule") or {}
                    if "min" in rule and "max" in rule:
                        question += f"(Between {rule['min']} and {rule['max']})"
            else:
                question = "All fields are ready for review. Say 'confirm' to submit or 'change' to edit."

            return ConversationNextResponse(
                next_question=question,
                field_key=field.get("field_key") if field else None,
                status="in_progress",
                current_field_index=sub.get("current_field_index", 0),
                total_fields=total,
                conversation_state=sub.get("conversation_state"),
            )
        except Exception as exc:
            logger.error(f"__start__ init failed: {exc}", exc_info=True)
            raise HTTPException(status_code=500, detail=f"Could not load form: {str(exc)}")

    # ── Normal conversation turn ───────────────────────────────────────────
    try:
        turn = conversation_service.handle_conversation_turn(
            submission_id=payload.submission_id,
            user_id=user_id,
            message=payload.message,
            db=db,
        )
    except Exception as exc:
        logger.error(f"Error in conversation_next: {exc}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Backend Error: {str(exc)}")

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


@router.post("/stt-token", summary="Generate short-lived Deepgram STT token")
async def generate_stt_token(
    user_id: str = Depends(get_current_user_id),
):
    """
    Generate a short-lived token (60-second TTL) for Deepgram STT WebSocket connection
    to avoid exposing main keys on the client-side browser.
    """
    if not settings.DEEPGRAM_API_KEY:
        raise HTTPException(
            status_code=400,
            detail="Deepgram service is not configured."
        )

    try:
        async with httpx.AsyncClient() as client:
            url = "https://api.deepgram.com/v1/auth/grant"
            headers = {
                "Authorization": f"Token {settings.DEEPGRAM_API_KEY}",
                "Content-Type": "application/json",
            }
            body = {"ttl_seconds": 60}
            
            res = await client.post(url, headers=headers, json=body, timeout=10.0)
            if res.status_code != 200:
                logger.error(f"Failed to grant token from Deepgram: status={res.status_code} body={res.text}")
                raise HTTPException(status_code=502, detail="Failed to acquire speech token.")
            
            data = res.json()
            return {"token": data.get("access_token")}
            
    except Exception as exc:
        logger.error(f"Error requesting Deepgram token: {exc}")
        raise HTTPException(
            status_code=502,
            detail="Speech service authentication failed.",
        )


# ---------------------------------------------------------------------------
# GET /status/{submission_id} — session restore: current conversation state
# ---------------------------------------------------------------------------

class ConversationStatusResponse(BaseModel):
    """Snapshot of the current conversation state (no turn processing)."""
    submission_id: str
    conversation_state: str
    current_field_index: int
    total_fields: int
    status: str          # draft | completed
    form_name: Optional[str] = None
    bank_name: Optional[str] = None
    progress_pct: int = 0


@router.get(
    "/status/{submission_id}",
    response_model=ConversationStatusResponse,
    summary="Get current conversation state for session restore",
)
def conversation_status(
    submission_id: str,
    user_id: str = Depends(get_current_user_id),
    db: Client = Depends(get_db),
):
    """
    Return current state of a submission without advancing the conversation.

    Used by the dashboard on page load to restore an in-progress session.
    Raises 404 if submission not found or not owned by this user.
    """
    from app.services import submission_service
    from app.services.form_service import get_ordered_active_fields
    from app.models import COLL_FORMS, COLL_BANKS

    sub = submission_service.get_submission(submission_id, user_id)

    fields = get_ordered_active_fields(sub["form_id"])
    total = len(fields)
    current_idx = sub.get("current_field_index", 0)
    pct = round((current_idx / total * 100)) if total > 0 else 0

    form_name = None
    bank_name = None
    try:
        form_doc = db.collection(COLL_FORMS).document(sub["form_id"]).get()
        if form_doc.exists:
            form_data = form_doc.to_dict()
            form_name = form_data.get("name")
            bank_doc = db.collection(COLL_BANKS).document(form_data.get("bank_id", "")).get()
            if bank_doc.exists:
                bank_name = bank_doc.to_dict().get("name")
    except Exception:
        pass

    return ConversationStatusResponse(
        submission_id=submission_id,
        conversation_state=sub.get("conversation_state", "filling_form"),
        current_field_index=current_idx,
        total_fields=total,
        status=sub.get("status", "draft"),
        form_name=form_name,
        bank_name=bank_name,
        progress_pct=pct,
    )
