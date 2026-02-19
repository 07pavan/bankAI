"""
Pydantic schemas for request/response validation — BankAI
"""

from pydantic import BaseModel, field_validator, ConfigDict
from typing import Optional, Any
from datetime import datetime
import re


# ---------------------------------------------------------------------------
# Existing KYC schemas
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
    id: int
    user_id: int
    status: str
    message: str
    access_token: str
    token_type: str = "bearer"
    is_new_user: bool
    created_at: datetime


class KYCStatusResponse(BaseModel):
    """KYC status lookup response."""
    id: int
    aadhaar_masked: str
    pan_masked: str
    status: str
    has_selfie: bool
    created_at: datetime


class TokenResponse(BaseModel):
    """JWT token response"""
    access_token: str
    token_type: str = "bearer"
    user_id: int


class UserResponse(BaseModel):
    """User information response"""
    id: int
    created_at: datetime
    kyc_count: int


# ---------------------------------------------------------------------------
# Phase 2 — Form Engine schemas
# ---------------------------------------------------------------------------

class BankOut(BaseModel):
    """Public bank representation."""
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    code: str


class FormListItem(BaseModel):
    """Lightweight form summary for listing."""
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    code: str
    description: Optional[str] = None


class FormFieldOut(BaseModel):
    """Full field definition returned to clients / voice agent."""
    model_config = ConfigDict(from_attributes=True)

    id: int
    field_key: str
    label: str
    field_type: str
    required: bool
    validation_rule: Optional[Any] = None
    options: Optional[Any] = None
    order_index: int
    section_id: Optional[int] = None


class FormSectionOut(BaseModel):
    """Section with its ordered fields."""
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    order_index: int
    fields: list[FormFieldOut] = []


class FormOut(BaseModel):
    """Full form definition with sections and all active fields."""
    model_config = ConfigDict(from_attributes=True)

    id: int
    bank_id: int
    name: str
    code: str
    description: Optional[str] = None
    sections: list[FormSectionOut] = []
    fields: list[FormFieldOut] = []


# ---------------------------------------------------------------------------
# Phase 2 — Submission schemas
# ---------------------------------------------------------------------------

class SubmissionCreate(BaseModel):
    """Start a new form submission."""
    form_id: int


class FieldAnswerIn(BaseModel):
    """Save a single field answer."""
    field_key: str
    value: str


class SubmissionDataOut(BaseModel):
    """A single answered field."""
    model_config = ConfigDict(from_attributes=True)

    field_key: str
    value: Optional[str] = None
    updated_at: Optional[datetime] = None


class SubmissionOut(BaseModel):
    """Full submission with all answered data."""
    model_config = ConfigDict(from_attributes=True)

    id: int
    user_id: int
    form_id: int
    status: str
    current_field_index: int
    created_at: datetime
    updated_at: Optional[datetime] = None
    data: list[SubmissionDataOut] = []


class SubmissionProgress(BaseModel):
    """Lightweight progress snapshot for the voice agent."""
    submission_id: int
    current_field_index: int
    total_fields: int
    status: str
    current_field: Optional[FormFieldOut] = None


# ---------------------------------------------------------------------------
# Phase 2 — Conversation Agent schemas
# ---------------------------------------------------------------------------

class ConversationStartResponse(BaseModel):
    """Response when a user starts a conversation session."""
    message: str                        # Greeting / prompt to the user
    available_forms: list[FormListItem]  # Forms the user can apply for


class ConversationTurnRequest(BaseModel):
    """A single turn of user text input to the conversation agent."""
    submission_id: int
    text_input: str


class ConversationTurnResponse(BaseModel):
    """Agent response after processing one user turn."""
    submission_id: int
    field_key: Optional[str] = None      # Field that was just answered
    agent_message: str                   # Next prompt or confirmation
    is_complete: bool = False            # True when form is fully submitted
    progress: Optional[SubmissionProgress] = None

