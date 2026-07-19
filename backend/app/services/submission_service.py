"""
SubmissionService — Firestore edition.
Manages the lifecycle of a form submission.

Responsibilities:
  - create_submission        → start a new draft
  - get_current_field        → what field should the user answer next?
  - save_field_value         → upsert a field answer
  - move_to_next_field       → advance the cursor
  - complete_submission      → validate and mark done
  - get_submission           → fetch with ownership check
  - get_user_submissions     → list all for a user
"""

from datetime import datetime, timezone
from typing import Optional

from fastapi import HTTPException, status
from google.cloud.firestore import SERVER_TIMESTAMP

from app.database import get_db
from app.models import (
    COLL_SUBMISSIONS, COLL_SUBMISSION_DATA, COLL_FORMS,
    SubmissionStatus, ConversationState,
)
from app.services.form_service import get_ordered_active_fields
from app.core.logging import get_logger

logger = get_logger()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _doc_to_dict(doc) -> dict:
    return {"id": doc.id, **doc.to_dict()}


def _get_submission_or_404(submission_id: str) -> dict:
    db = get_db()
    doc = db.collection(COLL_SUBMISSIONS).document(submission_id).get()
    if not doc.exists:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Submission {submission_id} not found",
        )
    return _doc_to_dict(doc)


def _assert_ownership(submission: dict, user_id: str) -> None:
    if submission["user_id"] != user_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Access denied to this submission",
        )


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def create_submission(user_id: str, form_id: str) -> dict:
    """
    Start a new draft submission for the given user and form.

    Raises:
        HTTPException 404: If the form does not exist or is inactive.
    """
    db = get_db()
    form_doc = db.collection(COLL_FORMS).document(form_id).get()
    if not form_doc.exists or not form_doc.to_dict().get("is_active", False):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Form {form_id} not found or inactive",
        )

    now = datetime.now(timezone.utc)
    sub_ref = db.collection(COLL_SUBMISSIONS).document()
    sub_data = {
        "user_id": user_id,
        "form_id": form_id,
        "status": SubmissionStatus.DRAFT,
        "current_field_index": 0,
        "conversation_state": ConversationState.FILLING_FORM,
        "signature_path": None,
        "pdf_path": None,
        "signed_at": None,
        "created_at": now,
        "updated_at": now,
    }
    sub_ref.set(sub_data)
    result = {"id": sub_ref.id, **sub_data}
    logger.info(f"Created submission {sub_ref.id} for user {user_id}, form {form_id}")
    return result


def get_submission(submission_id: str, user_id: str) -> dict:
    """
    Fetch a submission by ID, enforcing ownership.

    Raises:
        HTTPException 404: Submission not found.
        HTTPException 403: Caller does not own this submission.
    """
    sub = _get_submission_or_404(submission_id)
    _assert_ownership(sub, user_id)

    # Attach answered data
    sub["data"] = _get_submission_data(submission_id)
    return sub


def _get_submission_data(submission_id: str) -> list[dict]:
    """Fetch all answered field data for a submission."""
    db = get_db()
    docs = (
        db.collection(COLL_SUBMISSION_DATA)
        .where("submission_id", "==", submission_id)
        .stream()
    )
    return [{"id": d.id, **d.to_dict()} for d in docs]


def get_current_field(submission_id: str) -> Optional[dict]:
    """
    Return the field dict at the submission's current_field_index.
    Returns None if all fields have been answered (index out of range).
    """
    sub = _get_submission_or_404(submission_id)
    fields = get_ordered_active_fields(sub["form_id"])
    idx = sub["current_field_index"]
    if idx >= len(fields):
        return None
    return fields[idx]


