# Phase 5 — Skill engine + curator Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development.

**Goal:** Make authored skills durable in Postgres (survive ephemeral containers) and add a curator (list / pin / retire), with natural-language authoring via a tool + a guiding SKILL.md.

**Architecture:** Postgres `skills` table is the source of truth for *authored* skills; a startup step materializes them to the `SKILL.md` FS cache Agno loads; `author_skill` writes DB→FS→`reload()`. Curated in-repo skills are never touched. Curator destructive ops are admin-gated.

**Tech Stack:** Python 3.12, SQLAlchemy Core + raw SQL (records.py style), Agno Skills, pytest.

Spec: `docs/superpowers/specs/2026-07-01-bott-skill-engine-design.md`

## Global Constraints

- **Persistence convention (CRITICAL — follow `records.py` exactly):** raw-SQL modules do NOT take a `db` object. They import `from bott.shared.db import get_engine` and open connections via `with get_engine().begin() as conn: conn.execute(text(...), {...})`. `INSERT … ON CONFLICT(slug) DO UPDATE` works on Postgres and SQLite. Read `src/bott/shared/persistence/records.py` before writing `skills_store.py` and mirror its engine access, `text()` usage, and row→dict handling. Do NOT invent a `db`-parameter API.
- **Test DB setup convention (follow `test_records.py`/`test_approvals.py`):** a fixture that does `monkeypatch.delenv("DATABASE_URL", raising=False)`, `monkeypatch.setenv("AGENTOS_DB_PATH", str(tmp_path / "x.db"))`, `db.get_engine(fresh=True)`, `schema.init_schema()`. This points the shared engine at a fresh temp SQLite and creates all METADATA tables (including the new SKILLS). Do NOT use `agno.db.sqlite.SqliteDb` for these store tests.
- **Two skill kinds:** *curated* (in-repo `SKILL.md`, no DB row — permanent, never retired) vs *authored* (has a `skills` DB row — durable, synced to FS). A skill is authored iff it has a DB row.
- **Identity/gating:** `authored_by` = `require_user_id(run_context.user_id)`, never a param. Curator `pin`/`unpin`/`retire` are admin-gated via `config.bott_admins()` (actor = verified `run_context.user_id`), fail closed on blank identity. `author_skill` is open to all but fails closed on blank identity.
- **No silent deletion:** the curator never auto-retires; `retire_skill` is explicit and refuses pinned or built-in skills.
- **Templates:** `shared/persistence/records.py` (engine + upsert), `skills/workspace_tools.py:_skill_manage_impl` (FS write + reload + frontmatter/slug rules), `skills/scheduling.py:scheduling_tools` (`@tool` closure family + `_impl` split), `interfaces/slack_home/models.py` (admin gating).
- Process: in-place on `main`, commit-only, no push, no worktree.

---

### Task 1: `skills` table + `skills_store` persistence

**Files:** Modify `src/bott/shared/schema.py`; Create `src/bott/shared/persistence/skills_store.py`; Test `tests/test_skills_store.py`.

**Interfaces produced (all use `get_engine()` internally — NO db param):**
`skills_store.upsert_skill(slug, name, description, content, authored_by, now)`, `list_skills() -> list[dict]`, `get_skill(slug) -> dict|None`, `set_pinned(slug, pinned) -> bool`, `delete_skill(slug) -> bool`, `materialize_to_fs(skills_dir) -> int`.

- [ ] **Step 1: Add the SKILLS table** to `schema.py` (after the last table), using existing imports (`Column, Float, Integer, Table, Text, _sql_text`):

```python
# Authored skills (skills_store.py owns the DML). Source of truth for runtime-authored
# skills; materialized to the SKILL.md FS cache at startup. Curated in-repo skills have NO row.
SKILLS = Table(
    "skills",
    METADATA,
    Column("slug", Text, primary_key=True),
    Column("name", Text, nullable=False),
    Column("description", Text, nullable=False),
    Column("content", Text, nullable=False),
    Column("authored_by", Text),
    Column("pinned", Integer, nullable=False, server_default=_sql_text("0")),
    Column("usage_count", Integer, nullable=False, server_default=_sql_text("0")),
    Column("created", Float, nullable=False),
    Column("updated", Float, nullable=False),
    Column("last_used", Float),
)
```

