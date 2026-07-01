# Phase 5 — Skill engine + curator Design

**Date:** 2026-07-01
**Status:** build (part of the "build the whole app per the doc" mandate)
**Scope:** Make self-authored skills **durable** (survive ephemeral containers) and add a **curator** (list / pin / retire). Natural-language authoring is the agent conversing (guided by a `skill-authoring` SKILL.md) + an `author_skill` tool that persists to Postgres, materializes to the filesystem cache, and reloads. Curated in-repo skills are untouched.

Architecture doc Phase 5: "Natural-language skill-authoring interview loop; the curator (usage tracking, retire stale, protect pinned) — the 'do almost anything via skills' doubling-down."

---

## 1. Background & the gap

- Skills are Agno `SKILL.md` files loaded by `LocalSkills(config.bott_skills_dir())`; `skills.reload()` refreshes the library at runtime with no restart (verified: `test_skill_manage.py`).
- `workspace_tools._skill_manage_impl(skills, action, name, content)` already **creates/edits SKILL.md on the filesystem + reloads** (`workspace_tools.py:51-74`).
- **The gap:** the skills dir is in-repo/ephemeral. Runtime-authored skills written only to disk are **lost on container restart** — violating "Postgres is the only datastore." And there is **no curator** (no usage/lifecycle management).

**Two kinds of skill (the load-bearing distinction):**
- **Curated** — the 7 in-repo, git-tracked `SKILL.md`s under `bott_skills_dir`. Permanent, not in the DB, never retired by the curator.
- **Authored** — created at runtime via `author_skill`. **Source of truth = a Postgres `skills` table**; materialized to `bott_skills_dir/{slug}/SKILL.md` (the FS cache Agno loads) at startup and on each author/edit. These survive restarts because they re-materialize from Postgres.

A skill is "authored" iff it has a row in the `skills` table. The curator only manages authored skills; it refuses to retire a curated built-in.

---

## 2. Decisions (locked)

- **Persistence: Option C (hybrid).** Postgres `skills` table is the source of truth for authored skills; a startup step materializes them to the FS cache; `author_skill` writes DB → FS → `reload()` so they're usable in-session immediately AND durable. Curated in-repo skills stay on disk and are never overwritten (only rows present in the DB are materialized).
- **Authoring = conversation, not a rigid state machine.** The "interview loop" is the agent asking clarifying questions in Slack (guided by a new `skill-authoring` curated SKILL.md), then calling `author_skill(name, description, instructions)` once. The tool assembles the frontmatter, so the model supplies clean fields.
- **Curator retire is explicit, never silent.** No background auto-deletion of user-authored content (matches the approval-gate philosophy). The curator *surfaces* stale skills (by age) via `list_skills`; an admin explicitly retires. Pinned skills are protected.
- **Destructive curator ops are admin-gated** (`config.bott_admins()`, actor = verified `run_context.user_id`), like the App-Home model overrides. Authoring is open to all (additive). Pinning is admin-gated (it changes shared lifecycle policy).
- **Usage telemetry MVP:** track `usage_count` + `last_used`, bumped when a skill is authored/edited (a proxy for "touched"). Precise per-*activation* tracking needs an Agno skill-activation hook that the platform doesn't currently expose — documented as a deferred enhancement; the curator's staleness heuristic is age-of-`updated` + not-pinned.

---

## 3. Schema (`shared/schema.py`) — one new table

```python
SKILLS = Table(
    "skills",
    METADATA,
    Column("slug", Text, primary_key=True),      # kebab-case; == FS dir name == frontmatter name
    Column("name", Text, nullable=False),
    Column("description", Text, nullable=False),
    Column("content", Text, nullable=False),      # the full SKILL.md text (frontmatter + body)
    Column("authored_by", Text),                  # verified user_id who authored it
    Column("pinned", Integer, nullable=False, server_default=_sql_text("0")),
    Column("usage_count", Integer, nullable=False, server_default=_sql_text("0")),
    Column("created", Float, nullable=False),
    Column("updated", Float, nullable=False),
    Column("last_used", Float),
)
```

Mirrors the existing SQLAlchemy-Core style; `init_schema()` creates it idempotently (same as the other tables). Single table — no separate usage table (YAGNI for the MVP curator).

---

## 4. Persistence layer (`shared/persistence/skills_store.py`)

Raw-SQL + `INSERT … ON CONFLICT` upsert (works on Postgres and SQLite), mirroring `records.py`:

- `upsert_skill(db, slug, name, description, content, authored_by, now) -> None` — insert or update `content/name/description/updated` (preserves `created`, `pinned`, `usage_count` on update; bumps `usage_count`, sets `last_used=now`).
- `list_skills(db) -> list[dict]` — all authored rows (slug, name, description, authored_by, pinned, usage_count, created, updated, last_used).
- `get_skill(db, slug) -> dict | None`.
- `set_pinned(db, slug, pinned: bool) -> bool` — returns False if slug absent.
- `delete_skill(db, slug) -> bool` — returns False if slug absent.
- `materialize_to_fs(db, skills_dir) -> int` — for each DB row, write `{skills_dir}/{slug}/SKILL.md` (content). Returns count. Idempotent; does not touch dirs without a DB row (curated skills safe).

