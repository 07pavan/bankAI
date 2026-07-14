"""
End-to-End Firestore Integration Test Suite for BankAI.

Mocks the Firestore client in-memory and tests all core API routes:
- KYC Submissions & JWT Authentication
- Admin CRUD (Banks, Forms, Sections, Fields)
- Section-Form validation logic (Relational Integrity)
- Customer Forms Discovery & Submissions (answering fields, pagination, detail queries)
"""

import sys
import os
import uuid
from datetime import datetime, timezone
from typing import Optional, Any, Generator

import pytest
from fastapi import status
from fastapi.testclient import TestClient

# ─────────────────────────────────────────────────────────────────────────────
# 1. In-Memory Mock Firestore Implementation
# ─────────────────────────────────────────────────────────────────────────────

class MockDocumentSnapshot:
    def __init__(self, doc_id: str, data: Optional[dict]):
        self.id = doc_id
        self._data = data
        self.exists = data is not None

    def to_dict(self) -> dict:
        return self._data.copy() if self._data else {}

class MockDocumentReference:
    def __init__(self, doc_id: str, collection: "MockCollectionReference"):
        self.id = doc_id
        self.collection = collection

    def get(self) -> MockDocumentSnapshot:
        data = self.collection.store.get(self.id)
        return MockDocumentSnapshot(self.id, data)

    def set(self, data: dict) -> None:
        self.collection.store[self.id] = data.copy()

    def update(self, data: dict) -> None:
        if self.id not in self.collection.store:
            raise Exception(f"Document {self.id} not found in collection {self.collection.name}")
        self.collection.store[self.id].update(data)

    def delete(self) -> None:
        if self.id in self.collection.store:
            del self.collection.store[self.id]

class MockQuery:
    def __init__(
        self,
        collection: "MockCollectionReference",
        filters=None,
        orders=None,
        offset_val: int = 0,
        limit_val: Optional[int] = None
    ):
        self.collection = collection
        self.filters = filters or []
        self.orders = orders or []
        self.offset_val = offset_val
        self.limit_val = limit_val

    def where(self, field: str, op: str, val: Any) -> "MockQuery":
        new_filters = self.filters + [(field, op, val)]
        return MockQuery(self.collection, new_filters, self.orders, self.offset_val, self.limit_val)

    def order_by(self, field: str, direction: str = "ASCENDING") -> "MockQuery":
        new_orders = self.orders + [(field, direction)]
        return MockQuery(self.collection, self.filters, new_orders, self.offset_val, self.limit_val)

    def offset(self, val: int) -> "MockQuery":
        return MockQuery(self.collection, self.filters, self.orders, val, self.limit_val)

    def limit(self, val: int) -> "MockQuery":
        return MockQuery(self.collection, self.filters, self.orders, self.offset_val, val)

    def stream(self) -> Generator[MockDocumentSnapshot, None, None]:
        results = []
        for doc_id, data in self.collection.store.items():
            match = True
            for field, op, val in self.filters:
                doc_val = data.get(field)
                if op == "==":
                    if doc_val != val:
                        match = False
                elif op == ">=":
                    if doc_val is None or doc_val < val:
                        match = False
            if match:
                results.append(MockDocumentSnapshot(doc_id, data))

        # Apply sorting orders
        for field, direction in self.orders:
            reverse = (direction == "DESCENDING")
            
            def sort_key(snap):
                val = snap.to_dict().get(field)
                if isinstance(val, datetime):
                    return val.timestamp()
                if val is None:
                    return ""
                return val

            results.sort(key=sort_key, reverse=reverse)

        # Apply offset and limit
        if self.offset_val > 0:
            results = results[self.offset_val:]
        if self.limit_val is not None:
            results = results[:self.limit_val]

        for snap in results:
            yield snap

class MockCollectionReference:
    def __init__(self, name: str, db: "MockFirestoreClient"):
        self.name = name
        self.db = db
        if name not in db.store:
            db.store[name] = {}
        self.store = db.store[name]

    def document(self, doc_id: Optional[str] = None) -> MockDocumentReference:
        if doc_id is None:
            doc_id = str(uuid.uuid4())
        return MockDocumentReference(doc_id, self)

    def where(self, field: str, op: str, val: Any) -> MockQuery:
        return MockQuery(self).where(field, op, val)

    def order_by(self, field: str, direction: str = "ASCENDING") -> MockQuery:
        return MockQuery(self).order_by(field, direction)

    def offset(self, val: int) -> MockQuery:
        return MockQuery(self).offset(val)

    def limit(self, val: int) -> MockQuery:
        return MockQuery(self).limit(val)

    def stream(self) -> Generator[MockDocumentSnapshot, None, None]:
        return MockQuery(self).stream()

