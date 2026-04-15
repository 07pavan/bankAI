"""
AI Agent Service — LangGraph-powered conversation orchestrator for BankAI.

Replaces the keyword-based conversation_service state machine with a
LangGraph StateGraph that uses an xAI/Grok LLM for natural language
understanding while keeping the backend as the **single source of truth**
for all state transitions.

State Machine (identical to conversation_service — never skipped):
  CHAT → WELCOME → SELECT_APPLICATION → FILLING_FORM → REVIEW → COMPLETE

Security guarantees:
  - All user messages are PII-redacted before reaching the LLM.
  - All tool return values are PII-redacted (enforced by ai_agent_tools).
  - The LLM cannot skip states, invent fields, or bypass validation.
  - The backend controls every state transition via the supervisor router.

Architecture:
  ┌────────┐     ┌────────────┐     ┌──────────────┐
  │  User  │ ──→ │ Supervisor │ ──→ │  State Node  │
  └────────┘     │  (router)  │     │ (LLM + tools)│
                 └────────────┘     └──────┬───────┘
                                           │
                                    ┌──────▼──────┐
                                    │ Tool Executor│
                                    └─────────────┘

LLM Node returns structured AgentAction (Pydantic) containing:
  - response:   Text message to show the user
  - next_state: Requested state transition (backend validates)
  - action:     Semantic action tag for the API layer

# ── RAG placeholder ──────────────────────────────────────────────────
# TODO (Phase 3): Add a RAG retriever node between the router and the
# state nodes.  The retriever will:
#   1. Query a vector store (Pinecone / PGVector) with the user's
#      message to pull relevant banking FAQ / policy context.
#   2. Inject the retrieved documents as a SystemMessage addendum
#      so the LLM can give policy-aware answers.
#
# Suggested integration point:
#   - Add a "rag_retriever" node to the graph.
#   - Route: entry → rag_retriever → state_node → should_continue → ...
#   - The retriever node would append a SystemMessage with the context
#     and pass through to the state node without changing state.
# ─────────────────────────────────────────────────────────────────────
"""

from __future__ import annotations

from typing import Annotated, Any, Literal, Optional, Sequence

from pydantic import BaseModel, Field
from typing_extensions import TypedDict

from langchain_core.messages import (
    AIMessage,
    BaseMessage,
    HumanMessage,
    SystemMessage,
    ToolMessage,
)
from langgraph.graph import END, StateGraph
from langgraph.graph.message import add_messages
from langgraph.prebuilt import ToolNode
from langgraph.checkpoint.memory import MemorySaver

from app.core.config import llm_settings
from app.core.llm_redaction import redact_pii, should_redact_before_llm
from app.core.logging import get_logger
from app.models import ConversationState
from app import database as app_db
from app.services.ai_agent_tools import ALL_TOOLS

logger = get_logger()


# ═══════════════════════════════════════════════════════════════════════════
# 1. AgentState — TypedDict for the LangGraph state channel
# ═══════════════════════════════════════════════════════════════════════════

class AgentState(TypedDict):
    """
    Shared state flowing through every node in the graph.

    Fields:
        messages:           LangGraph message list (auto-merged via add_messages).
        conversation_state: Current BankAI state-machine state.
                            The supervisor reads this to pick the next node.
                            Only validated transitions are accepted.
        user_id:            Authenticated user ID (injected at entry).
        submission_id:      Active submission PK (None before form selection).
        current_field:      The field_key the agent is currently asking about.
        form_id:            Selected form PK (set during SELECT_APPLICATION).
        error:              Last error message, if any (cleared on success).
    """

    messages: Annotated[Sequence[BaseMessage], add_messages]
    conversation_state: str
    user_id: int
    submission_id: Optional[int]
    current_field: Optional[str]
    form_id: Optional[int]
    error: Optional[str]


# ═══════════════════════════════════════════════════════════════════════════
# 2. Structured output — Pydantic models for LLM responses
# ═══════════════════════════════════════════════════════════════════════════

