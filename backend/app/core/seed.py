"""
Seed data for BankAI — Firestore edition.

Idempotent: safe to call on every startup.
Seeds 1 bank (SBI) and 3 forms:
  1. Account Opening
  2. Aadhaar Seeding
  3. Cheque Book Request

Design principles:
  - All form structure is Firestore-driven (no hardcoding in service logic)
  - is_active flag on forms and fields enables admin soft-delete/deactivate
  - order_index on sections and fields enables drag-and-drop reordering
  - validation_rule dict enables new validation types without schema changes
  - options list enables new select/radio choices without schema changes
"""

from datetime import datetime, timezone
from app.database import get_db
from app.models import (
    COLL_BANKS, COLL_FORMS, COLL_FORM_SECTIONS,
    COLL_FORM_FIELDS, COLL_USERS,
)
from app.core.logging import get_logger

logger = get_logger()


# ---------------------------------------------------------------------------
# Bank definitions
# ---------------------------------------------------------------------------

BANKS = [
    {"name": "State Bank of India", "code": "SBI"},
]


# ---------------------------------------------------------------------------
# Form definitions
# ---------------------------------------------------------------------------

FORMS: dict[str, list[dict]] = {
    "SBI": [

        # ── 1. Account Opening ────────────────────────────────────────────────
        {
            "name": "Account Opening",
            "code": "account_opening",
            "description": "Open a new savings or current account with SBI",
            "sections": [
                {
                    "name": "Personal Information",
                    "order_index": 0,
                    "fields": [
                        {"field_key": "full_name", "label": "Full Name (as per Aadhaar)", "field_type": "text", "required": True, "validation_rule": {"min_length": 2, "max_length": 100}, "order_index": 0},
                        {"field_key": "dob", "label": "Date of Birth", "field_type": "date", "required": True, "validation_rule": {"pattern": r"^\d{4}-\d{2}-\d{2}$"}, "order_index": 1},
                        {"field_key": "gender", "label": "Gender", "field_type": "radio", "required": True, "options": [{"value": "male", "label": "Male"}, {"value": "female", "label": "Female"}, {"value": "other", "label": "Other"}], "order_index": 2},
                        {"field_key": "mobile", "label": "Mobile Number", "field_type": "text", "required": True, "validation_rule": {"pattern": r"^\d{10}$"}, "order_index": 3},
                        {"field_key": "email", "label": "Email Address", "field_type": "text", "required": False, "validation_rule": {"pattern": r"^[^@]+@[^@]+\.[^@]+$"}, "order_index": 4},
                    ],
                },
                {
                    "name": "Address Details",
                    "order_index": 1,
                    "fields": [
                        {"field_key": "address_line1", "label": "Address Line 1", "field_type": "text", "required": True, "validation_rule": {"min_length": 5, "max_length": 200}, "order_index": 5},
                        {"field_key": "city", "label": "City", "field_type": "text", "required": True, "validation_rule": {"min_length": 2}, "order_index": 6},
                        {"field_key": "state", "label": "State", "field_type": "text", "required": True, "validation_rule": {"min_length": 2}, "order_index": 7},
                        {"field_key": "pincode", "label": "PIN Code", "field_type": "text", "required": True, "validation_rule": {"pattern": r"^\d{6}$"}, "order_index": 8},
                    ],
                },
                {
                    "name": "Account Preferences",
                    "order_index": 2,
                    "fields": [
                        {"field_key": "account_type", "label": "Account Type", "field_type": "select", "required": True, "options": [{"value": "savings", "label": "Savings Account"}, {"value": "current", "label": "Current Account"}], "order_index": 9},
                        {"field_key": "nominee_name", "label": "Nominee Full Name", "field_type": "text", "required": True, "validation_rule": {"min_length": 2, "max_length": 100}, "order_index": 10},
                        {"field_key": "nominee_relation", "label": "Nominee Relationship", "field_type": "select", "required": True, "options": [{"value": "spouse", "label": "Spouse"}, {"value": "parent", "label": "Parent"}, {"value": "child", "label": "Child"}, {"value": "sibling", "label": "Sibling"}, {"value": "other", "label": "Other"}], "order_index": 11},
                        {"field_key": "initial_deposit", "label": "Initial Deposit Amount (₹)", "field_type": "number", "required": True, "validation_rule": {"min": 1000}, "order_index": 12},
                    ],
                },
            ],
        },

        # ── 2. Aadhaar Seeding ────────────────────────────────────────────────
        {
            "name": "Aadhaar Seeding",
            "code": "aadhaar_seeding",
            "description": "Link your Aadhaar number to your existing SBI account",
            "sections": [
                {
                    "name": "Account Verification",
                    "order_index": 0,
                    "fields": [
                        {"field_key": "account_number", "label": "Account Number", "field_type": "text", "required": True, "validation_rule": {"pattern": r"^\d{9,18}$"}, "order_index": 0},
                        {"field_key": "account_holder_name", "label": "Account Holder Name (as per bank records)", "field_type": "text", "required": True, "validation_rule": {"min_length": 2, "max_length": 100}, "order_index": 1},
                        {"field_key": "mobile", "label": "Registered Mobile Number", "field_type": "text", "required": True, "validation_rule": {"pattern": r"^\d{10}$"}, "order_index": 2},
                    ],
                },
                {
                    "name": "Aadhaar Details",
                    "order_index": 1,
                    "fields": [
                        {"field_key": "aadhaar_number", "label": "Aadhaar Number (12 digits)", "field_type": "text", "required": True, "validation_rule": {"pattern": r"^\d{12}$"}, "order_index": 3},
                        {"field_key": "consent", "label": "I consent to link my Aadhaar to this account", "field_type": "radio", "required": True, "options": [{"value": "yes", "label": "Yes, I consent"}, {"value": "no", "label": "No, I do not consent"}], "order_index": 4},
                    ],
                },
            ],
        },

        # ── 3. Cheque Book Request ────────────────────────────────────────────
        {
            "name": "Cheque Book Request",
            "code": "cheque_book_request",
            "description": "Request a new cheque book for your SBI account",
            "sections": [
                {
                    "name": "Account Information",
                    "order_index": 0,
                    "fields": [
                        {"field_key": "account_number", "label": "Account Number", "field_type": "text", "required": True, "validation_rule": {"pattern": r"^\d{9,18}$"}, "order_index": 0},
                        {"field_key": "account_holder_name", "label": "Account Holder Name", "field_type": "text", "required": True, "validation_rule": {"min_length": 2, "max_length": 100}, "order_index": 1},
                    ],
                },
                {
                    "name": "Delivery Preferences",
                    "order_index": 1,
                    "fields": [
                        {"field_key": "cheque_leaves", "label": "Number of Cheque Leaves", "field_type": "select", "required": True, "options": [{"value": "10", "label": "10 leaves"}, {"value": "25", "label": "25 leaves"}, {"value": "50", "label": "50 leaves"}], "order_index": 2},
                        {"field_key": "delivery_address", "label": "Delivery Address", "field_type": "select", "required": True, "options": [{"value": "registered", "label": "Registered address on file"}, {"value": "branch", "label": "Collect from branch"}], "order_index": 3},
                    ],
                },
            ],
        },

    ],
}


