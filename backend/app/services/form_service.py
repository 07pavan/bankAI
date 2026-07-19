"""
FormService — Firestore edition.
Read-only queries for form structure (banks, forms, sections, fields).
All IDs are Firestore string document IDs.
"""

from typing import Optional

from app.database import get_db
from app.models import COLL_BANKS, COLL_FORMS, COLL_FORM_SECTIONS, COLL_FORM_FIELDS
from app.core.logging import get_logger

logger = get_logger()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _doc_to_dict(doc) -> dict:
    return {"id": doc.id, **doc.to_dict()}


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def get_active_banks() -> list[dict]:
    """Return all active banks, ordered by name (sorted in memory)."""
    db = get_db()
    docs = (
        db.collection(COLL_BANKS)
        .where("is_active", "==", True)
        .stream()
    )
    banks = [_doc_to_dict(d) for d in docs]
    banks.sort(key=lambda x: x.get("name", "").lower())
    return banks


def get_active_forms(bank_id: str) -> list[dict]:
    """
    Return all active forms for a given bank (sorted in memory).

    Raises:
        ValueError: If the bank does not exist or is inactive.
    """
    db = get_db()
    bank_doc = db.collection(COLL_BANKS).document(bank_id).get()
    if not bank_doc.exists or not bank_doc.to_dict().get("is_active", False):
        raise ValueError(f"Bank {bank_id} not found or inactive")

    docs = (
        db.collection(COLL_FORMS)
        .where("bank_id", "==", bank_id)
        .where("is_active", "==", True)
        .stream()
    )
    forms = [_doc_to_dict(d) for d in docs]
    forms.sort(key=lambda x: x.get("name", "").lower())
    logger.info(f"Fetched {len(forms)} active forms for bank_id={bank_id}")
    return forms


def get_form_structure(form_id: str) -> Optional[dict]:
    """
    Return a form dict with its sections and all active fields, ordered correctly (sorted in memory).

    Returns dict with keys:
      id, bank_id, name, code, description, sections (list), fields (flat list)
    Returns None if form not found or inactive.
    """
    db = get_db()
    form_doc = db.collection(COLL_FORMS).document(form_id).get()
    if not form_doc.exists:
        logger.warning(f"Form {form_id} not found")
        return None

    form = _doc_to_dict(form_doc)
    if not form.get("is_active", False):
        logger.warning(f"Form {form_id} is inactive")
        return None

    # Load sections (sorted in memory by order_index)
    section_docs = (
        db.collection(COLL_FORM_SECTIONS)
        .where("form_id", "==", form_id)
        .stream()
    )
    sections_by_id: dict[str, dict] = {}
    sections_list: list[dict] = []
    for s_doc in section_docs:
        s = _doc_to_dict(s_doc)
        s["fields"] = []
        sections_by_id[s["id"]] = s
        sections_list.append(s)

    # Sort sections in memory by order_index
    sections_list.sort(key=lambda s: s.get("order_index", 0))

    # Load active fields (sorted in memory by order_index)
    field_docs = (
        db.collection(COLL_FORM_FIELDS)
        .where("form_id", "==", form_id)
        .where("is_active", "==", True)
        .stream()
    )
    flat_fields: list[dict] = []
    for f_doc in field_docs:
        f = _doc_to_dict(f_doc)
        flat_fields.append(f)
        # Place into section
        sec_id = f.get("section_id")
        if sec_id and sec_id in sections_by_id:
            sections_by_id[sec_id]["fields"].append(f)

    # Sort fields inside each section and flat fields in memory by order_index
    flat_fields.sort(key=lambda f: f.get("order_index", 0))
    for s in sections_list:
        s["fields"].sort(key=lambda f: f.get("order_index", 0))

    form["sections"] = sections_list
    form["fields"] = flat_fields

    logger.info(
        f"Loaded form {form_id} with {len(sections_list)} sections "
        f"and {len(flat_fields)} active fields"
    )
    return form


def get_ordered_active_fields(form_id: str) -> list[dict]:
    """
    Return only active fields for a form, sorted by order_index (sorted in memory).
    Used by SubmissionService to determine current_field_index boundaries.
    """
    db = get_db()
    docs = (
        db.collection(COLL_FORM_FIELDS)
        .where("form_id", "==", form_id)
        .where("is_active", "==", True)
        .stream()
    )
    fields = [_doc_to_dict(d) for d in docs]
    fields.sort(key=lambda x: x.get("order_index", 0))
    return fields