---

## 5. Authoring + curator tools (`skills/skill_authoring.py`)

`skill_authoring_tools(db=None, skills=None) -> list` (wired like `scheduling_tools(db)` / `build_workspace_tools(db, skills)`; returns `[]` if `db is None`). Tools:

- **`author_skill(run_context, name, description, instructions) -> str`** — `authored_by = require_user_id(run_context.user_id)`. Slugify `name` (reuse the kebab rule). **Refuse** if the slug matches a curated in-repo skill that has no DB row (`"'{slug}' is a built-in skill — pick another name."`). Assemble content = `---\nname: {slug}\ndescription: {description}\n---\n\n{instructions}`. Validate frontmatter. `upsert_skill(...)`; write `{skills_dir}/{slug}/SKILL.md`; `skills.reload()`; confirm it loaded (like `_skill_manage_impl`). Return success.
- **`list_skills(run_context) -> str`** — union of `skills.get_skill_names()` (curated + authored on FS) annotated from the DB: mark each `[authored by X · pinned · used N · updated <age>]` or `[built-in]`. Surfaces staleness (age).
- **`pin_skill(run_context, name) -> str`** / **`unpin_skill(...)`** — admin-gated (`_require_admin(run_context)`); `set_pinned`. Refuse on unknown/built-in slug.
- **`retire_skill(run_context, name) -> str`** — admin-gated. Refuse if the skill is pinned, or if it's a built-in (no DB row). Else `delete_skill` + remove `{skills_dir}/{slug}/` + `skills.reload()`.

`_require_admin(run_context)` → actor = `require_user_id(run_context.user_id)`; if actor not in `config.bott_admins()`, the tool returns a refusal string (fails closed on blank identity). Mirrors `slack_home/models.py` admin gating.

---

## 6. Startup materialization (`interfaces/app.py`)

At startup, after `init_schema()` and before/around agent construction (next to the existing Codex bootstrap), call `skills_store.materialize_to_fs(db, config.bott_skills_dir())` so DB-authored skills are on the FS cache before `LocalSkills` loads them. Guarded (best-effort; logs count). This is what makes authored skills survive container restarts.

---

## 7. The `skill-authoring` curated SKILL.md (`skills/library/skill-authoring/SKILL.md`)

A new **curated** skill that teaches the agent HOW to run the authoring interview conversationally: when a user asks Bott to "learn"/"remember how to" do a repeatable workflow, ask a few clarifying questions (when to use it; the steps; inputs/preconditions; how to know it worked), then call `author_skill` with a clear `name`, one-line `description`, and `instructions` body. Keeps authoring natural-language and consistent.

---

## 8. Wiring (`agents/bott_agent.py`)

`tools.extend(skill_authoring_tools(db=db, skills=skills))` alongside the existing families (needs both `db` and the `skills` object, both already in scope in `build_agent`).

---

## 9. Testing

- **skills_store:** upsert then get (round-trip); upsert-again updates content + bumps usage, preserves created/pinned; `set_pinned`/`delete_skill` return False on missing; `list_skills` shape; `materialize_to_fs` writes `{slug}/SKILL.md` for DB rows and leaves non-DB dirs alone (returns count). SQLite temp db.
- **author_skill:** persists a row (DB) AND writes the FS file AND the skill appears in `skills.get_skill_names()` after reload; `authored_by` = the run_context user (not a param); blank identity fails closed; refuses to overwrite a built-in slug; bad frontmatter/empty name rejected.
- **curator:** `pin_skill`/`retire_skill` admin-gated (non-admin → refusal, nothing changes); `retire_skill` refuses a pinned skill and a built-in; a successful retire removes DB row + FS dir; `list_skills` annotates authored vs built-in + pinned.
- **durability:** `materialize_to_fs` re-creates an authored skill's SKILL.md from the DB into a fresh (empty) skills dir — proves restart-survival.
- **wiring:** `skill_authoring_tools(db, skills)` returns the tools; `[]` when `db is None`; `build_agent` includes them (no regression to existing tool count).

## 10. Files

| File | Change |
|---|---|
| `src/bott/shared/schema.py` | add `SKILLS` table |
| `src/bott/shared/persistence/skills_store.py` | **create** — upsert/list/get/pin/delete/materialize |
| `src/bott/skills/skill_authoring.py` | **create** — author_skill + curator tools + `_require_admin` |
| `src/bott/skills/library/skill-authoring/SKILL.md` | **create** — curated authoring-interview guide |
| `src/bott/interfaces/app.py` | startup `materialize_to_fs` |
| `src/bott/agents/bott_agent.py` | wire `skill_authoring_tools(db, skills)` |
| `tests/test_skills_store.py`, `tests/test_skill_authoring.py` | **create** |

## 11. Non-goals

Skill versioning/rollback; automatic (silent) retirement; per-activation usage telemetry (needs an Agno hook — deferred); tool authoring (explicitly dropped earlier). Curated in-repo skills are never mutated by this engine.
