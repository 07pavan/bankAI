"""
Security utilities for JWT authentication (Firestore edition)
"""

from datetime import datetime, timedelta
from typing import Optional
from jose import JWTError, jwt
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials

from app.core.config import settings
from app.database import get_db
from app.models import COLL_USERS

security = HTTPBearer()


def create_access_token(data: dict, expires_delta: Optional[timedelta] = None) -> str:
    """
    Create JWT access token

    Args:
        data: Payload to encode (typically {"sub": user_id, "role": role})
        expires_delta: Optional custom expiration time

    Returns:
        Encoded JWT token string
    """
    to_encode = data.copy()

    if expires_delta:
        expire = datetime.utcnow() + expires_delta
    else:
        expire = datetime.utcnow() + timedelta(
            minutes=settings.JWT_ACCESS_TOKEN_EXPIRE_MINUTES
        )

    to_encode.update({"exp": expire})
    encoded_jwt = jwt.encode(
        to_encode,
        settings.JWT_SECRET_KEY,
        algorithm=settings.JWT_ALGORITHM
    )
    return encoded_jwt


def verify_token(token: str) -> dict:
    """
    Verify and decode JWT token

    Args:
        token: JWT token string

    Returns:
        Decoded token payload

    Raises:
        HTTPException: If token is invalid or expired
    """
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )

    try:
        payload = jwt.decode(
            token,
            settings.JWT_SECRET_KEY,
            algorithms=[settings.JWT_ALGORITHM]
        )
        return payload
    except JWTError:
        raise credentials_exception


def get_current_user_id(
    credentials: HTTPAuthorizationCredentials = Depends(security)
) -> str:
    """
    Dependency to extract user ID string from JWT token.

    Args:
        credentials: HTTP Bearer token from request

    Returns:
        User ID string (Firestore document ID)

    Raises:
        HTTPException: If token is invalid or missing user_id
    """
    token = credentials.credentials
    payload = verify_token(token)

    user_id: str = payload.get("sub")
    if user_id is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid authentication credentials"
        )

    return user_id


def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(security),
) -> dict:
    """
    Dependency to fetch the full user document from Firestore using the JWT.

    Returns:
        User dictionary with 'id' key

    Raises:
        HTTPException 401: Token invalid.
        HTTPException 404: User not found in Firestore.
    """
    user_id = get_current_user_id(credentials)
    db = get_db()
    user_doc = db.collection(COLL_USERS).document(user_id).get()
    if not user_doc.exists:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found",
        )
    return {"id": user_doc.id, **user_doc.to_dict()}


def require_admin_user(
    current_user: dict = Depends(get_current_user),
) -> dict:
    """
    Dependency that enforces admin role.
    Call this as a FastAPI Depends() on any admin-only endpoint.

    Returns:
        User dict (role == 'admin' guaranteed)

    Raises:
        HTTPException 401: Token invalid.
        HTTPException 403: User is not an admin.
    """
    if current_user.get("role") != "admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Admin access required",
        )
    return current_user
