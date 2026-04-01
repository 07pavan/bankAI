"""
Admin Service Layer — BankAI Admin Panel

Provides all business logic for the admin panel:
  - Bank CRUD
  - Form CRUD
  - FormSection CRUD
  - FormField CRUD
  - Submission read (admin view, no ownership restriction)

All functions accept a SQLAlchemy Session and raise HTTPException on errors.
"""

from sqlalchemy.orm import Session, joinedload
from typing import Optional, Any
from fastapi import HTTPException, status

from app.models import (
    Bank, Form, FormSection, FormField,
    Submission, SubmissionData,
)
from app.core.logging import get_logger

logger = get_logger()


# ---------------------------------------------------------------------------
# Banks
# ---------------------------------------------------------------------------

def list_banks(db: Session) -> list[Bank]:
    """Return all banks ordered by name."""
    return db.query(Bank).order_by(Bank.name).all()


def create_bank(name: str, code: str, db: Session) -> Bank:
    """
    Create a new bank.

    Raises:
        HTTPException 409: Bank with this code already exists.
    """
    code = code.upper().strip()
    existing = db.query(Bank).filter(Bank.code == code).first()
    if existing:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Bank with code '{code}' already exists",
        )
    bank = Bank(name=name.strip(), code=code, is_active=True)
    db.add(bank)
    db.commit()
    db.refresh(bank)
    logger.info(f"Admin created bank: {code}")
    return bank


# ---------------------------------------------------------------------------
# Forms
# ---------------------------------------------------------------------------

def list_forms(db: Session, bank_id: Optional[int] = None) -> list[Form]:
    """Return all forms, optionally filtered by bank."""
    q = db.query(Form).options(joinedload(Form.bank))
    if bank_id is not None:
        q = q.filter(Form.bank_id == bank_id)
    return q.order_by(Form.bank_id, Form.name).all()


def create_form(
    bank_id: int,
    name: str,
    code: str,
    description: Optional[str],
    db: Session,
) -> Form:
    """
    Create a new form under a bank.

    Raises:
        HTTPException 404: Bank not found.
        HTTPException 409: Form code already exists for this bank.
    """
    bank = db.query(Bank).filter(Bank.id == bank_id).first()
    if not bank:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Bank {bank_id} not found",
        )
    code = code.lower().strip().replace(" ", "_")
    existing = db.query(Form).filter(Form.bank_id == bank_id, Form.code == code).first()
    if existing:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Form code '{code}' already exists for this bank",
        )
    form = Form(
        bank_id=bank_id,
        name=name.strip(),
        code=code,
        description=description,
        is_active=True,
    )
    db.add(form)
    db.commit()
    db.refresh(form)
    logger.info(f"Admin created form: '{code}' for bank {bank_id}")
    return form


def update_form(
    form_id: int,
    name: Optional[str],
    description: Optional[str],
    is_active: Optional[bool],
    db: Session,
) -> Form:
    """
    Update a form's metadata.

    Raises:
        HTTPException 404: Form not found.
    """
    form = db.query(Form).filter(Form.id == form_id).first()
    if not form:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Form {form_id} not found",
        )
    if name is not None:
        form.name = name.strip()
    if description is not None:
        form.description = description
    if is_active is not None:
        form.is_active = is_active
    db.commit()
    db.refresh(form)
    logger.info(f"Admin updated form {form_id}")
    return form


# ---------------------------------------------------------------------------
# Sections
# ---------------------------------------------------------------------------

def list_sections(form_id: int, db: Session) -> list[FormSection]:
    """Return all sections for a form, ordered by order_index."""
    _assert_form_exists(form_id, db)
    return (
        db.query(FormSection)
        .filter(FormSection.form_id == form_id)
        .order_by(FormSection.order_index)
        .all()
    )


def create_section(
    form_id: int,
    name: str,
    order_index: int,
    db: Session,
) -> FormSection:
    """
    Create a new section within a form.

    Raises:
        HTTPException 404: Form not found.
    """
    _assert_form_exists(form_id, db)
    section = FormSection(
        form_id=form_id,
        name=name.strip(),
        order_index=order_index,
    )
    db.add(section)
    db.commit()
    db.refresh(section)
    logger.info(f"Admin created section '{name}' in form {form_id}")
    return section


# ---------------------------------------------------------------------------
# Fields
# ---------------------------------------------------------------------------

def list_fields(form_id: int, db: Session) -> list[FormField]:
    """Return all fields for a form, ordered by order_index."""
    _assert_form_exists(form_id, db)
    return (
        db.query(FormField)
        .filter(FormField.form_id == form_id)
        .order_by(FormField.order_index)
        .all()
    )