def save_field_value(
    submission_id: str,
    field_key: str,
    value: str,
) -> dict:
    """
    Upsert a field answer for the given submission.

    Raises:
        HTTPException 404: Submission or field not found.
        HTTPException 409: Submission already completed.
    """
    db = get_db()
    sub = _get_submission_or_404(submission_id)

    if sub["status"] == SubmissionStatus.COMPLETED:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Cannot modify a completed submission",
        )

    # Validate field_key belongs to this form
    fields = get_ordered_active_fields(sub["form_id"])
    field = next((f for f in fields if f["field_key"] == field_key), None)
    if not field:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Field '{field_key}' not found in form {sub['form_id']}",
        )

    now = datetime.now(timezone.utc)

    # Check for existing answer (upsert)
    existing_docs = (
        db.collection(COLL_SUBMISSION_DATA)
        .where("submission_id", "==", submission_id)
        .where("field_key", "==", field_key)
        .limit(1)
        .stream()
    )
    existing = next(existing_docs, None)

    if existing:
        db.collection(COLL_SUBMISSION_DATA).document(existing.id).update(
            {"value": value, "updated_at": now}
        )
        logger.info(f"Updated field '{field_key}' on submission {submission_id}")
        return {"id": existing.id, "submission_id": submission_id, "field_key": field_key, "value": value, "updated_at": now}
    else:
        data_ref = db.collection(COLL_SUBMISSION_DATA).document()
        entry = {
            "submission_id": submission_id,
            "field_key": field_key,
            "value": value,
            "created_at": now,
            "updated_at": now,
        }
        data_ref.set(entry)
        logger.info(f"Saved field '{field_key}' on submission {submission_id}")
        return {"id": data_ref.id, **entry}


def move_to_next_field(submission_id: str) -> dict:
    """
    Advance current_field_index by 1 (capped at total field count).
    Returns updated submission dict.
    """
    sub = _get_submission_or_404(submission_id)
    fields = get_ordered_active_fields(sub["form_id"])
    total = len(fields)

    new_index = sub["current_field_index"]
    if new_index < total:
        new_index += 1

    db = get_db()
    db.collection(COLL_SUBMISSIONS).document(submission_id).update(
        {"current_field_index": new_index, "updated_at": datetime.now(timezone.utc)}
    )
    sub["current_field_index"] = new_index
    logger.info(f"Submission {submission_id} moved to field index {new_index}/{total}")
    return sub


def complete_submission(submission_id: str, user_id: str) -> dict:
    """
    Validate all required fields are answered, then mark submission as completed.

    Raises:
        HTTPException 403: Caller does not own this submission.
        HTTPException 409: Already completed.
        HTTPException 422: One or more required fields are missing.
    """
    sub = _get_submission_or_404(submission_id)
    _assert_ownership(sub, user_id)

    if sub["status"] == SubmissionStatus.COMPLETED:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Submission is already completed",
        )

    fields = get_ordered_active_fields(sub["form_id"])
    answered_data = _get_submission_data(submission_id)
    answered_keys = {d["field_key"] for d in answered_data}

    missing = [f["field_key"] for f in fields if f.get("required", True) and f["field_key"] not in answered_keys]
    if missing:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Required fields not answered: {missing}",
        )

    now = datetime.now(timezone.utc)
    db = get_db()
    db.collection(COLL_SUBMISSIONS).document(submission_id).update({
        "status": SubmissionStatus.COMPLETED,
        "current_field_index": len(fields),
        "updated_at": now,
    })
    sub["status"] = SubmissionStatus.COMPLETED
    sub["current_field_index"] = len(fields)

    logger.info(f"Submission {submission_id} completed by user {user_id}")
    return sub


def get_user_submissions(user_id: str) -> list[dict]:
    """Return all submissions for a user, newest first (sorted in memory to avoid composite index requirement)."""
    db = get_db()
    docs = (
        db.collection(COLL_SUBMISSIONS)
        .where("user_id", "==", user_id)
        .stream()
    )
    docs_list = [{"id": d.id, **d.to_dict()} for d in docs]
    # Sort by created_at descending. Use datetime.min as fallback if created_at is missing.
    docs_list.sort(key=lambda d: d.get("created_at") or datetime.min.replace(tzinfo=timezone.utc), reverse=True)
    return docs_list
