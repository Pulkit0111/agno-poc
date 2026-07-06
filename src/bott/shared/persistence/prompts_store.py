"""Versioned prompt store (IDENTITY/VOICE) — append-only, mirrors skills_store.py's
convention exactly: get_engine() internally, no injected db, raw SQL via text()."""

from __future__ import annotations

from sqlalchemy import text

from bott.shared.db import get_engine


def save_version(prompt_name: str, content: str, note: str, author: str, now: float) -> int:
    with get_engine().begin() as c:
        res = c.execute(text(
            "INSERT INTO prompt_versions(prompt_name, content, note, author, created) "
            "VALUES (:n, :c, :note, :a, :t) RETURNING id"
        ), {"n": prompt_name, "c": content, "note": note, "a": author, "t": now})
        return int(res.fetchone()[0])


def latest(prompt_name: str) -> dict | None:
    with get_engine().connect() as c:
        row = c.execute(text(
            "SELECT id, prompt_name, content, note, author, created FROM prompt_versions "
            "WHERE prompt_name=:n ORDER BY id DESC LIMIT 1"
        ), {"n": prompt_name}).fetchone()
    return dict(row._mapping) if row else None


def list_versions(prompt_name: str, limit: int = 20) -> list[dict]:
    with get_engine().connect() as c:
        rows = c.execute(text(
            "SELECT id, prompt_name, content, note, author, created FROM prompt_versions "
            "WHERE prompt_name=:n ORDER BY id DESC LIMIT :lim"
        ), {"n": prompt_name, "lim": limit}).fetchall()
    return [dict(r._mapping) for r in rows]


def get_version(version_id: int) -> dict | None:
    with get_engine().connect() as c:
        row = c.execute(text(
            "SELECT id, prompt_name, content, note, author, created FROM prompt_versions "
            "WHERE id=:id"
        ), {"id": version_id}).fetchone()
    return dict(row._mapping) if row else None
