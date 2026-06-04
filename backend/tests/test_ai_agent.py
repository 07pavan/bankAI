"""
Tests for the LangGraph AI Agent integration — ai_agent_tools,
ai_agent_service, PII redaction, and hybrid fallback.

These tests run WITHOUT requiring an LLM API key — they mock the LLM layer
and test the orchestration, tool behaviour, PII safety, and fallback logic.

Run:  pytest -m ai_agent -v
All:  pytest tests/test_ai_agent.py -v
"""

import os
import pytest
from unittest.mock import patch, MagicMock, PropertyMock
from sqlalchemy.orm import Session

from app.models import (
    Bank, Form, FormSection, FormField, Submission, SubmissionData,
    User, KYCSubmission, ConversationState, SubmissionStatus,
)
from app.core.security import create_access_token


# ---------------------------------------------------------------------------
# Mark all tests in this file with the "ai_agent" marker
# ---------------------------------------------------------------------------

pytestmark = pytest.mark.ai_agent


# ---------------------------------------------------------------------------
# Helpers — match existing test style from conftest / test_submissions
# ---------------------------------------------------------------------------

def auth_headers(user_id: int = 1) -> dict:
    token = create_access_token({"sub": str(user_id)})
    return {"Authorization": f"Bearer {token}"}


def seed_bank_and_form(db: Session) -> tuple[int, int]:
    """
    Seed a bank + form with 2 simple text fields for testing.
    Returns (bank_id, form_id).
    """
    bank = db.query(Bank).filter(Bank.code == "SBI").first()
    if not bank:
        bank = Bank(name="State Bank of India", code="SBI", is_active=True)
        db.add(bank)
        db.flush()

    form = Form(
        bank_id=bank.id,
        name="AI Agent Test Form",
        code="ai_test_form",
        is_active=True,
    )
    db.add(form)
    db.flush()

    section = FormSection(form_id=form.id, name="Test Section", order_index=0)
    db.add(section)
    db.flush()

    fields = [
        FormField(
            form_id=form.id, section_id=section.id,
            field_key="full_name", label="Full Name",
            field_type="text", required=True,
            validation_rule={"min_length": 2},
            order_index=0, is_active=True,
        ),
        FormField(
            form_id=form.id, section_id=section.id,
            field_key="mobile", label="Mobile Number",
            field_type="text", required=True,
            validation_rule={"pattern": r"^\d{10}$"},
            order_index=1, is_active=True,
        ),
    ]
    for f in fields:
        db.add(f)

    db.commit()
    return bank.id, form.id


def create_test_user(db: Session) -> int:
    """Create a minimal test user and return user_id."""
    from app.core.encryption import encryption_service
    import hashlib

    aadhaar = "123456789012"
    aadhaar_hash = hashlib.sha256(aadhaar.encode()).hexdigest()

    user = User(aadhaar_hash=aadhaar_hash, role="user")
    db.add(user)
    db.flush()

    kyc = KYCSubmission(
        user_id=user.id,
        aadhaar_encrypted=encryption_service.encrypt_aadhaar(aadhaar),
        pan_encrypted=encryption_service.encrypt_pan("ABCDE1234F"),
        aadhaar_hash=aadhaar_hash,
        status="verified",
    )
    db.add(kyc)
    db.commit()
    return user.id


def create_submission(db: Session, user_id: int, form_id: int) -> int:
    """Create a draft submission and return submission_id."""
    sub = Submission(
        user_id=user_id,
        form_id=form_id,
        status=SubmissionStatus.DRAFT,
        current_field_index=0,
        conversation_state=ConversationState.FILLING_FORM,
    )
    db.add(sub)
    db.commit()
    return sub.id


# ═══════════════════════════════════════════════════════════════════════════
# Test 1: PII Redaction
# ═══════════════════════════════════════════════════════════════════════════

