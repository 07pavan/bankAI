"""
Tests for Submissions API — lifecycle endpoints.
Uses in-memory SQLite via conftest.py fixtures.

Updated for new API contracts:
  POST /api/v1/submissions/start    (was POST /api/v1/submissions)
  POST /api/v1/submissions/complete  body: { "submission_id": <int> }
"""

import pytest
from fastapi.testclient import TestClient

from app.models import Bank, Form, FormSection, FormField, Submission, SubmissionStatus
from app.core.security import create_access_token


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def auth_headers(user_id: int = 1) -> dict:
    token = create_access_token({"sub": str(user_id)})
    return {"Authorization": f"Bearer {token}"}


def seed_form_with_fields(db, required_fields: list[dict] = None) -> tuple[int, int]:
    """
    Seed a bank + form with the given fields.
    Reuses existing SBI bank if already seeded by startup event.
    Uses a unique test form code to avoid conflicts with startup-seeded forms.
    Returns (bank_id, form_id).
    """
    # Reuse existing bank if startup event already seeded it
    bank = db.query(Bank).filter(Bank.code == "SBI").first()
    if not bank:
        bank = Bank(name="State Bank of India", code="SBI", is_active=True)
        db.add(bank)
        db.flush()

    form = Form(
        bank_id=bank.id,
        name="Test Form",
        code="test_form",
        is_active=True,
    )
    db.add(form)
    db.flush()

    section = FormSection(form_id=form.id, name="Personal Info", order_index=0)
    db.add(section)
    db.flush()

    fields = required_fields or [
        {"field_key": "full_name", "label": "Full Name", "field_type": "text", "required": True, "order_index": 0},
        {"field_key": "mobile", "label": "Mobile Number", "field_type": "text", "required": True,
         "validation_rule": {"pattern": r"^\d{10}$"}, "order_index": 1},
        {"field_key": "email", "label": "Email", "field_type": "text", "required": False, "order_index": 2},
    ]

    for f in fields:
        field = FormField(
            form_id=form.id,
            section_id=section.id,
            field_key=f["field_key"],
            label=f["label"],
            field_type=f["field_type"],
            required=f.get("required", True),
            validation_rule=f.get("validation_rule"),
            options=f.get("options"),
            order_index=f["order_index"],
            is_active=True,
        )
        db.add(field)

    db.commit()
    return bank.id, form.id


def create_user_and_submit_kyc(client: TestClient) -> tuple[int, str]:
    """Submit KYC and return (user_id, access_token)."""
    resp = client.post("/api/v1/kyc/submit", json={
        "aadhaar": "1234 5678 9012",
        "pan": "ABCDE1234F",
    })
    assert resp.status_code == 200
    data = resp.json()
    return data["user_id"], data["access_token"]


# ---------------------------------------------------------------------------
# Tests — POST /api/v1/submissions/start
# ---------------------------------------------------------------------------