def create_field(
    form_id: int,
    field_key: str,
    label: str,
    field_type: str,
    required: bool,
    order_index: int,
    section_id: Optional[int],
    validation_rule: Optional[Any],
    options: Optional[Any],
    db: Session,
) -> FormField:
    """
    Create a new field within a form.

    Raises:
        HTTPException 404: Form not found.
        HTTPException 409: field_key already exists for this form.
    """
    _assert_form_exists(form_id, db)
    field_key = field_key.strip().lower().replace(" ", "_")
    existing = (
        db.query(FormField)
        .filter(FormField.form_id == form_id, FormField.field_key == field_key)
        .first()
    )
    if existing:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Field key '{field_key}' already exists in form {form_id}",
        )
    field = FormField(
        form_id=form_id,
        section_id=section_id,
        field_key=field_key,
        label=label.strip(),
        field_type=field_type,
        required=required,
        order_index=order_index,
        validation_rule=validation_rule,
        options=options,
        is_active=True,
    )
    db.add(field)
    db.commit()
    db.refresh(field)
    logger.info(f"Admin created field '{field_key}' in form {form_id}")
    return field


def update_field(
    field_id: int,
    label: Optional[str],
    field_type: Optional[str],
    required: Optional[bool],
    order_index: Optional[int],
    is_active: Optional[bool],
    validation_rule: Optional[Any],
    options: Optional[Any],
    db: Session,
) -> FormField:
    """
    Update a form field.

    Raises:
        HTTPException 404: Field not found.
    """
    field = db.query(FormField).filter(FormField.id == field_id).first()
    if not field:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Field {field_id} not found",
        )
    if label is not None:
        field.label = label.strip()
    if field_type is not None:
        field.field_type = field_type
    if required is not None:
        field.required = required
    if order_index is not None:
        field.order_index = order_index
    if is_active is not None:
        field.is_active = is_active
    if validation_rule is not None:
        field.validation_rule = validation_rule
    if options is not None:
        field.options = options
    db.commit()
    db.refresh(field)
    logger.info(f"Admin updated field {field_id}")
    return field


# ---------------------------------------------------------------------------
# Submissions (admin read-only)
# ---------------------------------------------------------------------------

def list_all_submissions(
    db: Session,
    skip: int = 0,
    limit: int = 50,
) -> list[dict]:
    """
    Return all submissions with form and bank metadata.
    Sorted newest first. Paginated via skip/limit.
    """
    rows = (
        db.query(Submission)
        .options(joinedload(Submission.form).joinedload(Form.bank))
        .order_by(Submission.created_at.desc())
        .offset(skip)
        .limit(limit)
        .all()
    )
    result = []
    for sub in rows:
        result.append({
            "id": sub.id,
            "user_id": sub.user_id,
            "form_id": sub.form_id,
            "form_name": sub.form.name if sub.form else None,
            "bank_name": sub.form.bank.name if sub.form and sub.form.bank else None,
            "status": sub.status,
            "conversation_state": sub.conversation_state,
            "created_at": sub.created_at.isoformat() if sub.created_at else None,
            "updated_at": sub.updated_at.isoformat() if sub.updated_at else None,
        })
    return result


def get_submission_detail(submission_id: int, db: Session) -> dict:
    """
    Return a single submission with all its answered field data.

    Raises:
        HTTPException 404: Submission not found.
    """
    sub = (
        db.query(Submission)
        .options(
            joinedload(Submission.data),
            joinedload(Submission.form).joinedload(Form.bank),
        )
        .filter(Submission.id == submission_id)
        .first()
    )
    if not sub:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Submission {submission_id} not found",
        )
    return {
        "id": sub.id,
        "user_id": sub.user_id,
        "form_id": sub.form_id,
        "form_name": sub.form.name if sub.form else None,
        "bank_name": sub.form.bank.name if sub.form and sub.form.bank else None,
        "status": sub.status,
        "conversation_state": sub.conversation_state,
        "current_field_index": sub.current_field_index,
        "created_at": sub.created_at.isoformat() if sub.created_at else None,
        "updated_at": sub.updated_at.isoformat() if sub.updated_at else None,
        "data": [
            {
                "field_key": d.field_key,
                "value": d.value,
                "updated_at": d.updated_at.isoformat() if d.updated_at else None,
            }
            for d in sub.data
        ],
    }


# ---------------------------------------------------------------------------
# Private helpers
# ---------------------------------------------------------------------------

def _assert_form_exists(form_id: int, db: Session) -> Form:
    form = db.query(Form).filter(Form.id == form_id).first()
    if not form:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Form {form_id} not found",
        )
    return form
