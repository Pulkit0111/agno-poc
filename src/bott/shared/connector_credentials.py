# src/bott/shared/connector_credentials.py
"""Console-added connector credentials — one encrypted JSON bundle per connector NAME,
stored in the SAME ``connector_tokens`` table ``codex_tokens.py`` uses, but under a
DIFFERENT sentinel ``user_id`` (``'connector-config'`` vs codex's ``'codex-org'``) so the
two can never collide, be listed together, or be deleted by each other's code path.

Mirrors ``codex_tokens.py``'s encrypt/store/load pattern (same ``SecretBox`` Fernet
helper, same upsert-via-delete-then-insert on the ``(user_id, provider)`` primary key).

``store(name, payload)`` / ``load(name)`` / ``remove(name)`` / ``configured_names()`` are
the whole surface. Names are case-insensitive slugs (``'github-app'``, ``'sentry-<org>'``,
``'http-<slug>'`` by the console router's convention) — this module itself is agnostic to
that convention and just stores whatever dict it's given under whatever name it's given.

**Live, no restart, for anything that reads it per-request.** ``config.py``'s
``github_app_credentials()`` / ``sentry_org_credentials()`` call ``load()`` on every
invocation, so an admin adding or removing a connector here from the console takes effect
on the very next request. The caveat (same as retiring a skill): anything captured ONCE
at agent/tool-registry BUILD time — e.g. a tool object constructed from env at process
start and held in a long-lived list — will not see the change until that registry is
rebuilt (today: a process restart). Nothing in this module needs that; whether a given
*consumer* of these credentials needs it depends on how that consumer reads them.

Read paths (``load``, ``configured_names``) are deliberately defensive: a missing
``connector_tokens`` table (fresh install, migrations not yet run, a test DB with no
schema) is treated as "nothing stored" rather than raised — these functions sit behind
config accessors called from many hot paths that must never crash on a passive overlay
check. Write paths (``store``, ``remove``) are NOT defensive — they're explicit admin
actions gated by a real console endpoint; a DB error there should surface loudly.
"""

from __future__ import annotations

import json
import time
from typing import Optional

from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from bott.shared.db import get_engine
from bott.shared.observability.logging_setup import get_logger
from bott.shared.secrets import SecretBox

log = get_logger("bott.connector_credentials")

_CONFIG_USER = "connector-config"


def _key(name: str) -> str:
    return (name or "").strip().lower()


def store(name: str, payload: dict) -> None:
    """Encrypt and upsert ``payload`` under ``provider=name`` (case-insensitive). Overwrites
    any existing bundle for this name."""
    key = _key(name)
    if not key:
        raise ValueError("connector name is required")
    ciphertext = SecretBox.from_env().encrypt(json.dumps(payload))
    with get_engine().begin() as c:
        c.execute(text("DELETE FROM connector_tokens WHERE user_id=:u AND provider=:p"),
                  {"u": _CONFIG_USER, "p": key})
        c.execute(text("INSERT INTO connector_tokens(user_id,provider,token,created) "
                       "VALUES (:u,:p,:t,:c)"),
                  {"u": _CONFIG_USER, "p": key, "t": ciphertext, "c": time.time()})


def load(name: str) -> Optional[dict]:
    """The stored bundle for ``name``, or ``None`` if nothing's stored (including when the
    underlying table doesn't exist yet — see module docstring)."""
    key = _key(name)
    if not key:
        return None
    try:
        with get_engine().connect() as c:
            row = c.execute(text(
                "SELECT token FROM connector_tokens WHERE user_id=:u AND provider=:p"
            ), {"u": _CONFIG_USER, "p": key}).fetchone()
    except DBAPIError:
        log.warning("connector_credentials.load(%r): connector_tokens table unavailable", key, exc_info=True)
        return None
    if not row:
        return None
    return json.loads(SecretBox.from_env().decrypt(row[0]))


def remove(name: str) -> None:
    """Delete the stored bundle for ``name``, if any. A no-op for an unknown name."""
    key = _key(name)
    if not key:
        return
    with get_engine().begin() as c:
        c.execute(text("DELETE FROM connector_tokens WHERE user_id=:u AND provider=:p"),
                  {"u": _CONFIG_USER, "p": key})


def configured_names() -> list[str]:
    """All connector names currently stored via the console, sorted. Never raises — see
    module docstring on why the read path is defensive."""
    try:
        with get_engine().connect() as c:
            rows = c.execute(text(
                "SELECT provider FROM connector_tokens WHERE user_id=:u ORDER BY provider"
            ), {"u": _CONFIG_USER}).fetchall()
    except DBAPIError:
        log.warning("connector_credentials.configured_names(): connector_tokens table unavailable", exc_info=True)
        return []
    return [r[0] for r in rows]
