"""
Signature Service — capture and persist user signatures.

Handles:
  - Base64 image decoding and validation
  - Saving signature as PNG to /backend/signatures/
  - Updating submission record with signature_path and signed_at

Security:
  - Max image size enforced (512 KB)
  - Only valid base64 PNG/JPEG accepted
  - Ownership verified by the API layer before calling this service
"""

import base64
import os
import uuid
from datetime import datetime, timezone

from fastapi import HTTPException, status

from app.database import get_db
from app.models import COLL_SUBMISSIONS, ConversationState
from app.core.logging import get_logger

logger = get_logger()

# Configuration
SIGNATURE_DIR = os.path.join(os.path.dirname(__file__), "..", "..", "signatures")
MAX_SIGNATURE_BYTES = 512 * 1024  # 512 KB


def _ensure_signature_dir() -> None:
    """Create the signatures directory if it doesn't exist."""
    os.makedirs(SIGNATURE_DIR, exist_ok=True)


def save_signature(
    submission_id: str,
    user_id: str,
    base64_image: str,
) -> dict:
    """
    Decode a base64 signature image, save to disk, and update the submission.

    Args:
        submission_id: Firestore document ID of the submission.
        user_id:       Authenticated user ID (for ownership check).
        base64_image:  Base64-encoded image string (with or without data URL prefix).

    Returns:
        dict with keys: submission_id, signature_path, signed_at

    Raises:
        HTTPException 400: Invalid or empty image data.
        HTTPException 404: Submission not found.
        HTTPException 403: Caller does not own this submission.
        HTTPException 409: Submission not in REVIEW/SIGNATURE state.
        HTTPException 413: Image too large.
    """
    # --- Validate input ---
    if not base64_image or not base64_image.strip():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Signature image data is required.",
        )

    # --- Load submission from Firestore ---
    db = get_db()
    sub_doc = db.collection(COLL_SUBMISSIONS).document(submission_id).get()
    if not sub_doc.exists:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Submission {submission_id} not found.",
        )
    sub = sub_doc.to_dict()

    # --- Ownership check ---
    if sub.get("user_id") != user_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Access denied to this submission.",
        )

    # --- State check: only allow in REVIEW or SIGNATURE state ---
    current_state = sub.get("conversation_state")
    allowed_states = {ConversationState.REVIEW.value, ConversationState.SIGNATURE.value}
    if current_state not in allowed_states:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                f"Signature can only be captured in REVIEW or SIGNATURE state. "
                f"Current state: {current_state}"
            ),
        )

    # --- Strip data URL prefix if present ---
    image_data = base64_image.strip()
    if image_data.startswith("data:"):
        # e.g. "data:image/png;base64,iVBOR..."
        try:
            _, image_data = image_data.split(",", 1)
        except ValueError:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Invalid data URL format for signature image.",
            )

    # --- Decode base64 ---
    try:
        image_bytes = base64.b64decode(image_data, validate=True)
    except Exception:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid base64 encoding for signature image.",
        )

    # --- Size check ---
    if len(image_bytes) > MAX_SIGNATURE_BYTES:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail=f"Signature image exceeds maximum size of {MAX_SIGNATURE_BYTES // 1024} KB.",
        )

    # --- Validate image magic bytes (PNG or JPEG) ---
    is_png = image_bytes[:8] == b'\x89PNG\r\n\x1a\n'
    is_jpeg = image_bytes[:2] == b'\xff\xd8'
    if not (is_png or is_jpeg):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Signature must be a PNG or JPEG image.",
        )

    extension = "png" if is_png else "jpg"

    # --- Save to disk ---
    _ensure_signature_dir()
    filename = f"{uuid.uuid4().hex}.{extension}"
    filepath = os.path.join(SIGNATURE_DIR, filename)

    try:
        with open(filepath, "wb") as f:
            f.write(image_bytes)
    except OSError as exc:
        logger.error(f"Failed to write signature file {filepath}: {exc}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to save signature. Please try again.",
        )

    # --- Update Firestore submission document ---
    now = datetime.now(timezone.utc)
    # Store RELATIVE path in DB (portable across OS / Docker)
    relative_path = f"signatures/{filename}"

    update_payload: dict = {
        "signature_path": relative_path,
        "signed_at": now,
    }

    # Transition to SIGNATURE state if currently in REVIEW
    if current_state == ConversationState.REVIEW.value:
        update_payload["conversation_state"] = ConversationState.SIGNATURE.value
        logger.info(
            f"Submission {submission_id} transitioned REVIEW → SIGNATURE "
            f"after signature capture"
        )

    db.collection(COLL_SUBMISSIONS).document(submission_id).update(update_payload)

    logger.info(
        f"Signature saved: submission={submission_id} user={user_id} "
        f"file={filename} size={len(image_bytes)} bytes"
    )

    return {
        "submission_id": submission_id,
        "signature_path": relative_path,
        "signed_at": now.isoformat(),
    }
