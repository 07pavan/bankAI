"""
FormService — read-only queries for form structure.
All business logic stays here; routers only call these functions.
"""

from sqlalchemy.orm import Session
from typing import Optional

from app.models import Bank, Form, FormField
from app.core.logging import get_logger

logger = get_logger()


def get_active_banks(db: Session) -> list[Bank]:
    """Return all active banks."""
    return db.query(Bank).filter(Bank.is_active == True).order_by(Bank.name).all()


def get_active_forms(bank_id: int, db: Session) -> list[Form]:
    """
    Return all active forms for a given bank.

    Args:
        bank_id: PK of the bank
        db: Database session

    Returns:
        List of Form objects (without sections/fields loaded)

    Raises:
        ValueError: If the bank does not exist or is inactive
    """
    bank = db.query(Bank).filter(Bank.id == bank_id, Bank.is_active == True).first()
    if not bank:
        raise ValueError(f"Bank {bank_id} not found or inactive")

    forms = (
        db.query(Form)
        .filter(Form.bank_id == bank_id, Form.is_active == True)
        .order_by(Form.name)
        .all()
    )
    logger.info(f"Fetched {len(forms)} active forms for bank_id={bank_id}")
    return forms


def get_form_structure(form_id: int, db: Session) -> Optional[Form]:
    """
    Return a form with its sections and all active fields, ordered correctly.

    The returned Form ORM object has:
      - .sections  → ordered list of FormSection, each with .fields
      - .fields    → flat ordered list of all active FormField objects

    Args:
        form_id: PK of the form
        db: Database session

    Returns:
        Form ORM object, or None if not found / inactive
    """
    form = (
        db.query(Form)
        .filter(Form.id == form_id, Form.is_active == True)
        .first()
    )
    if not form:
        logger.warning(f"Form {form_id} not found or inactive")
        return None

    # Filter to only active fields (relationship loads all; we filter in-place)
    form.fields = [f for f in form.fields if f.is_active]
    for section in form.sections:
        section.fields = [f for f in section.fields if f.is_active]

    logger.info(
        f"Loaded form {form_id} with {len(form.sections)} sections "
        f"and {len(form.fields)} active fields"
    )
    return form


def get_ordered_active_fields(form_id: int, db: Session) -> list[FormField]:
    """
    Return only active fields for a form, sorted by order_index.
    Used by SubmissionService to determine current_field_index boundaries.
    """
    return (
        db.query(FormField)
        .filter(FormField.form_id == form_id, FormField.is_active == True)
        .order_by(FormField.order_index)
        .all()
    )
