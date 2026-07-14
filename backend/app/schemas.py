"""
Pydantic schemas for request/response validation — BankAI (Firestore edition)

All entity IDs are now strings (Firestore document IDs) instead of integers.
"""

from pydantic import BaseModel, field_validator, ConfigDict
from typing import Optional, Any
from datetime import datetime
import re


# ---------------------------------------------------------------------------
# KYC schemas
# ---------------------------------------------------------------------------

class KYCSubmitRequest(BaseModel):
    """Incoming KYC submission from frontend."""
    aadhaar: str
    pan: str
    selfie: Optional[str] = None  # base64 data URL

    @field_validator("aadhaar")
    @classmethod
    def validate_aadhaar(cls, v):
        cleaned = v.replace(" ", "")
        if not re.match(r"^\d{12}$", cleaned):
            raise ValueError("Aadhaar must be 12 digits")
        return v

    @field_validator("pan")
    @classmethod
    def validate_pan(cls, v):
        if not re.match(r"^[A-Z]{5}\d{4}[A-Z]$", v.upper()):
            raise ValueError("PAN must be in format ABCDE1234F")
        return v.upper()


class KYCSubmitResponse(BaseModel):
    """Response after KYC submission with JWT token."""
    id: str
    user_id: str
    status: str
    message: str
    access_token: str
    token_type: str = "bearer"
    is_new_user: bool
    created_at: datetime


class KYCStatusResponse(BaseModel):
    """KYC status lookup response."""
    id: str
    aadhaar_masked: str
    pan_masked: str
    status: str
    has_selfie: bool
    created_at: datetime


class TokenResponse(BaseModel):
    """JWT token response"""
    access_token: str
    token_type: str = "bearer"
    user_id: str


class UserResponse(BaseModel):
    """User information response"""
    id: str
    created_at: datetime
    kyc_count: int


# ---------------------------------------------------------------------------
# Form Engine schemas
# ---------------------------------------------------------------------------

class BankOut(BaseModel):
    """Public bank representation."""
    id: str
    name: str
    code: str


class FormListItem(BaseModel):
    """Lightweight form summary for listing."""
    id: str
    name: str
    code: str
    description: Optional[str] = None


class FormFieldOut(BaseModel):
    """Full field definition returned to clients / voice agent."""
    id: str
    field_key: str
    label: str
    field_type: str
    required: bool
    validation_rule: Optional[Any] = None
    options: Optional[Any] = None
    order_index: int
    section_id: Optional[str] = None


class FormSectionOut(BaseModel):
    """Section with its ordered fields."""
    id: str
    name: str
    order_index: int
    fields: list[FormFieldOut] = []


class FormOut(BaseModel):
    """Full form definition with sections and all active fields."""
    id: str
    bank_id: str
    name: str
    code: str
    description: Optional[str] = None
    sections: list[FormSectionOut] = []
    fields: list[FormFieldOut] = []


# ---------------------------------------------------------------------------
# Submission schemas
# ---------------------------------------------------------------------------

class SubmissionCreate(BaseModel):
    """Start a new form submission."""
    form_id: str


class FieldAnswerIn(BaseModel):
    """Save a single field answer."""
    field_key: str
    value: str


class SubmissionDataOut(BaseModel):
    """A single answered field."""
    field_key: str
    value: Optional[str] = None
    updated_at: Optional[datetime] = None


class SubmissionOut(BaseModel):
    """Full submission with all answered data."""
    id: str
    user_id: str
    form_id: str
    status: str
    current_field_index: int
    conversation_state: Optional[str] = None
    signature_path: Optional[str] = None
    pdf_path: Optional[str] = None
    signed_at: Optional[datetime] = None
    created_at: datetime
    updated_at: Optional[datetime] = None
    data: list[SubmissionDataOut] = []


class SubmissionProgress(BaseModel):
    """Lightweight progress snapshot for the voice agent."""
    submission_id: str
    current_field_index: int
    total_fields: int
    status: str
    current_field: Optional[FormFieldOut] = None


