"""
Submissions API — form submission lifecycle.
All routes are JWT-protected.

Contracts:
  POST /api/v1/submissions/start              → start a new submission
  GET  /api/v1/submissions                    → list user's submissions
  GET  /api/v1/submissions/{id}               → get submission + answers
  POST /api/v1/submissions/complete           → complete a submission
  POST /api/v1/submissions/{id}/signature     → upload signature (Phase 3)
  GET  /api/v1/submissions/{id}/pdf           → download generated PDF (Phase 3)
"""

from fastapi import APIRouter, Depends, status
from fastapi.responses import FileResponse
from pydantic import BaseModel


from app.core.security import get_current_user_id
from app.core.logging import get_logger
from app.schemas import (
    SubmissionCreate, SubmissionOut,
    SignatureUploadRequest, SignatureUploadResponse,
)
from app.services import submission_service
from app.services import signature_service
from app.services import pdf_service

logger = get_logger()

router = APIRouter()


class CompleteSubmissionRequest(BaseModel):
    """Body for POST /submissions/complete."""
    submission_id: str


# ---------------------------------------------------------------------------
# POST /start  — begin a new draft submission
# ---------------------------------------------------------------------------

@router.post("/start", response_model=SubmissionOut, status_code=status.HTTP_201_CREATED)
def start_submission(
    payload: SubmissionCreate,
    user_id: str = Depends(get_current_user_id),
):
    """
    Start a new draft form submission.

    Body: { "form_id": <str> }
    Returns the created Submission with status="draft" and current_field_index=0.
    """
    return submission_service.create_submission(user_id, payload.form_id)


# ---------------------------------------------------------------------------
# GET /  — list user's submissions
# ---------------------------------------------------------------------------

@router.get("", response_model=list[SubmissionOut])
def list_submissions(
    user_id: str = Depends(get_current_user_id),
):
    """List all submissions for the authenticated user, newest first."""
    return submission_service.get_user_submissions(user_id)


# ---------------------------------------------------------------------------
# GET /{id}  — fetch a single submission
# ---------------------------------------------------------------------------

@router.get("/{submission_id}", response_model=SubmissionOut)
def get_submission(
    submission_id: str,
    user_id: str = Depends(get_current_user_id),
):
    """Get a submission with all answered fields. Enforces ownership."""
    return submission_service.get_submission(submission_id, user_id)


# ---------------------------------------------------------------------------
# POST /complete  — finalise a submission
# ---------------------------------------------------------------------------

@router.post("/complete", response_model=SubmissionOut)
def complete_submission(
    payload: CompleteSubmissionRequest,
    user_id: str = Depends(get_current_user_id),
):
    """
    Mark a submission as completed.

    Body: { "submission_id": <str> }
    Returns 422 if any required fields are unanswered.
    Returns 409 if already completed.
    """
    return submission_service.complete_submission(payload.submission_id, user_id)


# ---------------------------------------------------------------------------
# POST /{id}/signature  — upload signature image (Phase 3)
# ---------------------------------------------------------------------------

@router.post(
    "/{submission_id}/signature",
    response_model=SignatureUploadResponse,
    summary="Upload applicant signature",
)
def upload_signature(
    submission_id: str,
    payload: SignatureUploadRequest,
    user_id: str = Depends(get_current_user_id),
):
    """
    Upload a base64-encoded signature image for a submission.

    - Auth required (JWT)
    - Only the submission owner can upload
    - Only allowed when submission is in REVIEW or SIGNATURE state
    - Accepts PNG or JPEG, max 512 KB
    - Transitions submission to SIGNATURE state

    Body: { "image": "<base64 string>" }
    """
    result = signature_service.save_signature(
        submission_id=submission_id,
        user_id=user_id,
        base64_image=payload.image,
    )
    logger.info(f"Signature uploaded: submission={submission_id} user={user_id}")
    return SignatureUploadResponse(
        submission_id=result["submission_id"],
        signed_at=result["signed_at"],
    )


# ---------------------------------------------------------------------------
# GET /{id}/pdf  — download generated PDF (Phase 3)
# ---------------------------------------------------------------------------

@router.get(
    "/{submission_id}/pdf",
    summary="Download submission PDF",
    responses={
        200: {"content": {"application/pdf": {}}, "description": "PDF file"},
    },
)
def download_pdf(
    submission_id: str,
    user_id: str = Depends(get_current_user_id),
):
    """
    Generate and download a PDF for a completed submission.

    - Auth required (JWT)
    - Only the submission owner can download
    - Only available for completed submissions
    - Sensitive data (Aadhaar, PAN) is masked in the PDF
    - Includes the user's signature if captured
    """
    filepath = pdf_service.generate_pdf(
        submission_id=submission_id,
        user_id=user_id,
    )
    logger.info(f"PDF downloaded: submission={submission_id} user={user_id}")
    return FileResponse(
        path=filepath,
        media_type="application/pdf",
        filename=f"BankAI_Application_{submission_id}.pdf",
    )

