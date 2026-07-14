"""
Lightweight Firestore-based RAG (Retrieval-Augmented Generation) for BankAI.

Provides structured form metadata and banking FAQ context to the LLM
system prompt — no vector database, no embeddings, no extra dependencies.

Design rationale:
  BankAI has ~3 forms × ~25 total fields — a small knowledge base that
  fits entirely in structured text. The LLM needs to understand field
  labels, validation rules, options, and common banking scenarios.
  Firestore queries + text formatting accomplish this at near-zero cost.

Functions:
  get_all_forms_summary(db)           → overview of all active forms
  get_form_context(form_id, db)       → full form structure with all fields
  get_field_context(form_id, key, db) → detailed metadata for one field
  get_banking_faq_context(query)      → relevant FAQ entries (keyword match)
"""

from typing import Optional, Any
from google.cloud.firestore import Client

from app.database import get_db
from app.models import COLL_BANKS, COLL_FORMS, COLL_FORM_SECTIONS, COLL_FORM_FIELDS
from app.core.logging import get_logger

logger = get_logger()


# ═══════════════════════════════════════════════════════════════════════════
# 1. Form summary — all active forms at a glance
# ═══════════════════════════════════════════════════════════════════════════

def get_all_forms_summary(db: Optional[Client] = None) -> str:
    """
    Build a concise summary of all active forms across all banks.

    Returns plain text suitable for injection into an LLM system prompt.
    Includes: form name, description, bank name, field count.
    """
    if db is None:
        db = get_db()

    banks = db.collection(COLL_BANKS).where("is_active", "==", True).order_by("name").stream()
    bank_list = list(banks)

    if not bank_list:
        return "No active banks or forms are currently available."

    lines: list[str] = ["## Available Banking Forms\n"]

    for bank_doc in bank_list:
        bank = bank_doc.to_dict()
        bank_id = bank_doc.id

        forms = (
            db.collection(COLL_FORMS)
            .where("bank_id", "==", bank_id)
            .where("is_active", "==", True)
            .stream()
        )
        form_list = list(forms)
        if not form_list:
            continue

        lines.append(f"### {bank.get('name')} ({bank.get('code')})")

        for form_doc in form_list:
            form = form_doc.to_dict()
            form_id = form_doc.id

            fields = (
                db.collection(COLL_FORM_FIELDS)
                .where("form_id", "==", form_id)
                .where("is_active", "==", True)
                .stream()
            )
            field_list = [f.to_dict() for f in fields]
            field_count = len(field_list)
            required_count = sum(1 for f in field_list if f.get("required") is True)

            desc = form.get("description") or "No description available"
            lines.append(
                f"- **{form.get('name')}** (Form ID: {form_id})\n"
                f"  Description: {desc}\n"
                f"  Fields: {field_count} total, {required_count} required"
            )

        lines.append("")  # blank line between banks

    return "\n".join(lines)


# ═══════════════════════════════════════════════════════════════════════════
# 2. Full form context — all sections and fields
# ═══════════════════════════════════════════════════════════════════════════

def get_form_context(form_id: str, db: Optional[Client] = None) -> str:
    """
    Build a detailed context block for a single form, including all
    sections and fields with their validation rules and options.
    """
    if db is None:
        db = get_db()

    form_doc = db.collection(COLL_FORMS).document(form_id).get()
    if not form_doc.exists:
        return f"Form ID {form_id} not found."

    form = form_doc.to_dict()
    if not form.get("is_active", False):
        return f"Form ID {form_id} is inactive."

    bank_id = form.get("bank_id", "")
    bank_doc = db.collection(COLL_BANKS).document(bank_id).get()
    bank_name = bank_doc.to_dict().get("name", "Unknown Bank") if bank_doc.exists else "Unknown Bank"

    lines: list[str] = [
        f"## {form.get('name')}",
        f"Bank: {bank_name}",
        f"Description: {form.get('description') or 'N/A'}",
        "",
    ]

    sections = (
        db.collection(COLL_FORM_SECTIONS)
        .where("form_id", "==", form_id)
        .order_by("order_index")
        .stream()
    )

    for section_doc in sections:
        section = section_doc.to_dict()
        section_id = section_doc.id
        lines.append(f"### Section: {section.get('name')}")

        fields = (
            db.collection(COLL_FORM_FIELDS)
            .where("form_id", "==", form_id)
            .where("section_id", "==", section_id)
            .where("is_active", "==", True)
            .order_by("order_index")
            .stream()
        )

        for field_doc in fields:
            field = field_doc.to_dict()
            lines.append(_format_field(field))

        lines.append("")  # blank line between sections

    return "\n".join(lines)