class AgentAction(BaseModel):
    """
    Structured response from a state node.
    The API layer uses these fields to build ConversationTurnResponse.
    """
    response: str = Field(
        description="Natural-language message to display to the user."
    )
    next_state: Optional[str] = Field(
        default=None,
        description=(
            "Requested state transition. Must be a valid BankAI "
            "ConversationState value, or None to stay in current state."
        ),
    )
    action: str = Field(
        default="continue",
        description=(
            "Semantic action tag: 'continue', 'form_selected', "
            "'field_saved', 'review_requested', 'confirmed', "
            "'change_requested', 'completed', 'greeting', 'help'."
        ),
    )
    detected_form_id: Optional[int] = Field(
        default=None,
        description="Form ID detected from user's selection intent.",
    )
    detected_field_key: Optional[str] = Field(
        default=None,
        description="Field key that was just answered.",
    )


# ═══════════════════════════════════════════════════════════════════════════
# 3. System prompts — one base + per-state addenda
# ═══════════════════════════════════════════════════════════════════════════

SYSTEM_PROMPT = """\
You are the BankAI Assistant — a friendly, professional voice/text agent
embedded in an Indian banking platform.

YOUR ROLE:
• Guide the user through banking application forms one field at a time.
• Ask clear, natural-language questions based on field metadata from tools.
• Understand natural language answers and convert them to expected format.

HARD CONSTRAINTS (you MUST obey):
1. You CANNOT skip states. The backend controls state transitions.
2. You CANNOT invent fields or modify the form structure.
3. You CANNOT bypass validation — the backend enforces every rule.
4. You CANNOT reveal raw PII (Aadhaar, PAN, phone, email) in your output.
5. You ALWAYS use the provided tools to interact with forms and data.
6. When in CHAT state, answer greetings and help queries conversationally.
7. When in FILLING_FORM state, ask about ONE field at a time, save the
   answer with `answer_field`, then call `get_next_field` for the next.
8. When in REVIEW state, only process 'confirm' or 'change' intents.
9. Keep responses concise — users may be on voice input.
10. NEVER fabricate data. If unsure, ask the user to clarify.

AVAILABLE TOOLS:
• get_available_forms(user_id) — list forms the user can apply for
• get_kyc_status(user_id) — check user's KYC verification status
• answer_field(submission_id, field_key, value) — save a field answer
• get_current_submission_state(submission_id) — see submission progress
• get_next_field(submission_id) — get metadata for next unanswered field
"""

_STATE_PROMPTS: dict[str, str] = {
    ConversationState.CHAT: (
        "\nCURRENT STATE: CHAT (pre-submission, no active form).\n"
        "The user has NOT started filling a form yet.\n"
        "ALLOWED ACTIONS:\n"
        "• Answer greetings and small talk warmly.\n"
        "• If user asks about services or forms, call get_available_forms.\n"
        "• If user asks about KYC status, call get_kyc_status.\n"
        "• If user expresses intent to start a form (e.g. 'open account', "
        "'cheque book', 'aadhaar seeding'), identify the form and tell them "
        "you've detected their choice. Ask them to confirm.\n"
        "• DO NOT start filling any form in this state.\n"
    ),

    ConversationState.WELCOME: (
        "\nCURRENT STATE: WELCOME.\n"
        "The user just started a conversation session.\n"
        "INSTRUCTIONS:\n"
        "1. Greet the user warmly by name if known.\n"
        "2. Call get_available_forms to fetch available forms.\n"
        "3. Present the list of forms clearly.\n"
        "4. Ask which form they would like to fill.\n"
    ),

    ConversationState.SELECT_APPLICATION: (
        "\nCURRENT STATE: SELECT_APPLICATION.\n"
        "The user is choosing which form to fill.\n"
        "INSTRUCTIONS:\n"
        "1. If you haven't listed forms yet, call get_available_forms.\n"
        "2. Match the user's utterance to a form from the list.\n"
        "3. Confirm the exact form name with the user.\n"
        "4. If user confirms, tell them you'll start the form now.\n"
        "5. If unclear, ask for clarification.\n"
    ),

    ConversationState.FILLING_FORM: (
        "\nCURRENT STATE: FILLING_FORM.\n"
        "Active submission_id: {submission_id}\n"
        "Current field_key: {current_field}\n\n"
        "INSTRUCTIONS:\n"
        "1. If you don't know the current field, call get_next_field.\n"
        "2. Ask the user a natural-language question for the field.\n"
        "   - For 'select'/'radio' fields: present options clearly.\n"
        "   - For 'date' fields: mention YYYY-MM-DD format.\n"
        "   - For 'number' fields: mention any min/max constraints.\n"
        "3. When the user answers, parse their NL response to the expected\n"
        "   format and call answer_field(submission_id, field_key, value).\n"
        "4. After saving, call get_next_field for the next question.\n"
        "5. If get_next_field says all fields are done, tell the user\n"
        "   their form is ready for review.\n"
        "6. Ask about ONE field at a time. Be conversational.\n"
        "7. If answer_field returns an error, explain the validation\n"
        "   issue and re-ask the same field.\n"
    ),

    ConversationState.REVIEW: (
        "\nCURRENT STATE: REVIEW.\n"
        "Active submission_id: {submission_id}\n\n"
        "INSTRUCTIONS:\n"
        "1. Call get_current_submission_state to see answered fields.\n"
        "2. Read back a summary of all answered fields to the user.\n"
        "3. Ask them to say 'confirm' to submit or 'change' to edit.\n"
        "4. If user says confirm/yes/submit/ok → respond that you're\n"
        "   submitting their application.\n"
        "5. If user says change/edit/no/wrong → tell them you'll\n"
        "   restart the form from the beginning.\n"
        "6. If unclear, re-read the summary and ask again.\n"
    ),

    ConversationState.COMPLETE: (
        "\nCURRENT STATE: COMPLETE (terminal).\n"
        "The application has been submitted. Thank the user.\n"
        "Do NOT accept any more form answers.\n"
    ),
}


