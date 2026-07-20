"""
Audit Log Service — BankAI Admin Panel

Records every admin mutation event (create/update/delete) into the
`audit_logs` Firestore collection, and provides filtered/paginated
read access for the Audits tab in the admin panel.

Schema (audit_logs document):
    id           — Firestore auto-generated ID
    actor_id     — user_id of the admin who performed the action
    actor_role   — "admin"
    action       — "create" | "update" | "delete" | "toggle"
    entity_type  — "bank" | "form" | "section" | "field" | "submission"
    entity_id    — Firestore document ID of the affected entity
    entity_name  — human-readable name/code of the entity
    details      — dict with extra context (old/new values, etc.)
    created_at   — UTC datetime
"""

from datetime import datetime, timezone
from typing import Optional, Any

from fastapi import HTTPException, status

from app.database import get_db
from app.models import COLL_AUDIT_LOGS
from app.core.logging import get_logger

logger = get_logger()

# ---------------------------------------------------------------------------
# Write helpers — called from admin_service (fire-and-forget pattern)
# ---------------------------------------------------------------------------

def log_action(
    actor_id: str,
    action: str,
    entity_type: str,
    entity_id: str,
    entity_name: str,
    details: Optional[dict] = None,
) -> None:
    """
    Persist a single audit-log entry to Firestore.

    Args:
        actor_id:    The admin user_id performing the action.
        action:      Short verb: "create", "update", "delete", "toggle".
        entity_type: Collection/resource type: "bank", "form", "section", "field".
        entity_id:   Firestore document ID of the entity being acted on.
        entity_name: Human-readable label (e.g. bank name, form code).
        details:     Optional dict with additional context.
    """
    try:
        db = get_db()
        now = datetime.now(timezone.utc)
        ref = db.collection(COLL_AUDIT_LOGS).document()
        data = {
            "actor_id": actor_id,
            "actor_role": "admin",
            "action": action,
            "entity_type": entity_type,
            "entity_id": entity_id,
            "entity_name": entity_name,
            "details": details or {},
            "created_at": now,
        }
        ref.set(data)
        logger.debug(
            f"Audit: actor={actor_id} action={action} "
            f"entity={entity_type}/{entity_id} name={entity_name!r}"
        )
    except Exception as exc:
        # Audit failures MUST NOT crash the primary operation
        logger.error(f"Failed to write audit log: {exc}", exc_info=True)


# ---------------------------------------------------------------------------
# Read — paginated list for the admin panel
# ---------------------------------------------------------------------------

def list_audit_logs(
    skip: int = 0,
    limit: int = 50,
    entity_type: Optional[str] = None,
    action: Optional[str] = None,
) -> list[dict]:
    """
    Return audit log entries, newest first.

    Supports optional filters:
        entity_type — "bank" | "form" | "section" | "field"
        action      — "create" | "update" | "delete" | "toggle"

    Raises:
        HTTPException 400: Invalid filter values.
    """
    db = get_db()

    q = db.collection(COLL_AUDIT_LOGS).order_by("created_at", direction="DESCENDING")

    # Apply in-memory post-filters (Firestore requires composite indexes for
    # multi-field inequality queries; filtering after stream() is simpler here).
    docs = list(q.offset(skip).limit(limit).stream())

    results = []
    for doc in docs:
        data = doc.to_dict()
        # Apply filters client-side
        if entity_type and data.get("entity_type") != entity_type:
            continue
        if action and data.get("action") != action:
            continue

        created_at = data.get("created_at")
        results.append({
            "id": doc.id,
            "actor_id": data.get("actor_id"),
            "actor_role": data.get("actor_role", "admin"),
            "action": data.get("action"),
            "entity_type": data.get("entity_type"),
            "entity_id": data.get("entity_id"),
            "entity_name": data.get("entity_name"),
            "details": data.get("details", {}),
            "created_at": (
                created_at.isoformat()
                if hasattr(created_at, "isoformat")
                else str(created_at) if created_at else None
            ),
        })

    return results


def get_audit_stats() -> dict:
    """
    Return aggregate counts per action type and entity type.
    Used by the Audits tab summary cards.
    """
    db = get_db()
    docs = list(db.collection(COLL_AUDIT_LOGS).stream())

    stats = {
        "total": len(docs),
        "by_action": {},
        "by_entity": {},
    }
    for doc in docs:
        data = doc.to_dict()
        action = data.get("action", "unknown")
        entity = data.get("entity_type", "unknown")
        stats["by_action"][action] = stats["by_action"].get(action, 0) + 1
        stats["by_entity"][entity] = stats["by_entity"].get(entity, 0) + 1

    return stats
