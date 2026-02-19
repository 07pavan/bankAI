"""
Submissions API — form submission lifecycle.
All routes are JWT-protected.

Contracts:
  POST /api/v1/submissions/start    → start a new submission
  GET  /api/v1/submissions          → list user's submissions
  GET  /api/v1/submissions/{id}     → get submission + answers
  POST /api/v1/submissions/complete → complete a submission
"""

from fastapi import APIRouter, Depends, status
from sqlalchemy.orm import Session
from pydantic import BaseModel

from app.database import get_db
from app.core.security import get_current_user_id
from app.schemas import SubmissionCreate, SubmissionOut
from app.services import submission_service

router = APIRouter()


class CompleteSubmissionRequest(BaseModel):
    """Body for POST /submissions/complete."""
    submission_id: int


# ---------------------------------------------------------------------------
# POST /start  — begin a new draft submission
# ---------------------------------------------------------------------------

@router.post("/start", response_model=SubmissionOut, status_code=status.HTTP_201_CREATED)
def start_submission(
    payload: SubmissionCreate,
    user_id: int = Depends(get_current_user_id),
    db: Session = Depends(get_db),
):
    """
    Start a new draft form submission.

    Body: { "form_id": <int> }
    Returns the created Submission with status="draft" and current_field_index=0.
    """
    return submission_service.create_submission(user_id, payload.form_id, db)


# ---------------------------------------------------------------------------
# GET /  — list user's submissions
# ---------------------------------------------------------------------------

@router.get("", response_model=list[SubmissionOut])
def list_submissions(
    user_id: int = Depends(get_current_user_id),
    db: Session = Depends(get_db),
):
    """List all submissions for the authenticated user, newest first."""
    return submission_service.get_user_submissions(user_id, db)


# ---------------------------------------------------------------------------
# GET /{id}  — fetch a single submission
# ---------------------------------------------------------------------------

@router.get("/{submission_id}", response_model=SubmissionOut)
def get_submission(
    submission_id: int,
    user_id: int = Depends(get_current_user_id),
    db: Session = Depends(get_db),
):
    """Get a submission with all answered fields. Enforces ownership."""
    return submission_service.get_submission(submission_id, user_id, db)


# ---------------------------------------------------------------------------
# POST /complete  — finalise a submission
# ---------------------------------------------------------------------------

@router.post("/complete", response_model=SubmissionOut)
def complete_submission(
    payload: CompleteSubmissionRequest,
    user_id: int = Depends(get_current_user_id),
    db: Session = Depends(get_db),
):
    """
    Mark a submission as completed.

    Body: { "submission_id": <int> }
    Returns 422 if any required fields are unanswered.
    Returns 409 if already completed.
    """
    return submission_service.complete_submission(payload.submission_id, user_id, db)