# ═══════════════════════════════════════════════════════════════════════════
# 3. Single field context — detailed metadata for one field
# ═══════════════════════════════════════════════════════════════════════════

def get_field_context(form_id: str, field_key: str, db: Optional[Client] = None) -> str:
    """
    Build detailed context for a single form field, including its
    label, type, validation rules, options, and a helpful hint for
    the LLM to guide the user.
    """
    if db is None:
        db = get_db()

    fields = (
        db.collection(COLL_FORM_FIELDS)
        .where("form_id", "==", form_id)
        .where("field_key", "==", field_key)
        .limit(1)
        .stream()
    )
    field_doc = next(fields, None)

    if not field_doc:
        return f"Field '{field_key}' not found in form {form_id}."

    field = field_doc.to_dict()
    if not field.get("is_active", False):
        return f"Field '{field_key}' is inactive in form {form_id}."

    lines: list[str] = [
        "## Current Field Details",
        _format_field(field),
        "",
        "### Guidance for the Agent",
        _build_field_hint(field),
    ]

    return "\n".join(lines)


# ═══════════════════════════════════════════════════════════════════════════
# 4. Banking FAQ — static knowledge base
# ═══════════════════════════════════════════════════════════════════════════

# Each entry: (keywords, question, answer)
_BANKING_FAQ: list[tuple[list[str], str, str]] = [
    (
        ["address", "aadhaar", "different", "mismatch", "changed", "moved"],
        "What if my address is different from Aadhaar?",
        "You can enter your current residential address even if it differs "
        "from your Aadhaar address. The bank may ask for an address proof "
        "document (utility bill, rent agreement) during physical verification.",
    ),
    (
        ["document", "documents", "need", "required", "proof"],
        "What documents do I need to open an account?",
        "You need: (1) Identity proof — Aadhaar card, (2) PAN card, "
        "(3) Address proof — Aadhaar/utility bill, (4) Passport-size "
        "photograph. KYC verification is done through the BankAI platform.",
    ),
    (
        ["nominee", "nomination", "who", "why"],
        "Who should I name as a nominee?",
        "A nominee is the person who can claim your account balance in case "
        "of your demise. Common choices are spouse, parent, child, or sibling. "
        "You must provide the nominee's full name and relationship.",
    ),
    (
        ["minimum", "balance", "deposit", "amount", "initial"],
        "What is the minimum initial deposit?",
        "The minimum initial deposit for an SBI Savings Account is ₹1,000. "
        "For a Current Account, the requirement may vary. The exact minimum "
        "is enforced as a validation rule on the deposit field.",
    ),
    (
        ["mobile", "phone", "number", "format", "digits"],
        "What mobile number format is accepted?",
        "Enter your 10-digit Indian mobile number without country code or "
        "spaces. Example: 9876543210. This must be the number registered "
        "with the bank for OTP verification.",
    ),
    (
        ["email", "mail", "optional"],
        "Is email required?",
        "Email is optional for most forms. If provided, it must be a valid "
        "email address format (e.g. name@example.com). The bank uses email "
        "for digital correspondence and alerts.",
    ),
    (
        ["pan", "permanent", "account", "number", "why"],
        "Why is PAN required?",
        "PAN (Permanent Account Number) is mandatory for banking as per "
        "RBI regulations under the Prevention of Money Laundering Act. "
        "Format: 5 uppercase letters + 4 digits + 1 uppercase letter "
        "(e.g. ABCDE1234F).",
    ),
    (
        ["aadhaar", "link", "seed", "seeding", "why"],
        "Why link Aadhaar to bank account?",
        "Aadhaar seeding (linking) is required by RBI for Direct Benefit "
        "Transfer (DBT), LPG subsidy, and government scheme payments. "
        "It's a one-time process per account.",
    ),
    (
        ["cheque", "check", "book", "leaves", "how many"],
        "How many cheque leaves can I request?",
        "SBI offers cheque books in sets of 10, 25, or 50 leaves. "
        "The first cheque book is usually free. Additional books may "
        "have nominal charges.",
    ),
    (
        ["time", "long", "take", "processing", "how long"],
        "How long does account opening take?",
        "Digital applications through BankAI are processed within 1-2 "
        "business days after form completion and KYC verification. "
        "Physical verification may add 1-2 days if required.",
    ),
    (
        ["savings", "current", "difference", "type", "which"],
        "What is the difference between savings and current account?",
        "Savings account: For personal savings with interest earnings "
        "(~2.7% p.a. for SBI). Limited transactions per month. "
        "Current account: For businesses with unlimited transactions "
        "but no interest. Higher minimum balance requirement.",
    ),
    (
        ["date", "birth", "dob", "format"],
        "What date format should I use?",
        "Enter dates in YYYY-MM-DD format (e.g. 1995-06-15 for June 15, "
        "1995). You can also say it naturally like 'June 15, 1995' and "
        "the system will convert it.",
    ),
    (
        ["pincode", "pin", "code", "zip"],
        "What is a PIN code?",
        "PIN code (Postal Index Number) is the 6-digit area code used "
        "by India Post. Example: 400001 for Mumbai GPO. Enter exactly "
        "6 digits.",
    ),
    (
        ["gender", "other", "third"],
        "What gender options are available?",
        "The form offers Male, Female, and Other as options. This matches "
        "the Supreme Court's recognition of third gender rights in India.",
    ),
    (
        ["change", "edit", "mistake", "correct", "wrong"],
        "Can I change my answers after filling?",
        "Yes! After all fields are filled, you'll enter the Review state "
        "where you can see all your answers. Say 'change' to re-fill the "
        "form from the beginning, or 'confirm' to submit.",
    ),
    (
        ["kyc", "verification", "status", "verified"],
        "What is KYC and why do I need it?",
        "KYC (Know Your Customer) is mandatory verification required by "
        "RBI before opening any bank account. BankAI verifies your "
        "Aadhaar and PAN digitally. Your KYC must be 'verified' before "
        "you can start filling application forms.",
    ),
    (
        ["safe", "secure", "privacy", "data", "encryption"],
        "Is my data safe on BankAI?",
        "Yes. BankAI uses AES-256 encryption for sensitive data (Aadhaar, "
        "PAN). All PII is redacted before reaching any AI service. "
        "Passwords and tokens use JWT with HS256 signing. Your data is "
        "never shared with third parties.",
    ),
    (
        ["delivery", "branch", "collect", "cheque"],
        "Where will my cheque book be delivered?",
        "You can choose between: (1) Registered address on file — delivered "
        "by courier, or (2) Branch pickup — collect from your home branch. "
        "Select your preference during the application.",
    ),
]


