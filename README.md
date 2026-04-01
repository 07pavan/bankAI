<p align="center">
  <strong>🏦 BankAI</strong>
</p>

<p align="center">
  <em>AI-Powered KYC Verification & Dynamic Banking Forms Platform</em>
</p>

<p align="center">
  <img src="https://img.shields.io/badge/FastAPI-009688?style=for-the-badge&logo=fastapi&logoColor=white" alt="FastAPI" />
  <img src="https://img.shields.io/badge/PostgreSQL-4169E1?style=for-the-badge&logo=postgresql&logoColor=white" alt="PostgreSQL" />
  <img src="https://img.shields.io/badge/JavaScript-F7DF1E?style=for-the-badge&logo=javascript&logoColor=black" alt="JavaScript" />
  <img src="https://img.shields.io/badge/Tesseract.js-4285F4?style=for-the-badge&logo=google&logoColor=white" alt="Tesseract.js" />
  <img src="https://img.shields.io/badge/JWT-000000?style=for-the-badge&logo=jsonwebtokens&logoColor=white" alt="JWT" />
</p>

---

## 📖 Overview

**BankAI** is a production-grade, full-stack banking platform that combines **camera-based KYC verification**, a **conversational AI voice agent** for dynamic form filling, and a comprehensive **admin panel** — all built with security-first principles including field-level encryption, JWT authentication, and PII redaction.

### ✨ Key Highlights

| Feature | Description |
|---------|-------------|
| 🔐 **KYC Verification** | Camera-based Aadhaar & PAN scanning with Tesseract.js OCR + live selfie capture |
| 🤖 **AI Voice Agent** | Conversational interface that walks users through bank application forms via voice or text |
| 🏛️ **Admin Panel** | Full CRUD for banks, forms, fields, sections, and submission management |
| 🛡️ **Field-Level Encryption** | Aadhaar/PAN encrypted at rest with Fernet (AES-128 CBC) + SHA-256 hashing |
| 🗃️ **Dynamic Form Engine** | DB-driven forms with configurable fields, sections, validation rules, and options |
| 📊 **Submission Tracking** | State machine–driven form submissions with resume-from-where-you-left-off |

---

## 🏗️ Architecture

```
bankAI/
├── index.html              # KYC verification flow (Aadhaar → PAN → Selfie)
├── dashboard.html          # User dashboard with AI voice chat agent
├── admin.html              # Admin panel (banks, forms, fields, submissions)
├── css/
│   └── styles.css          # Design system — glassmorphism, dark theme, animations
├── js/
│   ├── app.js              # Main KYC flow orchestration
│   ├── camera.js           # Camera access & document capture
│   ├── ocr.js              # Tesseract.js OCR extraction (Aadhaar/PAN numbers)
│   ├── selfie.js           # Live selfie capture with face circle overlay
│   └── admin.js            # Admin panel logic (CRUD, auth, submissions)
├── backend/
│   ├── app/
│   │   ├── main.py         # FastAPI application entry point
│   │   ├── database.py     # SQLAlchemy engine & session
│   │   ├── models.py       # All database models (User, KYC, Bank, Form, Submission)
│   │   ├── schemas.py      # Pydantic request/response schemas
│   │   ├── core/
│   │   │   ├── config.py       # Settings via pydantic-settings
│   │   │   ├── encryption.py   # Fernet encryption + SHA-256 hashing
│   │   │   ├── security.py     # JWT token creation & validation
│   │   │   ├── logging.py      # Structured logging with PII redaction
│   │   │   └── seed.py         # Idempotent seed data (SBI bank, 3 forms)
│   │   ├── api/v1/
│   │   │   ├── kyc.py          # POST /api/v1/kyc/submit, GET ../status
│   │   │   ├── auth.py         # GET /api/v1/auth/me
│   │   │   ├── forms.py        # Public form listing & detail endpoints
│   │   │   ├── submissions.py  # Create, answer, complete submissions
│   │   │   ├── conversation.py # AI agent conversation turn endpoints
│   │   │   └── admin.py        # Admin-only CRUD endpoints
│   │   └── services/
│   │       ├── kyc_service.py          # KYC business logic
│   │       ├── auth_service.py         # Authentication logic
│   │       ├── form_service.py         # Form retrieval logic
│   │       ├── submission_service.py   # Submission lifecycle
│   │       ├── conversation_service.py # AI voice agent state machine
│   │       └── admin_service.py        # Admin operations
│   ├── alembic/             # Database migration scripts
│   ├── tests/               # pytest unit & integration tests
│   ├── requirements.txt     # Python dependencies
│   ├── alembic.ini          # Alembic configuration
│   └── .env.example         # Environment variables template
└── .gitignore
```