- [ ] **Step 2: Write failing tests** (`tests/test_skills_store.py`) — use the shared-engine fixture, NOT SqliteDb:

```python
import os

import pytest

from bott.shared import db, schema
from bott.shared.persistence import skills_store as store


@pytest.fixture
def dbenv(monkeypatch, tmp_path):
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.setenv("AGENTOS_DB_PATH", str(tmp_path / "s.db"))
    db.get_engine(fresh=True)
    schema.init_schema()
    yield tmp_path


def test_upsert_and_get(dbenv):
    store.upsert_skill("my-skill", "my-skill", "does a thing",
                       "---\nname: my-skill\n---\nbody", "a@x.com", now=100.0)
    row = store.get_skill("my-skill")
    assert row["slug"] == "my-skill" and row["authored_by"] == "a@x.com"
    assert row["description"] == "does a thing" and row["usage_count"] == 1


def test_upsert_updates_and_preserves(dbenv):
    store.upsert_skill("s", "s", "d1", "c1", "a@x.com", now=100.0)
    store.set_pinned("s", True)
    store.upsert_skill("s", "s", "d2", "c2", "a@x.com", now=200.0)
    row = store.get_skill("s")
    assert row["description"] == "d2" and row["content"] == "c2"
    assert row["created"] == 100.0 and row["updated"] == 200.0
    assert row["pinned"] == 1 and row["usage_count"] == 2  # preserved pin, bumped usage


def test_set_pinned_and_delete_missing_return_false(dbenv):
    assert store.set_pinned("nope", True) is False
    assert store.delete_skill("nope") is False


def test_delete_removes(dbenv):
    store.upsert_skill("s", "s", "d", "c", "a@x.com", now=1.0)
    assert store.delete_skill("s") is True
    assert store.get_skill("s") is None


def test_materialize_to_fs(dbenv):
    tmp_path = dbenv
    store.upsert_skill("s", "s", "d", "---\nname: s\ndescription: d\n---\nbody", "a@x.com", now=1.0)
    skills_dir = tmp_path / "lib"
    (skills_dir / "curated").mkdir(parents=True)
    (skills_dir / "curated" / "SKILL.md").write_text("---\nname: curated\n---\n")
    n = store.materialize_to_fs(str(skills_dir))
    assert n == 1
    assert (skills_dir / "s" / "SKILL.md").read_text().startswith("---")
    assert (skills_dir / "curated" / "SKILL.md").exists()  # non-DB dir untouched
```

- [ ] **Step 3: Run, expect fail** — `.venv/bin/python -m pytest tests/test_skills_store.py -v` → `ModuleNotFoundError: …skills_store`.

- [ ] **Step 4: Implement `src/bott/shared/persistence/skills_store.py`** — read `records.py` first; mirror its `get_engine()` + `text()` idiom. Behavior:
  - `upsert_skill(slug, name, description, content, authored_by, now)`:
    ```sql
    INSERT INTO skills (slug,name,description,content,authored_by,pinned,usage_count,created,updated,last_used)
    VALUES (:slug,:name,:description,:content,:authored_by,0,1,:now,:now,:now)
    ON CONFLICT(slug) DO UPDATE SET
      name=excluded.name, description=excluded.description, content=excluded.content,
      updated=excluded.updated, last_used=excluded.last_used,
      usage_count = skills.usage_count + 1
    ```
    (INSERT sets usage_count=1/created=now; conflict preserves created & pinned, bumps usage, updates the rest. Bind `now` once; pass as `:now`.)
  - `list_skills()`: `SELECT * FROM skills ORDER BY updated DESC` → list of dicts (use `row._mapping`).
  - `get_skill(slug)`: `SELECT * FROM skills WHERE slug=:slug` → dict or None.
  - `set_pinned(slug, pinned)`: `UPDATE skills SET pinned=:p WHERE slug=:slug`; return `result.rowcount > 0` (pinned → `1 if pinned else 0`).
  - `delete_skill(slug)`: `DELETE FROM skills WHERE slug=:slug`; return `result.rowcount > 0`.
  - `materialize_to_fs(skills_dir)`: for each `list_skills()` row, `os.makedirs(os.path.join(skills_dir, slug), exist_ok=True)` and write `content` to `{slug}/SKILL.md` (utf-8). Return the count written.

