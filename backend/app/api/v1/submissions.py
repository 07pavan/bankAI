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
    VoiceSignatureUploadRequest, VoiceSignatureUploadResponse,
)
from app.services import submission_service
from app.services import signature_service
from app.services import pdf_service

logger = get_logger()

router = APIRouter()


class CompleteSubmissionRequest(BaseModel):
    """Body for POST /submissions/complete."""
    submission_id: str


class BankerOverrideRequest(BaseModel):
    """Body for POST /submissions/{id}/override."""
    field_key: str
    value: str


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
# POST /{id}/voice-signature  — upload voice signature audio (Phase 4)
# ---------------------------------------------------------------------------

@router.post(
    "/{submission_id}/voice-signature",
    response_model=VoiceSignatureUploadResponse,
    summary="Upload applicant voice signature consent",
)
def upload_voice_signature(
    submission_id: str,
    payload: VoiceSignatureUploadRequest,
    user_id: str = Depends(get_current_user_id),
):
    """
    Upload a base64-encoded webm voice recording consent for a submission.
    Transitions submission to COMPLETE state and status to completed.
    """
    result = signature_service.save_voice_signature(
        submission_id=submission_id,
        user_id=user_id,
        base64_audio=payload.audio,
    )
    logger.info(f"Voice signature uploaded: submission={submission_id} user={user_id}")
    return VoiceSignatureUploadResponse(
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


# ---------------------------------------------------------------------------
# GET /active/monitor — retrieve all active draft submissions (Banker Co-Pilot)
# ---------------------------------------------------------------------------

@router.get("/active/monitor", summary="Retrieve all active submissions for banker monitor")
def get_active_monitor(
    user_id: str = Depends(get_current_user_id),
):
    """
    List all active draft submissions in the system.
    """
    return submission_service.get_active_submissions()


# ---------------------------------------------------------------------------
# POST /{id}/override — allow a banker to override a field (Banker Co-Pilot)
# ---------------------------------------------------------------------------

@router.post("/{submission_id}/override", summary="Banker override of form field")
def banker_override(
    submission_id: str,
    payload: BankerOverrideRequest,
    user_id: str = Depends(get_current_user_id),
):
    """
    Allow a banker to manually override a submission field.
    """
    return submission_service.banker_override_field(
        submission_id=submission_id,
        field_key=payload.field_key,
        value=payload.value,
    )