def _build_system_message(state: AgentState) -> SystemMessage:
    """Build the full system prompt with state-specific instructions."""
    conv_state = state.get("conversation_state", ConversationState.CHAT)
    state_prompt = _STATE_PROMPTS.get(conv_state, _STATE_PROMPTS[ConversationState.CHAT])

    # Template substitution for dynamic values
    state_prompt = state_prompt.format(
        submission_id=state.get("submission_id", "N/A"),
        current_field=state.get("current_field", "unknown"),
    )

    return SystemMessage(content=SYSTEM_PROMPT + state_prompt)


# ═══════════════════════════════════════════════════════════════════════════
# 4. LLM factory — lazy-initialised, temperature=0 for determinism
# ═══════════════════════════════════════════════════════════════════════════

_cached_llm = None
_cached_llm_with_tools = None


def _get_llm():
    """
    Return the raw ChatXAI model (no tool binding).
    Used for structured-output calls.
    """
    global _cached_llm
    if _cached_llm is not None:
        return _cached_llm

    if not llm_settings.is_configured:
        raise RuntimeError(
            "LLM is not configured. Set LLM_API_KEY in .env to enable "
            "the AI agent. Falling back to keyword-based conversation."
        )

    from langchain_xai import ChatXAI

    _cached_llm = ChatXAI(
        model=llm_settings.LLM_MODEL,
        temperature=0,  # Maximum determinism for banking operations
        api_key=llm_settings.LLM_API_KEY,
    )
    logger.info(f"ChatXAI LLM initialised: model={llm_settings.LLM_MODEL} temperature=0")
    return _cached_llm


def _get_llm_with_tools():
    """
    Return ChatXAI model with tools bound.
    Used in state nodes where the LLM may emit tool calls.
    """
    global _cached_llm_with_tools
    if _cached_llm_with_tools is not None:
        return _cached_llm_with_tools

    llm = _get_llm()
    _cached_llm_with_tools = llm.bind_tools(ALL_TOOLS)
    logger.info(f"LLM tools bound: {[t.name for t in ALL_TOOLS]}")
    return _cached_llm_with_tools


# ═══════════════════════════════════════════════════════════════════════════
# 5. State nodes — full implementations
# ═══════════════════════════════════════════════════════════════════════════