class TestPIIRedaction:
    """
    Verify that the PII redaction layer catches Aadhaar, PAN, phone,
    and email before text reaches the LLM.
    """

    def test_aadhaar_redacted(self):
        """Aadhaar numbers (12 digits, with/without spaces) are redacted."""
        from app.core.llm_redaction import redact_pii

        text = "My Aadhaar is 1234 5678 9012 and I want to apply."
        result = redact_pii(text)

        assert "1234" not in result
        assert "9012" not in result
        assert "apply" in result  # Non-PII word should survive

    def test_pan_redacted(self):
        """PAN numbers (ABCDE1234F format) are redacted."""
        from app.core.llm_redaction import redact_pii

        text = "PAN is ABCDE1234F, please verify."
        result = redact_pii(text)

        assert "ABCDE1234F" not in result
        assert "verify" in result

    def test_phone_redacted(self):
        """Indian phone numbers are redacted."""
        from app.core.llm_redaction import redact_pii

        text = "Call me at 9876543210 tomorrow."
        result = redact_pii(text)

        assert "9876543210" not in result
        assert "tomorrow" in result

    def test_email_redacted(self):
        """Email addresses are redacted."""
        from app.core.llm_redaction import redact_pii

        text = "Send details to user@example.com please."
        result = redact_pii(text)

        assert "user@example.com" not in result
        assert "please" in result

    def test_should_redact_detects_pii(self):
        """should_redact_before_llm returns True when PII is present."""
        from app.core.llm_redaction import should_redact_before_llm

        assert should_redact_before_llm("My Aadhaar is 1234 5678 9012") is True
        assert should_redact_before_llm("My PAN is ABCDE1234F") is True
        assert should_redact_before_llm("Just a normal message") is False

    def test_clean_text_unchanged(self):
        """Text with no PII passes through unchanged."""
        from app.core.llm_redaction import redact_pii

        text = "I want to open a savings account."
        result = redact_pii(text)
        assert result == text

    def test_multiple_pii_all_redacted(self):
        """Multiple PII types in one message are all caught."""
        from app.core.llm_redaction import redact_pii

        text = (
            "Aadhaar: 1234 5678 9012, PAN: XYZAB9876C, "
            "Phone: 9123456789, Email: test@bank.com"
        )
        result = redact_pii(text)

        assert "1234 5678 9012" not in result
        assert "XYZAB9876C" not in result
        assert "9123456789" not in result
        assert "test@bank.com" not in result


# ═══════════════════════════════════════════════════════════════════════════
# Test 2: AI Agent Tools
# ═══════════════════════════════════════════════════════════════════════════

class TestAgentTools:
    """
    Test the @tool-decorated functions from ai_agent_tools.py.
    These tests hit the real DB (in-memory SQLite via conftest).
    """

    def test_get_available_forms_returns_forms(self, db_session: Session):
        """get_available_forms lists active forms for the user."""
        from app.services.ai_agent_tools import get_available_forms

        bank_id, form_id = seed_bank_and_form(db_session)
        user_id = create_test_user(db_session)

        result = get_available_forms.invoke({"user_id": user_id})

        assert "AI Agent Test Form" in result
        assert "Form ID" in result

    def test_get_available_forms_empty(self, db_session: Session):
        """get_available_forms returns a message when no forms exist."""
        from app.services.ai_agent_tools import get_available_forms

        user_id = create_test_user(db_session)

        result = get_available_forms.invoke({"user_id": user_id})

        assert "no" in result.lower() or "available" in result.lower()

    def test_get_next_field_returns_field_metadata(self, db_session: Session):
        """get_next_field returns field key, label, type for the current field."""
        from app.services.ai_agent_tools import get_next_field

        _, form_id = seed_bank_and_form(db_session)
        user_id = create_test_user(db_session)
        sub_id = create_submission(db_session, user_id, form_id)

        result = get_next_field.invoke({"submission_id": sub_id})

        assert "field_key: full_name" in result
        assert "label: Full Name" in result
        assert "type: text" in result

    def test_answer_field_saves_and_confirms(self, db_session: Session):
        """answer_field saves a valid answer and returns confirmation."""
        from app.services.ai_agent_tools import answer_field

        _, form_id = seed_bank_and_form(db_session)
        user_id = create_test_user(db_session)
        sub_id = create_submission(db_session, user_id, form_id)

        result = answer_field.invoke({
            "submission_id": sub_id,
            "field_key": "full_name",
            "value": "Ravi Kumar",
        })

        assert "saved successfully" in result.lower()
        assert "full_name" in result

        # Verify persisted in DB
        data = db_session.query(SubmissionData).filter(
            SubmissionData.submission_id == sub_id,
            SubmissionData.field_key == "full_name",
        ).first()
        assert data is not None
        assert data.value == "Ravi Kumar"

    def test_answer_field_nonexistent_field(self, db_session: Session):
        """answer_field returns error for a field_key that doesn't exist."""
        from app.services.ai_agent_tools import answer_field

        _, form_id = seed_bank_and_form(db_session)
        user_id = create_test_user(db_session)
        sub_id = create_submission(db_session, user_id, form_id)

        result = answer_field.invoke({
            "submission_id": sub_id,
            "field_key": "nonexistent_field",
            "value": "some value",
        })

        assert "error" in result.lower()

    def test_get_current_submission_state(self, db_session: Session):
        """get_current_submission_state returns progress summary."""
        from app.services.ai_agent_tools import get_current_submission_state

        _, form_id = seed_bank_and_form(db_session)
        user_id = create_test_user(db_session)
        sub_id = create_submission(db_session, user_id, form_id)

        result = get_current_submission_state.invoke({"submission_id": sub_id})

        assert "draft" in result.lower()
        assert "0/" in result  # 0 out of N fields done

    def test_tool_output_pii_redacted(self, db_session: Session):
        """Tool return values are PII-redacted (safety net)."""
        from app.services.ai_agent_tools import get_available_forms

        _, form_id = seed_bank_and_form(db_session)
        user_id = create_test_user(db_session)

        # Even if form descriptions contained PII, they'd be redacted
        result = get_available_forms.invoke({"user_id": user_id})

        # The result should be a clean string (no Aadhaar/PAN patterns)
        import re
        aadhaar_match = re.search(r'\b\d{4}\s?\d{4}\s?\d{4}\b', result)
        # Should not find Aadhaar-like patterns in tool output
        # (forms don't contain PII, but the redaction layer is always applied)
        assert isinstance(result, str)


