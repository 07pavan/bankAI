"""
Forms API — read-only endpoints for form discovery (Firestore edition)
All routes are JWT-protected.

Contracts:
  GET /api/v1/forms           → active forms for the user's bank
  GET /api/v1/forms/{form_id} → full form structure (sections + fields)
"""

from fastapi import APIRouter, Depends, HTTPException, status
from typing import Optional

from app.database import get_db
from app.core.security import get_current_user_id
from app.schemas import FormListItem, FormOut
from app.services import form_service

router = APIRouter()


def _resolve_bank_id(user_id: str) -> str:
    """
    Resolve the bank_id for the authenticated user in Firestore.

    Priority:
      1. User's designated bank_id from their user document.
      2. First active bank (fallback for single-bank deployments).

    Raises HTTPException 404 if no active bank is found.
    """
    db = get_db()
    
    # Try user document preference
    user_doc = db.collection("users").document(user_id).get()
    if user_doc.exists:
        user_data = user_doc.to_dict()
        if user_data.get("bank_id"):
            return user_data["bank_id"]

    # Fallback: first active bank (works for single-bank deployments)
    banks = (
        db.collection("banks")
        .where("is_active", "==", True)
        .order_by("name")
        .limit(1)
        .stream()
    )
    bank_doc = next(banks, None)
    if not bank_doc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No active bank found. Please contact support.",
        )
    return bank_doc.id


@router.get("", response_model=list[FormListItem])
def list_forms(
    user_id: str = Depends(get_current_user_id),
):
    """
    Return all active forms for the authenticated user's bank.

    The bank is resolved from the user's document; falls back to the
    first active bank for single-bank deployments.
    """
    bank_id = _resolve_bank_id(user_id)
    try:
        return form_service.get_active_forms(bank_id)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))


@router.get("/{form_id}", response_model=FormOut)
def get_form(
    form_id: str,
    _user_id: str = Depends(get_current_user_id),
):
    """Return full form definition with sections and fields."""
    form = form_service.get_form_structure(form_id)
    if not form:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Form {form_id} not found",
        )
    return form