---

## 🖥️ Application Pages

### 1. KYC Verification (`index.html`)

A premium 3-step wizard with glassmorphism dark-theme design:

| Step | Action | Technology |
|------|--------|------------|
| **Step 1** — Aadhaar | Camera auto-captures card → OCR extracts 12-digit number | Tesseract.js |
| **Step 2** — PAN | Camera auto-captures card → OCR extracts PAN number | Tesseract.js |
| **Step 3** — Selfie | Face circle overlay → user captures live selfie | MediaStream API |
| **Submit** | Sends encrypted data to backend → receives JWT token | Fetch API |

### 2. User Dashboard (`dashboard.html`)

An AI-powered banking dashboard featuring:

- **Welcome Hero** — personalized greeting with selfie avatar & KYC badge
- **AI Voice Agent** — conversational interface (text + microphone) that:
  - Greets the user and shows available bank application forms
  - Walks through each form field sequentially via natural language
  - Validates answers against field rules in real-time
  - Shows a review summary before final submission
- **Form Progress Bar** — visual tracker for multi-field form completion
- **Text-to-Speech** — AI responses are spoken aloud using the Web Speech API

### 3. Admin Panel (`admin.html`)

A full-featured administration interface with:

- **JWT Token Authentication** — admin login via token (dev: submit KYC with Aadhaar `999 999 999 999`)
- **Banks Management** — create and manage bank entities
- **Forms Management** — create/edit forms, add sections and fields with type/validation/options
- **Submissions Viewer** — browse all submissions with pagination, view detailed field-level data
- **Toast Notifications** — real-time feedback for all admin operations

---

## 🚀 Getting Started

### Prerequisites

| Requirement | Version |
|-------------|---------|
| Python | 3.9+ |
| PostgreSQL | 12+ |
| Node.js | Not required (vanilla JS frontend) |
| Modern Browser | Chrome/Edge/Firefox with camera access |

### 1. Clone the Repository

```bash
git clone https://github.com/07pavan/bankAI.git
cd bankAI
```

### 2. Set Up PostgreSQL

```sql
-- Connect to PostgreSQL
psql -U postgres

-- Create the database
CREATE DATABASE bankai_db;

-- Exit
\q
```

### 3. Configure the Backend

```powershell
cd backend

# Create virtual environment
python -m venv bankAI
.\bankAI\Scripts\activate  # Windows

# Install dependencies
pip install -r requirements.txt

# Copy environment template
cp .env.example .env
```

Edit `.env` with your settings:

```env
DATABASE_URL=postgresql://postgres:your_password@localhost:5432/bankai_db
ENCRYPTION_KEY=<generated-fernet-key>
JWT_SECRET_KEY=<random-hex-string>
CORS_ORIGINS=http://localhost:8000,http://127.0.0.1:8000
```

Generate required keys:

```python
# Fernet encryption key
from cryptography.fernet import Fernet
print(Fernet.generate_key().decode())
```

```powershell
# JWT secret key  (or use: python -c "import secrets; print(secrets.token_hex(32))")
openssl rand -hex 32
```

### 4. Run Database Migrations

```powershell
alembic upgrade head
```

### 5. Start the Server