# ── RAG placeholder ──────────────────────────────────────────────────
# def rag_retriever_node(state: AgentState) -> dict:
#     """
#     RAG retriever node — injects relevant banking FAQ / policy context.
#
#     This node would:
#       1. Extract the latest user message from state["messages"].
#       2. Query a VectorStoreRetriever (Pinecone / PGVector) with the
#          message text to find top-k relevant documents.
#       3. Format retrieved docs as a SystemMessage addendum.
#       4. Append the SystemMessage to state["messages"].
#       5. Return — the next node (state node) will see the extra context.
#
#     Example integration:
#         from langchain_community.vectorstores import PGVector
#         from langchain_xai import XAIEmbeddings
#
#         embeddings = XAIEmbeddings(model="v1", api_key=...)
#         vectorstore = PGVector(
#             connection_string=settings.DATABASE_URL,
#             collection_name="banking_faq",
#             embedding_function=embeddings,
#         )
#         retriever = vectorstore.as_retriever(search_kwargs={"k": 3})
#
#         last_msg = state["messages"][-1].content
#         docs = retriever.invoke(last_msg)
#         context = "\n\n".join(d.page_content for d in docs)
#
#         return {
#             "messages": [
#                 SystemMessage(content=f"RELEVANT CONTEXT:\n{context}")
#             ]
#         }
#     """
#     pass
# ─────────────────────────────────────────────────────────────────────


def chat_node(state: AgentState) -> dict:
    """
    CHAT state — pre-submission dashboard mode.

    Responsibilities:
      - Handle greetings, small talk, and pleasantries.
      - Answer help queries by calling get_available_forms.
      - Check KYC status when asked.
      - Detect form-selection intent and ask user to confirm.
      - NEVER start filling a form (no submission_id exists yet).

    The LLM may emit tool calls (get_available_forms, get_kyc_status).
    """
    llm = _get_llm_with_tools()
    system = _build_system_message(state)
    messages = [system] + list(state["messages"])

    response = llm.invoke(messages)

    logger.info(f"chat_node: user={state.get('user_id')} response_type={'tool_call' if response.tool_calls else 'text'}")
    return {"messages": [response], "error": None}


def welcome_node(state: AgentState) -> dict:
    """
    WELCOME state — greet the user and list available forms.

    The LLM calls get_available_forms to fetch the form list, then
    presents it to the user with a warm greeting.

    State transition: WELCOME → SELECT_APPLICATION (automatic after
    the greeting is delivered).
    """
    llm = _get_llm_with_tools()
    system = _build_system_message(state)
    messages = [system] + list(state["messages"])

    response = llm.invoke(messages)

    logger.info(f"welcome_node: user={state.get('user_id')} → transitioning to SELECT_APPLICATION")
    return {
        "messages": [response],
        "conversation_state": ConversationState.SELECT_APPLICATION,
        "error": None,
    }


def select_application_node(state: AgentState) -> dict:
    """
    SELECT_APPLICATION state — user picks which form to fill.

    The LLM matches the user's utterance to a known form name and
    confirms their selection.  Once confirmed, the backend (via
    invoke_agent post-processing) creates a Submission and transitions
    to FILLING_FORM.

    Form detection logic:
      1. LLM calls get_available_forms if not already listed.
      2. LLM matches user's NL intent to a form name/ID.
      3. LLM asks user to confirm.
      4. On confirmation, the API layer creates the submission.
    """
    llm = _get_llm_with_tools()
    system = _build_system_message(state)
    messages = [system] + list(state["messages"])

    response = llm.invoke(messages)

    logger.info(f"select_application_node: user={state.get('user_id')}")
    return {"messages": [response], "error": None}


