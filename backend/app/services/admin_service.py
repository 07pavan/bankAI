"""
Admin Service Layer — BankAI Admin Panel (Firestore edition)

Provides all business logic for the admin panel:
  - Bank CRUD
  - Form CRUD
  - FormSection CRUD
  - FormField CRUD
  - Submission read (admin view, no ownership restriction)
  - Audit log write-through for all mutations

All IDs are Firestore string document IDs.
All functions raise HTTPException on errors.
"""

from datetime import datetime, timezone
from typing import Optional, Any

from fastapi import HTTPException, status

from app.database import get_db
from app.models import (
    COLL_BANKS, COLL_FORMS, COLL_FORM_SECTIONS,
    COLL_FORM_FIELDS, COLL_SUBMISSIONS, COLL_SUBMISSION_DATA,
    COLL_AUDIT_LOGS,
)
from app.core.logging import get_logger
from app.services import audit_service

logger = get_logger()


def _doc_to_dict(doc) -> dict:
    return {"id": doc.id, **doc.to_dict()}


# ---------------------------------------------------------------------------
# Banks
# ---------------------------------------------------------------------------

def list_banks() -> list[dict]:
    """Return all banks ordered by name."""
    db = get_db()
    docs = db.collection(COLL_BANKS).order_by("name").stream()
    return [_doc_to_dict(d) for d in docs]


def create_bank(name: str, code: str, actor_id: str = "system") -> dict:
    """
    Create a new bank.

    Raises:
        HTTPException 409: Bank with this code already exists.
    """
    db = get_db()
    code = code.upper().strip()

    existing = db.collection(COLL_BANKS).where("code", "==", code).limit(1).stream()
    if next(existing, None):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Bank with code '{code}' already exists",
        )

    now = datetime.now(timezone.utc)
    ref = db.collection(COLL_BANKS).document()
    data = {
        "name": name.strip(),
        "code": code,
        "is_active": True,
        "created_at": now,
        "updated_at": now,
    }
    ref.set(data)
    logger.info(f"Admin created bank: {code}")
    audit_service.log_action(
        actor_id=actor_id,
        action="create",
        entity_type="bank",
        entity_id=ref.id,
        entity_name=name.strip(),
        details={"code": code},
    )
    return {"id": ref.id, **data}


def update_bank(
    bank_id: str,
    name: Optional[str],
    is_active: Optional[bool],
    actor_id: str = "system",
) -> dict:
    """
    Update a bank's name and/or active status.

    Raises:
        HTTPException 404: Bank not found.
    """
    db = get_db()
    bank_doc = db.collection(COLL_BANKS).document(bank_id).get()
    if not bank_doc.exists:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Bank {bank_id} not found",
        )

    old = bank_doc.to_dict()
    updates: dict = {"updated_at": datetime.now(timezone.utc)}
    if name is not None:
        updates["name"] = name.strip()
    if is_active is not None:
        updates["is_active"] = is_active

    db.collection(COLL_BANKS).document(bank_id).update(updates)
    logger.info(f"Admin updated bank {bank_id}")
    action = "toggle" if is_active is not None and name is None else "update"
    audit_service.log_action(
        actor_id=actor_id,
        action=action,
        entity_type="bank",
        entity_id=bank_id,
        entity_name=updates.get("name") or old.get("name", bank_id),
        details={k: v for k, v in updates.items() if k != "updated_at"},
    )
    updated = db.collection(COLL_BANKS).document(bank_id).get()
    return _doc_to_dict(updated)



# ---------------------------------------------------------------------------
# Forms
# ---------------------------------------------------------------------------

def list_forms(bank_id: Optional[str] = None) -> list[dict]:
    """Return all forms, optionally filtered by bank."""
    db = get_db()

    # Pre-fetch all banks to prevent N+1 document queries
    banks_docs = db.collection(COLL_BANKS).stream()
    bank_cache = {d.id: d.to_dict().get("name", "") for d in banks_docs}

    q = db.collection(COLL_FORMS)
    if bank_id is not None:
        q = q.where("bank_id", "==", bank_id)
    docs = q.stream()

    forms = [_doc_to_dict(d) for d in docs]

    # Attach bank_name for each form
    for f in forms:
        bid = f.get("bank_id", "")
        f["bank_name"] = bank_cache.get(bid, "")

    return sorted(forms, key=lambda x: (x.get("bank_id", ""), x.get("name", "")))


