"""
Lightweight SQL-based RAG (Retrieval-Augmented Generation) for BankAI.

Provides structured form metadata and banking FAQ context to the LLM
system prompt — no vector database, no embeddings, no extra dependencies.

Design rationale:
  BankAI has ~3 forms × ~25 total fields — a small knowledge base that
  fits entirely in structured text.  The LLM needs to understand field
  labels, validation rules, options, and common banking scenarios.
  SQL queries + text formatting accomplish this at near-zero cost.

Functions:
  get_all_forms_summary(db)           → overview of all active forms
  get_form_context(form_id, db)       → full form structure with all fields
  get_field_context(form_id, key, db) → detailed metadata for one field
  get_banking_faq_context(query)      → relevant FAQ entries (keyword match)

Usage in ai_agent_service.py:
  context = get_field_context(form_id, "mobile", db)
  # → "Field: Mobile Number | Type: text | Required: Yes | Pattern: ..."
  # Injected into system prompt so the LLM can explain validation rules.
"""

from typing import Optional
from sqlalchemy.orm import Session

from app.models import Bank, Form, FormSection, FormField
from app.core.logging import get_logger

logger = get_logger()


# ═══════════════════════════════════════════════════════════════════════════
# 1. Form summary — all active forms at a glance
# ═══════════════════════════════════════════════════════════════════════════

def get_all_forms_summary(db: Session) -> str:
    """
    Build a concise summary of all active forms across all banks.

    Returns plain text suitable for injection into an LLM system prompt.
    Includes: form name, description, bank name, field count.

    Args:
        db: Active SQLAlchemy session.

    Returns:
        Formatted text listing all active forms, or a fallback message
        if no forms are found.
    """
    banks = db.query(Bank).filter(Bank.is_active == True).order_by(Bank.name).all()

    if not banks:
        return "No active banks or forms are currently available."

    lines: list[str] = ["## Available Banking Forms\n"]

    for bank in banks:
        forms = (
            db.query(Form)
            .filter(Form.bank_id == bank.id, Form.is_active == True)
            .order_by(Form.name)
            .all()
        )
        if not forms:
            continue

        lines.append(f"### {bank.name} ({bank.code})")

        for form in forms:
            field_count = (
                db.query(FormField)
                .filter(FormField.form_id == form.id, FormField.is_active == True)
                .count()
            )
            required_count = (
                db.query(FormField)
                .filter(
                    FormField.form_id == form.id,
                    FormField.is_active == True,
                    FormField.required == True,
                )
                .count()
            )

            desc = form.description or "No description available"
            lines.append(
                f"- **{form.name}** (Form ID: {form.id})\n"
                f"  Description: {desc}\n"
                f"  Fields: {field_count} total, {required_count} required"
            )

        lines.append("")  # blank line between banks

    return "\n".join(lines)


# ═══════════════════════════════════════════════════════════════════════════
# 2. Full form context — all sections and fields
# ═══════════════════════════════════════════════════════════════════════════

def get_form_context(form_id: int, db: Session) -> str:
    """
    Build a detailed context block for a single form, including all
    sections and fields with their validation rules and options.

    This is useful when the LLM needs a full overview (e.g. answering
    "what documents do I need?" or "how many fields are there?").

    Args:
        form_id: Primary key of the Form to retrieve.
        db:      Active SQLAlchemy session.

    Returns:
        Formatted text with full form structure, or a fallback message
        if the form is not found.
    """
    form = db.query(Form).filter(Form.id == form_id, Form.is_active == True).first()
    if not form:
        return f"Form ID {form_id} not found or inactive."

    bank = db.query(Bank).filter(Bank.id == form.bank_id).first()
    bank_name = bank.name if bank else "Unknown Bank"

    lines: list[str] = [
        f"## {form.name}",
        f"Bank: {bank_name}",
        f"Description: {form.description or 'N/A'}",
        "",
    ]

    sections = (
        db.query(FormSection)
        .filter(FormSection.form_id == form.id)
        .order_by(FormSection.order_index)
        .all()
    )

    for section in sections:
        lines.append(f"### Section: {section.name}")

        fields = (
            db.query(FormField)
            .filter(
                FormField.form_id == form.id,
                FormField.section_id == section.id,
                FormField.is_active == True,
            )
            .order_by(FormField.order_index)
            .all()
        )

        for field in fields:
            lines.append(_format_field(field))

        lines.append("")  # blank line between sections

    return "\n".join(lines)