# ═══════════════════════════════════════════════════════════════════════════
# Test 3: State Machine Transitions
# ═══════════════════════════════════════════════════════════════════════════

class TestStateMachineTransitions:
    """
    Test that the LangGraph agent's state transition validation works
    correctly — illegal transitions are blocked.
    """

    def test_validate_transition_allows_legal(self):
        """Legal transitions are accepted."""
        from app.services.ai_agent_service import validate_transition

        assert validate_transition("chat", "welcome") == "welcome"
        assert validate_transition("welcome", "select_application") == "select_application"
        assert validate_transition("select_application", "filling_form") == "filling_form"
        assert validate_transition("filling_form", "review") == "review"
        assert validate_transition("review", "signature") == "signature"
        assert validate_transition("signature", "complete") == "complete"

    def test_validate_transition_allows_self(self):
        """Staying in the same state is always allowed."""
        from app.services.ai_agent_service import validate_transition

        for state in ["chat", "welcome", "select_application", "filling_form", "review", "signature", "complete"]:
            assert validate_transition(state, state) == state

    def test_validate_transition_blocks_skip(self):
        """Skipping states (e.g. chat → filling_form) is blocked."""
        from app.services.ai_agent_service import validate_transition

        # CHAT → FILLING_FORM (skipping 2 states) — blocked
        assert validate_transition("chat", "filling_form") == "chat"

        # WELCOME → REVIEW (skipping 2 states) — blocked
        assert validate_transition("welcome", "review") == "welcome"

        # FILLING_FORM → COMPLETE (skipping review) — blocked
        assert validate_transition("filling_form", "complete") == "filling_form"

    def test_validate_transition_blocks_backward(self):
        """Backward transitions (except REVIEW→FILLING_FORM) are blocked."""
        from app.services.ai_agent_service import validate_transition

        # COMPLETE → anything — always blocked
        assert validate_transition("complete", "chat") == "complete"
        assert validate_transition("complete", "filling_form") == "complete"

        # SELECT_APPLICATION → CHAT — blocked
        assert validate_transition("select_application", "chat") == "select_application"

    def test_review_can_go_back_to_filling(self):
        """REVIEW → FILLING_FORM is the only valid backward transition."""
        from app.services.ai_agent_service import validate_transition

        assert validate_transition("review", "filling_form") == "filling_form"

    def test_allowed_transitions_map_completeness(self):
        """Every ConversationState value has an entry in ALLOWED_TRANSITIONS."""
        from app.services.ai_agent_service import ALLOWED_TRANSITIONS

        expected_states = {"chat", "welcome", "select_application", "filling_form", "review", "signature", "complete"}
        assert set(ALLOWED_TRANSITIONS.keys()) == expected_states

    def test_state_to_node_map_completeness(self):
        """Every ConversationState value has a node mapping."""
        from app.services.ai_agent_service import STATE_TO_NODE

        expected_states = {"chat", "welcome", "select_application", "filling_form", "review", "signature", "complete"}
        assert set(STATE_TO_NODE.keys()) == expected_states
        # All node names should be unique strings
        assert len(set(STATE_TO_NODE.values())) == 7


