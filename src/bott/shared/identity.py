"""Structural isolation guard. Every run MUST carry a verified user_id; a missing one
raises rather than silently joining a shared user_id=NULL bucket (the #1 multi-user bleed)."""

from __future__ import annotations


class IsolationError(RuntimeError):
    """Raised when a run lacks the verified user_id required for isolation."""


def require_user_id(user_id: str | None) -> str:
    if not user_id or not str(user_id).strip():
        raise IsolationError("Refusing to run without a verified user_id (isolation guard).")
    return str(user_id).strip()
