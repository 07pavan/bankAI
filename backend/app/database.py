"""
Firebase Firestore database initialization for BankAI.

Replaces the previous PostgreSQL/SQLAlchemy layer.
Provides a module-level Firestore client singleton via get_db().
"""

from __future__ import annotations

import json
import os
from typing import Optional

import firebase_admin
from firebase_admin import credentials, firestore
from google.cloud.firestore import Client

from app.core.logging import get_logger

logger = get_logger()

# Module-level singleton
_firestore_client: Optional[Client] = None


def _init_firebase() -> Client:
    """
    Initialize Firebase Admin SDK and return a Firestore client.

    Credential resolution order:
      1. FIREBASE_CREDENTIALS_JSON env var  — inline JSON string (Render secret)
      2. FIREBASE_CREDENTIALS_PATH env var  — path to service account JSON file
      3. Application Default Credentials    — works on GCP / Cloud Run

    The Firebase app is only initialized once (idempotent).
    """
    from app.core.config import settings

    if not firebase_admin._apps:
        cred_obj = None

        if settings.FIREBASE_CREDENTIALS_JSON:
            logger.info("Initializing Firebase from FIREBASE_CREDENTIALS_JSON env var")
            cred_dict = json.loads(settings.FIREBASE_CREDENTIALS_JSON)
            cred_obj = credentials.Certificate(cred_dict)

        elif settings.FIREBASE_CREDENTIALS_PATH:
            logger.info(
                f"Initializing Firebase from file: {settings.FIREBASE_CREDENTIALS_PATH}"
            )
            cred_obj = credentials.Certificate(settings.FIREBASE_CREDENTIALS_PATH)

        else:
            logger.info("Initializing Firebase with Application Default Credentials")
            cred_obj = credentials.ApplicationDefault()

        kwargs = {}
        if settings.FIREBASE_PROJECT_ID:
            kwargs["project"] = settings.FIREBASE_PROJECT_ID

        firebase_admin.initialize_app(cred_obj, kwargs)
        logger.info("Firebase Admin SDK initialized")

    client = firestore.client()
    logger.info("Firestore client ready")
    return client


def init_db() -> None:
    """
    Call once at startup to warm the Firestore connection.
    Safe to call multiple times (idempotent).
    """
    global _firestore_client
    if _firestore_client is None:
        _firestore_client = _init_firebase()


def get_db() -> Client:
    """
    Return the module-level Firestore client.
    Initializes on first call; subsequent calls return the cached client.
    """
    global _firestore_client
    if _firestore_client is None:
        _firestore_client = _init_firebase()
    return _firestore_client
