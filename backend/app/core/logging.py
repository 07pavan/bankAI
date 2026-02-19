"""
Structured logging configuration with PII redaction
"""

import logging
import logging.handlers
import os
import re
from contextvars import ContextVar
from typing import Optional
import uuid

from app.core.config import settings


# Context variable for correlation ID (request tracing)
correlation_id_var: ContextVar[Optional[str]] = ContextVar('correlation_id', default=None)


class PIIRedactionFilter(logging.Filter):
    """Filter to redact PII (Aadhaar, PAN) from log messages"""
    
    # Patterns to detect and redact
    AADHAAR_PATTERN = re.compile(r'\b\d{4}\s?\d{4}\s?\d{4}\b')
    PAN_PATTERN = re.compile(r'\b[A-Z]{5}\d{4}[A-Z]\b')
    
    def filter(self, record):
        """Redact PII from log message"""
        if isinstance(record.msg, str):
            # Redact Aadhaar
            record.msg = self.AADHAAR_PATTERN.sub('XXXX XXXX XXXX', record.msg)
            # Redact PAN
            record.msg = self.PAN_PATTERN.sub('XXXXX1234X', record.msg)
        
        # Add correlation ID if available
        correlation_id = correlation_id_var.get()
        if correlation_id:
            record.correlation_id = correlation_id
        else:
            record.correlation_id = 'N/A'
        
        return True


class CorrelationIdFormatter(logging.Formatter):
    """Custom formatter that includes correlation ID"""
    
    def format(self, record):
        # Add correlation ID to the record
        if not hasattr(record, 'correlation_id'):
            record.correlation_id = 'N/A'
        return super().format(record)


def setup_logging():
    """
    Configure application logging with:
    - Rotating file handler
    - Console handler for development
    - PII redaction
    - Correlation ID tracking
    """
    # Create logs directory if it doesn't exist
    log_dir = os.path.dirname(settings.LOG_FILE)
    if log_dir and not os.path.exists(log_dir):
        os.makedirs(log_dir, exist_ok=True)
    
    # Create logger
    logger = logging.getLogger("bankai")
    logger.setLevel(getattr(logging, settings.LOG_LEVEL.upper()))
    
    # Remove existing handlers
    logger.handlers.clear()
    
    # Create formatters
    detailed_formatter = CorrelationIdFormatter(
        '%(asctime)s - %(name)s - %(levelname)s - [%(correlation_id)s] - %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S'
    )
    
    simple_formatter = CorrelationIdFormatter(
        '%(levelname)s - [%(correlation_id)s] - %(message)s'
    )
    
    # Rotating file handler
    file_handler = logging.handlers.RotatingFileHandler(
        settings.LOG_FILE,
        maxBytes=settings.LOG_MAX_BYTES,
        backupCount=settings.LOG_BACKUP_COUNT
    )
    file_handler.setLevel(logging.INFO)
    file_handler.setFormatter(detailed_formatter)
    file_handler.addFilter(PIIRedactionFilter())
    
    # Console handler for development
    console_handler = logging.StreamHandler()
    console_handler.setLevel(logging.DEBUG)
    console_handler.setFormatter(simple_formatter)
    console_handler.addFilter(PIIRedactionFilter())
    
    # Add handlers
    logger.addHandler(file_handler)
    logger.addHandler(console_handler)
    
    return logger


def get_logger():
    """Get the application logger"""
    return logging.getLogger("bankai")


def set_correlation_id(correlation_id: Optional[str] = None):
    """Set correlation ID for current request context"""
    if correlation_id is None:
        correlation_id = str(uuid.uuid4())
    correlation_id_var.set(correlation_id)
    return correlation_id


def get_correlation_id() -> Optional[str]:
    """Get current correlation ID"""
    return correlation_id_var.get()
