"""
Tests for Forms API — form discovery endpoints.
Uses in-memory SQLite via conftest.py fixtures.

Updated for new API contracts:
  GET /api/v1/forms           → active forms for user's bank (auto-resolved)
  GET /api/v1/forms/{form_id} → full form structure
"""

import pytest
from fastapi.testclient import TestClient

from app.models import Bank, Form, FormSection, FormField
from app.core.security import create_access_token


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def auth_headers(user_id: int = 1) -> dict:
    token = create_access_token({"sub": str(user_id)})
    return {"Authorization": f"Bearer {token}"}


def seed_bank_and_forms(db, num_forms: int = 3) -> tuple[Bank, list[Form]]:
    """
    Return the bank and forms already seeded by the startup event.
    If not yet seeded (shouldn't happen with TestClient), creates them.
    """
    bank = db.query(Bank).filter(Bank.code == "SBI").first()
    if not bank:
        bank = Bank(name="State Bank of India", code="SBI", is_active=True)
        db.add(bank)
        db.flush()

    form_defs = [
        ("Account Opening", "account_opening", "Open a new account"),
        ("Aadhaar Seeding", "aadhaar_seeding", "Link Aadhaar to account"),
        ("Cheque Book Request", "cheque_book_request", "Request a cheque book"),
    ]

    forms = []
    for name, code, desc in form_defs[:num_forms]:
        existing = db.query(Form).filter(Form.bank_id == bank.id, Form.code == code).first()
        if existing:
            forms.append(existing)
        else:
            f = Form(bank_id=bank.id, name=name, code=code, description=desc, is_active=True)
            db.add(f)
            forms.append(f)
    db.flush()

    # Ensure forms[0] has at least one section and field for detail tests
    from app.models import FormSection as _FS, FormField as _FF
    if forms and not db.query(_FS).filter(_FS.form_id == forms[0].id).first():
        section = FormSection(form_id=forms[0].id, name="Personal Info", order_index=0)
        db.add(section)
        db.flush()

        field = FormField(
            form_id=forms[0].id,
            section_id=section.id,
            field_key="full_name",
            label="Full Name",
            field_type="text",
            required=True,
            order_index=0,
            is_active=True,
        )
        db.add(field)
    db.commit()

    return bank, forms


# ---------------------------------------------------------------------------
# Tests — GET /api/v1/forms  (list forms for user's bank)
# ---------------------------------------------------------------------------

class TestListForms:
    def test_returns_active_forms(self, client: TestClient, db_session):
        """Should return all 3 active forms for the seeded bank."""
        seed_bank_and_forms(db_session, num_forms=3)
        resp = client.get("/api/v1/forms", headers=auth_headers())
        assert resp.status_code == 200
        codes = {f["code"] for f in resp.json()}
        assert "account_opening" in codes
        assert "aadhaar_seeding" in codes
        assert "cheque_book_request" in codes

    def test_returns_exactly_three_forms(self, client: TestClient, db_session):
        """Seed data has exactly 3 forms."""
        seed_bank_and_forms(db_session, num_forms=3)
        resp = client.get("/api/v1/forms", headers=auth_headers())
        assert resp.status_code == 200
        assert len(resp.json()) == 3

    def test_inactive_form_not_returned(self, client: TestClient, db_session):
        """Inactive forms should be excluded."""
        _, forms = seed_bank_and_forms(db_session, num_forms=3)
        forms[2].is_active = False
        db_session.commit()

        resp = client.get("/api/v1/forms", headers=auth_headers())
        codes = {f["code"] for f in resp.json()}
        assert "cheque_book_request" not in codes
        assert len(resp.json()) == 2

    def test_no_active_bank_returns_404(self, client: TestClient, db_session):
        """If no active bank exists, should return 404."""
        # Deactivate the startup-seeded SBI bank
        bank = db_session.query(Bank).filter(Bank.code == "SBI").first()
        if bank:
            bank.is_active = False
            db_session.commit()

        resp = client.get("/api/v1/forms", headers=auth_headers())
        assert resp.status_code == 404

    def test_requires_auth(self, client: TestClient):
        resp = client.get("/api/v1/forms")
        assert resp.status_code == 403


# ---------------------------------------------------------------------------
# Tests — GET /api/v1/forms/{form_id}
# ---------------------------------------------------------------------------

class TestGetFormDetail:
    def test_returns_form_with_sections_and_fields(self, client: TestClient, db_session):
        _, forms = seed_bank_and_forms(db_session)
        resp = client.get(f"/api/v1/forms/{forms[0].id}", headers=auth_headers())
        assert resp.status_code == 200
        data = resp.json()
        assert data["code"] == "account_opening"
        # Startup-seeded form has multiple sections and fields
        assert len(data["sections"]) >= 1
        assert len(data["fields"]) >= 1
        field_keys = {f["field_key"] for f in data["fields"]}
        assert "full_name" in field_keys

    def test_form_has_correct_metadata(self, client: TestClient, db_session):
        _, forms = seed_bank_and_forms(db_session)
        resp = client.get(f"/api/v1/forms/{forms[0].id}", headers=auth_headers())
        data = resp.json()
        assert data["name"] == "Account Opening"
        # Description comes from the startup-seeded form
        assert data["description"] is not None
        assert "account" in data["description"].lower()

    def test_inactive_form_returns_404(self, client: TestClient, db_session):
        _, forms = seed_bank_and_forms(db_session)
        forms[0].is_active = False
        db_session.commit()
        resp = client.get(f"/api/v1/forms/{forms[0].id}", headers=auth_headers())
        assert resp.status_code == 404

    def test_nonexistent_form_returns_404(self, client: TestClient):
        resp = client.get("/api/v1/forms/9999", headers=auth_headers())
        assert resp.status_code == 404

    def test_requires_auth(self, client: TestClient, db_session):
        _, forms = seed_bank_and_forms(db_session)
        resp = client.get(f"/api/v1/forms/{forms[0].id}")
        assert resp.status_code == 403
