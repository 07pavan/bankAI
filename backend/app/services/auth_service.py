"""
Authentication Service — Firestore edition
JWT token management and user authentication.
"""

from typing import Optional

from app.database import get_db
from app.models import COLL_USERS
from app.core.security import create_access_token
from app.core.logging import get_logger

logger = get_logger()


def create_user_token(user_id: str) -> str:
    """
    Create JWT access token for user.

    Args:
        user_id: Firestore document ID for the user

    Returns:
        JWT token string
    """
    token = create_access_token(data={"sub": user_id})
    logger.info(f"Created access token for user {user_id}")
    return token


def get_user_by_id(user_id: str) -> Optional[dict]:
    """
    Get user document by Firestore document ID.

    Returns:
        User dict (with 'id' key) or None
    """
    db = get_db()
    doc = db.collection(COLL_USERS).document(user_id).get()
    if not doc.exists:
        return None
    return {"id": doc.id, **doc.to_dict()}
