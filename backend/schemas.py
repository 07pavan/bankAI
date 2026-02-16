"""
Pydantic schemas for request/response validation
"""

from pydantic import BaseModel, field_validator
from typing import Optional
from datetime import datetime
import re


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
    """Response after KYC submission."""
    id: int
    status: str
    message: str
    created_at: datetime


class KYCStatusResponse(BaseModel):
    """KYC status lookup response."""
    id: int
    aadhaar_masked: str
    pan: str
    status: str
    has_selfie: bool
    created_at: datetime
