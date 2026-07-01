"""Natural-language skill authoring + curator. Authored skills are durable (skills_store →
Postgres) and materialized to the SKILL.md FS cache; curated in-repo skills are never touched."""

from __future__ import annotations

import os
import re
import shutil
import time
from typing import Callable

from agno.run import RunContext
from agno.tools import tool

from bott.shared import config
from bott.shared.identity import IsolationError, require_user_id
from bott.shared.observability.logging_setup import get_logger
from bott.shared.persistence import skills_store as store

log = get_logger("bott.skills.authoring")


def _slugify(name: str) -> str:
    return re.sub(r"[^a-z0-9-]", "-", (name or "").strip().lower()).strip("-")


def _require_admin(run_context) -> str | None:
    try:
        actor = require_user_id(getattr(run_context, "user_id", None))
    except IsolationError:
        return "I couldn't tell who you are."
    if actor.lower() not in config.bott_admins():
        return "Only an admin can manage the skill library."
    return None


def _is_builtin(skills, slug: str) -> bool:
    """Present in the loaded library but with NO DB row => curated built-in."""
    return slug in set(skills.get_skill_names()) and store.get_skill(slug) is None


def _author_skill_impl(skills, run_context, name, description, instructions) -> str:
    try:
        author = require_user_id(getattr(run_context, "user_id", None))
    except IsolationError:
        return "I couldn't tell who you are, so I won't author a skill."
    slug = _slugify(name)
    if not slug:
        return "A skill needs a kebab-case name."
    if not (description or "").strip() or not (instructions or "").strip():
        return "A skill needs a one-line description and an instructions body."
    if _is_builtin(skills, slug):
        return f"'{slug}' is a built-in skill — pick another name."
    content = f"---\nname: {slug}\ndescription: {description.strip()}\n---\n\n{instructions.strip()}\n"
    store.upsert_skill(slug, slug, description.strip(), content, author, now=time.time())
    skill_dir = os.path.join(config.bott_skills_dir(), slug)
    os.makedirs(skill_dir, exist_ok=True)
    with open(os.path.join(skill_dir, "SKILL.md"), "w", encoding="utf-8") as f:
        f.write(content)
    try:
        skills.reload()
    except Exception as e:  # noqa: BLE001
        return f"Saved '{slug}' (durable) but reload failed ({e}); it'll load next restart."
    if slug not in skills.get_skill_names():
        return f"Saved '{slug}' but it didn't load — check the description."
    return f"Authored skill '{slug}'. It's available now and will persist."


def _list_skills_impl(skills, run_context) -> str:
    names = skills.get_skill_names()
    if not names:
        return "No skills yet."
    rows = {r["slug"]: r for r in store.list_skills()}
    lines = []
    for n in names:
        r = rows.get(n)
        if r:
            tag = "pinned" if r["pinned"] else "authored"
            lines.append(f"- {n} [{tag} · by {r['authored_by'] or 'unknown'} · used {r['usage_count']}]")
        else:
            lines.append(f"- {n} [built-in]")
    return "Skills:\n" + "\n".join(lines)


def _pin_impl(run_context, slug, pinned) -> str:
    gate = _require_admin(run_context)
    if gate:
        return gate
    slug = _slugify(slug)
    if not store.set_pinned(slug, pinned):
        return f"No authored skill '{slug}' (built-in skills are always kept)."
    return f"{'Pinned' if pinned else 'Unpinned'} '{slug}'."


def _retire_impl(skills, run_context, slug) -> str:
    gate = _require_admin(run_context)
    if gate:
        return gate
    slug = _slugify(slug)
    if _is_builtin(skills, slug):
        return f"'{slug}' is a built-in skill and can't be retired."
    row = store.get_skill(slug)
    if not row:
        return f"No skill '{slug}'."
    if row["pinned"]:
        return f"'{slug}' is pinned — unpin it first."
    store.delete_skill(slug)
    shutil.rmtree(os.path.join(config.bott_skills_dir(), slug), ignore_errors=True)
    try:
        skills.reload()
    except Exception:  # noqa: BLE001
        pass
    return f"Retired '{slug}'."


def skill_authoring_tools(skills=None) -> list[Callable]:
    if skills is None:
        return []

    @tool(name="author_skill")
    def author_skill(run_context: RunContext, name: str, description: str, instructions: str) -> str:
        """Teach Bott a new reusable skill. `name`: short title; `description`: one line on when
        to use it; `instructions`: the step-by-step body. Persists durably and loads immediately."""
        return _author_skill_impl(skills, run_context, name, description, instructions)

    @tool(name="list_skills")
    def list_skills(run_context: RunContext) -> str:
        """List all skills (built-in and authored) with author/pin/usage annotations."""
        return _list_skills_impl(skills, run_context)

    @tool(name="pin_skill")
    def pin_skill(run_context: RunContext, name: str) -> str:
        """Protect an authored skill from retirement (admin only)."""
        return _pin_impl(run_context, name, True)

    @tool(name="unpin_skill")
    def unpin_skill(run_context: RunContext, name: str) -> str:
        """Remove pin protection from an authored skill (admin only)."""
        return _pin_impl(run_context, name, False)

    @tool(name="retire_skill")
    def retire_skill(run_context: RunContext, name: str) -> str:
        """Retire (delete) an authored skill (admin only; refuses pinned/built-in)."""
        return _retire_impl(skills, run_context, name)

    return [author_skill, list_skills, pin_skill, unpin_skill, retire_skill]