def filling_form_node(state: AgentState) -> dict:
    """
    FILLING_FORM state — the core form-filling loop.

    Each invocation handles ONE turn of the form-filling conversation:
      1. If the current field is unknown → call get_next_field.
      2. Ask the user a natural-language question for the field.
      3. When the user answers → parse and call answer_field.
      4. After saving → call get_next_field for the next field.
      5. If all done → inform the user and request review.

    The LLM uses the ReAct loop (LLM → tools → LLM → ...) to handle
    multi-step tool interactions within a single turn.

    State transition: FILLING_FORM → REVIEW (when all fields are done,
    detected from get_next_field response).
    """
    llm = _get_llm_with_tools()
    system = _build_system_message(state)
    messages = [system] + list(state["messages"])

    response = llm.invoke(messages)

    # --- Detect "all fields done" from tool results -----------------------
    # After the ReAct loop completes, check if the last tool result
    # indicates all fields are answered.  If so, request REVIEW transition.
    new_state_updates: dict[str, Any] = {
        "messages": [response],
        "error": None,
    }

    # Check all messages for the "ready for review" signal from tools
    for msg in state.get("messages", []):
        if isinstance(msg, ToolMessage) and "ready for review" in msg.content.lower():
            new_state_updates["conversation_state"] = ConversationState.REVIEW
            logger.info(
                f"filling_form_node: all fields done for submission "
                f"{state.get('submission_id')} → transitioning to REVIEW"
            )
            break

    # Extract current field from the last get_next_field tool result
    for msg in reversed(state.get("messages", [])):
        if isinstance(msg, ToolMessage) and "field_key:" in msg.content:
            # Parse "field_key: some_key" from the tool output
            for line in msg.content.split("\n"):
                if "field_key:" in line:
                    key = line.split("field_key:")[1].strip()
                    new_state_updates["current_field"] = key
                    break
            break

    logger.info(
        f"filling_form_node: user={state.get('user_id')} "
        f"submission={state.get('submission_id')} "
        f"field={new_state_updates.get('current_field', state.get('current_field'))}"
    )
    return new_state_updates


def review_node(state: AgentState) -> dict:
    """
    REVIEW state — read back answers and process confirmation/rejection.

    The LLM calls get_current_submission_state to retrieve the summary
    of answered fields, reads them back to the user, and asks for
    confirmation or change requests.

    State transitions:
      - User confirms → COMPLETE (submission completed by API layer).
      - User rejects  → FILLING_FORM (restart from field 0).
    """
    llm = _get_llm_with_tools()
    system = _build_system_message(state)
    messages = [system] + list(state["messages"])

    response = llm.invoke(messages)

    # --- Detect confirmation/rejection intent from the user message ------
    new_state_updates: dict[str, Any] = {
        "messages": [response],
        "error": None,
    }

    # Look at the last user message to detect intent
    last_human = None
    for msg in reversed(state.get("messages", [])):
        if isinstance(msg, HumanMessage):
            last_human = msg.content.lower().strip()
            break

    if last_human:
        confirm_words = {"yes", "correct", "confirm", "ok", "okay", "right", "proceed", "submit", "done"}
        reject_words = {"no", "wrong", "incorrect", "change", "edit", "modify", "back"}

        user_words = set(last_human.split())

        if user_words & confirm_words:
            # User confirmed — complete the submission via service layer
            submission_id = state.get("submission_id")
            user_id = state.get("user_id")

            if submission_id and user_id:
                try:
                    from app.services import submission_service
                    db = app_db.SessionLocal()
                    try:
                        completed = submission_service.complete_submission(
                            submission_id, user_id, db
                        )
                        # Update DB conversation_state to COMPLETE
                        completed.conversation_state = ConversationState.COMPLETE
                        db.commit()
                        logger.info(
                            f"review_node: submission {submission_id} "
                            f"completed by user={user_id}"
                        )
                    finally:
                        db.close()

                    new_state_updates["conversation_state"] = ConversationState.COMPLETE
                    new_state_updates["messages"] = [
                        AIMessage(content=(
                            "Your application has been submitted successfully! 🎉 "
                            "Our team will review it and contact you shortly. "
                            "Thank you for choosing BankAI!"
                        ))
                    ]
                except Exception as exc:
                    logger.error(f"review_node: completion failed: {exc}")
                    new_state_updates["error"] = str(exc)
                    new_state_updates["messages"] = [
                        AIMessage(content=(
                            f"There was an issue submitting your application: "
                            f"{getattr(exc, 'detail', str(exc))}. "
                            f"Please try again."
                        ))
                    ]

        elif user_words & reject_words:
            # User wants to change — reset to FILLING_FORM
            submission_id = state.get("submission_id")
            if submission_id:
                try:
                    from app.models import Submission
                    db = app_db.SessionLocal()
                    try:
                        sub = db.query(Submission).filter(
                            Submission.id == submission_id
                        ).first()
                        if sub:
                            sub.conversation_state = ConversationState.FILLING_FORM
                            sub.current_field_index = 0
                            db.commit()
                    finally:
                        db.close()
                except Exception as exc:
                    logger.error(f"review_node: reset failed: {exc}")

            new_state_updates["conversation_state"] = ConversationState.FILLING_FORM
            new_state_updates["current_field"] = None
            new_state_updates["messages"] = [
                AIMessage(content=(
                    "No problem! Let's go through the form again. "
                    "I'll start from the first field."
                ))
            ]
            logger.info(
                f"review_node: submission {submission_id} returned to "
                f"FILLING_FORM (user requested changes)"
            )

    logger.info(f"review_node: user={state.get('user_id')} submission={state.get('submission_id')}")
    return new_state_updates


