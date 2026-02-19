"""
Tests for POST /api/v1/conversation/chat — guarded pre-submission chat mode.

Tests cover:
  - small_talk intent (greeting)
  - help intent (service listing)
  - form_selection intent (form name mentioned)
  - out_of_scope guard (unrelated question)
  - Requires JWT authentication (chat without token → 403)
"""

import pytest
from fastapi.testclient import TestClient

from app.models import Bank, Form, FormSection, FormField


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def get_token(client: TestClient) -> str:
    """Create a user via KYC and return the JWT."""
    resp = client.post("/api/v1/kyc/submit", json={
        "aadhaar": "2222 3333 4444",
        "pan": "ZZZZZ9999Z",
    })
    assert resp.status_code == 200, resp.text
    return resp.json()["access_token"]


def seed_bank_and_form(db) -> tuple[int, int]:
    """Seed a Bank + Form for form_selection tests."""
    bank = db.query(Bank).filter(Bank.code == "SBI").first()
    if not bank:
        bank = Bank(name="State Bank of India", code="SBI", is_active=True)
        db.add(bank)
        db.flush()

    existing = db.query(Form).filter(
        Form.bank_id == bank.id, Form.code == "account_opening"
    ).first()
    if not existing:
        form = Form(
            bank_id=bank.id,
            name="Savings Account Opening",
            code="account_opening",
            is_active=True,
        )
        db.add(form)
        db.commit()
        return bank.id, form.id

    db.commit()
    return bank.id, existing.id


def chat(client, message, token):
    return client.post(
        "/api/v1/conversation/chat",
        json={"message": message},
        headers={"Authorization": f"Bearer {token}"},
    )


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestChatSmallTalk:
    def test_hello_returns_small_talk(self, client: TestClient, db_session):
        token = get_token(client)
        resp = chat(client, "hello", token)
        assert resp.status_code == 200
        data = resp.json()
        assert data["intent"] == "small_talk"
        assert len(data["message"]) > 0

    def test_how_are_you_returns_small_talk(self, client: TestClient, db_session):
        token = get_token(client)
        resp = chat(client, "how are you", token)
        assert resp.status_code == 200
        assert resp.json()["intent"] == "small_talk"

    def test_goodbye_returns_small_talk(self, client: TestClient, db_session):
        token = get_token(client)
        resp = chat(client, "goodbye", token)
        assert resp.status_code == 200
        assert resp.json()["intent"] == "small_talk"


class TestChatHelp:
    def test_help_returns_help_intent(self, client: TestClient, db_session):
        seed_bank_and_form(db_session)
        token = get_token(client)
        resp = chat(client, "help", token)
        assert resp.status_code == 200
        data = resp.json()
        assert data["intent"] == "help"
        # available_forms may be empty if no forms seeded, but intent must be correct
        assert "message" in data

    def test_what_can_you_do_returns_help(self, client: TestClient, db_session):
        token = get_token(client)
        resp = chat(client, "what can you do", token)
        assert resp.status_code == 200
        assert resp.json()["intent"] == "help"


class TestChatFormSelection:
    def test_account_opening_intent(self, client: TestClient, db_session):
        seed_bank_and_form(db_session)
        token = get_token(client)
        resp = chat(client, "I want to open a savings account", token)
        assert resp.status_code == 200
        data = resp.json()
        assert data["intent"] == "form_selection"
        assert len(data["available_forms"]) > 0

    def test_aadhaar_seeding_intent(self, client: TestClient, db_session):
        bank = db_session.query(Bank).filter(Bank.code == "SBI").first()
        if not bank:
            bank = Bank(name="State Bank of India", code="SBI", is_active=True)
            db_session.add(bank)
            db_session.flush()
        existing = db_session.query(Form).filter(
            Form.bank_id == bank.id, Form.code == "aadhaar_seeding"
        ).first()
        if not existing:
            form = Form(bank_id=bank.id, name="Aadhaar Seeding", code="aadhaar_seeding", is_active=True)
            db_session.add(form)
        db_session.commit()

        token = get_token(client)
        resp = chat(client, "link my aadhaar to bank account", token)
        assert resp.status_code == 200
        data = resp.json()
        assert data["intent"] == "form_selection"


class TestChatOutOfScope:
    def test_stock_price_is_out_of_scope(self, client: TestClient, db_session):
        token = get_token(client)
        resp = chat(client, "What is the stock price of Reliance?", token)
        assert resp.status_code == 200
        data = resp.json()
        assert data["intent"] == "out_of_scope"

    def test_random_question_is_out_of_scope(self, client: TestClient, db_session):
        token = get_token(client)
        resp = chat(client, "Tell me a joke", token)
        assert resp.status_code == 200
        assert resp.json()["intent"] == "out_of_scope"


class TestChatAuth:
    def test_requires_auth(self, client: TestClient):
        resp = client.post(
            "/api/v1/conversation/chat",
            json={"message": "hello"},
        )
        assert resp.status_code == 403

    def test_empty_message_rejected(self, client: TestClient, db_session):
        token = get_token(client)
        resp = client.post(
            "/api/v1/conversation/chat",
            json={"message": ""},
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 422  # Pydantic min_length=1 enforced
