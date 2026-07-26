import sys
import os
import pytest
from datetime import datetime, timezone
from fastapi import status
from fastapi.testclient import TestClient

# Mock firestore client before any imports
from tests.test_e2e_firestore import MockFirestoreClient
import app.database

@pytest.fixture(autouse=True)
def patch_db(monkeypatch):
    mock_db = MockFirestoreClient()
    # Populate mock collections
    mock_db.collection("forms").document("test-form-id").set({
        "name": "Savings Account Form",
        "code": "SAVINGS_01",
        "is_active": True,
        "total_fields": 5,
        "created_at": datetime.now(timezone.utc),
    })
    monkeypatch.setattr("app.database.get_db", lambda: mock_db)
    monkeypatch.setattr("app.services.signature_service.get_db", lambda: mock_db)
    monkeypatch.setattr("app.services.submission_service.get_db", lambda: mock_db)
    yield mock_db

def test_language_welcome_prompts(monkeypatch):
    """Test that regional language directives are correctly built into the LLM system message."""
    from app.services.ai_agent_service import _build_system_message
    
    # Hindi prompt check
    sys_msg_hi = _build_system_message({
        "language": "hi-IN",
        "conversation_state": "chat",
        "messages": []
    })
    assert "Hindi" in sys_msg_hi.content or "हिन्दी" in sys_msg_hi.content
    assert "Nominee" in sys_msg_hi.content or "nominee" in sys_msg_hi.content or "संक्षिप्त" in sys_msg_hi.content
    
    # Kannada prompt check
    sys_msg_kn = _build_system_message({
        "language": "kn-IN",
        "conversation_state": "chat",
        "messages": []
    })
    assert "Kannada" in sys_msg_kn.content or "ಕನ್ನಡ" in sys_msg_kn.content

def test_voice_signature_upload(patch_db, monkeypatch):
    """Test that voice signature audio upload transitions the submission state."""
    from app.main import app as fastapi_app
    import app.core.security
    
    client = TestClient(fastapi_app)
    
    # Setup test submission
    submission_id = "test-sub-id"
    user_id = "test-user-id"
    
    patch_db.collection("submissions").document(submission_id).set({
        "id": submission_id,
        "user_id": user_id,
        "form_id": "test-form-id",
        "status": "draft",
        "current_field_index": 4,
        "conversation_state": "signature",
        "created_at": datetime.now(timezone.utc),
        "updated_at": datetime.now(timezone.utc),
    })
    
    # Mock current user JWT auth dependency
    fastapi_app.dependency_overrides[app.core.security.get_current_user_id] = lambda: user_id
    
    # Call the endpoint with a mock base64 audio string
    payload = {
        "audio": "data:audio/webm;base64,UklGRigAAABXQVZFZm10IBIAAAABAAERKgAAEsYAAAEABAAA"
    }
    
    res = client.post(
        f"/api/v1/submissions/{submission_id}/voice-signature",
        json=payload
    )
    
    assert res.status_code == status.HTTP_200_OK
    data = res.json()
    assert data["submission_id"] == submission_id
    
    # Verify DB update
    updated_doc = patch_db.collection("submissions").document(submission_id).get().to_dict()
    assert updated_doc["status"] == "completed"
    assert updated_doc["conversation_state"] == "complete"
    assert updated_doc["signing_method"] == "voice"
    
    fastapi_app.dependency_overrides.clear()

def test_banker_dashboard_and_override(patch_db, monkeypatch):
    """Test that banker dashboard can retrieve active submissions and perform manual field overrides."""
    from app.main import app as fastapi_app
    import app.core.security
    
    client = TestClient(fastapi_app)
    submission_id = "sub-to-override"
    user_id = "customer-user"
    
    patch_db.collection("submissions").document(submission_id).set({
        "id": submission_id,
        "user_id": user_id,
        "form_id": "test-form-id",
        "status": "draft",
        "current_field_index": 1,
        "conversation_state": "filling_form",
        "created_at": datetime.now(timezone.utc),
        "updated_at": datetime.now(timezone.utc),
    })
    
    # Mock current user JWT auth dependency
    fastapi_app.dependency_overrides[app.core.security.get_current_user_id] = lambda: "banker-user-id"
    
    # Mock form ordered active fields (for field validation in save_field_value)
    monkeypatch.setattr(
        "app.services.submission_service.get_ordered_active_fields",
        lambda form_id: [{"field_key": "full_name", "label": "Full Name", "field_type": "text", "required": True}]
    )
    
    # Retrieve active submissions
    res_monitor = client.get("/api/v1/submissions/active/monitor")
    assert res_monitor.status_code == status.HTTP_200_OK
    assert len(res_monitor.json()) == 1
    
    # Post banker override
    payload = {
        "field_key": "full_name",
        "value": "John Doe Senior"
    }
    
    res_override = client.post(
        f"/api/v1/submissions/{submission_id}/override",
        json=payload
    )
    
    assert res_override.status_code == status.HTTP_200_OK
    
    # Check that the override answer is stored in COLL_SUBMISSION_DATA
    answers_docs = list(patch_db.collection("submission_data").stream())
    assert len(answers_docs) == 1
    assert answers_docs[0].to_dict()["value"] == "John Doe Senior"
    assert answers_docs[0].to_dict()["field_key"] == "full_name"
    
    fastapi_app.dependency_overrides.clear()


def test_admin_static_login(monkeypatch):
    """Test that temporary banker login works with fixed admin/adminpass credentials."""
    from app.main import app as fastapi_app
    client = TestClient(fastapi_app)
    
    # Correct credentials
    res = client.post(
        "/api/v1/auth/admin/login",
        json={"username": "admin", "password": "adminpass"}
    )
    assert res.status_code == status.HTTP_200_OK
    data = res.json()
    assert "access_token" in data
    assert data["message"] == "Admin login successful!"
    
    # Incorrect credentials
    res_fail = client.post(
        "/api/v1/auth/admin/login",
        json={"username": "admin", "password": "wrongpassword"}
    )
    assert res_fail.status_code == status.HTTP_401_UNAUTHORIZED


def test_admin_user_bypass(monkeypatch):
    """Test that get_current_user bypasses Firestore query for admin_user."""
    from app.core.security import get_current_user, create_access_token
    from fastapi.security import HTTPAuthorizationCredentials
    
    # Generate access token for admin_user
    token = create_access_token(data={"sub": "admin_user", "role": "admin"})
    
    # Call dependency
    creds = HTTPAuthorizationCredentials(scheme="Bearer", credentials=token)
    user = get_current_user(creds)
    
    assert user["id"] == "admin_user"
    assert user["role"] == "admin"