def complete_node(state: AgentState) -> dict:
    """
    COMPLETE state — terminal node.

    The form has been submitted. Thank the user and refuse any further
    form modifications.  This node does NOT call the LLM — just returns
    a canned success message for efficiency and determinism.
    """
    logger.info(
        f"complete_node: submission {state.get('submission_id')} "
        f"is complete for user={state.get('user_id')}"
    )
    return {
        "messages": [
            AIMessage(content=(
                "Your application has been submitted successfully! 🎉 "
                "Our team will review it and contact you shortly. "
                "Thank you for using BankAI!"
            ))
        ],
        "conversation_state": ConversationState.COMPLETE,
        "error": None,
    }


# ═══════════════════════════════════════════════════════════════════════════
# 6. Tool executor node — runs tool calls emitted by the LLM
# ═══════════════════════════════════════════════════════════════════════════

tool_node = ToolNode(ALL_TOOLS)


# ═══════════════════════════════════════════════════════════════════════════
# 7. Supervisor / Conditional routing — backend is SOLE authority
# ═══════════════════════════════════════════════════════════════════════════

# Allowed transitions — the LLM cannot skip states.
# This is the enforcement layer that prevents prompt injection from
# causing illegal state jumps.
ALLOWED_TRANSITIONS: dict[str, set[str]] = {
    ConversationState.CHAT:               {ConversationState.CHAT, ConversationState.WELCOME},
    ConversationState.WELCOME:            {ConversationState.WELCOME, ConversationState.SELECT_APPLICATION},
    ConversationState.SELECT_APPLICATION: {ConversationState.SELECT_APPLICATION, ConversationState.FILLING_FORM},
    ConversationState.FILLING_FORM:       {ConversationState.FILLING_FORM, ConversationState.REVIEW},
    ConversationState.REVIEW:             {ConversationState.REVIEW, ConversationState.FILLING_FORM, ConversationState.COMPLETE},
    ConversationState.COMPLETE:           {ConversationState.COMPLETE},
}

# Map each conversation state → graph node name
STATE_TO_NODE: dict[str, str] = {
    ConversationState.CHAT:               "chat_node",
    ConversationState.WELCOME:            "welcome_node",
    ConversationState.SELECT_APPLICATION: "select_application_node",
    ConversationState.FILLING_FORM:       "filling_form_node",
    ConversationState.REVIEW:             "review_node",
    ConversationState.COMPLETE:           "complete_node",
}


def validate_transition(current: str, requested: str) -> str:
    """
    Validate a state transition against ALLOWED_TRANSITIONS.

    If the requested transition is illegal, log a warning and return
    the current state (blocking the transition).

    Args:
        current:   Current conversation_state value.
        requested: Requested next state.

    Returns:
        The validated next state (either requested or current if blocked).
    """
    allowed = ALLOWED_TRANSITIONS.get(current, {current})
    if requested in allowed:
        if requested != current:
            logger.info(f"State transition validated: {current} → {requested}")
        return requested

    logger.warning(
        f"BLOCKED illegal state transition: {current} → {requested}. "
        f"Allowed: {allowed}. Staying in {current}."
    )
    return current


def route_by_state(state: AgentState) -> str:
    """
    Supervisor router — deterministically selects the graph node based on
    conversation_state.

    This is the core enforcement mechanism:
      - The LLM CANNOT influence which node runs next.
      - State transitions written by nodes are validated against
        ALLOWED_TRANSITIONS by the supervisor post-processing in
        invoke_agent().
      - Unknown states default to chat_node.

    Used as the conditional entry point of the StateGraph.
    """
    conv_state = state.get("conversation_state", ConversationState.CHAT)
    node_name = STATE_TO_NODE.get(conv_state, "chat_node")
    logger.info(f"Supervisor router: conversation_state={conv_state} → {node_name}")
    return node_name