class TestStartSubmission:
    def test_creates_draft_submission(self, client: TestClient, db_session):
        _, form_id = seed_form_with_fields(db_session)
        user_id, token = create_user_and_submit_kyc(client)
        resp = client.post(
            "/api/v1/submissions/start",
            json={"form_id": form_id},
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 201
        data = resp.json()
        assert data["status"] == "draft"
        assert data["current_field_index"] == 0
        assert data["form_id"] == form_id
        assert data["user_id"] == user_id

    def test_invalid_form_returns_404(self, client: TestClient, db_session):
        user_id, token = create_user_and_submit_kyc(client)
        resp = client.post(
            "/api/v1/submissions/start",
            json={"form_id": 9999},
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 404

    def test_requires_auth(self, client: TestClient, db_session):
        _, form_id = seed_form_with_fields(db_session)
        resp = client.post("/api/v1/submissions/start", json={"form_id": form_id})
        assert resp.status_code == 403


# ---------------------------------------------------------------------------
# Tests — GET /api/v1/submissions/{id}
# ---------------------------------------------------------------------------

class TestGetSubmission:
    def test_returns_submission_with_empty_data(self, client: TestClient, db_session):
        _, form_id = seed_form_with_fields(db_session)
        user_id, token = create_user_and_submit_kyc(client)
        headers = {"Authorization": f"Bearer {token}"}

        create_resp = client.post("/api/v1/submissions/start", json={"form_id": form_id}, headers=headers)
        sub_id = create_resp.json()["id"]

        resp = client.get(f"/api/v1/submissions/{sub_id}", headers=headers)
        assert resp.status_code == 200
        assert resp.json()["data"] == []

    def test_other_user_cannot_access(self, client: TestClient, db_session):
        _, form_id = seed_form_with_fields(db_session)
        user_id, token = create_user_and_submit_kyc(client)
        headers = {"Authorization": f"Bearer {token}"}

        create_resp = client.post("/api/v1/submissions/start", json={"form_id": form_id}, headers=headers)
        sub_id = create_resp.json()["id"]

        other_token = create_access_token({"sub": "9999"})
        resp = client.get(
            f"/api/v1/submissions/{sub_id}",
            headers={"Authorization": f"Bearer {other_token}"},
        )
        assert resp.status_code == 403


# ---------------------------------------------------------------------------
# Tests — GET /api/v1/submissions (list)
# ---------------------------------------------------------------------------

class TestListSubmissions:
    def test_returns_user_submissions(self, client: TestClient, db_session):
        _, form_id = seed_form_with_fields(db_session)
        user_id, token = create_user_and_submit_kyc(client)
        headers = {"Authorization": f"Bearer {token}"}

        client.post("/api/v1/submissions/start", json={"form_id": form_id}, headers=headers)
        client.post("/api/v1/submissions/start", json={"form_id": form_id}, headers=headers)

        resp = client.get("/api/v1/submissions", headers=headers)
        assert resp.status_code == 200
        assert len(resp.json()) == 2

    def test_requires_auth(self, client: TestClient):
        resp = client.get("/api/v1/submissions")
        assert resp.status_code == 403


# ---------------------------------------------------------------------------
# Tests — POST /api/v1/submissions/complete
# ---------------------------------------------------------------------------

class TestCompleteSubmission:
    def _setup_with_all_required_answered(self, client, db_session):
        _, form_id = seed_form_with_fields(db_session)
        user_id, token = create_user_and_submit_kyc(client)
        headers = {"Authorization": f"Bearer {token}"}
        create_resp = client.post("/api/v1/submissions/start", json={"form_id": form_id}, headers=headers)
        sub_id = create_resp.json()["id"]
        # Use conversation/next to answer required fields
        client.post("/api/v1/conversation/next",
                    json={"submission_id": sub_id, "message": "Ravi Kumar"}, headers=headers)
        client.post("/api/v1/conversation/next",
                    json={"submission_id": sub_id, "message": "9876543210"}, headers=headers)
        return sub_id, headers, token

    def test_completes_when_all_required_answered(self, client: TestClient, db_session):
        sub_id, headers, _ = self._setup_with_all_required_answered(client, db_session)
        resp = client.post(
            "/api/v1/submissions/complete",
            json={"submission_id": sub_id},
            headers=headers,
        )
        assert resp.status_code == 200
        assert resp.json()["status"] == "completed"

    def test_fails_when_required_field_missing(self, client: TestClient, db_session):
        _, form_id = seed_form_with_fields(db_session)
        user_id, token = create_user_and_submit_kyc(client)
        headers = {"Authorization": f"Bearer {token}"}
        create_resp = client.post("/api/v1/submissions/start", json={"form_id": form_id}, headers=headers)
        sub_id = create_resp.json()["id"]
        # Only answer one of two required fields
        client.post("/api/v1/conversation/next",
                    json={"submission_id": sub_id, "message": "Ravi Kumar"}, headers=headers)
        resp = client.post(
            "/api/v1/submissions/complete",
            json={"submission_id": sub_id},
            headers=headers,
        )
        assert resp.status_code == 422

    def test_double_complete_returns_409(self, client: TestClient, db_session):
        sub_id, headers, _ = self._setup_with_all_required_answered(client, db_session)
        client.post("/api/v1/submissions/complete", json={"submission_id": sub_id}, headers=headers)
        resp = client.post("/api/v1/submissions/complete", json={"submission_id": sub_id}, headers=headers)
        assert resp.status_code == 409

    def test_other_user_cannot_complete(self, client: TestClient, db_session):
        sub_id, _, _ = self._setup_with_all_required_answered(client, db_session)
        other_token = create_access_token({"sub": "9999"})
        resp = client.post(
            "/api/v1/submissions/complete",
            json={"submission_id": sub_id},
            headers={"Authorization": f"Bearer {other_token}"},
        )
        assert resp.status_code == 403

    def test_requires_auth(self, client: TestClient):
        resp = client.post("/api/v1/submissions/complete", json={"submission_id": 1})
        assert resp.status_code == 403
