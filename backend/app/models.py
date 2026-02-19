"""
SQLAlchemy models for BankAI:
  - KYC (existing): User, KYCSubmission
  - Phase 2 (new): Bank, Form, FormSection, FormField, Submission, SubmissionData
"""

from sqlalchemy import (
    Column, Integer, String, Text, Boolean, DateTime,
    ForeignKey, Index, UniqueConstraint, JSON
)
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from app.database import Base
import enum


# ---------------------------------------------------------------------------
# Existing KYC models
# ---------------------------------------------------------------------------

class KYCStatus(str, enum.Enum):
    """KYC verification status"""
    PENDING = "pending"
    VERIFIED = "verified"
    REJECTED = "rejected"


class User(Base):
    """
    User model for authentication.
    Created after successful KYC submission.
    """
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    aadhaar_hash = Column(String(64), unique=True, nullable=False, index=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    # Relationships
    kyc_submissions = relationship("KYCSubmission", back_populates="user")
    submissions = relationship("Submission", back_populates="user")  # Phase 2

    def __repr__(self):
        return f"<User(id={self.id})>"


class KYCSubmission(Base):
    """KYC submission with field-level encrypted sensitive data."""
    __tablename__ = "kyc_submissions"

    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)

    aadhaar_encrypted = Column(Text, nullable=False)
    pan_encrypted = Column(Text, nullable=False)
    aadhaar_hash = Column(String(64), nullable=False, index=True)
    selfie_path = Column(String(255), nullable=True)

    status = Column(String(20), default=KYCStatus.PENDING)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

    user = relationship("User", back_populates="kyc_submissions")

    def __repr__(self):
        return f"<KYCSubmission(id={self.id}, user_id={self.user_id}, status={self.status})>"


Index('idx_user_status', KYCSubmission.user_id, KYCSubmission.status)


# ---------------------------------------------------------------------------
# Phase 2 — Dynamic Form Engine models
# ---------------------------------------------------------------------------