def should_continue(state: AgentState) -> str:
    """
    After a state node runs, decide whether to:
      - "tools"   → route to ToolNode (LLM emitted tool calls)
      - "end"     → stop and return to user

    This implements the ReAct loop: LLM node ↔ tool node.
    The loop continues until the LLM produces a plain text response
    (no more tool calls).
    """
    messages = state.get("messages", [])
    if not messages:
        return "end"

    last_message = messages[-1]

    # If the LLM emitted tool calls, execute them
    if isinstance(last_message, AIMessage) and getattr(last_message, "tool_calls", None):
        tool_names = [tc["name"] for tc in last_message.tool_calls]
        logger.info(f"ReAct loop: {len(last_message.tool_calls)} tool call(s): {tool_names}")
        return "tools"

    # Otherwise the turn is complete — return to the user
    return "end"


def after_tools(state: AgentState) -> str:
    """
    After tools execute, route back to the current state's node so
    the LLM can process tool results and decide what to say/do next.

    This completes the ReAct cycle:
      state_node → tools → state_node → (tools|end)
    """
    conv_state = state.get("conversation_state", ConversationState.CHAT)
    node_name = STATE_TO_NODE.get(conv_state, "chat_node")
    logger.info(f"After-tools → back to {node_name}")
    return node_name


# ═══════════════════════════════════════════════════════════════════════════
# 8. Graph assembly
# ═══════════════════════════════════════════════════════════════════════════

def build_agent_graph() -> StateGraph:
    """
    Assemble the full LangGraph StateGraph.

    Graph topology:
      ┌─────────┐
      │  Entry  │ ──(route_by_state)──→ [chat|welcome|select|fill|review|complete]
      └─────────┘
           ↕
      Each state node:
        node ──(should_continue)──→ tools ──(after_tools)──→ node
          │                                                     │
          └──(should_continue="end")──→ END                    └──→ ...

    Returns an uncompiled StateGraph (compile with checkpointer separately).
    """
    graph = StateGraph(AgentState)

    # --- Add state nodes ---------------------------------------------------
    graph.add_node("chat_node", chat_node)
    graph.add_node("welcome_node", welcome_node)
    graph.add_node("select_application_node", select_application_node)
    graph.add_node("filling_form_node", filling_form_node)
    graph.add_node("review_node", review_node)
    graph.add_node("complete_node", complete_node)
    graph.add_node("tools", tool_node)

    # --- RAG placeholder --------------------------------------------------
    # graph.add_node("rag_retriever", rag_retriever_node)
    # To enable RAG, change entry routing:
    #   entry → rag_retriever → state_node → should_continue → ...
    # and add edge: rag_retriever → route_by_state (pass through)

    # --- Entry point: supervisor routes by conversation_state --------------
    graph.set_conditional_entry_point(
        route_by_state,
        {
            "chat_node": "chat_node",
            "welcome_node": "welcome_node",
            "select_application_node": "select_application_node",
            "filling_form_node": "filling_form_node",
            "review_node": "review_node",
            "complete_node": "complete_node",
        },
    )

    # --- Each state node → should_continue (ReAct: tools or end) -----------
    for node_name in STATE_TO_NODE.values():
        graph.add_conditional_edges(
            node_name,
            should_continue,
            {
                "tools": "tools",
                "end": END,
            },
        )

    # --- After tools → back to the current state's node (ReAct loop) -------
    graph.add_conditional_edges(
        "tools",
        after_tools,
        {
            "chat_node": "chat_node",
            "welcome_node": "welcome_node",
            "select_application_node": "select_application_node",
            "filling_form_node": "filling_form_node",
            "review_node": "review_node",
            "complete_node": "complete_node",
        },
    )

    return graph


# ═══════════════════════════════════════════════════════════════════════════
# 9. Compiled graph singleton + checkpointer
# ═══════════════════════════════════════════════════════════════════════════

