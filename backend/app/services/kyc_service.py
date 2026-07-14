"""
KYC Service Layer — Firestore edition
Business logic for KYC submission, duplicate detection, and status retrieval.
"""

import base64
import os
import uuid
from datetime import datetime, timezone
from typing import Optional, Tuple

from app.database import get_db
from app.models import KYCStatus, COLL_USERS, COLL_KYC_SUBMISSIONS
from app.core.encryption import encryption_service
from app.core.logging import get_logger

logger = get_logger()

# Directory to store selfie images
SELFIE_DIR = os.path.join(os.path.dirname(__file__), "..", "..", "selfies")
os.makedirs(SELFIE_DIR, exist_ok=True)


def save_selfie(data_url: str) -> str:
    """
    Save a base64 data URL as a JPEG file.
    Returns the relative file path.
    """
    if "," in data_url:
        data_url = data_url.split(",", 1)[1]

    img_bytes = base64.b64decode(data_url)
    filename = f"selfie_{uuid.uuid4().hex[:12]}.jpg"
    filepath = os.path.join(SELFIE_DIR, filename)

    with open(filepath, "wb") as f:
        f.write(img_bytes)

    logger.info(f"Saved selfie to {filepath}")
    return filename  # Store relative filename only


def submit_kyc(
    aadhaar: str,
    pan: str,
    selfie: Optional[str],
) -> Tuple[dict, dict, bool]:
    """
    Submit KYC data with duplicate Aadhaar detection.

    Returns:
        Tuple of (user_doc, kyc_doc, is_new_user)
        - is_new_user: True if new registration, False if existing user (login)
    """
    db = get_db()
    aadhaar_hash = encryption_service.hash_aadhaar(aadhaar)

    # Check if user already exists
    existing_users = (
        db.collection(COLL_USERS)
        .where("aadhaar_hash", "==", aadhaar_hash)
        .limit(1)
        .stream()
    )
    existing_user_doc = next(existing_users, None)

    if existing_user_doc:
        user_data = {"id": existing_user_doc.id, **existing_user_doc.to_dict()}
        logger.info(f"Existing user detected with Aadhaar hash: {aadhaar_hash[:8]}...")

        # Get the most recent KYC submission for this user
        kyc_docs = (
            db.collection(COLL_KYC_SUBMISSIONS)
            .where("user_id", "==", existing_user_doc.id)
            .order_by("created_at", direction="DESCENDING")
            .limit(1)
            .stream()
        )
        kyc_doc = next(kyc_docs, None)
        kyc_data = {"id": kyc_doc.id, **kyc_doc.to_dict()} if kyc_doc else None
        return user_data, kyc_data, False

    # New user — encrypt and persist
    logger.info("Creating new user")
    aadhaar_encrypted = encryption_service.encrypt_aadhaar(aadhaar)
    pan_encrypted = encryption_service.encrypt_pan(pan)

    selfie_path = None
    if selfie:
        try:
            selfie_path = save_selfie(selfie)
        except Exception as e:
            logger.error(f"Failed to save selfie: {str(e)}")
            raise ValueError(f"Invalid selfie data: {str(e)}")

    now = datetime.now(timezone.utc)

    # Create User document
    user_ref = db.collection(COLL_USERS).document()
    user_data = {
        "aadhaar_hash": aadhaar_hash,
        "role": "user",
        "created_at": now,
    }
    user_ref.set(user_data)
    user_data = {"id": user_ref.id, **user_data}

    # Create KYC Submission document
    kyc_ref = db.collection(COLL_KYC_SUBMISSIONS).document()
    kyc_data = {
        "user_id": user_ref.id,
        "aadhaar_encrypted": aadhaar_encrypted,
        "pan_encrypted": pan_encrypted,
        "aadhaar_hash": aadhaar_hash,
        "selfie_path": selfie_path,
        "status": KYCStatus.PENDING,
        "created_at": now,
        "updated_at": now,
    }
    kyc_ref.set(kyc_data)
    kyc_data = {"id": kyc_ref.id, **kyc_data}

    logger.info(f"Created new user {user_ref.id} with KYC submission {kyc_ref.id}")
    return user_data, kyc_data, True


def get_kyc_status(submission_id: str) -> Optional[dict]:
    """
    Get KYC submission status with masked data.
    """
    db = get_db()
    doc = db.collection(COLL_KYC_SUBMISSIONS).document(submission_id).get()
    if not doc.exists:
        return None

    s = doc.to_dict()
    aadhaar = encryption_service.decrypt_aadhaar(s["aadhaar_encrypted"])
    pan = encryption_service.decrypt_pan(s["pan_encrypted"])

    return {
        "id": doc.id,
        "aadhaar_masked": encryption_service.mask_aadhaar(aadhaar),
        "pan_masked": encryption_service.mask_pan(pan),
        "status": s["status"],
        "has_selfie": s.get("selfie_path") is not None,
        "created_at": s.get("created_at"),
    }


def get_all_submissions() -> list:
    """
    Get all KYC submissions (admin endpoint). Returns masked data.
    """
    db = get_db()
    docs = (
        db.collection(COLL_KYC_SUBMISSIONS)
        .order_by("created_at", direction="DESCENDING")
        .stream()
    )

    result = []
    for doc in docs:
        s = doc.to_dict()
        aadhaar = encryption_service.decrypt_aadhaar(s["aadhaar_encrypted"])
        pan = encryption_service.decrypt_pan(s["pan_encrypted"])
        created_at = s.get("created_at")
        result.append({
            "id": doc.id,
            "user_id": s["user_id"],
            "aadhaar_masked": encryption_service.mask_aadhaar(aadhaar),
            "pan_masked": encryption_service.mask_pan(pan),
            "status": s["status"],
            "has_selfie": s.get("selfie_path") is not None,
            "created_at": created_at.isoformat() if hasattr(created_at, "isoformat") else str(created_at),
        })
    return result
