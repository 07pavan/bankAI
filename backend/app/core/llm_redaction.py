"""
PII redaction layer for LLM interactions
Prevents Aadhaar, PAN, and other PII from being sent to external LLM APIs.
Uses Presidio Analyzer with custom Indian-PII recognizers alongside the
same regex patterns used in core/logging.py for consistency.

NOTE: Presidio is an optional dependency. If it is unavailable (e.g. due to
Python version incompatibility with spacy/typer), the service falls back to
regex-only redaction which still catches Aadhaar, PAN, phone, and email.
"""

import re

from app.core.logging import get_logger

# ---------------------------------------------------------------------------
# Try to import Presidio — graceful fallback if unavailable
# ---------------------------------------------------------------------------
_PRESIDIO_AVAILABLE = False
try:
    from presidio_analyzer import AnalyzerEngine, PatternRecognizer, Pattern
    from presidio_anonymizer import AnonymizerEngine
    from presidio_anonymizer.entities import OperatorConfig
    _PRESIDIO_AVAILABLE = True
except Exception:
    # Presidio or one of its transitive deps (spacy → typer) may fail on
    # Python 3.14+.  Fall through to regex-only mode.
    pass


# ---------------------------------------------------------------------------
# PII regex patterns — identical to core/logging.PIIRedactionFilter
# Kept in sync so log redaction and LLM redaction catch the same tokens.
# ---------------------------------------------------------------------------

# Aadhaar: 12 digits, optionally grouped with spaces (1234 5678 9012)
AADHAAR_PATTERN = re.compile(r'\b\d{4}\s?\d{4}\s?\d{4}\b')

# PAN: ABCDE1234F (5 uppercase + 4 digits + 1 uppercase)
PAN_PATTERN = re.compile(r'\b[A-Z]{5}\d{4}[A-Z]\b')

# Additional defensive patterns for common formats
PHONE_PATTERN = re.compile(r'\b(?:\+91[\s-]?)?[6-9]\d{9}\b')
EMAIL_PATTERN = re.compile(r'\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b')


# ---------------------------------------------------------------------------
# Placeholder constants — used as replacement tokens
# ---------------------------------------------------------------------------

AADHAAR_PLACEHOLDER = "XXXX XXXX XXXX"
PAN_PLACEHOLDER = "XXXXX1234X"
PHONE_PLACEHOLDER = "[REDACTED_PHONE]"
EMAIL_PLACEHOLDER = "[REDACTED_EMAIL]"


