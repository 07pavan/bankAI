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


from pydantic import BaseModel

class OCRSpaceRequest(BaseModel):
    base64_image: str


@router.post("/ocr-space")
@limiter.limit("10/minute")
async def ocr_space_scan(request: Request, req: OCRSpaceRequest):
    """
    Perform server-side OCR scan using OCR.space API.
    Uses the configured OCR_SPACE_API_KEY, falling back to 'helloworld' testing key.
    """
    import httpx
    from app.core.config import settings

    api_key = settings.OCR_SPACE_API_KEY or "helloworld"
    url = "https://api.ocr.space/parse/image"

    payload = {
        "apikey": api_key,
        "base64Image": req.base64_image,
        "language": "eng",
        "detectOrientation": "true",
        "scale": "true",
        "isTable": "false"
    }

    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            response = await client.post(url, data=payload)

        if response.status_code != 200:
            logger.error(f"OCR.space API responded with status {response.status_code}: {response.text}")
            raise HTTPException(status_code=500, detail="OCR service failed to respond")

        res_data = response.json()

        if res_data.get("IsErroredOnProcessing"):
            error_msg = res_data.get("ErrorMessage") or "Unknown processing error"
            logger.error(f"OCR.space processing error: {error_msg}")
            raise HTTPException(status_code=400, detail=f"OCR processing failed: {error_msg}")

        parsed_results = res_data.get("ParsedResults", [])
        if not parsed_results:
            return {"text": ""}

        parsed_text = parsed_results[0].get("ParsedText", "")
        return {"text": parsed_text}

    except httpx.RequestError as exc:
        logger.error(f"Connection to OCR.space failed: {exc}")
        raise HTTPException(status_code=503, detail="Could not reach OCR service")
    except HTTPException:
        raise
    except Exception as exc:
        logger.error(f"OCR.space integration error: {exc}", exc_info=True)
        raise HTTPException(status_code=500, detail="Internal server error during OCR")
