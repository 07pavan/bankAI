"""
Integration tests for KYC API endpoints
"""

import pytest


@pytest.mark.integration
def test_submit_kyc_new_user(client, sample_kyc_data):
    """Test full KYC submission flow for new user"""
    response = client.post("/api/v1/kyc/submit", json=sample_kyc_data)
    
    assert response.status_code == 200
    data = response.json()
    
    assert "id" in data
    assert "user_id" in data
    assert "access_token" in data
    assert data["token_type"] == "bearer"
    assert data["is_new_user"] is True
    assert data["status"] == "pending"


@pytest.mark.integration
def test_submit_kyc_duplicate_aadhaar(client, sample_kyc_data):
    """Test KYC submission with duplicate Aadhaar"""
    # First submission
    response1 = client.post("/api/v1/kyc/submit", json=sample_kyc_data)
    assert response1.status_code == 200
    data1 = response1.json()
    
    # Second submission with same Aadhaar
    response2 = client.post("/api/v1/kyc/submit", json=sample_kyc_data)
    assert response2.status_code == 200
    data2 = response2.json()
    
    assert data2["is_new_user"] is False
    assert data2["user_id"] == data1["user_id"]
    assert "access_token" in data2


@pytest.mark.integration
def test_submit_kyc_invalid_aadhaar(client):
    """Test KYC submission with invalid Aadhaar"""
    response = client.post("/api/v1/kyc/submit", json={
        "aadhaar": "123",  # Too short
        "pan": "ABCDE1234F"
    })
    
    assert response.status_code == 422  # Validation error


@pytest.mark.integration
def test_submit_kyc_invalid_pan(client):
    """Test KYC submission with invalid PAN"""
    response = client.post("/api/v1/kyc/submit", json={
        "aadhaar": "123456789012",
        "pan": "INVALID"  # Wrong format
    })
    
    assert response.status_code == 422  # Validation error


@pytest.mark.integration
def test_get_kyc_status_authenticated(client, sample_kyc_data):
    """Test retrieving KYC status with authentication"""
    # Submit KYC
    submit_response = client.post("/api/v1/kyc/submit", json=sample_kyc_data)
    submit_data = submit_response.json()
    
    submission_id = submit_data["id"]
    token = submit_data["access_token"]
    
    # Get status with token
    response = client.get(
        f"/api/v1/kyc/status/{submission_id}",
        headers={"Authorization": f"Bearer {token}"}
    )
    
    assert response.status_code == 200
    data = response.json()
    
    assert data["id"] == submission_id
    assert "XXXX XXXX" in data["aadhaar_masked"]
    assert "XX" in data["pan_masked"]
    assert data["status"] == "pending"


@pytest.mark.integration
def test_get_kyc_status_unauthenticated(client):
    """Test retrieving KYC status without authentication"""
    response = client.get("/api/v1/kyc/status/1")
    
    assert response.status_code == 401  # Unauthorized (no auth header)


@pytest.mark.integration
def test_get_all_submissions_authenticated(client, sample_kyc_data):
    """Test that /kyc/all returns 403 — endpoint is restricted until admin roles are implemented."""
    # Submit KYC to get token
    submit_response = client.post("/api/v1/kyc/submit", json=sample_kyc_data)
    token = submit_response.json()["access_token"]

    # /kyc/all is blocked for all users until admin roles are implemented
    response = client.get(
        "/api/v1/kyc/all",
        headers={"Authorization": f"Bearer {token}"}
    )

    assert response.status_code == 403
    assert "Admin access required" in response.json()["detail"]


@pytest.mark.integration
def test_get_current_user(client, sample_kyc_data):
    """Test getting current user profile"""
    # Submit KYC to create user and get token
    submit_response = client.post("/api/v1/kyc/submit", json=sample_kyc_data)
    submit_data = submit_response.json()
    token = submit_data["access_token"]
    user_id = submit_data["user_id"]
    
    # Get current user
    response = client.get(
        "/api/v1/auth/me",
        headers={"Authorization": f"Bearer {token}"}
    )
    
    assert response.status_code == 200
    data = response.json()
    
    assert data["id"] == user_id
    assert "created_at" in data
    assert data["kyc_count"] >= 1


@pytest.mark.integration
def test_health_check(client):
    """Test health check endpoint"""
    response = client.get("/api/health")
    
    assert response.status_code == 200
    data = response.json()
    
    assert data["status"] == "healthy"
    assert "service" in data
    assert "timestamp" in data
