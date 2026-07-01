# CodexModel Gateway Final Fix Wave Report

**Date:** 2026-07-01
**Branch:** main (in-place)

---

## Fixes Applied

### A — Refactored codex_model.py — seedable constructor
Added `make_codex_model(model_id, access_token, account_id, **overrides)` that builds a CodexModel seeded with an already-fetched token (does NOT call `get_valid_token` itself). Updated `build_codex_model` to delegate to `make_codex_model` after fetching the token.
- File: `src/bott/shared/codex_model.py`

### B — Repointed build_model's codex branch to return CodexModel
`src/bott/shared/model.py` now imports `make_codex_model` from `codex_model` and calls it with the token fetched via `model.get_valid_token` (module-level). The test patch-point (`monkeypatch.setattr(model_mod, "get_valid_token", …)` in `test_model_gateway.py` + the autouse conftest stub on `_model_mod.get_valid_token`) still takes effect correctly. Removed now-unused `codex_backend_base_url` import (ruff F401).

**Patch-point verification**: `test_codex_provider_builds_adapter` and all gateway tests passed after the repoint — the monkeypatch on `model_mod.get_valid_token` intercepted the call before `make_codex_model` was invoked.
- File: `src/bott/shared/model.py`

### C — Regression test — tests/test_codex_model.py (new file)
Two tests:
- `test_codex_model_reresolves_token_on_rotation`: seeds model with tok-A, patches `cm.get_valid_token` to return tok-B, calls `_refresh_if_rotated()`, asserts `api_key == "tok-B"` and `client is None`.
- `test_codex_model_no_invalidation_when_token_stable`: verifies cached client is NOT invalidated when token is unchanged.
- File: `tests/test_codex_model.py`

### D — use_json_mode on codex review agent
Imported `model_provider` from config; changed `use_json_mode=use_json_mode` to `use_json_mode=(use_json_mode or model_provider() == "codex")`. CLI override still works.
- File: `src/bott/agents/code_review/core/runner.py`

### E — Minors
- `codex_tokens.py` `bootstrap_from_local`: replaced bare `json.load(open(p))` with `with open(p, encoding="utf-8") as f: data = json.load(f)`.
- `tests/test_codex_tokens.py` PG concurrency test: added `assert ct._load_bundle()["refresh_token"] == "rt-new"`.

---

## Test Results

| Check | Result |
|---|---|
| Targeted tests (4 files, -v) | 18 passed, 1 skipped (PG needs TEST_DATABASE_URL) |
| Full suite `pytest -q` | **365 passed, 2 skipped** (was 363; +2 new codex_model tests) |
| `ruff check src tests scripts` | **All checks passed!** |
| App construct (openrouter) | **ok True** (bare codex path requires live DB+token — same as before) |

## Patch-Point Status

The conftest autouse fixture patches `_model_mod.get_valid_token`; individual gateway tests patch `model_mod.get_valid_token`. Both continue to intercept the call in `build_model` before `make_codex_model` is invoked — no test was broken by the repoint.

## Deferred

Nothing deferred. All items A–E completed and verified.
