"""
Admin API Router — BankAI Admin Panel

All endpoints require the `require_admin_user` dependency.
Routes are registered under /api/v1/admin/ in main.py.

Firestore edition:
- No SQLAlchemy Session dependency — admin_service uses get_db() internally.
- All IDs are Firestore string document IDs (str), not ints.
"""

from fastapi import APIRouter, Depends, Query
from typing import Optional

from app.core.security import require_admin_user
from app.core.logging import get_logger
from app.services import admin_service
from app.schemas import (
    # Banks
    BankCreate, BankAdminOut,
    # Forms
    FormCreate, FormUpdate, FormAdminOut,
    # Sections
    SectionCreate, SectionAdminOut,
    # Fields
    FieldCreate, FieldUpdate, FieldAdminOut,
    # Submissions
    AdminSubmissionListItem, AdminSubmissionDetail,
)

logger = get_logger()
router = APIRouter()


# ────────────────────────────────────────────────────────────────────────────
# Banks
# ────────────────────────────────────────────────────────────────────────────

@router.get("/banks", response_model=list[BankAdminOut])
def list_banks(
    _admin=Depends(require_admin_user),
):
    """List all banks ordered by name."""
    return admin_service.list_banks()


@router.post("/banks", response_model=BankAdminOut, status_code=201)
def create_bank(
    payload: BankCreate,
    _admin=Depends(require_admin_user),
):
    """Create a new bank."""
    return admin_service.create_bank(payload.name, payload.code)


# ────────────────────────────────────────────────────────────────────────────
# Forms
# ────────────────────────────────────────────────────────────────────────────

@router.get("/forms", response_model=list[FormAdminOut])
def list_forms(
    bank_id: Optional[str] = Query(None, description="Filter by bank Firestore ID"),
    _admin=Depends(require_admin_user),
):
    """List all forms, optionally filtered by bank_id."""
    return admin_service.list_forms(bank_id=bank_id)


@router.post("/forms", response_model=FormAdminOut, status_code=201)
def create_form(
    payload: FormCreate,
    _admin=Depends(require_admin_user),
):
    """Create a new form under a bank."""
    return admin_service.create_form(
        bank_id=payload.bank_id,
        name=payload.name,
        code=payload.code,
        description=payload.description,
    )


@router.put("/forms/{form_id}", response_model=FormAdminOut)
def update_form(
    form_id: str,
    payload: FormUpdate,
    _admin=Depends(require_admin_user),
):
    """Update a form's metadata (name, description, is_active)."""
    return admin_service.update_form(
        form_id=form_id,
        name=payload.name,
        description=payload.description,
        is_active=payload.is_active,
    )


# ────────────────────────────────────────────────────────────────────────────
# Sections
# ────────────────────────────────────────────────────────────────────────────

@router.get("/forms/{form_id}/sections", response_model=list[SectionAdminOut])
def list_sections(
    form_id: str,
    _admin=Depends(require_admin_user),
):
    """List all sections of a form ordered by order_index."""
    return admin_service.list_sections(form_id)


@router.post("/forms/{form_id}/sections", response_model=SectionAdminOut, status_code=201)
def create_section(
    form_id: str,
    payload: SectionCreate,
    _admin=Depends(require_admin_user),
):
    """Create a new section within a form."""
    return admin_service.create_section(
        form_id=form_id,
        name=payload.name,
        order_index=payload.order_index,
    )


# ────────────────────────────────────────────────────────────────────────────
# Fields
# ────────────────────────────────────────────────────────────────────────────

@router.get("/forms/{form_id}/fields", response_model=list[FieldAdminOut])
def list_fields(
    form_id: str,
    _admin=Depends(require_admin_user),
):
    """List all fields of a form ordered by order_index."""
    return admin_service.list_fields(form_id)


@router.post("/forms/{form_id}/fields", response_model=FieldAdminOut, status_code=201)
def create_field(
    form_id: str,
    payload: FieldCreate,
    _admin=Depends(require_admin_user),
):
    """Create a new field within a form."""
    return admin_service.create_field(
        form_id=form_id,
        field_key=payload.field_key,
        label=payload.label,
        field_type=payload.field_type,
        required=payload.required,
        order_index=payload.order_index,
        section_id=payload.section_id,
        validation_rule=payload.validation_rule,
        options=payload.options,
    )


@router.put("/fields/{field_id}", response_model=FieldAdminOut)
def update_field(
    field_id: str,
    payload: FieldUpdate,
    _admin=Depends(require_admin_user),
):
    """Update a form field's properties."""
    return admin_service.update_field(
        field_id=field_id,
        label=payload.label,
        field_type=payload.field_type,
        required=payload.required,
        order_index=payload.order_index,
        is_active=payload.is_active,
        validation_rule=payload.validation_rule,
        options=payload.options,
    )


# ────────────────────────────────────────────────────────────────────────────
# Submissions (read-only for admin)
# ────────────────────────────────────────────────────────────────────────────

@router.get("/submissions", response_model=list[AdminSubmissionListItem])
def list_submissions(
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=200),
    _admin=Depends(require_admin_user),
):
    """
    List all form submissions (all users, all banks).
    Sorted newest first, paginated via skip/limit.
    """
    return admin_service.list_all_submissions(skip=skip, limit=limit)


@router.get("/submissions/{submission_id}", response_model=AdminSubmissionDetail)
def get_submission(
    submission_id: str,
    _admin=Depends(require_admin_user),
):
    """Get full detail of a single submission including all answered fields."""
    return admin_service.get_submission_detail(submission_id)