- [ ] **Step 5: Run tests green** — `.venv/bin/python -m pytest tests/test_skills_store.py -v` (5 tests). `.venv/bin/ruff check src/bott/shared/persistence/skills_store.py src/bott/shared/schema.py tests/test_skills_store.py`.

- [ ] **Step 6: Commit** — `git add … && git commit -m "feat(skills): SKILLS table + skills_store persistence (durable authored skills)"`

---

### Task 2: authoring + curator tools + the authoring SKILL.md

**Files:** Create `src/bott/skills/skill_authoring.py`; Create `src/bott/skills/library/skill-authoring/SKILL.md`; Test `tests/test_skill_authoring.py`.

**Interfaces produced:** `skill_authoring_tools(skills=None) -> list` (gated on `skills`); module-level impls `_author_skill_impl(skills, run_context, name, description, instructions)`, `_list_skills_impl(skills, run_context)`, `_pin_impl(run_context, name, pinned)`, `_retire_impl(skills, run_context, name)`, plus `_require_admin(run_context)`, `_slugify(name)`, `_is_builtin(skills, slug)`. (No `db` param — impls call `skills_store`, which uses `get_engine()`.)

- [ ] **Step 1: Write failing tests** (`tests/test_skill_authoring.py`) — reuse the shared-engine fixture:

```python
from types import SimpleNamespace

import pytest

import bott.skills.skill_authoring as sa
from bott.shared import db, schema
from bott.shared.persistence import skills_store as store


class _Skills:
    def __init__(self, names): self._names = set(names)
    def get_skill_names(self): return sorted(self._names)
    def reload(self): pass


@pytest.fixture
def dbenv(monkeypatch, tmp_path):
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.setenv("AGENTOS_DB_PATH", str(tmp_path / "s.db"))
    db.get_engine(fresh=True)
    schema.init_schema()
    monkeypatch.setattr(sa.config, "bott_skills_dir", lambda: str(tmp_path / "lib"))
    yield tmp_path


def _ctx(uid="admin@x.com"): return SimpleNamespace(user_id=uid)


def test_author_skill_persists_and_reloads(dbenv, monkeypatch):
    skills = _Skills([])
    monkeypatch.setattr(skills, "reload", lambda: skills._names.add("greet-user"))
    out = sa._author_skill_impl(skills, _ctx("a@x.com"), "Greet User", "greets a user", "Say hi.")
    assert "greet-user" in out
    row = store.get_skill("greet-user")
    assert row and row["authored_by"] == "a@x.com"
    assert (dbenv / "lib" / "greet-user" / "SKILL.md").exists()


def test_author_skill_blank_identity_fails_closed(dbenv):
    out = sa._author_skill_impl(_Skills([]), _ctx(None), "X", "d", "body")
    assert "couldn't tell who you are" in out.lower()
    assert store.get_skill("x") is None


def test_author_skill_refuses_builtin_slug(dbenv):
    skills = _Skills(["sprint-report"])  # curated built-in, no DB row
    out = sa._author_skill_impl(skills, _ctx("a@x.com"), "sprint report", "d", "body")
    assert "built-in" in out.lower()
    assert store.get_skill("sprint-report") is None


def test_author_requires_description_and_body(dbenv):
    assert "description" in sa._author_skill_impl(_Skills([]), _ctx("a@x.com"), "n", "", "b").lower()


def test_retire_admin_gated(dbenv, monkeypatch):
    monkeypatch.setattr(sa.config, "bott_admins", lambda: {"admin@x.com"})
    store.upsert_skill("s", "s", "d", "c", "a@x.com", now=1.0)
    out = sa._retire_impl(_Skills(["s"]), _ctx("notadmin@x.com"), "s")
    assert "admin" in out.lower()
    assert store.get_skill("s") is not None


def test_retire_refuses_pinned_and_builtin(dbenv, monkeypatch):
    monkeypatch.setattr(sa.config, "bott_admins", lambda: {"admin@x.com"})
    store.upsert_skill("s", "s", "d", "c", "a@x.com", now=1.0)
    store.set_pinned("s", True)
    skills = _Skills(["s", "sprint-report"])
    assert "pinned" in sa._retire_impl(skills, _ctx("admin@x.com"), "s").lower()
    assert "built-in" in sa._retire_impl(skills, _ctx("admin@x.com"), "sprint-report").lower()


def test_retire_removes_db_and_fs(dbenv, monkeypatch):
    monkeypatch.setattr(sa.config, "bott_admins", lambda: {"admin@x.com"})
    lib = dbenv / "lib"
    store.upsert_skill("s", "s", "d", "c", "a@x.com", now=1.0)
    (lib / "s").mkdir(parents=True); (lib / "s" / "SKILL.md").write_text("x")
    out = sa._retire_impl(_Skills(["s"]), _ctx("admin@x.com"), "s")
    assert "retired" in out.lower()
    assert store.get_skill("s") is None and not (lib / "s").exists()


def test_pin_admin_gated(dbenv, monkeypatch):
    monkeypatch.setattr(sa.config, "bott_admins", lambda: {"admin@x.com"})
    store.upsert_skill("s", "s", "d", "c", "a@x.com", now=1.0)
    assert "admin" in sa._pin_impl(_ctx("no@x.com"), "s", True).lower()
    assert store.get_skill("s")["pinned"] == 0


def test_tools_family_gates_on_skills():
    assert sa.skill_authoring_tools(skills=None) == []
    tools = sa.skill_authoring_tools(skills=_Skills([]))
    names = {getattr(t, "name", getattr(t, "__name__", "")) for t in tools}
    assert {"author_skill", "list_skills", "pin_skill", "unpin_skill", "retire_skill"} <= names
```

