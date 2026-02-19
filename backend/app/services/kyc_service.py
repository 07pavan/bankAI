"""
KYC Service Layer
Business logic for KYC submission, duplicate detection, and status retrieval
"""

from sqlalchemy.orm import Session
from typing import Tuple, Optional
import base64
import os
import uuid

from app.models import User, KYCSubmission, KYCStatus
from app.core.encryption import encryption_service
from app.core.logging import get_logger

logger = get_logger()

# Directory to store selfie images
SELFIE_DIR = os.path.join(os.path.dirname(__file__), "..", "..", "selfies")
os.makedirs(SELFIE_DIR, exist_ok=True)


def save_selfie(data_url: str) -> str:
    """
    Save a base64 data URL as a JPEG file.
    Returns the file path.
    """
    # Strip data URL prefix: "data:image/jpeg;base64,..."
    if "," in data_url:
        data_url = data_url.split(",", 1)[1]

    img_bytes = base64.b64decode(data_url)
    filename = f"selfie_{uuid.uuid4().hex[:12]}.jpg"
    filepath = os.path.join(SELFIE_DIR, filename)

    with open(filepath, "wb") as f:
        f.write(img_bytes)

    logger.info(f"Saved selfie to {filepath}")
    return filepath


def submit_kyc(
    aadhaar: str,
    pan: str,
    selfie: Optional[str],
    db: Session
) -> Tuple[User, KYCSubmission, bool]:
    """
    Submit KYC data with duplicate Aadhaar detection
    
    Args:
        aadhaar: Aadhaar number (12 digits)
        pan: PAN number
        selfie: Optional base64 selfie data URL
        db: Database session
    
    Returns:
        Tuple of (User, KYCSubmission, is_new_user)
        - is_new_user: True if new registration, False if existing user (login)
    """
    # Generate Aadhaar hash for duplicate detection
    aadhaar_hash = encryption_service.hash_aadhaar(aadhaar)
    
    # Check if user already exists
    existing_user = db.query(User).filter(User.aadhaar_hash == aadhaar_hash).first()
    
    if existing_user:
        logger.info(f"Existing user detected with Aadhaar hash: {aadhaar_hash[:8]}...")
        
        # Get the most recent KYC submission for this user
        latest_submission = db.query(KYCSubmission).filter(
            KYCSubmission.user_id == existing_user.id
        ).order_by(KYCSubmission.created_at.desc()).first()
        
        return existing_user, latest_submission, False  # Existing user (login flow)
    
    # New user - create User and KYCSubmission
    logger.info("Creating new user")
    
    # Encrypt sensitive data
    aadhaar_encrypted = encryption_service.encrypt_aadhaar(aadhaar)
    pan_encrypted = encryption_service.encrypt_pan(pan)
    
    # Save selfie if provided
    selfie_path = None
    if selfie:
        try:
            selfie_path = save_selfie(selfie)
        except Exception as e:
            logger.error(f"Failed to save selfie: {str(e)}")
            raise ValueError(f"Invalid selfie data: {str(e)}")
    
    # Create User
    user = User(aadhaar_hash=aadhaar_hash)
    db.add(user)
    db.flush()  # Get user.id without committing
    
    # Create KYC Submission
    submission = KYCSubmission(
        user_id=user.id,
        aadhaar_encrypted=aadhaar_encrypted,
        pan_encrypted=pan_encrypted,
        aadhaar_hash=aadhaar_hash,
        selfie_path=selfie_path,
        status=KYCStatus.PENDING,
    )
    db.add(submission)
    db.commit()
    db.refresh(user)
    db.refresh(submission)
    
    logger.info(f"Created new user {user.id} with KYC submission {submission.id}")
    
    return user, submission, True  # New user (registration flow)


def get_kyc_status(submission_id: int, db: Session) -> Optional[dict]:
    """
    Get KYC submission status with masked data
    
    Args:
        submission_id: KYC submission ID
        db: Database session
    
    Returns:
        Dictionary with submission details and masked PII
    """
    submission = db.query(KYCSubmission).filter(
        KYCSubmission.id == submission_id
    ).first()
    
    if not submission:
        return None
    
    # Decrypt for masking
    aadhaar = encryption_service.decrypt_aadhaar(submission.aadhaar_encrypted)
    pan = encryption_service.decrypt_pan(submission.pan_encrypted)
    
    return {
        "id": submission.id,
        "aadhaar_masked": encryption_service.mask_aadhaar(aadhaar),
        "pan_masked": encryption_service.mask_pan(pan),
        "status": submission.status,
        "has_selfie": submission.selfie_path is not None,
        "created_at": submission.created_at,
    }


def get_all_submissions(db: Session) -> list:
    """
    Get all KYC submissions (admin endpoint)
    Returns masked data for all submissions
    """
    submissions = db.query(KYCSubmission).order_by(
        KYCSubmission.created_at.desc()
    ).all()
    
    result = []
    for s in submissions:
        # Decrypt for masking
        aadhaar = encryption_service.decrypt_aadhaar(s.aadhaar_encrypted)
        pan = encryption_service.decrypt_pan(s.pan_encrypted)
        
        result.append({
            "id": s.id,
            "user_id": s.user_id,
            "aadhaar_masked": encryption_service.mask_aadhaar(aadhaar),
            "pan_masked": encryption_service.mask_pan(pan),
            "status": s.status,
            "has_selfie": s.selfie_path is not None,
            "created_at": s.created_at.isoformat() if s.created_at else None,
        })
    
    return result
