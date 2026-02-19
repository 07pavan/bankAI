"""
Tests for the Conversation API — voice agent state machine.

Tests cover:
  - POST /api/v1/conversation/next returns first question
  - Saves answer and advances to next field
  - Validates bad input (pattern mismatch)
  - Transitions to REVIEW when all fields answered
  - Full flow: FILLING_FORM → REVIEW → COMPLETE
  - Requires authentication
"""

import pytest
from fastapi.testclient import TestClient

from app.models import Bank, Form, FormSection, FormField, ConversationState
from app.core.security import create_access_token


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def create_user_and_submit_kyc(client: TestClient) -> tuple[int, str]:
    """Submit KYC and return (user_id, access_token)."""
    resp = client.post("/api/v1/kyc/submit", json={
        "aadhaar": "1234 5678 9012",
        "pan": "ABCDE1234F",
    })
    assert resp.status_code == 200
    data = resp.json()
    return data["user_id"], data["access_token"]


def seed_simple_form(db, num_fields: int = 2) -> tuple[int, int]:
    """
    Seed a bank + form with `num_fields` simple text fields.
    Uses a test-only form code ('test_simple_form') to avoid conflicts with
    the startup-seeded 'account_opening' form (which has 13 fields).
    Reuses existing SBI bank if already seeded by startup event.
    Returns (bank_id, form_id).
    """
    # Reuse existing bank if startup event already seeded it
    bank = db.query(Bank).filter(Bank.code == "SBI").first()
    if not bank:
        bank = Bank(name="State Bank of India", code="SBI", is_active=True)
        db.add(bank)
        db.flush()

    # Always create a fresh test form with the exact num_fields requested
    form = Form(
        bank_id=bank.id,
        name="Test Simple Form",
        code="test_simple_form",
        is_active=True,
    )
    db.add(form)
    db.flush()

    section = FormSection(form_id=form.id, name="Personal Info", order_index=0)
    db.add(section)
    db.flush()

    field_defs = [
        {"field_key": "full_name", "label": "Full Name", "field_type": "text",
         "required": True, "validation_rule": {"min_length": 2}, "order_index": 0},
        {"field_key": "mobile", "label": "Mobile Number", "field_type": "text",
         "required": True, "validation_rule": {"pattern": r"^\d{10}$"}, "order_index": 1},
        {"field_key": "city", "label": "City", "field_type": "text",
         "required": True, "validation_rule": None, "order_index": 2},
    ]

    for f in field_defs[:num_fields]:
        db.add(FormField(
            form_id=form.id,
            section_id=section.id,
            field_key=f["field_key"],
            label=f["label"],
            field_type=f["field_type"],
            required=f["required"],
            validation_rule=f.get("validation_rule"),
            order_index=f["order_index"],
            is_active=True,
        ))

    db.commit()
    return bank.id, form.id


