"""Durable persistence for runtime-authored skills.

All functions use ``get_engine()`` internally — no db param.  Source of truth
is the ``skills`` table; ``materialize_to_fs`` syncs it to the SKILL.md cache.
"""

from __future__ import annotations

import os

from sqlalchemy import text

from bott.shared.db import get_engine


def upsert_skill(
    slug: str,
    name: str,
    description: str,
    content: str,
    authored_by: str | None,
    now: float,
) -> None:
    """Insert or update a skill row.

    On conflict (same slug): preserves ``created`` and ``pinned``, bumps
    ``usage_count`` by 1, and updates name/description/content/updated/last_used.
    """
    with get_engine().begin() as conn:
        conn.execute(
            text(
                "INSERT INTO skills "
                "(slug, name, description, content, authored_by, pinned, usage_count, created, updated, last_used) "
                "VALUES (:slug, :name, :description, :content, :authored_by, 0, 1, :now, :now, :now) "
                "ON CONFLICT(slug) DO UPDATE SET "
                "  name = excluded.name, "
                "  description = excluded.description, "
                "  content = excluded.content, "
                "  updated = excluded.updated, "
                "  last_used = excluded.last_used, "
                "  usage_count = skills.usage_count + 1"
            ),
            {
                "slug": slug,
                "name": name,
                "description": description,
                "content": content,
                "authored_by": authored_by,
                "now": now,
            },
        )


def list_skills() -> list[dict]:
    """Return all skill rows ordered by updated desc."""
    with get_engine().begin() as conn:
        rows = conn.execute(
            text("SELECT * FROM skills ORDER BY updated DESC")
        ).fetchall()
    return [dict(row._mapping) for row in rows]


def get_skill(slug: str) -> dict | None:
    """Return the skill row for *slug*, or None if absent."""
    with get_engine().begin() as conn:
        row = conn.execute(
            text("SELECT * FROM skills WHERE slug = :slug"),
            {"slug": slug},
        ).fetchone()
    if row is None:
        return None
    return dict(row._mapping)


def set_pinned(slug: str, pinned: bool) -> bool:
    """Set the pinned flag for *slug*. Returns True if the row existed, False otherwise."""
    with get_engine().begin() as conn:
        result = conn.execute(
            text("UPDATE skills SET pinned = :p WHERE slug = :slug"),
            {"p": 1 if pinned else 0, "slug": slug},
        )
    return result.rowcount > 0


def delete_skill(slug: str) -> bool:
    """Delete *slug*. Returns True if a row was deleted, False if absent."""
    with get_engine().begin() as conn:
        result = conn.execute(
            text("DELETE FROM skills WHERE slug = :slug"),
            {"slug": slug},
        )
    return result.rowcount > 0


def materialize_to_fs(skills_dir: str) -> int:
    """Write each DB skill to ``{skills_dir}/{slug}/SKILL.md`` (utf-8).

    Only DB-backed skills are written; existing directories not corresponding
    to a DB skill are left untouched.  Returns the number of files written.
    """
    rows = list_skills()
    count = 0
    for row in rows:
        slug = row["slug"]
        dest_dir = os.path.join(skills_dir, slug)
        os.makedirs(dest_dir, exist_ok=True)
        dest_file = os.path.join(dest_dir, "SKILL.md")
        with open(dest_file, "w", encoding="utf-8") as fh:
            fh.write(row["content"])
        count += 1
    return count
