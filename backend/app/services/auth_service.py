"""
Authentication Service
JWT token management and user authentication
"""

from sqlalchemy.orm import Session
from typing import Optional

from app.models import User
from app.core.security import create_access_token
from app.core.logging import get_logger

logger = get_logger()


def create_user_token(user_id: int) -> str:
    """
    Create JWT access token for user
    
    Args:
        user_id: User ID to encode in token
    
    Returns:
        JWT token string
    """
    token = create_access_token(data={"sub": str(user_id)})
    logger.info(f"Created access token for user {user_id}")
    return token


def get_user_by_id(user_id: int, db: Session) -> Optional[User]:
    """
    Get user by ID
    
    Args:
        user_id: User ID
        db: Database session
    
    Returns:
        User object or None
    """
    return db.query(User).filter(User.id == user_id).first()