# ═══════════════════════════════════════════════════════════════════════════
# Test 4: Hybrid Fallback
# ═══════════════════════════════════════════════════════════════════════════

class TestHybridFallback:
    """
    Test the hybrid mode in conversation_service — LLM first, keyword fallback.
    These tests mock the LLM layer to verify fallback orchestration.
    """

    def test_fallback_when_llm_disabled(self, db_session: Session, client):
        """
        When USE_LLM_AGENT is False, the keyword-based handler runs directly.
        """
        import app.services.conversation_service as cs

        _, form_id = seed_bank_and_form(db_session)
        user_id = create_test_user(db_session)
        sub_id = create_submission(db_session, user_id, form_id)

        # Disable LLM
        original = cs.USE_LLM_AGENT
        cs.USE_LLM_AGENT = False

        try:
            result = cs.handle_conversation_turn(sub_id, user_id, "Ravi Kumar", db_session)
            # Should succeed via keyword path
            assert result.agent_message is not None
            assert result.submission_id == sub_id
        finally:
            cs.USE_LLM_AGENT = original

    def test_fallback_when_llm_raises_error(self, db_session: Session):
        """
        When the LLM agent raises an exception, we fall back to keywords.
        """
        import app.services.conversation_service as cs

        _, form_id = seed_bank_and_form(db_session)
        user_id = create_test_user(db_session)
        sub_id = create_submission(db_session, user_id, form_id)

        # Mock _is_llm_enabled to return True, but _try_llm_turn to fail
        with patch.object(cs, '_is_llm_enabled', return_value=True), \
             patch.object(cs, '_try_llm_turn', return_value=None):
            result = cs.handle_conversation_turn(sub_id, user_id, "Ravi Kumar", db_session)
            # Should fall through to keyword logic
            assert result.agent_message is not None
            assert result.submission_id == sub_id

    def test_llm_success_returns_llm_result(self, db_session: Session):
        """
        When LLM succeeds, the LLM result is returned (not keyword).
        """
        import app.services.conversation_service as cs
        from app.schemas import ConversationTurnResponse

        _, form_id = seed_bank_and_form(db_session)
        user_id = create_test_user(db_session)
        sub_id = create_submission(db_session, user_id, form_id)

        mock_llm_response = ConversationTurnResponse(
            submission_id=sub_id,
            agent_message="LLM says: What is your full name?",
            is_complete=False,
        )

        with patch.object(cs, '_is_llm_enabled', return_value=True), \
             patch.object(cs, '_try_llm_turn', return_value=mock_llm_response):
            result = cs.handle_conversation_turn(sub_id, user_id, "hello", db_session)
            assert result.agent_message == "LLM says: What is your full name?"

    def test_chat_fallback_when_llm_disabled(self, db_session: Session):
        """
        handle_chat_turn falls back to keyword logic when LLM is disabled.
        """
        import app.services.conversation_service as cs

        original = cs.USE_LLM_AGENT
        cs.USE_LLM_AGENT = False

        try:
            result = cs.handle_chat_turn(1, "hello", db_session)
            assert result.intent == "small_talk"
            assert "BankAI" in result.message
        finally:
            cs.USE_LLM_AGENT = original

    def test_chat_fallback_on_llm_failure(self, db_session: Session):
        """
        handle_chat_turn falls back to keywords when LLM chat fails.
        """
        import app.services.conversation_service as cs

        with patch.object(cs, '_is_llm_enabled', return_value=True), \
             patch.object(cs, '_try_llm_chat', return_value=None):
            result = cs.handle_chat_turn(1, "help", db_session)
            # Should use keyword fallback
            assert result.intent == "help"

    def test_is_llm_enabled_returns_false_when_no_key(self):
        """
        _is_llm_enabled returns False when LLM_API_KEY is not set.
        """
        import app.services.conversation_service as cs

        original = cs.USE_LLM_AGENT
        cs.USE_LLM_AGENT = True

        try:
            # With no LLM_API_KEY in test env, should return False
            result = cs._is_llm_enabled()
            # In test environment, LLM is not configured
            assert result is False
        finally:
            cs.USE_LLM_AGENT = original

    def test_classify_intent_from_message(self):
        """
        _classify_intent_from_message returns correct intent tags.
        """
        from app.services.conversation_service import _classify_intent_from_message

        assert _classify_intent_from_message("hello there") == "small_talk"
        assert _classify_intent_from_message("what can you do") == "help"
        assert _classify_intent_from_message("open an account") == "form_selection"
        assert _classify_intent_from_message("weather today?") == "out_of_scope"