def create_form(
    bank_id: str,
    name: str,
    code: str,
    description: Optional[str],
    actor_id: str = "system",
) -> dict:
    """
    Create a new form under a bank.

    Raises:
        HTTPException 404: Bank not found.
        HTTPException 409: Form code already exists for this bank.
    """
    db = get_db()
    bank_doc = db.collection(COLL_BANKS).document(bank_id).get()
    if not bank_doc.exists:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Bank {bank_id} not found",
        )

    code = code.lower().strip().replace(" ", "_")
    existing = (
        db.collection(COLL_FORMS)
        .where("bank_id", "==", bank_id)
        .where("code", "==", code)
        .limit(1)
        .stream()
    )
    if next(existing, None):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Form code '{code}' already exists for this bank",
        )

    now = datetime.now(timezone.utc)
    ref = db.collection(COLL_FORMS).document()
    data = {
        "bank_id": bank_id,
        "name": name.strip(),
        "code": code,
        "description": description,
        "is_active": True,
        "created_at": now,
        "updated_at": now,
    }
    ref.set(data)
    logger.info(f"Admin created form: '{code}' for bank {bank_id}")
    audit_service.log_action(
        actor_id=actor_id,
        action="create",
        entity_type="form",
        entity_id=ref.id,
        entity_name=name.strip(),
        details={"bank_id": bank_id, "code": code},
    )
    return {"id": ref.id, **data}


def update_form(
    form_id: str,
    name: Optional[str],
    description: Optional[str],
    is_active: Optional[bool],
    actor_id: str = "system",
) -> dict:
    """
    Update a form's metadata.

    Raises:
        HTTPException 404: Form not found.
    """
    db = get_db()
    form_doc = db.collection(COLL_FORMS).document(form_id).get()
    if not form_doc.exists:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Form {form_id} not found",
        )

    old = form_doc.to_dict()
    updates: dict = {"updated_at": datetime.now(timezone.utc)}
    if name is not None:
        updates["name"] = name.strip()
    if description is not None:
        updates["description"] = description
    if is_active is not None:
        updates["is_active"] = is_active

    db.collection(COLL_FORMS).document(form_id).update(updates)
    logger.info(f"Admin updated form {form_id}")
    action = "toggle" if is_active is not None and name is None else "update"
    audit_service.log_action(
        actor_id=actor_id,
        action=action,
        entity_type="form",
        entity_id=form_id,
        entity_name=updates.get("name") or old.get("name", form_id),
        details={k: v for k, v in updates.items() if k != "updated_at"},
    )
    updated = db.collection(COLL_FORMS).document(form_id).get()
    return _doc_to_dict(updated)


# ---------------------------------------------------------------------------
# Sections
# ---------------------------------------------------------------------------

def list_sections(form_id: str) -> list[dict]:
    """Return all sections for a form, ordered by order_index (sorted in memory to avoid index requirement)."""
    _assert_form_exists(form_id)
    db = get_db()
    docs = (
        db.collection(COLL_FORM_SECTIONS)
        .where("form_id", "==", form_id)
        .stream()
    )
    sections = [_doc_to_dict(d) for d in docs]
    sections.sort(key=lambda s: s.get("order_index", 0))
    return sections


def create_section(form_id: str, name: str, order_index: int, actor_id: str = "system") -> dict:
    """
    Create a new section within a form.

    Raises:
        HTTPException 404: Form not found.
    """
    _assert_form_exists(form_id)
    db = get_db()
    ref = db.collection(COLL_FORM_SECTIONS).document()
    data = {
        "form_id": form_id,
        "name": name.strip(),
        "order_index": order_index,
    }
    ref.set(data)
    logger.info(f"Admin created section '{name}' in form {form_id}")
    audit_service.log_action(
        actor_id=actor_id,
        action="create",
        entity_type="section",
        entity_id=ref.id,
        entity_name=name.strip(),
        details={"form_id": form_id, "order_index": order_index},
    )
    return {"id": ref.id, **data}


