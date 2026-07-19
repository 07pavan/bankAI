"""
PDF Generation Service — dynamic form-to-PDF rendering.

Generates a professional PDF from a completed form submission,
including all sections, field labels/values, and the user's signature.

Design:
  - NEVER hardcodes form fields — reads dynamic form structure from DB.
  - Masks sensitive PII (Aadhaar, PAN) in the PDF.
  - Embeds signature image if available.
  - Uses reportlab for PDF generation (no external dependencies).

Output: /backend/pdfs/{uuid}.pdf
"""

import os
import re
import uuid
import hashlib
from datetime import datetime, timezone

from fastapi import HTTPException, status

from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm, cm
from reportlab.lib.colors import HexColor
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle,
    Image as RLImage, HRFlowable,
)
from reportlab.lib.enums import TA_LEFT, TA_CENTER, TA_RIGHT

from app.database import get_db
from app.models import (
    COLL_SUBMISSIONS, COLL_FORMS, COLL_FORM_SECTIONS,
    COLL_FORM_FIELDS, COLL_SUBMISSION_DATA, COLL_BANKS,
    COLL_USERS, COLL_KYC_SUBMISSIONS, SubmissionStatus,
)
from app.core.logging import get_logger

logger = get_logger()

# Configuration
PDF_DIR = os.path.join(os.path.dirname(__file__), "..", "..", "pdfs")
# Base directory for resolving relative paths stored in DB
_BACKEND_DIR = os.path.join(os.path.dirname(__file__), "..", "..")

# PII masking patterns (same as core/llm_redaction.py)
AADHAAR_PATTERN = re.compile(r'\b\d{4}\s?\d{4}\s?\d{4}\b')
PAN_PATTERN = re.compile(r'\b[A-Z]{5}\d{4}[A-Z]\b')


def _ensure_pdf_dir() -> None:
    """Create the pdfs directory if it doesn't exist."""
    os.makedirs(PDF_DIR, exist_ok=True)


def _mask_aadhaar(value: str) -> str:
    """Mask Aadhaar: show only last 4 digits."""
    cleaned = value.replace(" ", "")
    if re.match(r'^\d{12}$', cleaned):
        return f"XXXX XXXX {cleaned[-4:]}"
    return value


def _mask_pan(value: str) -> str:
    """Mask PAN: show first 2 and last 1 characters."""
    if re.match(r'^[A-Z]{5}\d{4}[A-Z]$', value.upper()):
        return f"{value[:2]}XXX{value[5:8]}X{value[9]}"
    return value


def _mask_sensitive_value(field_key: str, value: str) -> str:
    """Apply PII masking based on field_key heuristics."""
    key_lower = field_key.lower()
    if "aadhaar" in key_lower:
        return _mask_aadhaar(value)
    if "pan" in key_lower:
        return _mask_pan(value)
    # Also catch raw patterns in any field
    value = AADHAAR_PATTERN.sub(
        lambda m: _mask_aadhaar(m.group()), value
    )
    value = PAN_PATTERN.sub(
        lambda m: _mask_pan(m.group()), value
    )
    return value