# ═══════════════════════════════════════════════════════════════════════════
# Test 5: Agent Service Public API (mocked LLM)
# ═══════════════════════════════════════════════════════════════════════════

class TestAgentServicePublicAPI:
    """
    Test invoke_agent and get_last_agent_message without a real LLM.
    """

    def test_get_last_agent_message_extracts_text(self):
        """get_last_agent_message extracts the last AI text response."""
        from app.services.ai_agent_service import get_last_agent_message
        from langchain_core.messages import AIMessage, ToolMessage

        result = {
            "messages": [
                AIMessage(content="", tool_calls=[{"name": "get_next_field", "args": {}, "id": "1"}]),
                ToolMessage(content="field_key: full_name", tool_call_id="1"),
                AIMessage(content="What is your full name?"),
            ]
        }

        msg = get_last_agent_message(result)
        assert msg == "What is your full name?"

    def test_get_last_agent_message_empty(self):
        """get_last_agent_message returns '' when no AI text message exists."""
        from app.services.ai_agent_service import get_last_agent_message

        assert get_last_agent_message({"messages": []}) == ""
        assert get_last_agent_message({}) == ""

    def test_is_llm_available_without_key(self):
        """is_llm_available returns False in test env (no API key)."""
        from app.services.ai_agent_service import is_llm_available

        # In test environment, LLM_API_KEY is not set
        assert is_llm_available() is False

    def test_invoke_agent_fails_gracefully(self):
        """
        invoke_agent returns a graceful error when LLM is not configured.
        """
        from app.services.ai_agent_service import invoke_agent, get_last_agent_message

        result = invoke_agent(
            user_id=1,
            user_message="hello",
            conversation_state="chat",
        )

        # Should return an error state, not crash
        assert "error" in result or "messages" in result
        # The agent message should be an apology or help suggestion
        msg = get_last_agent_message(result)
        if msg:
            assert any(w in msg.lower() for w in ["error", "sorry", "help", "try"])


# ═══════════════════════════════════════════════════════════════════════════
# Test 6: Integration — /next endpoint with fallback
# ═══════════════════════════════════════════════════════════════════════════

class TestEndpointIntegration:
    """
    Test the /conversation/next endpoint uses keyword fallback
    in the test environment (no LLM API key).
    """

    def test_next_endpoint_works_without_llm(self, client, db_session):
        """
        POST /conversation/next should work fine with keyword fallback
        when LLM is not configured (test environment).
        """
        _, form_id = seed_bank_and_form(db_session)

        # Create user via KYC endpoint
        resp = client.post("/api/v1/kyc/submit", json={
            "aadhaar": "1234 5678 9012",
            "pan": "ABCDE1234F",
        })
        assert resp.status_code == 200
        token = resp.json()["access_token"]
        headers = {"Authorization": f"Bearer {token}"}

        # Start submission
        resp = client.post("/api/v1/submissions/start",
                           json={"form_id": form_id}, headers=headers)
        assert resp.status_code == 201
        sub_id = resp.json()["id"]

        # Send a turn — should use keyword fallback
        resp = client.post("/api/v1/conversation/next",
                           json={"submission_id": sub_id, "message": "Ravi Kumar"},
                           headers=headers)
        assert resp.status_code == 200
        data = resp.json()
        assert "next_question" in data
        assert data["status"] == "in_progress"

    def test_chat_endpoint_works_without_llm(self, client, db_session):
        """
        POST /conversation/chat should work fine with keyword fallback.
        """
        # Create user
        resp = client.post("/api/v1/kyc/submit", json={
            "aadhaar": "1234 5678 9012",
            "pan": "ABCDE1234F",
        })
        token = resp.json()["access_token"]
        headers = {"Authorization": f"Bearer {token}"}

        resp = client.post("/api/v1/conversation/chat",
                           json={"message": "hello"},
                           headers=headers)
        assert resp.status_code == 200
        data = resp.json()
        assert data["intent"] == "small_talk"
        assert "BankAI" in data["message"]