class Bank(Base):
    """A bank that owns one or more application forms."""
    __tablename__ = "banks"

    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String(200), nullable=False)
    code = Column(String(20), unique=True, nullable=False, index=True)
    is_active = Column(Boolean, default=True, nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

    forms = relationship("Form", back_populates="bank")

    def __repr__(self):
        return f"<Bank(code={self.code})>"


class Form(Base):
    """
    A bank application form (e.g. Savings Account, Fixed Deposit).
    code is unique per bank.
    """
    __tablename__ = "forms"
    __table_args__ = (
        UniqueConstraint("bank_id", "code", name="uq_form_bank_code"),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    bank_id = Column(Integer, ForeignKey("banks.id"), nullable=False, index=True)
    name = Column(String(200), nullable=False)
    code = Column(String(50), nullable=False)
    description = Column(Text, nullable=True)
    is_active = Column(Boolean, default=True, nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

    bank = relationship("Bank", back_populates="forms")
    sections = relationship(
        "FormSection", back_populates="form",
        cascade="all, delete-orphan", order_by="FormSection.order_index"
    )
    fields = relationship(
        "FormField", back_populates="form",
        cascade="all, delete-orphan", order_by="FormField.order_index"
    )

    def __repr__(self):
        return f"<Form(code={self.code}, bank_id={self.bank_id})>"


class FormSection(Base):
    """
    A logical grouping of fields within a form (e.g. 'Personal Info').
    order_index controls display order.
    """
    __tablename__ = "form_sections"

    id = Column(Integer, primary_key=True, autoincrement=True)
    form_id = Column(
        Integer, ForeignKey("forms.id", ondelete="CASCADE"),
        nullable=False, index=True
    )
    name = Column(String(200), nullable=False)
    order_index = Column(Integer, nullable=False, default=0)

    form = relationship("Form", back_populates="sections")
    fields = relationship(
        "FormField", back_populates="section", order_by="FormField.order_index"
    )

    def __repr__(self):
        return f"<FormSection(name={self.name}, form_id={self.form_id})>"


class FieldType(str, enum.Enum):
    """Supported form field types."""
    TEXT = "text"
    NUMBER = "number"
    DATE = "date"
    SELECT = "select"
    RADIO = "radio"
    CHECKBOX = "checkbox"


class FormField(Base):
    """
    A single field within a form.
    field_key is unique per form and used as the stable identifier
    for the voice agent and submission_data storage.

    validation_rule JSON shape: {"pattern": "regex", "min": 0, "max": 100, "min_length": 2}
    options JSON shape (for select/radio/checkbox): [{"value": "...", "label": "..."}]
    """
    __tablename__ = "form_fields"
    __table_args__ = (
        UniqueConstraint("form_id", "field_key", name="uq_field_form_key"),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    form_id = Column(
        Integer, ForeignKey("forms.id", ondelete="CASCADE"),
        nullable=False, index=True
    )
    section_id = Column(
        Integer, ForeignKey("form_sections.id", ondelete="SET NULL"),
        nullable=True, index=True
    )
    field_key = Column(String(100), nullable=False)
    label = Column(String(300), nullable=False)
    field_type = Column(String(20), nullable=False)   # FieldType enum values
    required = Column(Boolean, default=True, nullable=False)
    validation_rule = Column(JSON, nullable=True)
    options = Column(JSON, nullable=True)
    order_index = Column(Integer, nullable=False, default=0)
    is_active = Column(Boolean, default=True, nullable=False)

    form = relationship("Form", back_populates="fields")
    section = relationship("FormSection", back_populates="fields")

    def __repr__(self):
        return f"<FormField(key={self.field_key}, type={self.field_type})>"


class SubmissionStatus(str, enum.Enum):
    """Lifecycle status of a form submission."""
    DRAFT = "draft"
    COMPLETED = "completed"


class ConversationState(str, enum.Enum):
    """
    Voice agent state machine states.

    Transitions (enforced by conversation_service):
      WELCOME → SELECT_APPLICATION → FILLING_FORM → REVIEW → COMPLETE

    The backend is the single source of truth for state.
    The AI reads this state and generates the appropriate prompt;
    it cannot skip states or modify form structure.
    """
    WELCOME = "welcome"
    SELECT_APPLICATION = "select_application"
    FILLING_FORM = "filling_form"
    REVIEW = "review"
    COMPLETE = "complete"
    CHAT = "chat"   # Pre-submission dashboard chat mode (greeting / small-talk / help)


class Submission(Base):
    """
    A user's in-progress or completed form submission.
    current_field_index enables the voice agent to resume mid-form.
    """
    __tablename__ = "submissions"

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    form_id = Column(Integer, ForeignKey("forms.id"), nullable=False, index=True)
    status = Column(String(20), default=SubmissionStatus.DRAFT, nullable=False)
    current_field_index = Column(Integer, default=0, nullable=False)
    # State machine — controls voice agent flow
    conversation_state = Column(
        String(30),
        default=ConversationState.FILLING_FORM,
        nullable=False,
    )
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

    user = relationship("User", back_populates="submissions")
    form = relationship("Form")
    data = relationship(
        "SubmissionData", back_populates="submission",
        cascade="all, delete-orphan"
    )

    def __repr__(self):
        return f"<Submission(id={self.id}, user_id={self.user_id}, status={self.status})>"


class SubmissionData(Base):
    """
    Key-value store for individual field answers within a submission.
    Unique on (submission_id, field_key) — safe to upsert.
    """
    __tablename__ = "submission_data"
    __table_args__ = (
        UniqueConstraint("submission_id", "field_key", name="uq_submission_field"),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    submission_id = Column(
        Integer, ForeignKey("submissions.id", ondelete="CASCADE"),
        nullable=False, index=True
    )
    field_key = Column(String(100), nullable=False)
    value = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

    submission = relationship("Submission", back_populates="data")

    def __repr__(self):
        return f"<SubmissionData(submission_id={self.submission_id}, key={self.field_key})>"