# ---------------------------------------------------------------------------
# Fields
# ---------------------------------------------------------------------------

def list_fields(form_id: str) -> list[dict]:
    """Return all fields for a form, ordered by order_index (sorted in memory to avoid index requirement)."""
    _assert_form_exists(form_id)
    db = get_db()
    docs = (
        db.collection(COLL_FORM_FIELDS)
        .where("form_id", "==", form_id)
        .stream()
    )
    fields = [_doc_to_dict(d) for d in docs]
    fields.sort(key=lambda f: f.get("order_index", 0))
    return fields


def create_field(
    form_id: str,
    field_key: str,
    label: str,
    field_type: str,
    required: bool,
    order_index: int,
    section_id: Optional[str],
    validation_rule: Optional[Any],
    options: Optional[Any],
    actor_id: str = "system",
) -> dict:
    """
    Create a new field within a form.

    Raises:
        HTTPException 404: Form not found.
        HTTPException 409: field_key already exists for this form.
    """
    _assert_form_exists(form_id)
    db = get_db()

    # Validate section_id exists and belongs to this form
    if section_id:
        section_doc = db.collection(COLL_FORM_SECTIONS).document(section_id).get()
        if not section_doc.exists:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Section {section_id} not found",
            )
        if section_doc.to_dict().get("form_id") != form_id:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Section {section_id} does not belong to form {form_id}",
            )

    field_key = field_key.strip().lower().replace(" ", "_")

    existing = (
        db.collection(COLL_FORM_FIELDS)
        .where("form_id", "==", form_id)
        .where("field_key", "==", field_key)
        .limit(1)
        .stream()
    )
    if next(existing, None):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Field key '{field_key}' already exists in form {form_id}",
        )

    ref = db.collection(COLL_FORM_FIELDS).document()
    data = {
        "form_id": form_id,
        "section_id": section_id,
        "field_key": field_key,
        "label": label.strip(),
        "field_type": field_type,
        "required": required,
        "order_index": order_index,
        "validation_rule": validation_rule,
        "options": options,
        "is_active": True,
    }
    ref.set(data)
    logger.info(f"Admin created field '{field_key}' in form {form_id}")
    audit_service.log_action(
        actor_id=actor_id,
        action="create",
        entity_type="field",
        entity_id=ref.id,
        entity_name=label.strip(),
        details={"form_id": form_id, "field_key": field_key, "field_type": field_type},
    )
    return {"id": ref.id, **data}


def update_field(
    field_id: str,
    label: Optional[str],
    field_type: Optional[str],
    required: Optional[bool],
    order_index: Optional[int],
    is_active: Optional[bool],
    validation_rule: Optional[Any],
    options: Optional[Any],
    actor_id: str = "system",
) -> dict:
    """
    Update a form field.

    Raises:
        HTTPException 404: Field not found.
    """
    db = get_db()
    field_doc = db.collection(COLL_FORM_FIELDS).document(field_id).get()
    if not field_doc.exists:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Field {field_id} not found",
        )

    old = field_doc.to_dict()
    updates: dict = {}
    if label is not None:
        updates["label"] = label.strip()
    if field_type is not None:
        updates["field_type"] = field_type
    if required is not None:
        updates["required"] = required
    if order_index is not None:
        updates["order_index"] = order_index
    if is_active is not None:
        updates["is_active"] = is_active
    if validation_rule is not None:
        updates["validation_rule"] = validation_rule
    if options is not None:
        updates["options"] = options

    if updates:
        db.collection(COLL_FORM_FIELDS).document(field_id).update(updates)
    logger.info(f"Admin updated field {field_id}")
    action = "toggle" if is_active is not None and label is None else "update"
    audit_service.log_action(
        actor_id=actor_id,
        action=action,
        entity_type="field",
        entity_id=field_id,
        entity_name=old.get("label", field_id),
        details={k: v for k, v in updates.items()},
    )
    updated = db.collection(COLL_FORM_FIELDS).document(field_id).get()
    return _doc_to_dict(updated)


# ---------------------------------------------------------------------------
# Submissions (admin read-only)
# ---------------------------------------------------------------------------