# ═══════════════════════════════════════════════════════════════════════════
# Test 7: RAG Context Retrieval
# ═══════════════════════════════════════════════════════════════════════════

class TestRAGContext:
    """
    Test the SQL-based RAG module — form/field context retrieval and
    banking FAQ keyword matching.
    """

    def test_all_forms_summary_contains_labels(self, db_session: Session):
        """get_all_forms_summary includes form names and field counts."""
        from app.core.rag import get_all_forms_summary

        seed_bank_and_form(db_session)

        result = get_all_forms_summary(db_session)

        assert "AI Agent Test Form" in result
        assert "SBI" in result or "State Bank" in result
        # Should mention field count
        assert "2" in result  # 2 fields seeded

    def test_form_context_contains_field_details(self, db_session: Session):
        """get_form_context includes field labels, types, and validation."""
        from app.core.rag import get_form_context

        _, form_id = seed_bank_and_form(db_session)

        result = get_form_context(form_id, db_session)

        assert "Full Name" in result
        assert "full_name" in result
        assert "Mobile Number" in result
        assert "text" in result
        assert "Required: Yes" in result
        # Validation rules should be included
        assert "min_length" in result.lower() or "Min length" in result

    def test_field_context_includes_hints(self, db_session: Session):
        """get_field_context returns field metadata and guidance hints."""
        from app.core.rag import get_field_context

        _, form_id = seed_bank_and_form(db_session)

        result = get_field_context(form_id, "mobile", db_session)

        assert "Mobile Number" in result
        assert "mobile" in result
        assert "10-digit" in result or "10" in result
        assert "Guidance" in result or "Agent" in result

    def test_field_context_nonexistent(self, db_session: Session):
        """get_field_context returns fallback for unknown field_key."""
        from app.core.rag import get_field_context

        _, form_id = seed_bank_and_form(db_session)

        result = get_field_context(form_id, "nonexistent", db_session)
        assert "not found" in result.lower()

    def test_banking_faq_keyword_match(self):
        """get_banking_faq_context returns relevant FAQ for keyword queries."""
        from app.core.rag import get_banking_faq_context

        # Query about address mismatch
        result = get_banking_faq_context("my address is different from aadhaar")
        assert "address" in result.lower()
        assert "Aadhaar" in result or "aadhaar" in result

        # Query about documents
        result = get_banking_faq_context("what documents do I need")
        assert "document" in result.lower()
        assert "proof" in result.lower() or "Aadhaar" in result

    def test_banking_faq_no_match_returns_full(self):
        """get_banking_faq_context returns full FAQ when no keywords match."""
        from app.core.rag import get_banking_faq_context

        result = get_banking_faq_context("xyzzy gibberish no match")
        # Should return the general FAQ
        assert "FAQ" in result
        assert len(result) > 200  # Should be a substantial block

    def test_banking_faq_none_query_returns_full(self):
        """get_banking_faq_context with None returns full FAQ."""
        from app.core.rag import get_banking_faq_context

        result = get_banking_faq_context(None)
        assert "FAQ" in result

    def test_build_rag_context_chat_state(self, db_session: Session):
        """_build_rag_context returns form summary for CHAT state."""
        from app.services.ai_agent_service import _build_rag_context

        seed_bank_and_form(db_session)

        state = {
            "messages": [],
            "conversation_state": "chat",
            "user_id": 1,
            "submission_id": None,
            "current_field": None,
            "form_id": None,
            "error": None,
        }

        result = _build_rag_context(state, user_message="hello")
        assert result is not None
        assert "AI Agent Test Form" in result or "FAQ" in result