```powershell
# Development mode with auto-reload
python -m app.main

# Or using uvicorn directly
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

### 6. Open the Application

| Page | URL |
|------|-----|
| **KYC Verification** | [http://localhost:8000/index.html](http://localhost:8000/index.html) |
| **Dashboard** | [http://localhost:8000/dashboard.html](http://localhost:8000/dashboard.html) |
| **Admin Panel** | [http://localhost:8000/admin.html](http://localhost:8000/admin.html) |
| **API Docs (Swagger)** | [http://localhost:8000/docs](http://localhost:8000/docs) |
| **API Docs (ReDoc)** | [http://localhost:8000/redoc](http://localhost:8000/redoc) |

---

## 🔑 API Reference

### KYC Endpoints

| Method | Endpoint | Description | Auth |
|--------|----------|-------------|------|
| `POST` | `/api/v1/kyc/submit` | Submit Aadhaar + PAN + selfie for verification | — |
| `GET` | `/api/v1/kyc/status/{id}` | Get KYC submission status | Bearer |

### Auth Endpoints

| Method | Endpoint | Description | Auth |
|--------|----------|-------------|------|
| `GET` | `/api/v1/auth/me` | Get current authenticated user | Bearer |

### Form Endpoints (Public)

| Method | Endpoint | Description | Auth |
|--------|----------|-------------|------|
| `GET` | `/api/v1/forms/banks` | List all active banks | Bearer |
| `GET` | `/api/v1/forms/banks/{id}/forms` | List active forms for a bank | Bearer |
| `GET` | `/api/v1/forms/{id}` | Get full form definition with fields | Bearer |

### Submission Endpoints

| Method | Endpoint | Description | Auth |
|--------|----------|-------------|------|
| `POST` | `/api/v1/submissions/` | Create a new submission | Bearer |
| `POST` | `/api/v1/submissions/{id}/answer` | Save a field answer | Bearer |
| `POST` | `/api/v1/submissions/{id}/complete` | Mark submission as complete | Bearer |
| `GET` | `/api/v1/submissions/{id}` | Get submission with all data | Bearer |

### Conversation (AI Agent) Endpoints

| Method | Endpoint | Description | Auth |
|--------|----------|-------------|------|
| `GET` | `/api/v1/conversation/start` | Start conversation, get available forms | Bearer |
| `POST` | `/api/v1/conversation/turn` | Process one user turn | Bearer |

### Admin Endpoints

| Method | Endpoint | Description | Auth |
|--------|----------|-------------|------|
| `POST` | `/api/v1/admin/banks` | Create a bank | Admin |
| `GET` | `/api/v1/admin/banks` | List all banks | Admin |
| `POST` | `/api/v1/admin/forms` | Create a form | Admin |
| `GET` | `/api/v1/admin/forms` | List all forms (filterable) | Admin |
| `PUT` | `/api/v1/admin/forms/{id}` | Update a form | Admin |
| `POST` | `/api/v1/admin/forms/{id}/sections` | Add a section to a form | Admin |
| `POST` | `/api/v1/admin/forms/{id}/fields` | Add a field to a form | Admin |
| `PUT` | `/api/v1/admin/fields/{id}` | Update a field | Admin |
| `DELETE` | `/api/v1/admin/fields/{id}` | Delete a field | Admin |
| `GET` | `/api/v1/admin/submissions` | List all submissions (paginated) | Admin |
| `GET` | `/api/v1/admin/submissions/{id}` | Get submission detail | Admin |

### Health Check

| Method | Endpoint | Description |
|--------|----------|-------------|
| `GET` | `/api/health` | System health status |

---

## 🔒 Security

### Encryption & Hashing

- **Aadhaar & PAN** — encrypted at rest using **Fernet (AES-128 CBC)** with a server-managed key
- **Duplicate Detection** — Aadhaar hashed with **SHA-256** for deduplication without decryption
- **Selfie Storage** — saved to disk (path stored in DB), not base64 in database

### Authentication & Authorization

- **JWT Tokens** — HS256 algorithm, 24-hour expiration (configurable)
- **Role-Based Access** — `user` role for regular users, `admin` role for admin panel access
- **Dev Admin** — submit KYC with Aadhaar `999999999999` to receive an admin JWT (dev only)

### Logging & PII Protection

- **PII Redaction** — automatic masking of Aadhaar & PAN numbers in all log output
- **Correlation IDs** — request tracing via `X-Correlation-ID` headers
- **Rotating Log Files** — 10MB max file size, 5 backup rotations

---

## 🧪 Testing

```powershell
cd backend

