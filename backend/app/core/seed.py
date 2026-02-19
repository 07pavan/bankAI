"""
Seed data for BankAI Phase 2 — Dynamic Form Engine.

Idempotent: safe to call on every startup.
Seeds 1 bank (SBI) and 3 forms:
  1. Account Opening
  2. Aadhaar Seeding
  3. Cheque Book Request

Design principles:
  - All form structure is DB-driven (no hardcoding in service logic)
  - is_active flag on forms and fields enables admin soft-delete/deactivate
  - order_index on sections and fields enables admin drag-and-drop reordering
  - validation_rule JSON enables adding new validation types without schema changes
  - options JSON enables adding new select/radio choices without schema changes
"""

from sqlalchemy.orm import Session
from app.models import Bank, Form, FormSection, FormField
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
                        {
                            "field_key": "full_name",
                            "label": "Full Name (as per Aadhaar)",
                            "field_type": "text",
                            "required": True,
                            "validation_rule": {"min_length": 2, "max_length": 100},
                            "order_index": 0,
                        },
                        {
                            "field_key": "dob",
                            "label": "Date of Birth",
                            "field_type": "date",
                            "required": True,
                            "validation_rule": {"pattern": r"^\d{4}-\d{2}-\d{2}$"},
                            "order_index": 1,
                        },
                        {
                            "field_key": "gender",
                            "label": "Gender",
                            "field_type": "radio",
                            "required": True,
                            "options": [
                                {"value": "male", "label": "Male"},
                                {"value": "female", "label": "Female"},
                                {"value": "other", "label": "Other"},
                            ],
                            "order_index": 2,
                        },
                        {
                            "field_key": "mobile",
                            "label": "Mobile Number",
                            "field_type": "text",
                            "required": True,
                            "validation_rule": {"pattern": r"^\d{10}$"},
                            "order_index": 3,
                        },
                        {
                            "field_key": "email",
                            "label": "Email Address",
                            "field_type": "text",
                            "required": False,
                            "validation_rule": {"pattern": r"^[^@]+@[^@]+\.[^@]+$"},
                            "order_index": 4,
                        },
                    ],
                },
                {
                    "name": "Address Details",
                    "order_index": 1,
                    "fields": [
                        {
                            "field_key": "address_line1",
                            "label": "Address Line 1",
                            "field_type": "text",
                            "required": True,
                            "validation_rule": {"min_length": 5, "max_length": 200},
                            "order_index": 5,
                        },
                        {
                            "field_key": "city",
                            "label": "City",
                            "field_type": "text",
                            "required": True,
                            "validation_rule": {"min_length": 2},
                            "order_index": 6,
                        },
                        {
                            "field_key": "state",
                            "label": "State",
                            "field_type": "text",
                            "required": True,
                            "validation_rule": {"min_length": 2},
                            "order_index": 7,
                        },
                        {
                            "field_key": "pincode",
                            "label": "PIN Code",
                            "field_type": "text",
                            "required": True,
                            "validation_rule": {"pattern": r"^\d{6}$"},
                            "order_index": 8,
                        },
                    ],
                },
                {
                    "name": "Account Preferences",
                    "order_index": 2,
                    "fields": [
                        {
                            "field_key": "account_type",
                            "label": "Account Type",
                            "field_type": "select",
                            "required": True,
                            "options": [
                                {"value": "savings", "label": "Savings Account"},
                                {"value": "current", "label": "Current Account"},
                            ],
                            "order_index": 9,
                        },
                        {
                            "field_key": "nominee_name",
                            "label": "Nominee Full Name",
                            "field_type": "text",
                            "required": True,
                            "validation_rule": {"min_length": 2, "max_length": 100},
                            "order_index": 10,
                        },
                        {
                            "field_key": "nominee_relation",
                            "label": "Nominee Relationship",
                            "field_type": "select",
                            "required": True,
                            "options": [
                                {"value": "spouse", "label": "Spouse"},
                                {"value": "parent", "label": "Parent"},
                                {"value": "child", "label": "Child"},
                                {"value": "sibling", "label": "Sibling"},
                                {"value": "other", "label": "Other"},
                            ],
                            "order_index": 11,
                        },
                        {
                            "field_key": "initial_deposit",
                            "label": "Initial Deposit Amount (₹)",
                            "field_type": "number",
                            "required": True,
                            "validation_rule": {"min": 1000},
                            "order_index": 12,
                        },
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
                        {
                            "field_key": "account_number",
                            "label": "Account Number",
                            "field_type": "text",
                            "required": True,
                            "validation_rule": {"pattern": r"^\d{9,18}$"},
                            "order_index": 0,
                        },
                        {
                            "field_key": "account_holder_name",
                            "label": "Account Holder Name (as per bank records)",
                            "field_type": "text",
                            "required": True,
                            "validation_rule": {"min_length": 2, "max_length": 100},
                            "order_index": 1,
                        },
                        {
                            "field_key": "mobile",
                            "label": "Registered Mobile Number",
                            "field_type": "text",
                            "required": True,
                            "validation_rule": {"pattern": r"^\d{10}$"},
                            "order_index": 2,
                        },
                    ],
                },
                {
                    "name": "Aadhaar Details",
                    "order_index": 1,
                    "fields": [
                        {
                            "field_key": "aadhaar_number",
                            "label": "Aadhaar Number (12 digits)",
                            "field_type": "text",
                            "required": True,
                            "validation_rule": {"pattern": r"^\d{12}$"},
                            "order_index": 3,
                        },
                        {
                            "field_key": "consent",
                            "label": "I consent to link my Aadhaar to this account",
                            "field_type": "radio",
                            "required": True,
                            "options": [
                                {"value": "yes", "label": "Yes, I consent"},
                                {"value": "no", "label": "No, I do not consent"},
                            ],
                            "order_index": 4,
                        },
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
                        {
                            "field_key": "account_number",
                            "label": "Account Number",
                            "field_type": "text",
                            "required": True,
                            "validation_rule": {"pattern": r"^\d{9,18}$"},
                            "order_index": 0,
                        },
                        {
                            "field_key": "account_holder_name",
                            "label": "Account Holder Name",
                            "field_type": "text",
                            "required": True,
                            "validation_rule": {"min_length": 2, "max_length": 100},
                            "order_index": 1,
                        },
                    ],
                },
                {
                    "name": "Delivery Preferences",
                    "order_index": 1,
                    "fields": [
                        {
                            "field_key": "cheque_leaves",
                            "label": "Number of Cheque Leaves",
                            "field_type": "select",
                            "required": True,
                            "options": [
                                {"value": "10", "label": "10 leaves"},
                                {"value": "25", "label": "25 leaves"},
                                {"value": "50", "label": "50 leaves"},
                            ],
                            "order_index": 2,
                        },
                        {
                            "field_key": "delivery_address",
                            "label": "Delivery Address",
                            "field_type": "select",
                            "required": True,
                            "options": [
                                {"value": "registered", "label": "Registered address on file"},
                                {"value": "branch", "label": "Collect from branch"},
                            ],
                            "order_index": 3,
                        },
                    ],
                },
            ],
        },

    ],
}