def get_banking_faq_context(query: Optional[str] = None) -> str:
    """
    Retrieve relevant banking FAQ entries based on keyword matching.
    """
    if query:
        query_words = set(query.lower().split())
        matched = []

        for keywords, question, answer in _BANKING_FAQ:
            if query_words & set(keywords):
                matched.append((question, answer))

        if matched:
            lines = ["## Relevant Banking Information\n"]
            for q, a in matched:
                lines.append(f"**Q: {q}**\n{a}\n")
            return "\n".join(lines)

    lines = ["## General Banking FAQ\n"]
    for _, question, answer in _BANKING_FAQ:
        lines.append(f"**Q: {question}**\n{answer}\n")
    return "\n".join(lines)


# ═══════════════════════════════════════════════════════════════════════════
# Internal helpers
# ═══════════════════════════════════════════════════════════════════════════

def _format_field(field: dict) -> str:
    """
    Format a FormField document dictionary as a readable text block.
    """
    lines = [
        f"- **{field.get('label')}** (`{field.get('field_key')}`)",
        f"  Type: {field.get('field_type')} | Required: {'Yes' if field.get('required') else 'No'}",
    ]

    rules = field.get("validation_rule")
    if rules:
        rule_parts: list[str] = []

        if "pattern" in rules:
            rule_parts.append(f"Pattern: `{rules['pattern']}`")
        if "min_length" in rules:
            rule_parts.append(f"Min length: {rules['min_length']}")
        if "max_length" in rules:
            rule_parts.append(f"Max length: {rules['max_length']}")
        if "min" in rules:
            rule_parts.append(f"Min value: {rules['min']}")
        if "max" in rules:
            rule_parts.append(f"Max value: {rules['max']}")

        if rule_parts:
            lines.append(f"  Validation: {' | '.join(rule_parts)}")

    options = field.get("options")
    if options:
        opts = ", ".join(
            f"'{o.get('value')}' ({o.get('label')})" for o in options
        )
        lines.append(f"  Options: {opts}")

    return "\n".join(lines)