# ═══════════════════════════════════════════════════════════════════════════
# 3. Single field context — detailed metadata for one field
# ═══════════════════════════════════════════════════════════════════════════

def get_field_context(form_id: int, field_key: str, db: Session) -> str:
    """
    Build detailed context for a single form field, including its
    label, type, validation rules, options, and a helpful hint for
    the LLM to guide the user.

    Injected into the filling_form_node system prompt so the LLM can
    ask the right question and explain validation requirements.

    Args:
        form_id:   Primary key of the parent Form.
        field_key: The field_key to look up (e.g. "mobile", "dob").
        db:        Active SQLAlchemy session.

    Returns:
        Formatted text describing the field, or a fallback message
        if the field is not found.
    """
    field = (
        db.query(FormField)
        .filter(
            FormField.form_id == form_id,
            FormField.field_key == field_key,
            FormField.is_active == True,
        )
        .first()
    )

    if not field:
        return f"Field '{field_key}' not found in form {form_id}."

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
# Keywords are used for simple keyword matching against user queries.
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

    If *query* is provided, returns only FAQ entries whose keywords
    match words in the query.  If no query or no matches, returns
    the full FAQ as general context.

    The FAQ is a static, in-memory knowledge base — no DB queries.
    Designed to be injected into the LLM system prompt so it can
    answer common "what if" user questions.

    Args:
        query: Optional user message to match against FAQ keywords.

    Returns:
        Formatted FAQ text (markdown-style Q&A pairs).
    """
    if query:
        query_words = set(query.lower().split())
        matched = []

        for keywords, question, answer in _BANKING_FAQ:
            # Match if any FAQ keyword appears in the user's query
            if query_words & set(keywords):
                matched.append((question, answer))

        if matched:
            lines = ["## Relevant Banking Information\n"]
            for q, a in matched:
                lines.append(f"**Q: {q}**\n{a}\n")
            return "\n".join(lines)

    # No query or no matches — return top-level summary
    lines = ["## General Banking FAQ\n"]
    for _, question, answer in _BANKING_FAQ:
        lines.append(f"**Q: {question}**\n{answer}\n")
    return "\n".join(lines)


# ═══════════════════════════════════════════════════════════════════════════
# Internal helpers
# ═══════════════════════════════════════════════════════════════════════════

def _format_field(field: FormField) -> str:
    """
    Format a single FormField ORM object as a readable text block.

    Includes: field_key, label, type, required, validation rules,
    and options (for select/radio/checkbox fields).
    """
    lines = [
        f"- **{field.label}** (`{field.field_key}`)",
        f"  Type: {field.field_type} | Required: {'Yes' if field.required else 'No'}",
    ]

    # Validation rules
    if field.validation_rule:
        rules = field.validation_rule
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

    # Options (select, radio, checkbox)
    if field.options:
        opts = ", ".join(
            f"'{o['value']}' ({o['label']})" for o in field.options
        )
        lines.append(f"  Options: {opts}")

    return "\n".join(lines)


def _build_field_hint(field: FormField) -> str:
    """
    Generate a helpful hint for the LLM about how to ask for this field.

    The hint tells the LLM what a valid answer looks like, so it can
    guide the user and convert natural-language answers to the expected
    format.
    """
    hints: list[str] = []
    key = field.field_key.lower()
    ftype = field.field_type.lower()

    # Type-specific hints
    if ftype == "date":
        hints.append(
            "Ask the user for a date. Accept natural language like "
            "'June 15, 1995' and convert to YYYY-MM-DD format before "
            "saving with answer_field."
        )
    elif ftype in ("select", "radio"):
        if field.options:
            valid_values = [o["value"] for o in field.options]
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

    # Key-specific hints
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

    # Validation-specific hints
    if field.validation_rule:
        rules = field.validation_rule
        if "min" in rules:
            hints.append(f"Minimum value: {rules['min']}.")
        if "max" in rules:
            hints.append(f"Maximum value: {rules['max']}.")
        if "min_length" in rules:
            hints.append(f"Minimum {rules['min_length']} characters.")

    if not hints:
        hints.append("Ask a clear, concise question for this field.")

    return "\n".join(f"- {h}" for h in hints)