# ---------------------------------------------------------------------------
# Seed function (idempotent)
# ---------------------------------------------------------------------------

def seed_defaults(db: Session) -> None:
    """
    Idempotently seed banks and forms.
    Skips any record that already exists (checked by unique code).
    Safe to call on every application startup.
    """
    try:
        _seed_banks(db)
        _seed_forms(db)
        logger.info("Seed data verified/applied successfully")
    except Exception as exc:
        logger.error(f"Seed failed: {exc}", exc_info=True)
        db.rollback()
        raise


def _seed_banks(db: Session) -> None:
    for bank_data in BANKS:
        existing = db.query(Bank).filter(Bank.code == bank_data["code"]).first()
        if not existing:
            bank = Bank(**bank_data)
            db.add(bank)
            db.flush()
            logger.info(f"Seeded bank: {bank_data['code']}")
    db.commit()


def _seed_forms(db: Session) -> None:
    for bank_code, forms in FORMS.items():
        bank = db.query(Bank).filter(Bank.code == bank_code).first()
        if not bank:
            logger.warning(f"Bank '{bank_code}' not found — skipping form seed")
            continue

        for form_data in forms:
            existing_form = db.query(Form).filter(
                Form.bank_id == bank.id,
                Form.code == form_data["code"],
            ).first()

            if existing_form:
                continue  # Already seeded — idempotent

            form = Form(
                bank_id=bank.id,
                name=form_data["name"],
                code=form_data["code"],
                description=form_data.get("description"),
                is_active=True,
            )
            db.add(form)
            db.flush()

            for section_data in form_data.get("sections", []):
                section = FormSection(
                    form_id=form.id,
                    name=section_data["name"],
                    order_index=section_data["order_index"],
                )
                db.add(section)
                db.flush()

                for field_data in section_data.get("fields", []):
                    field = FormField(
                        form_id=form.id,
                        section_id=section.id,
                        field_key=field_data["field_key"],
                        label=field_data["label"],
                        field_type=field_data["field_type"],
                        required=field_data.get("required", True),
                        validation_rule=field_data.get("validation_rule"),
                        options=field_data.get("options"),
                        order_index=field_data["order_index"],
                        is_active=True,
                    )
                    db.add(field)

            db.flush()
            logger.info(f"Seeded form: '{form_data['code']}' for bank '{bank_code}'")

    db.commit()