def list_all_submissions(skip: int = 0, limit: int = 50) -> list[dict]:
    """
    Return all submissions with form and bank metadata.
    Sorted newest first. Paginated via skip/limit at the database level.
    """
    db = get_db()
    docs = (
        db.collection(COLL_SUBMISSIONS)
        .order_by("created_at", direction="DESCENDING")
        .offset(skip)
        .limit(limit)
        .stream()
    )

    rows = list(docs)

    # Pre-cache forms and banks
    form_cache: dict[str, dict] = {}
    bank_cache: dict[str, dict] = {}

    result = []
    for doc in rows:
        sub = doc.to_dict()
        form_id = sub.get("form_id", "")
        if form_id not in form_cache:
            form_doc = db.collection(COLL_FORMS).document(form_id).get()
            form_cache[form_id] = form_doc.to_dict() if form_doc.exists else {}

        form_data = form_cache[form_id]
        bank_id = form_data.get("bank_id", "")
        if bank_id not in bank_cache:
            bank_doc = db.collection(COLL_BANKS).document(bank_id).get()
            bank_cache[bank_id] = bank_doc.to_dict() if bank_doc.exists else {}

        bank_data = bank_cache[bank_id]
        created_at = sub.get("created_at")
        updated_at = sub.get("updated_at")
        result.append({
            "id": doc.id,
            "user_id": sub.get("user_id"),
            "form_id": form_id,
            "form_name": form_data.get("name"),
            "bank_name": bank_data.get("name"),
            "status": sub.get("status"),
            "conversation_state": sub.get("conversation_state"),
            "created_at": created_at.isoformat() if hasattr(created_at, "isoformat") else str(created_at) if created_at else None,
            "updated_at": updated_at.isoformat() if hasattr(updated_at, "isoformat") else str(updated_at) if updated_at else None,
        })
    return result


def get_submission_detail(submission_id: str) -> dict:
    """
    Return a single submission with all its answered field data.

    Raises:
        HTTPException 404: Submission not found.
    """
    db = get_db()
    sub_doc = db.collection(COLL_SUBMISSIONS).document(submission_id).get()
    if not sub_doc.exists:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Submission {submission_id} not found",
        )
    sub = sub_doc.to_dict()

    form_id = sub.get("form_id", "")
    form_doc = db.collection(COLL_FORMS).document(form_id).get()
    form_data = form_doc.to_dict() if form_doc.exists else {}

    bank_id = form_data.get("bank_id", "")
    bank_doc = db.collection(COLL_BANKS).document(bank_id).get()
    bank_data = bank_doc.to_dict() if bank_doc.exists else {}

    # Load submission data
    data_docs = (
        db.collection(COLL_SUBMISSION_DATA)
        .where("submission_id", "==", submission_id)
        .stream()
    )

    created_at = sub.get("created_at")
    updated_at = sub.get("updated_at")
    return {
        "id": sub_doc.id,
        "user_id": sub.get("user_id"),
        "form_id": form_id,
        "form_name": form_data.get("name"),
        "bank_name": bank_data.get("name"),
        "status": sub.get("status"),
        "conversation_state": sub.get("conversation_state"),
        "current_field_index": sub.get("current_field_index", 0),
        "created_at": created_at.isoformat() if hasattr(created_at, "isoformat") else str(created_at) if created_at else None,
        "updated_at": updated_at.isoformat() if hasattr(updated_at, "isoformat") else str(updated_at) if updated_at else None,
        "data": [
            {
                "field_key": d.to_dict().get("field_key"),
                "value": d.to_dict().get("value"),
                "updated_at": (
                    d.to_dict()["updated_at"].isoformat()
                    if d.to_dict().get("updated_at") and hasattr(d.to_dict()["updated_at"], "isoformat")
                    else None
                ),
            }
            for d in data_docs
        ],
    }


# ---------------------------------------------------------------------------
# Private helpers
# ---------------------------------------------------------------------------

def _assert_form_exists(form_id: str) -> dict:
    db = get_db()
    form_doc = db.collection(COLL_FORMS).document(form_id).get()
    if not form_doc.exists:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Form {form_id} not found",
        )
    return _doc_to_dict(form_doc)
