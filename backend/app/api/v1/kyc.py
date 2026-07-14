"""
KYC API Endpoints (v1) — Firestore edition
Handles KYC submission, status retrieval, and admin endpoints.
"""

from fastapi import APIRouter, Depends, HTTPException, Request, status

from app.schemas import KYCSubmitRequest, KYCSubmitResponse, KYCStatusResponse
from app.services import kyc_service, auth_service
from app.core.security import get_current_user_id
from app.core.logging import get_logger
from app.core.rate_limit import limiter

logger = get_logger()
router = APIRouter()


@router.post("/submit", response_model=KYCSubmitResponse)
@limiter.limit("5/minute")
def submit_kyc(request: Request, req: KYCSubmitRequest):
    """
    Submit KYC data: Aadhaar, PAN, and selfie image.

    - If Aadhaar already exists: Returns existing user with JWT (login flow)
    - If new Aadhaar: Creates user and KYC submission, returns JWT (registration flow)
    """
    try:
        user, submission, is_new_user = kyc_service.submit_kyc(
            aadhaar=req.aadhaar,
            pan=req.pan,
            selfie=req.selfie,
        )

        access_token = auth_service.create_user_token(user["id"])

        message = (
            "KYC submitted successfully. Verification pending."
            if is_new_user
            else "Welcome back! Login successful."
        )

        logger.info(
            f"KYC submission successful - User: {user['id']}, "
            f"Submission: {submission['id']}, New: {is_new_user}"
        )

        return KYCSubmitResponse(
            id=submission["id"],
            user_id=user["id"],
            status=submission["status"],
            message=message,
            access_token=access_token,
            token_type="bearer",
            is_new_user=is_new_user,
            created_at=submission["created_at"],
        )

    except ValueError as e:
        logger.error(f"KYC submission validation error: {str(e)}")
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"KYC submission error: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail="Internal server error")


@router.get("/status/{submission_id}", response_model=KYCStatusResponse)
def get_kyc_status(
    submission_id: str,
    current_user_id: str = Depends(get_current_user_id),
):
    """
    Get KYC submission status by ID.
    Requires authentication. Only the submitting user may view their own record.
    """
    from app.database import get_db
    from app.models import COLL_KYC_SUBMISSIONS

    db = get_db()
    doc = db.collection(COLL_KYC_SUBMISSIONS).document(submission_id).get()
    if not doc.exists:
        raise HTTPException(status_code=404, detail="Submission not found")

    sub = doc.to_dict()
    if sub.get("user_id") != current_user_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Access denied to this submission",
        )

    result = kyc_service.get_kyc_status(submission_id)
    logger.info(f"User {current_user_id} retrieved KYC status for submission {submission_id}")
    return KYCStatusResponse(**result)


@router.get("/all")
def get_all_submissions(
    current_user_id: str = Depends(get_current_user_id),
):
    """
    Get all KYC submissions.
    SECURITY: Restricted to admin users only.
    """
    raise HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail="Admin access required. This endpoint is not yet available.",
    )