class MockFirestoreClient:
    def __init__(self):
        self.store = {}

    def collection(self, name: str) -> MockCollectionReference:
        return MockCollectionReference(name, self)

# ─────────────────────────────────────────────────────────────────────────────
# 2. Patch Database Module BEFORE Importing App
# ─────────────────────────────────────────────────────────────────────────────

import app.database
mock_db = MockFirestoreClient()

# Override singleton and functions
app.database._firestore_client = mock_db
app.database.get_db = lambda: mock_db
app.database._init_firebase = lambda: mock_db

# Suppress startup seeding during testing to isolate tests
import app.core.seed
app.core.seed.seed_defaults = lambda: None

from app.main import app
from app.core.security import create_access_token
from app.models import COLL_USERS, COLL_BANKS, COLL_FORMS, COLL_FORM_SECTIONS, COLL_FORM_FIELDS

# Disable rate limit
from app.core.rate_limit import limiter
limiter.enabled = False

# Create TestClient
client = TestClient(app)

# ─────────────────────────────────────────────────────────────────────────────
# 3. Test Fixtures
# ─────────────────────────────────────────────────────────────────────────────

@pytest.fixture(autouse=True)
def clear_db():
    """Reset the mock database store before each test run."""
    mock_db.store.clear()

def create_admin_user() -> str:
    """Create an admin user in the mock store and return an access token."""
    user_id = str(uuid.uuid4())
    mock_db.collection(COLL_USERS).document(user_id).set({
        "aadhaar_hash": "admin_aadhaar_hash",
        "role": "admin",
        "created_at": datetime.now(timezone.utc)
    })
    token = create_access_token({"sub": user_id, "role": "admin"})
    return token

def create_regular_user(bank_id: Optional[str] = None) -> str:
    """Create a regular user in the mock store and return an access token."""
    user_id = str(uuid.uuid4())
    mock_db.collection(COLL_USERS).document(user_id).set({
        "aadhaar_hash": "user_aadhaar_hash",
        "role": "user",
        "bank_id": bank_id,
        "created_at": datetime.now(timezone.utc)
    })
    token = create_access_token({"sub": user_id, "role": "user"})
    return token

# ─────────────────────────────────────────────────────────────────────────────
# 4. E2E Test Cases
# ─────────────────────────────────────────────────────────────────────────────

def test_admin_flow_crud_and_validation():
    """
    Test Admin Flow:
    1. Create a bank
    2. Create a form under the bank
    3. Create a section under the form
    4. Create a field inside the section
    5. Test validation: adding field with section_id of a different form should fail
    """
    token = create_admin_user()
    headers = {"Authorization": f"Bearer {token}"}

    # 1. Create a Bank
    bank_resp = client.post(
        "/api/v1/admin/banks",
        headers=headers,
        json={"name": "State Bank of India", "code": "SBI"}
    )
    assert bank_resp.status_code == 201
    bank_id = bank_resp.json()["id"]
    assert bank_resp.json()["code"] == "SBI"

    # List Banks
    banks_list = client.get("/api/v1/admin/banks", headers=headers)
    assert banks_list.status_code == 200
    assert len(banks_list.json()) == 1

    # 2. Create a Form under Bank
    form_resp = client.post(
        "/api/v1/admin/forms",
        headers=headers,
        json={"bank_id": bank_id, "name": "Savings Account", "code": "savings_account", "description": "Open savings"}
    )
    assert form_resp.status_code == 201
    form_id = form_resp.json()["id"]

    # 3. Create a Section under Form
    section_resp = client.post(
        f"/api/v1/admin/forms/{form_id}/sections",
        headers=headers,
        json={"name": "Personal Details", "order_index": 0}
    )
    assert section_resp.status_code == 201
    section_id = section_resp.json()["id"]

    # 4. Create a Field inside the Section
    field_resp = client.post(
        f"/api/v1/admin/forms/{form_id}/fields",
        headers=headers,
        json={
            "field_key": "full_name",
            "label": "Full Name",
            "field_type": "text",
            "required": True,
            "order_index": 0,
            "section_id": section_id
        }
    )
    assert field_resp.status_code == 201
    assert field_resp.json()["field_key"] == "full_name"

    # 5. Create another Form to test referential integrity validation
    other_form_resp = client.post(
        "/api/v1/admin/forms",
        headers=headers,
        json={"bank_id": bank_id, "name": "Other Account", "code": "other_account"}
    )
    other_form_id = other_form_resp.json()["id"]

    # Try to add a field to other_form_id using section_id from the first form
    mismatched_resp = client.post(
        f"/api/v1/admin/forms/{other_form_id}/fields",
        headers=headers,
        json={
            "field_key": "mismatched_key",
            "label": "Mismatched Field",
            "field_type": "text",
            "required": True,
            "section_id": section_id  # belongs to form_id, not other_form_id
        }
    )
    # Backend should block it with HTTP 400 Bad Request
    assert mismatched_resp.status_code == 400
    assert "does not belong to form" in mismatched_resp.json()["detail"]


