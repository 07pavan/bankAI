"""
Firestore Document Schema Definitions — BankAI

This module replaces SQLAlchemy ORM models.
It documents Firestore collection/document structures as Python dataclasses
and provides shared Enum types used throughout the codebase.

Firestore Collections:
  users/               {id, aadhaar_hash, role, created_at}
  kyc_submissions/     {id, user_id, aadhaar_encrypted, pan_encrypted,
                         aadhaar_hash, selfie_path, status, created_at, updated_at}
  banks/               {id, name, code, is_active, created_at, updated_at}
  forms/               {id, bank_id, name, code, description, is_active,
                         created_at, updated_at}
  form_sections/       {id, form_id, name, order_index}
  form_fields/         {id, form_id, section_id, field_key, label, field_type,
                         required, validation_rule, options, order_index, is_active}
  submissions/         {id, user_id, form_id, status, current_field_index,
                         conversation_state, signature_path, pdf_path,
                         signed_at, created_at, updated_at}
  submission_data/     {id, submission_id, field_key, value, created_at, updated_at}

All document IDs are auto-generated Firestore string IDs.
"""

import enum


# ---------------------------------------------------------------------------
# Enums (shared across services)
# ---------------------------------------------------------------------------

class KYCStatus(str, enum.Enum):
    """KYC verification status."""
    PENDING = "pending"
    VERIFIED = "verified"
    REJECTED = "rejected"


class SubmissionStatus(str, enum.Enum):
    """Lifecycle status of a form submission."""
    DRAFT = "draft"
    COMPLETED = "completed"


class ConversationState(str, enum.Enum):
    """
    Voice agent state machine states.

    Transitions (enforced by conversation_service):
      WELCOME → SELECT_APPLICATION → FILLING_FORM → REVIEW → SIGNATURE → COMPLETE
    """
    WELCOME = "welcome"
    SELECT_APPLICATION = "select_application"
    FILLING_FORM = "filling_form"
    REVIEW = "review"
    SIGNATURE = "signature"
    COMPLETE = "complete"
    CHAT = "chat"


class FieldType(str, enum.Enum):
    """Supported form field types."""
    TEXT = "text"
    NUMBER = "number"
    DATE = "date"
    SELECT = "select"
    RADIO = "radio"
    CHECKBOX = "checkbox"


# ---------------------------------------------------------------------------
# Collection name constants
# ---------------------------------------------------------------------------

COLL_USERS = "users"
COLL_KYC_SUBMISSIONS = "kyc_submissions"
COLL_BANKS = "banks"
COLL_FORMS = "forms"
COLL_FORM_SECTIONS = "form_sections"
COLL_FORM_FIELDS = "form_fields"
COLL_SUBMISSIONS = "submissions"
COLL_SUBMISSION_DATA = "submission_data"