- [ ] **Step 2: Run, expect fail** — `ModuleNotFoundError: …skill_authoring`.

- [ ] **Step 3: Implement `src/bott/skills/skill_authoring.py`** — read `_skill_manage_impl`, `scheduling_tools`, and `slack_home/models.py` admin gating first. Full module:

```python
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
    if actor not in config.bott_admins():
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
            lines.append(f"- {n} [{tag} · by {r['authored_by']} · used {r['usage_count']}]")
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
```

- [ ] **Step 4: Create `src/bott/skills/library/skill-authoring/SKILL.md`**

```markdown
---
name: skill-authoring
description: How to learn a new reusable skill from the user by interviewing them, then saving it.
---

## When to use
When someone asks Bott to "learn", "remember how to", or "always do" a repeatable workflow — or when a useful multi-step routine keeps recurring.

## How to do it
Run a short, friendly interview (one or two turns) to capture:
1. **When to use it** — the trigger/situation (this becomes the description).
2. **The steps** — what Bott should do, in order, including which tools/connectors to use.
3. **Inputs / preconditions** — anything needed first (an engagement name, a channel, credentials).
4. **Done check** — how to know it worked.

Then call `author_skill` with `name` (a short title → kebab-case id), `description` (one line on when to use it), and `instructions` (the steps as a clear Markdown body). Confirm the saved skill name back. Don't ask more than a couple of questions — infer sensible defaults. Never author over a built-in skill; pick a distinct name.

## Curation
Use `list_skills` to review the library. Admins can `pin_skill` (protect) or `retire_skill` (remove) authored skills; built-ins are always kept.
```

- [ ] **Step 5: Run tests green** — `.venv/bin/python -m pytest tests/test_skill_authoring.py -v` (9 tests). Ruff the module + test.

- [ ] **Step 6: Commit** — `git commit -m "feat(skills): NL author_skill + curator (list/pin/retire) + authoring SKILL.md"`

---

### Task 3: startup materialization + agent wiring

**Files:** Modify `src/bott/interfaces/app.py`; Modify `src/bott/agents/bott_agent.py`; Test `tests/test_skill_engine_wiring.py`.

