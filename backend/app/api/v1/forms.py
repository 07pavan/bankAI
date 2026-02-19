"""
Forms API — read-only endpoints for form discovery.
All routes are JWT-protected.

Contracts:
  GET /api/v1/forms           → active forms for the user's bank
  GET /api/v1/forms/{form_id} → full form structure (sections + fields)
"""

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.database import get_db
from app.core.security import get_current_user_id
from app.schemas import FormListItem, FormOut
from app.services import form_service
from app.models import Bank

router = APIRouter()


def _resolve_bank_id(user_id: int, db: Session) -> int:
    """
    Resolve the bank_id for the authenticated user.

    Priority:
      1. UserPreference.bank_id (if the table exists and has a row)
      2. First active bank (fallback for single-bank deployments)

    Raises HTTPException 404 if no active bank is found.
    """
    # Try UserPreference first (table may not exist yet in early migrations)
    try:
        from app.models import UserPreference  # noqa: F401 — optional model
        pref = db.query(UserPreference).filter(UserPreference.user_id == user_id).first()
        if pref and pref.bank_id:
            return pref.bank_id
    except (ImportError, AttributeError):
        pass  # UserPreference model/table not yet migrated — fall through

    # Fallback: first active bank (works for single-bank deployments)
    bank = db.query(Bank).filter(Bank.is_active == True).order_by(Bank.id).first()
    if not bank:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No active bank found. Please contact support.",
        )
    return bank.id


@router.get("", response_model=list[FormListItem])
def list_forms(
    user_id: int = Depends(get_current_user_id),
    db: Session = Depends(get_db),
):
    """
    Return all active forms for the authenticated user's bank.

    The bank is resolved from the user's preference; falls back to the
    first active bank for single-bank deployments.
    """
    bank_id = _resolve_bank_id(user_id, db)
    try:
        return form_service.get_active_forms(bank_id, db)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))


@router.get("/{form_id}", response_model=FormOut)
def get_form(
    form_id: int,
    _user_id: int = Depends(get_current_user_id),
    db: Session = Depends(get_db),
):
    """Return full form definition with sections and fields."""
    form = form_service.get_form_structure(form_id, db)
    if not form:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Form {form_id} not found",
        )
    return form

