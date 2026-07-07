"""Fairness for the ONE shared Codex (ChatGPT) login: an org-wide concurrency cap, plus a
smaller per-user cap so a single heavy user can't claim every concurrent slot.

Without this, a burst of concurrent Slack messages from different users — or one user
firing off many requests at once — hits the shared backend simultaneously and 429s
everyone, since there is exactly one account's rate-limit pool to go around. Callers that
exceed a cap simply wait for a slot to free (Slack's own ack already returns immediately;
this only delays how soon the actual reply lands, not whether the request is accepted).

Semaphores are process-wide singletons, sized once from config at first use — recreating
them per-call would reset the "how many are in flight" count and defeat the point.
"""

from __future__ import annotations

import asyncio
import threading
from contextlib import asynccontextmanager, contextmanager
from typing import Optional

from bott.shared.config import codex_max_concurrent_per_user, codex_max_concurrent_requests

_global_sync_sem: Optional[threading.Semaphore] = None
_global_async_sem: Optional[asyncio.Semaphore] = None
_user_sync_sems: dict[str, threading.Semaphore] = {}
_user_async_sems: dict[str, asyncio.Semaphore] = {}
_lock = threading.Lock()


def _global_sync() -> threading.Semaphore:
    global _global_sync_sem
    with _lock:
        if _global_sync_sem is None:
            _global_sync_sem = threading.Semaphore(codex_max_concurrent_requests())
        return _global_sync_sem


def _global_async() -> asyncio.Semaphore:
    global _global_async_sem
    with _lock:
        if _global_async_sem is None:
            _global_async_sem = asyncio.Semaphore(codex_max_concurrent_requests())
        return _global_async_sem


def _user_sync(user_id: str) -> threading.Semaphore:
    with _lock:
        sem = _user_sync_sems.get(user_id)
        if sem is None:
            sem = threading.Semaphore(codex_max_concurrent_per_user())
            _user_sync_sems[user_id] = sem
        return sem


def _user_async(user_id: str) -> asyncio.Semaphore:
    with _lock:
        sem = _user_async_sems.get(user_id)
        if sem is None:
            sem = asyncio.Semaphore(codex_max_concurrent_per_user())
            _user_async_sems[user_id] = sem
        return sem


def reset_for_tests() -> None:
    """Test-only: drop all cached semaphores so the next acquire re-reads config."""
    global _global_sync_sem, _global_async_sem
    with _lock:
        _global_sync_sem = None
        _global_async_sem = None
        _user_sync_sems.clear()
        _user_async_sems.clear()


@contextmanager
def acquire_sync(user_id: Optional[str]):
    """Block until under both the org-wide and (if user_id is known) per-user cap."""
    _global_sync().acquire()
    user_sem = _user_sync(user_id) if user_id else None
    if user_sem is not None:
        user_sem.acquire()
    try:
        yield
    finally:
        if user_sem is not None:
            user_sem.release()
        _global_sync().release()


@asynccontextmanager
async def acquire_async(user_id: Optional[str]):
    """Async equivalent of acquire_sync — same two caps, non-blocking for other tasks."""
    await _global_async().acquire()
    user_sem = _user_async(user_id) if user_id else None
    if user_sem is not None:
        await user_sem.acquire()
    try:
        yield
    finally:
        if user_sem is not None:
            user_sem.release()
        _global_async().release()
