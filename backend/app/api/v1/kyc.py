"""
KYC API Endpoints (v1)
Handles KYC submission, status retrieval, and admin endpoints
"""

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.database import get_db
from app.schemas import KYCSubmitRequest, KYCSubmitResponse, KYCStatusResponse
from app.services import kyc_service, auth_service
from app.core.security import get_current_user_id
from app.core.logging import get_logger

logger = get_logger()
router = APIRouter()


@router.post("/submit", response_model=KYCSubmitResponse)
def submit_kyc(req: KYCSubmitRequest, db: Session = Depends(get_db)):
    """
    Submit KYC data: Aadhaar, PAN, and selfie image.
    
    - If Aadhaar already exists: Returns existing user with JWT (login flow)
    - If new Aadhaar: Creates user and KYC submission, returns JWT (registration flow)
    """
    try:
        # Submit KYC with duplicate detection
        user, submission, is_new_user = kyc_service.submit_kyc(
            aadhaar=req.aadhaar,
            pan=req.pan,
            selfie=req.selfie,
            db=db
        )
        
        # Create JWT token
        access_token = auth_service.create_user_token(user.id)
        
        message = (
            "KYC submitted successfully. Verification pending."
            if is_new_user
            else "Welcome back! Login successful."
        )
        
        logger.info(
            f"KYC submission successful - User: {user.id}, "
            f"Submission: {submission.id}, New: {is_new_user}"
        )
        
        return KYCSubmitResponse(
            id=submission.id,
            user_id=user.id,
            status=submission.status,
            message=message,
            access_token=access_token,
            token_type="bearer",
            is_new_user=is_new_user,
            created_at=submission.created_at,
        )
    
    except ValueError as e:
        logger.error(f"KYC submission validation error: {str(e)}")
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"KYC submission error: {str(e)}")
        raise HTTPException(status_code=500, detail="Internal server error")


@router.get("/status/{submission_id}", response_model=KYCStatusResponse)
def get_kyc_status(
    submission_id: int,
    db: Session = Depends(get_db),
    current_user_id: int = Depends(get_current_user_id)
):
    """
    Get KYC submission status by ID.
    Requires authentication. Only the submitting user may view their own record.
    """
    from app.models import KYCSubmission
    # Ownership check — prevent horizontal privilege escalation
    submission_record = db.query(KYCSubmission).filter(
        KYCSubmission.id == submission_id
    ).first()
    if not submission_record:
        raise HTTPException(status_code=404, detail="Submission not found")
    if submission_record.user_id != current_user_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Access denied to this submission",
        )

    result = kyc_service.get_kyc_status(submission_id, db)
    logger.info(f"User {current_user_id} retrieved KYC status for submission {submission_id}")
    return KYCStatusResponse(**result)


@router.get("/all")
def get_all_submissions(
    db: Session = Depends(get_db),
    current_user_id: int = Depends(get_current_user_id)
):
    """
    Get all KYC submissions.

    SECURITY: This endpoint is restricted until admin roles are implemented.
    Any authenticated user hitting this endpoint receives 403.
    TODO: Replace this guard with a proper admin role check.
    """
    # SECURITY GUARD — remove when admin roles are implemented
    raise HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail="Admin access required. This endpoint is not yet available.",
    )