# ---------------------------------------------------------------------------
# Signature & PDF schemas
# ---------------------------------------------------------------------------

class SignatureUploadRequest(BaseModel):
    """Upload a base64-encoded signature image."""
    image: str  # base64 string (with or without data URL prefix)


class SignatureUploadResponse(BaseModel):
    """Response after successful signature upload."""
    submission_id: str
    message: str = "Signature saved successfully."
    signed_at: str


# ---------------------------------------------------------------------------
# Conversation Agent schemas
# ---------------------------------------------------------------------------

class ConversationStartResponse(BaseModel):
    """Response when a user starts a conversation session."""
    message: str
    available_forms: list[FormListItem]


class ConversationTurnRequest(BaseModel):
    """A single turn of user text input to the conversation agent."""
    submission_id: str
    text_input: str


class ConversationTurnResponse(BaseModel):
    """Agent response after processing one user turn."""
    submission_id: str
    field_key: Optional[str] = None
    agent_message: str
    is_complete: bool = False
    progress: Optional[SubmissionProgress] = None


# ---------------------------------------------------------------------------
# Admin Panel schemas
# ---------------------------------------------------------------------------

class BankCreate(BaseModel):
    """Create a new bank."""
    name: str
    code: str


class BankAdminOut(BaseModel):
    """Full bank representation for admin."""
    id: str
    name: str
    code: str
    is_active: bool
    created_at: Optional[datetime] = None


class FormCreate(BaseModel):
    """Create a new form."""
    bank_id: str
    name: str
    code: str
    description: Optional[str] = None


class FormUpdate(BaseModel):
    """Partial update for a form."""
    name: Optional[str] = None
    description: Optional[str] = None
    is_active: Optional[bool] = None


class FormAdminOut(BaseModel):
    """Full form representation for admin."""
    id: str
    bank_id: str
    name: str
    code: str
    description: Optional[str] = None
    is_active: bool
    created_at: Optional[datetime] = None


class SectionCreate(BaseModel):
    """Create a new form section."""
    name: str
    order_index: int = 0


class SectionAdminOut(BaseModel):
    """Section representation for admin."""
    id: str
    form_id: str
    name: str
    order_index: int


class FieldCreate(BaseModel):
    """Create a new form field."""
    field_key: str
    label: str
    field_type: str
    required: bool = True
    order_index: int = 0
    section_id: Optional[str] = None
    validation_rule: Optional[Any] = None
    options: Optional[Any] = None


class FieldUpdate(BaseModel):
    """Partial update for a form field."""
    label: Optional[str] = None
    field_type: Optional[str] = None
    required: Optional[bool] = None
    order_index: Optional[int] = None
    is_active: Optional[bool] = None
    validation_rule: Optional[Any] = None
    options: Optional[Any] = None


class FieldAdminOut(BaseModel):
    """Field representation for admin."""
    id: str
    form_id: str
    section_id: Optional[str] = None
    field_key: str
    label: str
    field_type: str
    required: bool
    order_index: int
    is_active: bool
    validation_rule: Optional[Any] = None
    options: Optional[Any] = None


class AdminSubmissionListItem(BaseModel):
    """Summary row for the admin submissions list."""
    id: str
    user_id: str
    form_id: str
    form_name: Optional[str] = None
    bank_name: Optional[str] = None
    status: str
    conversation_state: Optional[str] = None
    created_at: Optional[str] = None
    updated_at: Optional[str] = None


class AdminSubmissionDataItem(BaseModel):
    """A single answered field in a submission."""
    field_key: str
    value: Optional[str] = None
    updated_at: Optional[str] = None


class AdminSubmissionDetail(BaseModel):
    """Full detail view of a submission for admin."""
    id: str
    user_id: str
    form_id: str
    form_name: Optional[str] = None
    bank_name: Optional[str] = None
    status: str
    conversation_state: Optional[str] = None
    current_field_index: int
    created_at: Optional[str] = None
    updated_at: Optional[str] = None
    data: list[AdminSubmissionDataItem] = []
