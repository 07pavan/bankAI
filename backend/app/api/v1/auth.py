"""
Authentication API Endpoints (v1) — Firestore edition
User authentication and profile management.

Endpoints:
  GET  /api/v1/auth/me      — return profile for current JWT
  POST /api/v1/auth/login   — returning-user login by aadhaar (demo) → JWT
"""

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from typing import Optional

from app.schemas import UserResponse
from app.services import auth_service
from app.core.security import get_current_user_id, create_access_token
from app.core.logging import get_logger
from app.database import get_db
from app.models import COLL_KYC_SUBMISSIONS, COLL_USERS

logger = get_logger()
router = APIRouter()


# ---------------------------------------------------------------------------
# GET /me — return authenticated user profile
# ---------------------------------------------------------------------------

@router.get("/me", response_model=UserResponse)
def get_current_user(
    current_user_id: str = Depends(get_current_user_id),
):
    """Get current authenticated user information from their JWT token."""
    user = auth_service.get_user_by_id(current_user_id)

    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found",
        )

    logger.info(f"User {current_user_id} retrieved their profile")

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


# ---------------------------------------------------------------------------
# POST /login — returning user login by aadhaar (demo / offline mode)
# ---------------------------------------------------------------------------

class LoginRequest(BaseModel):
    """Login body — returning user identifies via their masked Aadhaar last 4."""
    aadhaar_last4: str          # Last 4 digits of the aadhaar they provided at KYC
    demo_mode: bool = False     # If True, accepts any value (for offline demo)


class LoginResponse(BaseModel):
    """Successful login response."""
    access_token: str
    token_type: str = "bearer"
    user_id: str
    message: str


@router.post("/login", response_model=LoginResponse)
def login(payload: LoginRequest):
    """
    Returning-user login endpoint.

    Strategy (demo/offline mode):
      1. If demo_mode=True → find ANY KYC-verified user and issue a token.
      2. Otherwise → look up user by aadhaar_last4 in kyc_submissions.

    In production, this would be replaced by OTP/biometric verification.
    For now it allows returning users to access the dashboard without repeating KYC.
    """
    db = get_db()

    if payload.demo_mode:
        # Demo mode: find first KYC-verified user (with timeout)
        try:
            timeout_sec = 8  # Give Firestore 8 seconds max before giving up

            import concurrent.futures
            with concurrent.futures.ThreadPoolExecutor(max_workers=1) as executor:
                future = executor.submit(
                    lambda: list(db.collection(COLL_KYC_SUBMISSIONS).limit(1).stream())
                )
                try:
                    kyc_docs = future.result(timeout=timeout_sec)
                except concurrent.futures.TimeoutError:
                    raise HTTPException(
                        status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                        detail="Database is unreachable (dummy credentials). Complete KYC first or configure real Firebase credentials.",
                    )

        except HTTPException:
            raise
        except Exception as exc:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail=f"Database error in demo login: {str(exc)[:120]}",
            )

        if not kyc_docs:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="No users found. Please complete KYC first.",
            )
        user_id = kyc_docs[0].to_dict().get("user_id")
    else:
        # Real mode: match by aadhaar last 4 digits
        last4 = (payload.aadhaar_last4 or "").strip()
        if len(last4) != 4 or not last4.isdigit():
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Please enter the last 4 digits of your Aadhaar number.",
            )

        # Search KYC submissions for a matching aadhaar_last4 field
        kyc_docs = list(
            db.collection(COLL_KYC_SUBMISSIONS)
            .where("aadhaar_last4", "==", last4)
            .limit(1)
            .stream()
        )
        if not kyc_docs:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="No account found for this Aadhaar. Please complete KYC first.",
            )
        user_id = kyc_docs[0].to_dict().get("user_id")

    if not user_id:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Could not resolve user account. Please try again.",
        )

    token = create_access_token(data={"sub": user_id})
    logger.info(f"Returning user login: user_id={user_id}")

    return LoginResponse(
        access_token=token,
        user_id=user_id,
        message="Login successful! Welcome back.",
    )