def start_submission(client, form_id, token) -> int:
    """Create a submission via POST /api/v1/submissions/start."""
    resp = client.post(
        "/api/v1/submissions/start",
        json={"form_id": form_id},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 201, f"Expected 201, got {resp.status_code}: {resp.text}"
    return resp.json()["id"]


def next_turn(client, sub_id, message, token) -> dict:
    """Send one conversation turn via POST /api/v1/conversation/next."""
    resp = client.post(
        "/api/v1/conversation/next",
        json={"submission_id": sub_id, "message": message},
        headers={"Authorization": f"Bearer {token}"},
    )
    return resp


# ---------------------------------------------------------------------------
# Test: First question returned
# ---------------------------------------------------------------------------

class TestConversationFirstQuestion:
    def test_first_turn_returns_next_question(self, client: TestClient, db_session):
        """
        After starting a submission, the first conversation turn should
        return the question for field[0] (full_name).
        """
        _, form_id = seed_simple_form(db_session, num_fields=2)
        _, token = create_user_and_submit_kyc(client)
        sub_id = start_submission(client, form_id, token)

        resp = next_turn(client, sub_id, "Ravi Kumar", token)
        assert resp.status_code == 200
        data = resp.json()

        assert "next_question" in data
        assert "field_key" in data
        assert data["status"] == "in_progress"
        # The answered field should be full_name
        assert data["field_key"] == "full_name"


# ---------------------------------------------------------------------------
# Test: Answer saves and advances
# ---------------------------------------------------------------------------

class TestConversationAdvances:
    def test_second_turn_advances_to_next_field(self, client: TestClient, db_session):
        """
        After answering field[0], the next turn should ask for field[1].
        """
        _, form_id = seed_simple_form(db_session, num_fields=2)
        _, token = create_user_and_submit_kyc(client)
        sub_id = start_submission(client, form_id, token)

        # Answer field[0] = full_name
        resp1 = next_turn(client, sub_id, "Ravi Kumar", token)
        assert resp1.status_code == 200
        assert resp1.json()["field_key"] == "full_name"

        # The next question should mention mobile (field[1])
        next_q = resp1.json()["next_question"].lower()
        assert "mobile" in next_q or "next" in next_q

    def test_field_value_persisted_in_submission(self, client: TestClient, db_session):
        """
        After answering a field via conversation, the answer should appear
        in GET /api/v1/submissions/{id}.
        """
        _, form_id = seed_simple_form(db_session, num_fields=2)
        _, token = create_user_and_submit_kyc(client)
        headers = {"Authorization": f"Bearer {token}"}
        sub_id = start_submission(client, form_id, token)

        next_turn(client, sub_id, "Ravi Kumar", token)

        get_resp = client.get(f"/api/v1/submissions/{sub_id}", headers=headers)
        assert get_resp.status_code == 200
        answered_keys = [d["field_key"] for d in get_resp.json()["data"]]
        assert "full_name" in answered_keys


# ---------------------------------------------------------------------------
# Test: Validation enforced by backend
# ---------------------------------------------------------------------------

class TestConversationValidation:
    def test_invalid_pattern_returns_422(self, client: TestClient, db_session):
        """
        Sending a bad mobile number (not 10 digits) should return 422.
        The backend enforces validation — the AI cannot bypass it.
        """
        _, form_id = seed_simple_form(db_session, num_fields=2)
        _, token = create_user_and_submit_kyc(client)
        sub_id = start_submission(client, form_id, token)

        # Answer field[0] correctly
        next_turn(client, sub_id, "Ravi Kumar", token)

        # Now answer field[1] (mobile) with an invalid value
        resp = next_turn(client, sub_id, "not-a-phone-number", token)
        assert resp.status_code == 422

    def test_empty_required_field_returns_422(self, client: TestClient, db_session):
        """Empty answer for a required field should fail validation."""
        _, form_id = seed_simple_form(db_session, num_fields=1)
        _, token = create_user_and_submit_kyc(client)
        sub_id = start_submission(client, form_id, token)

        resp = next_turn(client, sub_id, "   ", token)
        assert resp.status_code == 422


# ---------------------------------------------------------------------------
# Test: Transition to REVIEW state
# ---------------------------------------------------------------------------

class TestConversationReview:
    def test_all_fields_answered_transitions_to_review(self, client: TestClient, db_session):
        """
        After answering all fields, the agent should enter REVIEW state
        and the response should indicate in_progress (waiting for confirmation).
        """
        _, form_id = seed_simple_form(db_session, num_fields=2)
        _, token = create_user_and_submit_kyc(client)
        sub_id = start_submission(client, form_id, token)

        # Answer field[0]
        resp1 = next_turn(client, sub_id, "Ravi Kumar", token)
        assert resp1.status_code == 200

        # Answer field[1] (mobile — valid 10 digits)
        resp2 = next_turn(client, sub_id, "9876543210", token)
        assert resp2.status_code == 200
        data = resp2.json()

        # Should be in REVIEW — still in_progress, not completed
        assert data["status"] == "in_progress"
        # Review message should mention confirm or summary
        msg = data["next_question"].lower()
        assert any(word in msg for word in ["confirm", "summary", "submit", "review"])


# ---------------------------------------------------------------------------
# Test: Full state machine flow
# ---------------------------------------------------------------------------

class TestConversationFullFlow:
    def test_filling_form_to_complete(self, client: TestClient, db_session):
        """
        Full flow: answer all fields → REVIEW → confirm → COMPLETE.
        """
        _, form_id = seed_simple_form(db_session, num_fields=2)
        _, token = create_user_and_submit_kyc(client)
        headers = {"Authorization": f"Bearer {token}"}
        sub_id = start_submission(client, form_id, token)

        # Step 1: Answer field[0] = full_name
        r1 = next_turn(client, sub_id, "Ravi Kumar", token)
        assert r1.status_code == 200
        assert r1.json()["status"] == "in_progress"

        # Step 2: Answer field[1] = mobile (valid)
        r2 = next_turn(client, sub_id, "9876543210", token)
        assert r2.status_code == 200
        # Now in REVIEW state — still in_progress
        assert r2.json()["status"] == "in_progress"

        # Step 3: Confirm — triggers COMPLETE
        r3 = next_turn(client, sub_id, "confirm", token)
        assert r3.status_code == 200
        assert r3.json()["status"] == "completed"

        # Verify submission is marked completed in DB
        get_resp = client.get(f"/api/v1/submissions/{sub_id}", headers=headers)
        assert get_resp.json()["status"] == "completed"

    def test_rejection_in_review_restarts_form(self, client: TestClient, db_session):
        """
        Saying 'no' in REVIEW state should restart from field[0].
        """
        _, form_id = seed_simple_form(db_session, num_fields=2)
        _, token = create_user_and_submit_kyc(client)
        sub_id = start_submission(client, form_id, token)

        # Answer both fields
        next_turn(client, sub_id, "Ravi Kumar", token)
        next_turn(client, sub_id, "9876543210", token)

        # Reject in REVIEW
        r = next_turn(client, sub_id, "no, change something", token)
        assert r.status_code == 200
        data = r.json()
        assert data["status"] == "in_progress"
        # Should ask for field[0] again
        assert "full name" in data["next_question"].lower() or "name" in data["next_question"].lower()


# ---------------------------------------------------------------------------
# Test: Auth enforcement
# ---------------------------------------------------------------------------

class TestConversationAuth:
    def test_requires_auth(self, client: TestClient):
        resp = client.post(
            "/api/v1/conversation/next",
            json={"submission_id": 1, "message": "hello"},
        )
        assert resp.status_code == 403

    def test_cannot_access_other_users_submission(self, client: TestClient, db_session):
        _, form_id = seed_simple_form(db_session, num_fields=1)
        _, token = create_user_and_submit_kyc(client)
        sub_id = start_submission(client, form_id, token)

        other_token = create_access_token({"sub": "9999"})
        resp = next_turn(client, sub_id, "hello", other_token)
        assert resp.status_code == 403
