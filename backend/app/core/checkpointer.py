"""
Persistent checkpointer for LangGraph — PostgresSaver backed by psycopg.

Gives the BankAI agent cross-restart, production-grade conversation memory.
Every ``thread_id`` (= ``user_{user_id}``) accumulates a full message
history that survives server restarts, re-deploys, and container cycling.

Configuration:
  LANGGRAPH_CHECKPOINT_DB  — explicit DSN for the checkpoint database.
                             Falls back to the main DATABASE_URL if unset.

Usage in ai_agent_service.py:
  from app.core.checkpointer import get_checkpointer
  checkpointer = get_checkpointer()          # PostgresSaver or MemorySaver
  graph = build_agent_graph().compile(checkpointer=checkpointer)

Lifecycle:
  - ``init_checkpointer()`` must be called once at application startup
    (from ``main.py`` startup event) to create the checkpoint tables
    and warm the connection.
  - ``shutdown_checkpointer()`` is called at shutdown to close the pool.
  - ``get_checkpointer()`` returns the active checkpointer instance.
    If PostgresSaver hasn't been initialised (e.g. in tests),
    falls back to an in-memory MemorySaver.
"""

from __future__ import annotations

from typing import Optional

from langgraph.checkpoint.memory import MemorySaver
from app.core.logging import get_logger

logger = get_logger()

# Module-level singleton — set by init_checkpointer()
_checkpointer: Optional[object] = None
_postgres_connection: Optional[object] = None


def _build_dsn() -> str:
    """
    Build the PostgreSQL DSN for the checkpoint database.

    Uses LANGGRAPH_CHECKPOINT_DB if set, otherwise falls back to
    DATABASE_URL.  The DSN must be in libpq/psycopg format:
        postgresql://user:pass@host:port/dbname
    """
    from app.core.config import llm_settings
    dsn = llm_settings.checkpoint_db_url
    logger.info(f"Checkpoint DSN resolved (host hidden for security)")
    return dsn


def init_checkpointer() -> None:
    """
    Initialise the PostgresSaver checkpointer.

    Creates the checkpoint tables (``checkpoints``, ``checkpoint_blobs``,
    ``checkpoint_writes``, ``checkpoint_migrations``) on first run.
    Idempotent — safe to call on every startup.

    Call this from ``main.py`` startup event BEFORE any agent invocations.
    """
    global _checkpointer, _postgres_connection

    try:
        from langgraph.checkpoint.postgres import PostgresSaver
        from psycopg import Connection

        dsn = _build_dsn()

        # Open a persistent connection with autocommit (required by setup)
        conn = Connection.connect(dsn, autocommit=True)
        _postgres_connection = conn

        checkpointer = PostgresSaver(conn)

        # Create checkpoint tables if they don't exist (idempotent)
        checkpointer.setup()

        _checkpointer = checkpointer
        logger.info(
            "PostgresSaver checkpointer initialised — "
            "persistent conversation memory enabled"
        )

    except ImportError as exc:
        logger.warning(
            f"PostgresSaver dependencies not installed ({exc}). "
            f"Falling back to in-memory MemorySaver."
        )
        _checkpointer = MemorySaver()

    except Exception as exc:
        logger.error(
            f"Failed to initialise PostgresSaver: {exc}. "
            f"Falling back to in-memory MemorySaver.",
            exc_info=True,
        )
        _checkpointer = MemorySaver()


def shutdown_checkpointer() -> None:
    """
    Close the PostgresSaver connection cleanly.

    Call this from ``main.py`` shutdown event.
    """
    global _checkpointer, _postgres_connection

    if _postgres_connection is not None:
        try:
            _postgres_connection.close()
            logger.info("PostgresSaver connection closed")
        except Exception as exc:
            logger.warning(f"Error closing PostgresSaver connection: {exc}")
        _postgres_connection = None

    _checkpointer = None


def get_checkpointer():
    """
    Return the active checkpointer instance.

    If ``init_checkpointer()`` has been called successfully, returns the
    PostgresSaver.  Otherwise returns a fresh MemorySaver (safe for tests
    and for the case where the DB is unavailable).
    """
    if _checkpointer is not None:
        return _checkpointer

    logger.warning(
        "get_checkpointer() called before init_checkpointer() — "
        "returning ephemeral MemorySaver"
    )
    return MemorySaver()