def test_public_forms_discovery():
    """Test standard users discovering banks and forms."""
    bank_id = "test_bank_uuid"
    mock_db.collection(COLL_BANKS).document(bank_id).set({
        "name": "HDFC Bank",
        "code": "HDFC",
        "is_active": True,
        "created_at": datetime.now(timezone.utc)
    })
    form_id = "test_form_uuid"
    mock_db.collection(COLL_FORMS).document(form_id).set({
        "bank_id": bank_id,
        "name": "Credit Card Application",
        "code": "credit_card",
        "is_active": True,
        "created_at": datetime.now(timezone.utc)
    })

    token = create_regular_user(bank_id=bank_id)
    headers = {"Authorization": f"Bearer {token}"}

    # Query public forms (resolved from user's bank)
    forms_resp = client.get("/api/v1/forms", headers=headers)
    assert forms_resp.status_code == 200
    assert len(forms_resp.json()) == 1
    assert forms_resp.json()[0]["name"] == "Credit Card Application"


def test_submissions_drafting_and_answering():
    """Test user drafting a form, answering fields, and admin viewing details."""
    # Setup bank, form, section, and fields in DB
    bank_id = "bank_1"
    mock_db.collection(COLL_BANKS).document(bank_id).set({"name": "SBI", "code": "SBI", "is_active": True})
    form_id = "form_1"
    mock_db.collection(COLL_FORMS).document(form_id).set({"bank_id": bank_id, "name": "Form 1", "code": "f1", "is_active": True})
    field_id = "field_1"
    mock_db.collection(COLL_FORM_FIELDS).document(field_id).set({
        "form_id": form_id, "field_key": "mobile", "label": "Mobile", "field_type": "text", "required": True, "order_index": 0, "is_active": True
    })

    user_token = create_regular_user(bank_id=bank_id)
    user_headers = {"Authorization": f"Bearer {user_token}"}
    admin_token = create_admin_user()
    admin_headers = {"Authorization": f"Bearer {admin_token}"}

    # Start a submission
    sub_resp = client.post(
        "/api/v1/submissions/start",
        headers=user_headers,
        json={"form_id": form_id}
    )
    assert sub_resp.status_code == 201
    sub_id = sub_resp.json()["id"]
    assert sub_resp.json()["status"] == "draft"

    # Answer field directly via submission service
    from app.services import submission_service
    submission_service.save_field_value(sub_id, "mobile", "9876543210")

    # Admin view list with pagination
    admin_list_resp = client.get(
        "/api/v1/admin/submissions?skip=0&limit=10",
        headers=admin_headers
    )
    assert admin_list_resp.status_code == 200
    submissions = admin_list_resp.json()
    assert len(submissions) == 1
    assert submissions[0]["id"] == sub_id

    # Admin view detailed submission (includes answers)
    admin_detail_resp = client.get(
        f"/api/v1/admin/submissions/{sub_id}",
        headers=admin_headers
    )
    assert admin_detail_resp.status_code == 200
    details = admin_detail_resp.json()
    assert details["id"] == sub_id
    assert len(details["data"]) == 1
    assert details["data"][0]["field_key"] == "mobile"
    assert details["data"][0]["value"] == "9876543210"