# ---------------------------------------------------------------------------
# Seed function (idempotent)
# ---------------------------------------------------------------------------

def seed_defaults() -> None:
    """
    Idempotently seed banks, forms, and admin user into Firestore.
    Safe to call on every application startup.
    """
    try:
        _seed_banks()
        _seed_forms()
        _seed_admin_user()
        logger.info("Seed data verified/applied successfully")
    except Exception as exc:
        logger.error(f"Seed failed: {exc}", exc_info=True)
        raise


def _seed_banks() -> None:
    db = get_db()
    for bank_data in BANKS:
        existing = db.collection(COLL_BANKS).where("code", "==", bank_data["code"]).limit(1).stream()
        if next(existing, None):
            continue  # Already seeded
        now = datetime.now(timezone.utc)
        ref = db.collection(COLL_BANKS).document()
        ref.set({
            "name": bank_data["name"],
            "code": bank_data["code"],
            "is_active": True,
            "created_at": now,
            "updated_at": now,
        })
        logger.info(f"Seeded bank: {bank_data['code']}")


def _seed_forms() -> None:
    db = get_db()
    now = datetime.now(timezone.utc)

    for bank_code, forms in FORMS.items():
        # Find the bank
        bank_docs = db.collection(COLL_BANKS).where("code", "==", bank_code).limit(1).stream()
        bank_doc = next(bank_docs, None)
        if not bank_doc:
            logger.warning(f"Bank '{bank_code}' not found — skipping form seed")
            continue
        bank_id = bank_doc.id

        for form_data in forms:
            # Check if form already exists
            existing = (
                db.collection(COLL_FORMS)
                .where("bank_id", "==", bank_id)
                .where("code", "==", form_data["code"])
                .limit(1)
                .stream()
            )
            if next(existing, None):
                continue  # Already seeded

            form_ref = db.collection(COLL_FORMS).document()
            form_ref.set({
                "bank_id": bank_id,
                "name": form_data["name"],
                "code": form_data["code"],
                "description": form_data.get("description"),
                "is_active": True,
                "created_at": now,
                "updated_at": now,
            })

            for section_data in form_data.get("sections", []):
                section_ref = db.collection(COLL_FORM_SECTIONS).document()
                section_ref.set({
                    "form_id": form_ref.id,
                    "name": section_data["name"],
                    "order_index": section_data["order_index"],
                })

                for field_data in section_data.get("fields", []):
                    field_ref = db.collection(COLL_FORM_FIELDS).document()
                    field_ref.set({
                        "form_id": form_ref.id,
                        "section_id": section_ref.id,
                        "field_key": field_data["field_key"],
                        "label": field_data["label"],
                        "field_type": field_data["field_type"],
                        "required": field_data.get("required", True),
                        "validation_rule": field_data.get("validation_rule"),
                        "options": field_data.get("options"),
                        "order_index": field_data["order_index"],
                        "is_active": True,
                    })

            logger.info(f"Seeded form: '{form_data['code']}' for bank '{bank_code}'")


