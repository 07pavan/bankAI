"""
KYC Router — endpoints for KYC submission and status
"""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from datetime import datetime
import base64
import os
import uuid

from database import get_db
from models import KYCSubmission, KYCStatus
from schemas import KYCSubmitRequest, KYCSubmitResponse, KYCStatusResponse

router = APIRouter()

# Directory to store selfie images
SELFIE_DIR = os.path.join(os.path.dirname(__file__), "..", "selfies")
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

    return filepath


@router.post("/submit", response_model=KYCSubmitResponse)
def submit_kyc(req: KYCSubmitRequest, db: Session = Depends(get_db)):
    """
    Submit KYC data: Aadhaar, PAN, and selfie image.
    Saves selfie to disk, stores metadata in DB.
    """
    # Save selfie
    selfie_path = None
    if req.selfie:
        try:
            selfie_path = save_selfie(req.selfie)
        except Exception as e:
            raise HTTPException(status_code=400, detail=f"Invalid selfie data: {str(e)}")

    # Create DB record
    submission = KYCSubmission(
        aadhaar_number=req.aadhaar,
        pan_number=req.pan,
        selfie_path=selfie_path,
        status=KYCStatus.PENDING,
    )
    db.add(submission)
    db.commit()
    db.refresh(submission)

    return KYCSubmitResponse(
        id=submission.id,
        status=submission.status,
        message="KYC submitted successfully. Verification pending.",
        created_at=submission.created_at,
    )


@router.get("/status/{submission_id}", response_model=KYCStatusResponse)
def get_kyc_status(submission_id: int, db: Session = Depends(get_db)):
    """
    Get KYC submission status by ID.
    """
    submission = db.query(KYCSubmission).filter(
        KYCSubmission.id == submission_id
    ).first()

    if not submission:
        raise HTTPException(status_code=404, detail="Submission not found")

    # Mask Aadhaar for security
    aadhaar_masked = "XXXX XXXX " + submission.aadhaar_number[-4:]

    return KYCStatusResponse(
        id=submission.id,
        aadhaar_masked=aadhaar_masked,
        pan=submission.pan_number,
        status=submission.status,
        has_selfie=submission.selfie_path is not None,
        created_at=submission.created_at,
    )


@router.get("/all")
def get_all_submissions(db: Session = Depends(get_db)):
    """
    Get all KYC submissions (admin endpoint).
    """
    submissions = db.query(KYCSubmission).order_by(
        KYCSubmission.created_at.desc()
    ).all()

    return [
        {
            "id": s.id,
            "aadhaar_masked": "XXXX XXXX " + s.aadhaar_number[-4:],
            "pan": s.pan_number,
            "status": s.status,
            "has_selfie": s.selfie_path is not None,
            "created_at": s.created_at.isoformat() if s.created_at else None,
        }
        for s in submissions
    ]
