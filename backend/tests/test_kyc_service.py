"""
Unit tests for KYC service
"""

import pytest
from app.services import kyc_service
from app.models import User, KYCSubmission


@pytest.mark.unit
def test_submit_kyc_new_user(db_session, sample_kyc_data):
    """Test KYC submission for a new user"""
    user, submission, is_new_user = kyc_service.submit_kyc(
        aadhaar=sample_kyc_data["aadhaar"],
        pan=sample_kyc_data["pan"],
        selfie=sample_kyc_data["selfie"],
        db=db_session
    )
    
    assert is_new_user is True
    assert user.id is not None
    assert submission.id is not None
    assert submission.user_id == user.id
    assert submission.status == "pending"


@pytest.mark.unit
def test_submit_kyc_duplicate_aadhaar(db_session, sample_kyc_data):
    """Test KYC submission with duplicate Aadhaar (login flow)"""
    # First submission
    user1, submission1, is_new1 = kyc_service.submit_kyc(
        aadhaar=sample_kyc_data["aadhaar"],
        pan=sample_kyc_data["pan"],
        selfie=None,
        db=db_session
    )
    
    assert is_new1 is True
    
    # Second submission with same Aadhaar
    user2, submission2, is_new2 = kyc_service.submit_kyc(
        aadhaar=sample_kyc_data["aadhaar"],
        pan="ZZZZZ9999Z",  # Different PAN
        selfie=None,
        db=db_session
    )
    
    assert is_new2 is False
    assert user2.id == user1.id  # Same user
    assert submission2.id == submission1.id  # Same submission returned


@pytest.mark.unit
def test_get_kyc_status(db_session, sample_kyc_data):
    """Test retrieving KYC status"""
    # Create submission
    user, submission, _ = kyc_service.submit_kyc(
        aadhaar=sample_kyc_data["aadhaar"],
        pan=sample_kyc_data["pan"],
        selfie=None,
        db=db_session
    )
    
    # Get status
    result = kyc_service.get_kyc_status(submission.id, db_session)
    
    assert result is not None
    assert result["id"] == submission.id
    assert "XXXX XXXX" in result["aadhaar_masked"]
    assert "XX" in result["pan_masked"]
    assert result["status"] == "pending"
    assert result["has_selfie"] is False


@pytest.mark.unit
def test_get_kyc_status_not_found(db_session):
    """Test retrieving non-existent KYC status"""
    result = kyc_service.get_kyc_status(99999, db_session)
    assert result is None


@pytest.mark.unit
def test_get_all_submissions(db_session, sample_aadhaar, sample_pan):
    """Test retrieving all KYC submissions"""
    # Create multiple submissions
    kyc_service.submit_kyc(sample_aadhaar, sample_pan, None, db_session)
    kyc_service.submit_kyc("9876 5432 1098", "ZZZZZ9999Z", None, db_session)
    
    # Get all
    results = kyc_service.get_all_submissions(db_session)
    
    assert len(results) == 2
    assert all("aadhaar_masked" in r for r in results)
    assert all("pan_masked" in r for r in results)
