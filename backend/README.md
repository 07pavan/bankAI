# BankAI Backend - Production-Grade KYC System

A production-ready KYC (Know Your Customer) verification backend built with FastAPI, PostgreSQL, field-level encryption, and JWT authentication.

## 🚀 Features

- **PostgreSQL Database**: Production-ready database with connection pooling
- **Field-Level Encryption**: Aadhaar and PAN numbers encrypted at rest using Fernet
- **JWT Authentication**: Secure token-based authentication
- **Duplicate Detection**: Automatic detection of existing Aadhaar (login flow)
- **Structured Logging**: Request tracing with correlation IDs and PII redaction
- **Database Migrations**: Alembic for version-controlled schema changes
- **Comprehensive Testing**: Unit and integration tests with pytest

## 📋 Prerequisites

- Python 3.9+
- PostgreSQL 12+
- pip or pipenv

## 🛠️ Installation

### 1. Install PostgreSQL

**Windows:**
```powershell
# Download and install from https://www.postgresql.org/download/windows/
# Or use Chocolatey:
choco install postgresql

# Start PostgreSQL service
net start postgresql-x64-14
```

**Create Database:**
```powershell
# Open psql
psql -U postgres

# Create database
CREATE DATABASE bankai_db;

# Exit psql
\q
```

### 2. Clone and Setup

```powershell
cd d:\bankAI\backend

# Install dependencies
pip install -r requirements.txt
```

### 3. Configure Environment

Copy `.env.example` to `.env` and update with your settings:

```powershell
cp .env.example .env
```

**Important:** Generate a secure encryption key:

```python
# Run in Python
from cryptography.fernet import Fernet
print(Fernet.generate_key().decode())
```

Update `.env` with:
- `DATABASE_URL`: Your PostgreSQL connection string
- `ENCRYPTION_KEY`: Generated Fernet key
- `JWT_SECRET_KEY`: Random secure string (use `openssl rand -hex 32`)

### 4. Run Database Migrations

```powershell
# Run migrations
alembic upgrade head
```

### 5. Start the Server

```powershell
# Development mode with auto-reload
python -m app.main

# Or using uvicorn directly
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

Server will be available at: `http://localhost:8000`

## 🧪 Running Tests

```powershell
# Run all tests
pytest

# Run with coverage
pytest --cov=app --cov-report=html

# Run specific test categories
pytest -m unit          # Unit tests only
pytest -m integration   # Integration tests only

# Run specific test file
pytest tests/test_encryption.py -v
```

## 📚 API Documentation

Once the server is running, visit:
- **Swagger UI**: http://localhost:8000/docs
- **ReDoc**: http://localhost:8000/redoc

### Key Endpoints

#### KYC Submission
```http
POST /api/v1/kyc/submit
Content-Type: application/json

{
  "aadhaar": "1234 5678 9012",
  "pan": "ABCDE1234F",
  "selfie": "data:image/jpeg;base64,..."
}
```

**Response:**
```json
{
  "id": 1,
  "user_id": 1,
  "status": "pending",
  "message": "KYC submitted successfully. Verification pending.",
  "access_token": "eyJ0eXAiOiJKV1QiLCJhbGc...",
  "token_type": "bearer",
  "is_new_user": true,
  "created_at": "2026-02-16T22:00:00Z"
}
```

#### Get KYC Status (Authenticated)
```http
GET /api/v1/kyc/status/{submission_id}
Authorization: Bearer {access_token}
```

#### Get Current User (Authenticated)
```http
GET /api/v1/auth/me
Authorization: Bearer {access_token}
```

## 🔒 Security Features

### Encryption
- **Aadhaar & PAN**: Encrypted using Fernet (AES-128 CBC)
- **Storage**: Only encrypted data stored in database
- **Hashing**: SHA-256 for duplicate detection without decryption

### Authentication
- **JWT Tokens**: HS256 algorithm
- **Expiration**: 24 hours (configurable)
- **Protected Routes**: Require valid Bearer token

### Logging
- **PII Redaction**: Automatic masking of Aadhaar/PAN in logs
- **Correlation IDs**: Request tracing across services
- **Rotating Files**: 10MB max, 5 backup files

## 📁 Project Structure

```
backend/
├── app/
│   ├── core/
│   │   ├── config.py          # Configuration management
│   │   ├── encryption.py      # Encryption utilities
│   │   ├── security.py        # JWT authentication
│   │   └── logging.py         # Structured logging
│   ├── models.py              # SQLAlchemy models
│   ├── schemas.py             # Pydantic schemas
│   ├── database.py            # Database configuration
│   ├── services/
│   │   ├── kyc_service.py     # KYC business logic
│   │   └── auth_service.py    # Authentication logic
│   ├── api/
│   │   └── v1/
│   │       ├── kyc.py         # KYC endpoints
│   │       └── auth.py        # Auth endpoints
│   └── main.py                # FastAPI application
├── alembic/
│   ├── versions/              # Migration scripts
│   └── env.py                 # Alembic configuration
├── tests/
│   ├── conftest.py            # Test fixtures
│   ├── test_encryption.py     # Encryption tests
│   ├── test_kyc_service.py    # KYC service tests
│   ├── test_auth.py           # Auth tests
│   └── test_api_kyc.py        # API integration tests
├── .env                       # Environment variables (gitignored)
├── .env.example               # Environment template
├── alembic.ini                # Alembic config
├── pytest.ini                 # Pytest config
└── requirements.txt           # Python dependencies
```

## 🔄 Database Migrations

### Create a New Migration
```powershell
alembic revision --autogenerate -m "Description of changes"
```

### Apply Migrations
```powershell
alembic upgrade head
```

### Rollback Migration
```powershell
alembic downgrade -1
```

### View Migration History
```powershell
alembic history
```

## 🐛 Troubleshooting

### PostgreSQL Connection Issues
```powershell
# Check if PostgreSQL is running
Get-Service postgresql*

# Start PostgreSQL
net start postgresql-x64-14
```

### Import Errors
```powershell
# Ensure you're in the backend directory
cd d:\bankAI\backend

# Run with Python module syntax
python -m app.main
```

### Encryption Key Issues
```python
# Generate a new key
from cryptography.fernet import Fernet
print(Fernet.generate_key().decode())
```

## 📝 Development Workflow

1. **Make Code Changes**: Edit files in `app/`
2. **Update Models**: If changing database schema, create migration
3. **Write Tests**: Add tests in `tests/`
4. **Run Tests**: `pytest`
5. **Check Logs**: View `logs/app.log`

## 🚧 Next Steps (Phase 1B)

- [ ] Add language selection
- [ ] Add bank selection
- [ ] Add multi-step forms
- [ ] Add admin dashboard
- [ ] Add role-based access control
- [ ] Add rate limiting
- [ ] Add email notifications

## 📄 License

Proprietary - BankAI Project

## 👥 Contributors

- Development Team

---

**Note**: This is a production-grade foundation. Always review security settings before deploying to production environments.
