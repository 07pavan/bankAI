"""
SubmissionService — manages the lifecycle of a form submission.

Responsibilities:
  - create_submission        → start a new draft
  - get_current_field        → what field should the user answer next?
  - save_field_value         → upsert a field answer
  - move_to_next_field       → advance the cursor
  - complete_submission      → validate and mark done
  - get_submission           → fetch with ownership check
  - get_user_submissions     → list all for a user

All business logic stays here; routers only call these functions.
"""

from sqlalchemy.orm import Session
from typing import Optional
from fastapi import HTTPException, status

from app.models import Submission, SubmissionData, SubmissionStatus, Form, FormField
from app.services.form_service import get_ordered_active_fields
from app.core.logging import get_logger

logger = get_logger()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _get_submission_or_404(submission_id: int, db: Session) -> Submission:
    sub = db.query(Submission).filter(Submission.id == submission_id).first()
    if not sub:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Submission {submission_id} not found",
        )
    return sub


def _assert_ownership(submission: Submission, user_id: int) -> None:
    if submission.user_id != user_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Access denied to this submission",
        )


def _answered_keys(submission: Submission) -> set[str]:
    return {d.field_key for d in submission.data}


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def create_submission(user_id: int, form_id: int, db: Session) -> Submission:
    """
    Start a new draft submission for the given user and form.

    Raises:
        HTTPException 404: If the form does not exist or is inactive.
    """
    form = db.query(Form).filter(Form.id == form_id, Form.is_active == True).first()
    if not form:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Form {form_id} not found or inactive",
        )

    submission = Submission(
        user_id=user_id,
        form_id=form_id,
        status=SubmissionStatus.DRAFT,
        current_field_index=0,
    )
    db.add(submission)
    db.commit()
    db.refresh(submission)

    logger.info(f"Created submission {submission.id} for user {user_id}, form {form_id}")
    return submission


def get_submission(submission_id: int, user_id: int, db: Session) -> Submission:
    """
    Fetch a submission by ID, enforcing ownership.

    Raises:
        HTTPException 404: Submission not found.
        HTTPException 403: Caller does not own this submission.
    """
    sub = _get_submission_or_404(submission_id, db)
    _assert_ownership(sub, user_id)
    return sub


def get_current_field(submission_id: int, db: Session) -> Optional[FormField]:
    """
    Return the FormField at the submission's current_field_index.
    Returns None if all fields have been answered (index out of range).
    """
    sub = _get_submission_or_404(submission_id, db)
    fields = get_ordered_active_fields(sub.form_id, db)

    idx = sub.current_field_index
    if idx >= len(fields):
        return None  # All fields done
    return fields[idx]


def save_field_value(
    submission_id: int,
    field_key: str,
    value: str,
    db: Session,
) -> SubmissionData:
    """
    Upsert a field answer for the given submission.

    Validates:
      - Submission exists
      - field_key belongs to the form
      - Submission is still a draft

    Raises:
        HTTPException 404: Submission or field not found.
        HTTPException 409: Submission already completed.
    """
    sub = _get_submission_or_404(submission_id, db)

    if sub.status == SubmissionStatus.COMPLETED:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Cannot modify a completed submission",
        )

    # Validate field_key belongs to this form
    field = (
        db.query(FormField)
        .filter(
            FormField.form_id == sub.form_id,
            FormField.field_key == field_key,
            FormField.is_active == True,
        )
        .first()
    )
    if not field:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Field '{field_key}' not found in form {sub.form_id}",
        )

    # Upsert
    existing = (
        db.query(SubmissionData)
        .filter(
            SubmissionData.submission_id == submission_id,
            SubmissionData.field_key == field_key,
        )
        .first()
    )

    if existing:
        existing.value = value
        db.commit()
        db.refresh(existing)
        logger.info(f"Updated field '{field_key}' on submission {submission_id}")
        return existing
    else:
        entry = SubmissionData(
            submission_id=submission_id,
            field_key=field_key,
            value=value,
        )
        db.add(entry)
        db.commit()
        db.refresh(entry)
        logger.info(f"Saved field '{field_key}' on submission {submission_id}")
        return entry


def move_to_next_field(submission_id: int, db: Session) -> Submission:
    """
    Advance current_field_index by 1 (capped at total field count).

    Returns:
        Updated Submission object.
    """
    sub = _get_submission_or_404(submission_id, db)
    fields = get_ordered_active_fields(sub.form_id, db)
    total = len(fields)

    if sub.current_field_index < total:
        sub.current_field_index += 1

    db.commit()
    db.refresh(sub)
    logger.info(
        f"Submission {submission_id} moved to field index {sub.current_field_index}/{total}"
    )
    return sub


def complete_submission(submission_id: int, user_id: int, db: Session) -> Submission:
    """
    Validate all required fields are answered, then mark submission as completed.

    Raises:
        HTTPException 403: Caller does not own this submission.
        HTTPException 409: Already completed.
        HTTPException 422: One or more required fields are missing.
    """
    sub = _get_submission_or_404(submission_id, db)
    _assert_ownership(sub, user_id)

    if sub.status == SubmissionStatus.COMPLETED:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Submission is already completed",
        )

    fields = get_ordered_active_fields(sub.form_id, db)
    answered = _answered_keys(sub)

    missing = [
        f.field_key
        for f in fields
        if f.required and f.field_key not in answered
    ]

    if missing:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Required fields not answered: {missing}",
        )

    sub.status = SubmissionStatus.COMPLETED
    sub.current_field_index = len(fields)  # Advance past all fields
    db.commit()
    db.refresh(sub)

    logger.info(f"Submission {submission_id} completed by user {user_id}")
    return sub


def get_user_submissions(user_id: int, db: Session) -> list[Submission]:
    """Return all submissions for a user, newest first."""
    return (
        db.query(Submission)
        .filter(Submission.user_id == user_id)
        .order_by(Submission.created_at.desc())
        .all()
    )