class PIIRedactionService:
    """
    Service for detecting and redacting PII before text is sent to an LLM.

    Combines two detection strategies:
      1. **Presidio Analyzer** — NER-based entity recognition for names,
         addresses, and generic PII.  *Only active when presidio is installed.*
      2. **Custom regex recognizers** — purpose-built patterns for Indian
         Aadhaar (12 digits) and PAN (10 alphanumeric) that mirror the
         patterns in ``core/logging.PIIRedactionFilter``.

    Usage::

        from app.core.llm_redaction import redaction_service

        safe_text = redaction_service.redact_pii(user_message)
        if redaction_service.should_redact_before_llm(user_message):
            # message contains PII — redact first
            ...
    """

    def __init__(self) -> None:
        self._logger = get_logger()
        self._presidio_ready = False

        if _PRESIDIO_AVAILABLE:
            try:
                # --- Presidio custom recognizers for Indian PII -----------------
                aadhaar_recognizer = PatternRecognizer(
                    supported_entity="IN_AADHAAR",
                    name="aadhaar_recognizer",
                    patterns=[
                        Pattern(
                            name="aadhaar_12digit",
                            regex=r'\b\d{4}\s?\d{4}\s?\d{4}\b',
                            score=0.9,
                        ),
                    ],
                    context=["aadhaar", "aadhar", "uid", "uidai"],
                )

                pan_recognizer = PatternRecognizer(
                    supported_entity="IN_PAN",
                    name="pan_recognizer",
                    patterns=[
                        Pattern(
                            name="pan_10char",
                            regex=r'\b[A-Z]{5}\d{4}[A-Z]\b',
                            score=0.9,
                        ),
                    ],
                    context=["pan", "permanent account"],
                )

                phone_recognizer = PatternRecognizer(
                    supported_entity="IN_PHONE",
                    name="phone_recognizer",
                    patterns=[
                        Pattern(
                            name="indian_phone",
                            regex=r'\b(?:\+91[\s-]?)?[6-9]\d{9}\b',
                            score=0.7,
                        ),
                    ],
                    context=["phone", "mobile", "contact"],
                )

                # --- Presidio engines -------------------------------------------
                self._analyzer = AnalyzerEngine()
                self._analyzer.registry.add_recognizer(aadhaar_recognizer)
                self._analyzer.registry.add_recognizer(pan_recognizer)
                self._analyzer.registry.add_recognizer(phone_recognizer)

                self._anonymizer = AnonymizerEngine()

                # Operator overrides — use our branded placeholders
                self._operators = {
                    "IN_AADHAAR": OperatorConfig("replace", {"new_value": AADHAAR_PLACEHOLDER}),
                    "IN_PAN": OperatorConfig("replace", {"new_value": PAN_PLACEHOLDER}),
                    "IN_PHONE": OperatorConfig("replace", {"new_value": PHONE_PLACEHOLDER}),
                    "EMAIL_ADDRESS": OperatorConfig("replace", {"new_value": EMAIL_PLACEHOLDER}),
                    "PERSON": OperatorConfig("replace", {"new_value": "[REDACTED_NAME]"}),
                    "DEFAULT": OperatorConfig("replace", {"new_value": "[REDACTED]"}),
                }

                self._presidio_ready = True
                self._logger.info("PIIRedactionService initialised with Presidio + custom recognizers")

            except Exception as exc:
                self._logger.warning(
                    f"Presidio init failed ({exc}); falling back to regex-only PII redaction"
                )
        else:
            self._logger.info(
                "Presidio not available — using regex-only PII redaction "
                "(Aadhaar, PAN, phone, email patterns)"
            )

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def redact_pii(self, text: str) -> str:
        """
        Redact all detected PII from *text* and return a safe string.

        Applies two passes:
          1. **Presidio pass** — runs the full analyzer pipeline (NER +
             custom pattern recognizers) and anonymises matched entities.
             *Skipped if Presidio is unavailable.*
          2. **Regex fallback pass** — catches any residual Aadhaar/PAN
             tokens that Presidio may have missed (e.g., when surrounding
             context is absent).

        Args:
            text: Raw user message or any string that may contain PII.

        Returns:
            A copy of *text* with all detected PII replaced by safe
            placeholder tokens.
        """
        if not text or not text.strip():
            return text

        # Pass 1 — Presidio-based detection + anonymisation
        if self._presidio_ready:
            try:
                results = self._analyzer.analyze(
                    text=text,
                    language="en",
                    entities=[
                        "IN_AADHAAR", "IN_PAN", "IN_PHONE",
                        "EMAIL_ADDRESS", "PERSON",
                    ],
                )
                if results:
                    anonymised = self._anonymizer.anonymize(
                        text=text,
                        analyzer_results=results,
                        operators=self._operators,
                    )
                    text = anonymised.text
            except Exception as exc:
                # Never let redaction failure crash the pipeline — fall through
                # to regex pass instead.
                self._logger.warning(f"Presidio redaction pass failed: {exc}")

        # Pass 2 — deterministic regex fallback (same patterns as logging)
        text = AADHAAR_PATTERN.sub(AADHAAR_PLACEHOLDER, text)
        text = PAN_PATTERN.sub(PAN_PLACEHOLDER, text)
        text = PHONE_PATTERN.sub(PHONE_PLACEHOLDER, text)
        text = EMAIL_PATTERN.sub(EMAIL_PLACEHOLDER, text)

        return text

    def should_redact_before_llm(self, message: str) -> bool:
        """
        Fast boolean check — does *message* contain likely PII?

        This is a lightweight pre-filter that avoids spinning up the full
        Presidio pipeline.  Use it to decide whether ``redact_pii()``
        needs to be called at all.

        Args:
            message: The candidate text to inspect.

        Returns:
            ``True`` if any Aadhaar, PAN, phone, or email pattern is found.
        """
        if not message:
            return False

        return bool(
            AADHAAR_PATTERN.search(message)
            or PAN_PATTERN.search(message)
            or PHONE_PATTERN.search(message)
            or EMAIL_PATTERN.search(message)
        )

    def redact_for_log(self, text: str) -> str:
        """
        Convenience wrapper that applies the *same* regex rules used by
        ``core/logging.PIIRedactionFilter`` so callers don't need to
        import two modules.

        Args:
            text: String that may contain PII.

        Returns:
            Redacted string safe for log output.
        """
        text = AADHAAR_PATTERN.sub(AADHAAR_PLACEHOLDER, text)
        text = PAN_PATTERN.sub(PAN_PLACEHOLDER, text)
        return text


# Global redaction service instance
redaction_service = PIIRedactionService()


# ---------------------------------------------------------------------------
# Convenience module-level functions (thin wrappers around the singleton)
# ---------------------------------------------------------------------------

def redact_pii(text: str) -> str:
    """Redact all detected PII from *text* — module-level shortcut."""
    return redaction_service.redact_pii(text)


def should_redact_before_llm(message: str) -> bool:
    """Quick boolean check for PII presence — module-level shortcut."""
    return redaction_service.should_redact_before_llm(message)