- [ ] **Step 1: Write failing tests** (`tests/test_skill_engine_wiring.py`)

```python
import pytest

from bott.shared import db, schema
from bott.shared.persistence import skills_store as store


@pytest.fixture
def dbenv(monkeypatch, tmp_path):
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.setenv("AGENTOS_DB_PATH", str(tmp_path / "s.db"))
    db.get_engine(fresh=True)
    schema.init_schema()
    yield tmp_path


def test_build_agent_includes_skill_authoring(dbenv, monkeypatch):
    monkeypatch.setattr("bott.shared.config.bott_skills_dir", lambda: str(dbenv / "lib"))
    import bott.agents.bott_agent as ba
    agent = ba.build_agent("alice@axelerant.com", db=None)
    names = {getattr(t, "name", getattr(t, "__name__", "")) for t in agent.tools}
    assert {"author_skill", "list_skills", "retire_skill"} <= names


def test_materialize_on_empty_db_is_noop(dbenv):
    assert store.materialize_to_fs(str(dbenv / "lib")) == 0
```

Note: `build_agent`'s `db` param feeds session_search/scheduling; the skill-authoring family only needs the `skills` object, so `db=None` is fine for this wiring assertion. If `agent.tools` isn't the exposed attribute on the constructed Agno `Agent`, inspect the object and adapt the assertion to how tools are listed — the goal is proving the family is wired.

- [ ] **Step 2: Run, expect fail** — `author_skill` not among the agent's tools.

- [ ] **Step 3: Wire in `bott_agent.py`** — add `from bott.skills.skill_authoring import skill_authoring_tools` (top imports) and, in `build_agent` right after the `build_workspace_tools(...)` line:
```python
    tools.extend(skill_authoring_tools(skills=skills))
```
(`skills` is built via `build_skills()` earlier in `build_agent`.)

- [ ] **Step 4: Startup materialization in `app.py`** — read the startup block first (where `init_schema()` / the Codex `bootstrap_from_local` run, before `build_bott_agent`). Match the surrounding variable/logger names. Add, guarded, AFTER schema init and BEFORE the agent is built:
```python
    try:
        from bott.shared.persistence import skills_store
        _n = skills_store.materialize_to_fs(config.bott_skills_dir())
        log.info("materialized %d authored skill(s) from DB", _n)
    except Exception as e:  # noqa: BLE001
        log.warning("skill materialize skipped: %s", e)
```
(If the module's logger is named differently, use that; if `config` isn't imported there, import it.)

- [ ] **Step 5: Run tests + full suite** — `.venv/bin/python -m pytest tests/test_skill_engine_wiring.py tests/test_skill_authoring.py tests/test_skills_store.py -v`, then `.venv/bin/python -m pytest -q` (expect prior 418 + 5 + 9 + 2 = 434 passed / 2 skipped — report ACTUAL; investigate if materially off). Ruff `src/bott/skills/skill_authoring.py src/bott/agents/bott_agent.py src/bott/interfaces/app.py`.

- [ ] **Step 6: Commit** — `git commit -m "feat(skills): wire skill-authoring family + startup DB→FS materialization"`

---

## Self-Review

- Spec coverage: schema §3 → T1; store §4 → T1; tools §5 → T2; authoring SKILL.md §7 → T2; startup §6 → T3; wiring §8 → T3; tests §9 across all three. ✓
- Persistence convention corrected: `skills_store` uses `get_engine()` (no db param); tests use the `AGENTOS_DB_PATH` + `get_engine(fresh=True)` + `init_schema()` fixture (matches records/approvals tests). ✓
- Decisions honored: Option C (materialize + author DB→FS→reload); admin-gated pin/retire; authoring open + fail-closed; built-in protection; no silent deletion. ✓
- Placeholders: full code for schema, store behavior (with SQL), tools, SKILL.md, and all tests; app.py step points at a real integration site with an explicit guard and a note to match local names. ✓
- Type consistency: `skills_store` and `skill_authoring` signatures/names match across tasks, spec, and tests (no db param anywhere). ✓