def _build_field_hint(field: dict) -> str:
    """
    Generate a helpful hint for the LLM about how to ask for this field.
    """
    hints: list[str] = []
    key = str(field.get("field_key", "")).lower()
    ftype = str(field.get("field_type", "")).lower()

    if ftype == "date":
        hints.append(
            "Ask the user for a date. Accept natural language like "
            "'June 15, 1995' and convert to YYYY-MM-DD format before "
            "saving."
        )
    elif ftype in ("select", "radio"):
        options = field.get("options")
        if options:
            valid_values = [o.get("value") for o in options]
            hints.append(
                f"Present the options clearly. Valid values to save: "
                f"{valid_values}. Match the user's natural response to "
                f"the closest option value."
            )
    elif ftype == "checkbox":
        hints.append(
            "This is a multi-select field. The user can choose multiple "
            "options. Save as a comma-separated list."
        )
    elif ftype == "number":
        hints.append("Accept numeric input. Remove currency symbols or commas before saving.")

    if "mobile" in key or "phone" in key:
        hints.append(
            "The user should provide a 10-digit Indian mobile number. "
            "Remove any +91, spaces, or dashes before saving."
        )
    elif "email" in key:
        hints.append(
            "Accept a valid email address. This field is likely optional."
        )
    elif "pincode" in key or "pin_code" in key:
        hints.append(
            "Indian PIN code: exactly 6 digits. Example: 400001."
        )
    elif "aadhaar" in key:
        hints.append(
            "Aadhaar is a 12-digit number. Remove any spaces before saving. "
            "IMPORTANT: The PII redaction layer will mask this — guide the "
            "user but never display the full number back to them."
        )
    elif "name" in key:
        hints.append(
            "Accept the user's name as spoken. Capitalize properly. "
            "The name should match official documents for banking purposes."
        )
    elif "consent" in key:
        hints.append(
            "This is a consent field. Clearly explain what the user is "
            "agreeing to before asking for their response."
        )
    elif "deposit" in key or "amount" in key:
        hints.append(
            "Ask for the amount in Indian Rupees (₹). Remove currency "
            "symbols before saving. Mention any minimum requirement."
        )

    rules = field.get("validation_rule")
    if rules:
        if "min" in rules:
            hints.append(f"Minimum value: {rules['min']}.")
        if "max" in rules:
            hints.append(f"Maximum value: {rules['max']}.")
        if "min_length" in rules:
            hints.append(f"Minimum {rules['min_length']} characters.")

    if not hints:
        hints.append("Ask a clear, concise question for this field.")

    return "\n".join(f"- {h}" for h in hints)
