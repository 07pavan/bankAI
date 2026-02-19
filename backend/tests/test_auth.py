"""
Unit tests for authentication service
"""

import pytest
from jose import jwt
from app.services import auth_service
from app.core.config import settings
from app.core.security import verify_token, create_access_token
from app.models import User


@pytest.mark.unit
def test_create_user_token():
    """Test JWT token creation"""
    user_id = 123
    token = auth_service.create_user_token(user_id)
    
    assert token is not None
    assert len(token) > 0
    
    # Verify token payload
    payload = jwt.decode(
        token,
        settings.JWT_SECRET_KEY,
        algorithms=[settings.JWT_ALGORITHM]
    )
    assert payload["sub"] == str(user_id)


@pytest.mark.unit
def test_verify_token_valid():
    """Test verifying a valid token"""
    user_id = 456
    token = create_access_token(data={"sub": str(user_id)})
    
    payload = verify_token(token)
    assert payload["sub"] == str(user_id)


@pytest.mark.unit
def test_verify_token_invalid():
    """Test verifying an invalid token"""
    from fastapi import HTTPException
    
    with pytest.raises(HTTPException) as exc_info:
        verify_token("invalid.token.here")
    
    assert exc_info.value.status_code == 401


@pytest.mark.unit
def test_get_user_by_id(db_session):
    """Test retrieving user by ID"""
    # Create a user
    user = User(aadhaar_hash="test_hash_123")
    db_session.add(user)
    db_session.commit()
    db_session.refresh(user)
    
    # Retrieve user
    retrieved = auth_service.get_user_by_id(user.id, db_session)
    
    assert retrieved is not None
    assert retrieved.id == user.id
    assert retrieved.aadhaar_hash == "test_hash_123"


@pytest.mark.unit
def test_get_user_by_id_not_found(db_session):
    """Test retrieving non-existent user"""
    result = auth_service.get_user_by_id(99999, db_session)
    assert result is None