checkpointer = MemorySaver()

# Compile at import time so the graph is ready for requests
_compiled_graph = build_agent_graph().compile(checkpointer=checkpointer)

logger.info("LangGraph agent graph compiled with MemorySaver checkpointer")


# ═══════════════════════════════════════════════════════════════════════════
# 10. Public API — invoke the agent for a single turn
# ═══════════════════════════════════════════════════════════════════════════

def invoke_agent(
    user_id: int,
    user_message: str,
    conversation_state: str = ConversationState.CHAT,
    submission_id: Optional[int] = None,
    current_field: Optional[str] = None,
    form_id: Optional[int] = None,
    thread_id: Optional[str] = None,
) -> dict[str, Any]:
    """
    Run one turn of the AI agent and return the updated state.

    This is the main entry point called by the API router.  It:
      1. Redacts PII from the user's message before the LLM sees it.
      2. Builds the LangGraph input state.
      3. Invokes the compiled graph (supervisor routes to correct node).
      4. Validates any state transitions against ALLOWED_TRANSITIONS.
      5. Returns the final state dict.

    Args:
        user_id:            Authenticated user's ID.
        user_message:       Raw user input (voice transcript or text).
        conversation_state: Current BankAI state (from Submission or 'chat').
        submission_id:      Active submission PK (None for CHAT/WELCOME).
        current_field:      Field key the agent is asking about (optional).
        form_id:            Currently selected form ID (optional).
        thread_id:          Checkpoint thread ID for conversation continuity.
                            Defaults to "user_{user_id}" if not provided.

    Returns:
        Dict with keys: messages, conversation_state, submission_id,
        current_field, form_id, error.
    """
    # --- PII redaction before LLM sees the message -------------------------
    safe_message = user_message
    if should_redact_before_llm(user_message):
        safe_message = redact_pii(user_message)
        logger.info(f"PII redacted from user message for user_id={user_id}")

    # --- Build input state -------------------------------------------------
    input_state: AgentState = {
        "messages": [HumanMessage(content=safe_message)],
        "conversation_state": conversation_state,
        "user_id": user_id,
        "submission_id": submission_id,
        "current_field": current_field,
        "form_id": form_id,
        "error": None,
    }

    # --- Invoke the graph --------------------------------------------------
    config = {
        "configurable": {
            "thread_id": thread_id or f"user_{user_id}",
        }
    }

    logger.info(
        f"Invoking agent: user={user_id} state={conversation_state} "
        f"submission={submission_id} field={current_field} "
        f"thread={config['configurable']['thread_id']}"
    )

    try:
        result = _compiled_graph.invoke(input_state, config=config)
    except Exception as exc:
        logger.error(f"Agent invocation failed: {exc}", exc_info=True)
        return {
            "messages": [
                AIMessage(content=(
                    "I'm sorry, I encountered an error processing your request. "
                    "Please try again or say 'help' for assistance."
                ))
            ],
            "conversation_state": conversation_state,
            "user_id": user_id,
            "submission_id": submission_id,
            "current_field": current_field,
            "form_id": form_id,
            "error": str(exc),
        }

    # --- Supervisor: validate state transitions ----------------------------
    new_state = result.get("conversation_state", conversation_state)
    validated_state = validate_transition(conversation_state, new_state)
    result["conversation_state"] = validated_state

    logger.info(
        f"Agent turn complete: user={user_id} "
        f"state={conversation_state}→{validated_state} "
        f"submission={result.get('submission_id')}"
    )
    return result


def get_last_agent_message(result: dict[str, Any]) -> str:
    """
    Extract the last AI text message from an invoke_agent result.

    Walks the message list in reverse and returns the first AIMessage
    with text content and no tool calls.  Useful for the API router
    to build the response payload.

    Returns empty string if no AI message is found.
    """
    messages = result.get("messages", [])
    for msg in reversed(messages):
        if isinstance(msg, AIMessage) and msg.content and not getattr(msg, "tool_calls", None):
            return msg.content
    return ""


def is_llm_available() -> bool:
    """
    Check whether the LLM is configured and available.
    Used by the API layer to decide between AI agent and keyword fallback.
    """
    return llm_settings.is_configured
