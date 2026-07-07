"""Fairness for the shared Codex login: an org-wide concurrency cap, plus a smaller
per-user cap so one heavy user can't claim every concurrent slot."""

from __future__ import annotations

import asyncio
import threading
import time

import pytest

from bott.shared import codex_concurrency as cc


@pytest.fixture(autouse=True)
def _reset(monkeypatch):
    cc.reset_for_tests()
    yield
    cc.reset_for_tests()


def test_global_cap_serializes_beyond_the_limit(monkeypatch):
    monkeypatch.setattr(cc, "codex_max_concurrent_requests", lambda: 1)
    monkeypatch.setattr(cc, "codex_max_concurrent_per_user", lambda: 5)
    in_flight = []
    max_seen = 0
    lock = threading.Lock()

    def worker():
        nonlocal max_seen
        with cc.acquire_sync(None):
            with lock:
                in_flight.append(1)
                max_seen = max(max_seen, len(in_flight))
            time.sleep(0.05)
            with lock:
                in_flight.pop()

    threads = [threading.Thread(target=worker) for _ in range(5)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=2)

    assert max_seen == 1, f"expected at most 1 concurrent holder, saw {max_seen}"


def test_global_cap_allows_up_to_the_configured_count(monkeypatch):
    monkeypatch.setattr(cc, "codex_max_concurrent_requests", lambda: 3)
    monkeypatch.setattr(cc, "codex_max_concurrent_per_user", lambda: 10)
    barrier = threading.Barrier(3, timeout=2)

    def worker():
        with cc.acquire_sync(None):
            barrier.wait()  # only reachable if all 3 got in concurrently

    threads = [threading.Thread(target=worker) for _ in range(3)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=2)
    assert all(not t.is_alive() for t in threads)


def test_per_user_cap_limits_one_user_even_under_global_headroom(monkeypatch):
    """A single user hitting their own cap must wait even though the org-wide cap has
    plenty of headroom left — this is what stops one heavy user from starving everyone."""
    monkeypatch.setattr(cc, "codex_max_concurrent_requests", lambda: 10)
    monkeypatch.setattr(cc, "codex_max_concurrent_per_user", lambda: 1)
    max_seen = 0
    in_flight = []
    lock = threading.Lock()

    def worker():
        nonlocal max_seen
        with cc.acquire_sync("U_HEAVY"):
            with lock:
                in_flight.append(1)
                max_seen = max(max_seen, len(in_flight))
            time.sleep(0.05)
            with lock:
                in_flight.pop()

    threads = [threading.Thread(target=worker) for _ in range(4)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=2)
    assert max_seen == 1


def test_different_users_do_not_block_each_other(monkeypatch):
    """Two different users, each capped at 1, must still be able to run CONCURRENTLY with
    each other (the per-user cap isolates users, it doesn't serialize everyone globally)."""
    monkeypatch.setattr(cc, "codex_max_concurrent_requests", lambda: 10)
    monkeypatch.setattr(cc, "codex_max_concurrent_per_user", lambda: 1)
    barrier = threading.Barrier(2, timeout=2)

    def worker(user_id):
        with cc.acquire_sync(user_id):
            barrier.wait()  # only reachable if both users' calls run concurrently

    t1 = threading.Thread(target=worker, args=("U_ALICE",))
    t2 = threading.Thread(target=worker, args=("U_BOB",))
    t1.start()
    t2.start()
    t1.join(timeout=2)
    t2.join(timeout=2)
    assert not t1.is_alive() and not t2.is_alive()


def test_no_user_id_only_applies_the_global_cap(monkeypatch):
    monkeypatch.setattr(cc, "codex_max_concurrent_requests", lambda: 2)
    monkeypatch.setattr(cc, "codex_max_concurrent_per_user", lambda: 1)
    with cc.acquire_sync(None):
        with cc.acquire_sync(None):
            pass  # must not deadlock — global cap of 2 covers both, no user_id to gate on


# ---- async equivalents --------------------------------------------------------------------

def test_async_global_cap_serializes_beyond_the_limit(monkeypatch):
    monkeypatch.setattr(cc, "codex_max_concurrent_requests", lambda: 1)
    monkeypatch.setattr(cc, "codex_max_concurrent_per_user", lambda: 5)

    async def run():
        in_flight = []
        max_seen = 0

        async def worker():
            nonlocal max_seen
            async with cc.acquire_async(None):
                in_flight.append(1)
                max_seen = max(max_seen, len(in_flight))
                await asyncio.sleep(0.05)
                in_flight.pop()

        await asyncio.gather(*(worker() for _ in range(5)))
        return max_seen

    assert asyncio.run(run()) == 1


def test_async_per_user_cap_isolates_users(monkeypatch):
    monkeypatch.setattr(cc, "codex_max_concurrent_requests", lambda: 10)
    monkeypatch.setattr(cc, "codex_max_concurrent_per_user", lambda: 1)

    async def run():
        started = asyncio.Event()
        released = asyncio.Event()

        async def hold():
            async with cc.acquire_async("U_ALICE"):
                started.set()
                await released.wait()

        async def other():
            await started.wait()
            async with cc.acquire_async("U_BOB"):
                return "ran"

        holder = asyncio.create_task(hold())
        result = await asyncio.wait_for(other(), timeout=1)
        released.set()
        await holder
        return result

    assert asyncio.run(run()) == "ran"
