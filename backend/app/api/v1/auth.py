"""
Authentication API Endpoints (v1) — Firestore edition
User authentication and profile management.
"""

from fastapi import APIRouter, Depends, HTTPException, status

from app.schemas import UserResponse
from app.services import auth_service
from app.core.security import get_current_user_id
from app.core.logging import get_logger

logger = get_logger()
router = APIRouter()


@router.get("/me", response_model=UserResponse)
def get_current_user(
    current_user_id: str = Depends(get_current_user_id),
):
    """Get current authenticated user information."""
    user = auth_service.get_user_by_id(current_user_id)

    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found",
        )

    logger.info(f"User {current_user_id} retrieved their profile")

    # Count KYC submissions for this user
    from app.database import get_db
    from app.models import COLL_KYC_SUBMISSIONS
    db = get_db()
    kyc_docs = list(
        db.collection(COLL_KYC_SUBMISSIONS)
        .where("user_id", "==", current_user_id)
        .stream()
    )

    return UserResponse(
        id=user["id"],
        created_at=user["created_at"],
        kyc_count=len(kyc_docs),
    )