def generate_pdf(submission_id: str, user_id: str) -> str:
    """
    Generate a PDF for a completed submission.

    Args:
        submission_id: Firestore document ID of the submission.
        user_id:       Authenticated user ID (for ownership check).

    Returns:
        Absolute path to the generated PDF file.

    Raises:
        HTTPException 404: Submission not found.
        HTTPException 403: Caller does not own this submission.
        HTTPException 409: Submission not yet completed.
    """
    db = get_db()

    # --- Load submission ---
    sub_doc = db.collection(COLL_SUBMISSIONS).document(submission_id).get()
    if not sub_doc.exists:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Submission {submission_id} not found.",
        )
    sub = sub_doc.to_dict()

    # --- Load user details for audit & role authorization ---
    user_doc = db.collection(COLL_USERS).document(user_id).get()
    if not user_doc.exists:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found.",
        )
    user_data = user_doc.to_dict()
    is_admin = user_data.get("role") == "admin"
    aadhaar_hash = user_data.get("aadhaar_hash", "N/A")

    # --- Ownership check (allow owner OR admin) ---
    if sub.get("user_id") != user_id and not is_admin:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Access denied to this submission.",
        )

    # --- Load user's KYC details (e.g. selfie path, sorted in memory to avoid composite index requirement) ---
    owner_user_id = sub.get("user_id")
    kyc_docs = (
        db.collection(COLL_KYC_SUBMISSIONS)
        .where("user_id", "==", owner_user_id)
        .stream()
    )
    kyc_docs_list = list(kyc_docs)
    kyc_doc = None
    if kyc_docs_list:
        kyc_docs_list.sort(key=lambda d: d.to_dict().get("created_at") or datetime.min.replace(tzinfo=timezone.utc), reverse=True)
        kyc_doc = kyc_docs_list[0]
    selfie_path = None
    if kyc_doc:
        selfie_path = kyc_doc.to_dict().get("selfie_path")

    # --- Status check ---
    if sub.get("status") != SubmissionStatus.COMPLETED.value:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="PDF can only be generated for completed submissions.",
        )

    form_id = sub.get("form_id")

    # --- Load form ---
    form_doc = db.collection(COLL_FORMS).document(form_id).get()
    if not form_doc.exists:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Form definition not found.",
        )
    form = form_doc.to_dict()

    # --- Load bank name ---
    bank_id = form.get("bank_id")
    bank_name = "BankAI"
    if bank_id:
        bank_doc = db.collection(COLL_BANKS).document(bank_id).get()
        if bank_doc.exists:
            bank_name = bank_doc.to_dict().get("name", "BankAI")

    # --- Load sections (ordered) ---
    sections_query = (
        db.collection(COLL_FORM_SECTIONS)
        .where("form_id", "==", form_id)
        .order_by("order_index")
        .stream()
    )
    sections = [{"id": d.id, **d.to_dict()} for d in sections_query]

    # --- Load active fields (ordered) ---
    fields_query = (
        db.collection(COLL_FORM_FIELDS)
        .where("form_id", "==", form_id)
        .where("is_active", "==", True)
        .order_by("order_index")
        .stream()
    )
    fields = [{"id": d.id, **d.to_dict()} for d in fields_query]

    # Build section lookup: section_id → [field]
    section_fields: dict[str, list] = {}
    unsectioned_fields: list = []
    for f in fields:
        sid = f.get("section_id")
        if sid:
            section_fields.setdefault(sid, []).append(f)
        else:
            unsectioned_fields.append(f)

    # --- Load submitted answers ---
    data_query = (
        db.collection(COLL_SUBMISSION_DATA)
        .where("submission_id", "==", submission_id)
        .stream()
    )
    answers = {d.to_dict().get("field_key"): d.to_dict().get("value", "") for d in data_query}

    # --- Build PDF ---
    _ensure_pdf_dir()
    filename = f"{uuid.uuid4().hex}.pdf"
    filepath = os.path.join(PDF_DIR, filename)

    doc = SimpleDocTemplate(
        filepath,
        pagesize=A4,
        leftMargin=20 * mm,
        rightMargin=20 * mm,
        topMargin=15 * mm,
        bottomMargin=15 * mm,
    )

    # --- Styles ---
    styles = getSampleStyleSheet()
    styles.add(ParagraphStyle(
        name='BankHeader',
        parent=styles['Title'],
        fontSize=18,
        textColor=HexColor('#1e3a5f'),
        spaceAfter=4,
        alignment=TA_CENTER,
    ))
    styles.add(ParagraphStyle(
        name='FormTitle',
        parent=styles['Heading2'],
        fontSize=14,
        textColor=HexColor('#2d5aa0'),
        spaceAfter=2,
        alignment=TA_CENTER,
    ))
    styles.add(ParagraphStyle(
        name='SectionHeader',
        parent=styles['Heading3'],
        fontSize=12,
        textColor=HexColor('#1e3a5f'),
        spaceBefore=12,
        spaceAfter=6,
        borderWidth=0,
    ))
    styles.add(ParagraphStyle(
        name='FieldLabel',
        parent=styles['Normal'],
        fontSize=9,
        textColor=HexColor('#666666'),
    ))
    styles.add(ParagraphStyle(
        name='FieldValue',
        parent=styles['Normal'],
        fontSize=10,
        textColor=HexColor('#1a1a1a'),
        fontName='Helvetica-Bold',
    ))
    styles.add(ParagraphStyle(
        name='FooterText',
        parent=styles['Normal'],
        fontSize=8,
        textColor=HexColor('#999999'),
        alignment=TA_CENTER,
    ))

    elements = []

    # --- Resolve Selfie Path ---
    selfie_dir = os.path.join(os.path.dirname(__file__), "..", "..", "selfies")
    selfie_abs_path = None
    if selfie_path:
        selfie_abs_path = os.path.normpath(
            os.path.join(selfie_dir, selfie_path)
        )

    # --- Header Table Layout (Left: Metadata, Right: Selfie photo) ---
    header_left = []
    header_left.append(Paragraph(f"🏦 {bank_name}", styles['BankHeader']))
    header_left.append(Paragraph(form.get("name", "Application"), styles['FormTitle']))
    header_left.append(Spacer(1, 3 * mm))

    # Application metadata
    meta_data = [
        ["Application ID:", f"#{submission_id}"],
        ["Date:", datetime.now(timezone.utc).strftime("%d %B %Y, %H:%M UTC")],
        ["Status:", "Completed ✅"],
    ]
    meta_table = Table(meta_data, colWidths=[90, 240])
    meta_table.setStyle(TableStyle([
        ('FONTNAME', (0, 0), (0, -1), 'Helvetica-Bold'),
        ('FONTSIZE', (0, 0), (-1, -1), 9),
        ('TEXTCOLOR', (0, 0), (0, -1), HexColor('#666666')),
        ('TEXTCOLOR', (1, 0), (1, -1), HexColor('#1a1a1a')),
        ('VALIGN', (0, 0), (-1, -1), 'TOP'),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 3),
    ]))
    header_left.append(meta_table)

    header_right = []
    if selfie_abs_path and os.path.isfile(selfie_abs_path):
        try:
            selfie_img = RLImage(selfie_abs_path, width=28 * mm, height=35 * mm)
            header_right.append(selfie_img)
            header_right.append(Spacer(1, 1 * mm))
            header_right.append(Paragraph("KYC Photo", styles['FooterText']))
        except Exception as exc:
            logger.warning(f"Could not embed selfie image in PDF: {exc}")
            header_right.append(Paragraph("[Photo Error]", styles['FieldLabel']))
    else:
        header_right.append(Paragraph("[No Photo Captured]", styles['FieldLabel']))

    # Create top header table
    header_table_data = [[header_left, header_right]]
    header_table = Table(header_table_data, colWidths=[350, 130])
    header_table.setStyle(TableStyle([
        ('VALIGN', (0, 0), (-1, -1), 'TOP'),
        ('ALIGN', (1, 0), (1, 0), 'RIGHT'),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 0),
        ('TOPPADDING', (0, 0), (-1, -1), 0),
    ]))
    elements.append(header_table)
    elements.append(Spacer(1, 4 * mm))

    # Horizontal rule
    elements.append(HRFlowable(
        width="100%", thickness=1,
        color=HexColor('#cccccc'), spaceAfter=8,
    ))

    # --- Sections with fields ---
    def _render_fields(field_list: list) -> None:
        """Render a list of field dicts as table rows."""
        table_data = []
        for field in field_list:
            field_key = field.get("field_key", "")
            raw_value = answers.get(field_key, "—") or "—"
            display_value = (
                _mask_sensitive_value(field_key, raw_value)
                if raw_value != "—" else "—"
            )

            # Resolve select/radio display labels
            options = field.get("options") or []
            if options and raw_value != "—":
                for opt in options:
                    if opt.get("value") == raw_value:
                        display_value = opt.get("label", raw_value)
                        break

            required_marker = " *" if field.get("required") else ""
            table_data.append([
                Paragraph(f"{field.get('label', field_key)}{required_marker}", styles['FieldLabel']),
                Paragraph(display_value, styles['FieldValue']),
            ])

        if table_data:
            t = Table(table_data, colWidths=[170, 310])
            t.setStyle(TableStyle([
                ('VALIGN', (0, 0), (-1, -1), 'TOP'),
                ('BOTTOMPADDING', (0, 0), (-1, -1), 6),
                ('TOPPADDING', (0, 0), (-1, -1), 4),
                ('LINEBELOW', (0, 0), (-1, -2), 0.5, HexColor('#eeeeee')),
            ]))
            elements.append(t)

    if sections:
        for section in sections:
            s_id = section.get("id")
            s_fields = section_fields.get(s_id, [])
            if not s_fields:
                continue
            elements.append(
                Paragraph(f"📋 {section.get('name', 'Section')}", styles['SectionHeader'])
            )
            _render_fields(s_fields)
            elements.append(Spacer(1, 4 * mm))

    # Unsectioned fields
    if unsectioned_fields:
        if sections:
            elements.append(
                Paragraph("📋 Other Fields", styles['SectionHeader'])
            )
        _render_fields(unsectioned_fields)

    # --- Signature & Consent Audit Trail ---
    elements.append(Spacer(1, 6 * mm))
    elements.append(HRFlowable(
        width="100%", thickness=1,
        color=HexColor('#cccccc'), spaceBefore=4, spaceAfter=8,
    ))

    # Resolve relative path from DB to absolute path on this OS
    sig_rel_path = sub.get("signature_path")
    sig_abs_path = None
    if sig_rel_path:
        sig_abs_path = os.path.normpath(
            os.path.join(_BACKEND_DIR, sig_rel_path)
        )

    signed_at = sub.get("signed_at")
    signed_str = "—"
    if signed_at:
        if hasattr(signed_at, "strftime"):
            signed_str = signed_at.strftime('%d %B %Y, %H:%M UTC')
        else:
            signed_str = str(signed_at)

    if sig_abs_path and os.path.isfile(sig_abs_path):
        elements.append(
            Paragraph("Applicant Signature:", styles['FieldLabel'])
        )
        elements.append(Spacer(1, 2 * mm))
        try:
            sig_img = RLImage(sig_abs_path, width=50 * mm, height=20 * mm)
            elements.append(sig_img)
        except Exception as exc:
            logger.warning(f"Could not embed signature image: {exc}")
            elements.append(
                Paragraph("[Signature on file]", styles['FieldValue'])
            )
        elements.append(Spacer(1, 2 * mm))
        elements.append(Paragraph(
            f"Signed on: {signed_str}",
            styles['FieldLabel'],
        ))
    else:
        elements.append(
            Paragraph("[No signature captured]", styles['FieldLabel'])
        )

    elements.append(Spacer(1, 4 * mm))

    # Proactive Consent Audit Trail block
    consent_payload = f"{submission_id}-{owner_user_id}-{signed_str}"
    consent_hash = hashlib.sha256(consent_payload.encode('utf-8')).hexdigest()[:24].upper()
    verification_seal = f"BANKAI-SECURE-SEAL-{consent_hash[:6]}-{consent_hash[6:12]}-{consent_hash[12:18]}-{consent_hash[18:24]}"

    # Retrieve owner's Aadhaar Hash from submission context
    owner_doc = db.collection(COLL_USERS).document(owner_user_id).get()
    owner_aadhaar_hash = owner_doc.to_dict().get("aadhaar_hash", "N/A") if owner_doc.exists else "N/A"

    audit_data = [
        [Paragraph("Consent Audit Trail", styles['FieldLabel']), ""],
        [Paragraph("Verification Seal:", styles['FieldLabel']), Paragraph(verification_seal, styles['FieldValue'])],
        [Paragraph("Aadhaar KYC Verification Hash:", styles['FieldLabel']), Paragraph(owner_aadhaar_hash, styles['FieldValue'])],
        [Paragraph("Consent Authorization Status:", styles['FieldLabel']), Paragraph("AUTHORIZED & SIGNED ELECTRONICALLY", styles['FieldValue'])],
        [Paragraph("System Audit Timestamp:", styles['FieldLabel']), Paragraph(signed_str, styles['FieldValue'])],
    ]
    
    audit_table = Table(audit_data, colWidths=[160, 320])
    audit_table.setStyle(TableStyle([
        ('SPAN', (0, 0), (1, 0)),
        ('BACKGROUND', (0, 0), (-1, 0), HexColor('#f3f4f6')),
        ('GRID', (0, 0), (-1, -1), 0.5, HexColor('#e5e7eb')),
        ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
        ('TOPPADDING', (0, 0), (-1, -1), 4),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 4),
    ]))
    elements.append(audit_table)

    # --- Footer ---
    elements.append(Spacer(1, 10 * mm))
    elements.append(HRFlowable(
        width="100%", thickness=0.5,
        color=HexColor('#dddddd'), spaceAfter=6,
    ))
    elements.append(Paragraph(
        f"Generated by BankAI Platform — {datetime.now(timezone.utc).strftime('%d %b %Y %H:%M UTC')} — "
        f"This document is digitally generated and does not require a physical stamp.",
        styles['FooterText'],
    ))

    # --- Build ---
    try:
        doc.build(elements)
    except Exception as exc:
        logger.error(f"PDF generation failed for submission {submission_id}: {exc}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to generate PDF. Please try again.",
        )

    # --- Update submission with pdf_path ---
    db.collection(COLL_SUBMISSIONS).document(submission_id).update({
        "pdf_path": f"pdfs/{filename}",
    })

    logger.info(
        f"PDF generated: submission={submission_id} user={user_id} file={filename}"
    )

    return filepath
