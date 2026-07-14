"""
LangGraph Checkpointer — Firestore-backed conversation memory.

For production persistence the agent uses langgraph's MemorySaver by default
(in-process, restarts lose history). For true cross-restart persistence a
custom FirestoreCheckpointer can be plugged in here later.

Lifecycle (called from main.py):
  init_checkpointer()  — call at startup
  get_checkpointer()   — called by ai_agent_service to build the agent graph
  shutdown_checkpointer() — call at shutdown
"""

from __future__ import annotations

from typing import Optional

from langgraph.checkpoint.memory import MemorySaver
from app.core.logging import get_logger

logger = get_logger()

# Module-level singleton
_checkpointer: Optional[object] = None


def init_checkpointer() -> None:
    """
    Initialize the checkpointer.

    Currently uses MemorySaver (in-process). If you want cross-restart
    persistence via Firestore, swap in a custom FirestoreCheckpointer here.
    """
    global _checkpointer
    _checkpointer = MemorySaver()
    logger.info(
        "Checkpointer initialised — using MemorySaver "
        "(in-process; conversations reset on restart)"
    )


def shutdown_checkpointer() -> None:
    """Release the checkpointer on application shutdown."""
    global _checkpointer
    _checkpointer = None
    logger.info("Checkpointer shut down")


def get_checkpointer():
    """
    Return the active checkpointer.

    If init_checkpointer() has not been called (e.g. in tests),
    returns a fresh MemorySaver so the agent can still function.
    """
    if _checkpointer is not None:
        return _checkpointer

    logger.warning(
        "get_checkpointer() called before init_checkpointer() — "
        "returning ephemeral MemorySaver"
    )
    return MemorySaver()