# Run all tests
pytest

# Run with coverage report
pytest --cov=app --cov-report=html

# Run by category
pytest -m unit           # Unit tests only
pytest -m integration    # Integration tests only

# Run a specific test file
pytest tests/test_encryption.py -v
```

---

## 🗄️ Database

### Models

| Model | Description |
|-------|-------------|
| `User` | Authenticated user with `aadhaar_hash` and `role` |
| `KYCSubmission` | Encrypted KYC data (Aadhaar, PAN, selfie path) |
| `Bank` | Bank entity (e.g., "State Bank of India") |
| `Form` | Bank application form (e.g., "Account Opening") |
| `FormSection` | Logical grouping of fields within a form |
| `FormField` | Individual form field with type, validation, and options |
| `Submission` | User's in-progress or completed form submission |
| `SubmissionData` | Key-value field answers within a submission |

### Migrations

```powershell
# Create a new migration
alembic revision --autogenerate -m "Description of changes"

# Apply migrations
alembic upgrade head

# Rollback one migration
alembic downgrade -1

# View migration history
alembic history
```

### Seed Data

On startup, the server idempotently seeds:
- **1 Bank** — State Bank of India (SBI)
- **3 Forms** — Account Opening, Aadhaar Seeding, Cheque Book Request
- **1 Admin User** — dev admin with known Aadhaar hash

---

## 🛠️ Tech Stack

### Frontend
| Technology | Purpose |
|------------|---------|
| HTML5 + CSS3 | Semantic markup with glassmorphism dark theme |
| Vanilla JavaScript | No framework overhead — pure ES6+ |
| Tesseract.js v5 | Client-side OCR for document scanning |
| Web Speech API | Text-to-speech for AI agent responses |
| MediaStream API | Camera access for document/selfie capture |
| Inter (Google Fonts) | Modern, clean typography |

### Backend
| Technology | Purpose |
|------------|---------|
| FastAPI | High-performance async Python API framework |
| PostgreSQL | Production-ready relational database |
| SQLAlchemy 2.0 | ORM with connection pooling |
| Alembic | Version-controlled database migrations |
| Pydantic v2 | Request/response validation & serialization |
| Fernet (cryptography) | AES-128 encryption for sensitive fields |
| python-jose | JWT token creation & verification |
| uvicorn | ASGI server with auto-reload |

---

## 📝 Development Notes

### Conversation State Machine

The AI voice agent follows a strict state machine:

```
CHAT → WELCOME → SELECT_APPLICATION → FILLING_FORM → REVIEW → COMPLETE
```

- State transitions are enforced by the backend — the AI cannot skip states
- The backend is the single source of truth for the current state
- Form progress is persisted, allowing users to resume from where they left off

### Dynamic Form Engine

All form structure is **database-driven** — no hardcoded fields in service logic:

- `is_active` flags enable admin soft-delete/deactivation
- `order_index` on sections & fields enables admin reordering
- `validation_rule` JSON supports extensible validation without schema changes
- `options` JSON supports dynamic select/radio/checkbox choices

---

## 📄 License

Proprietary — BankAI Project

## 👤 Author

**Pavan Hegade** — [pavanhegade06@gmail.com](mailto:pavanhegade06@gmail.com)

---

<p align="center">
  <sub>Built with ❤️ using FastAPI, PostgreSQL, and vanilla JavaScript</sub>
</p>