def _seed_admin_user() -> None:
    """
    Create one admin user if none exists.

    In development the 'admin' User document is seeded with a known Aadhaar hash
    so that calling POST /api/v1/kyc/submit with Aadhaar='999999999999' and
    any PAN returns a JWT that grants admin access.
    """
    db = get_db()

    # Check if any admin user exists
    existing_admins = db.collection(COLL_USERS).where("role", "==", "admin").limit(1).stream()
    if next(existing_admins, None):
        logger.info("Admin user already exists")
        return

    from app.core.encryption import encryption_service
    dev_aadhaar = "999999999999"
    aadhaar_hash = encryption_service.hash_aadhaar(dev_aadhaar)

    # Check if the dev user already exists with a different role
    existing = db.collection(COLL_USERS).where("aadhaar_hash", "==", aadhaar_hash).limit(1).stream()
    existing_doc = next(existing, None)
    if existing_doc:
        db.collection(COLL_USERS).document(existing_doc.id).update({"role": "admin"})
        logger.info(f"Promoted existing user (id={existing_doc.id}) to admin")
        return

    ref = db.collection(COLL_USERS).document()
    ref.set({
        "aadhaar_hash": aadhaar_hash,
        "role": "admin",
        "created_at": datetime.now(timezone.utc),
    })
    logger.info(
        f"[ADMIN SEED] Created dev admin user (id={ref.id}). "
        f"Login with Aadhaar=999999999999 and any PAN to get an admin JWT."
    )
