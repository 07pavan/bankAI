"""
Test configuration and fixtures.

IMPORTANT: DATABASE_URL must be set to SQLite BEFORE any app module is imported,
because app.database creates the engine at module load time.
"""

import os
# Override DATABASE_URL and clear LLM API Key before importing any app module
os.environ["DATABASE_URL"] = "sqlite:///:memory:"
os.environ["JWT_SECRET_KEY"] = "test-secret-key-for-testing-only"
os.environ["ENCRYPTION_KEY"] = "ymvd_FUwFxxgXOtibihMGmhdWIvLwe1fW5ze3aQ5_-8="
os.environ["LLM_API_KEY"] = ""

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import app.database as app_db  # import after env vars are set
from app.database import Base, get_db
from app.main import app
from app.core.encryption import encryption_service
from app.core.rate_limit import limiter

# Disable rate limiting during tests
limiter.enabled = False


# Use in-memory SQLite for testing
SQLALCHEMY_DATABASE_URL = "sqlite:///:memory:"

engine = create_engine(
    SQLALCHEMY_DATABASE_URL,
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)
TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

# Patch the app's engine so Base.metadata.create_all uses SQLite
app_db.engine = engine
app_db.SessionLocal = TestingSessionLocal


@pytest.fixture(scope="function")
def db_session():
    """Create a fresh database session for each test"""
    Base.metadata.create_all(bind=engine)
    db = TestingSessionLocal()
    try:
        yield db
    finally:
        db.close()
        Base.metadata.drop_all(bind=engine)


@pytest.fixture(scope="function")
def client(db_session):
    """Create a test client with overridden database dependency"""
    def override_get_db():
        try:
            yield db_session
        finally:
            pass

    app.dependency_overrides[get_db] = override_get_db
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()


@pytest.fixture
def sample_aadhaar():
    """Sample Aadhaar number for testing"""
    return "1234 5678 9012"


@pytest.fixture
def sample_pan():
    """Sample PAN number for testing"""
    return "ABCDE1234F"


@pytest.fixture
def sample_kyc_data(sample_aadhaar, sample_pan):
    """Sample KYC submission data"""
    return {
        "aadhaar": sample_aadhaar,
        "pan": sample_pan,
        "selfie": None
    }
