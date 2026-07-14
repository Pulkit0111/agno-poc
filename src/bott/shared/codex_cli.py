"""Subprocess bridge to the official `codex` CLI binary (`codex exec`).

Used for the `build`/`review` roles, which need Codex's OWN agentic loop (shell + file
tools running inside its own sandbox against a repo checkout) — something the direct
Responses-API adapter (codex_model.py) cannot offer, since that path exists specifically
so Agno's tool-calling protocol stays in control for the `chat` role. Spawning the real,
officially-distributed binary also means every request has the same shape/telemetry as a
human running the CLI interactively — materially lower ban-risk on the shared org
subscription than hand-built calls to the undocumented Responses backend.

CRITICAL: the org refresh token is single-use and rotates on every refresh (see
codex_tokens.py). If the CLI subprocess ever refreshes it independently, the rotated token
lands ONLY in this call's scratch CODEX_HOME — never reconciling it back into bott's
Postgres-backed store would silently invalidate the org connection on the next refresh
(the old refresh_token bott still holds would already be consumed). `_read_back_rotation`
detects and persists that case.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from typing import Callable, Optional

from bott.shared import codex_tokens, config
from bott.shared.observability.logging_setup import get_logger, redact

log = get_logger("bott.codex_cli")

_TOKENS_USED_RE = re.compile(r"tokens\s*used\s*[:=]\s*(\d+)", re.IGNORECASE)
_VALID_SANDBOXES = ("read-only", "workspace-write")

SubprocessRunner = Callable[..., subprocess.CompletedProcess]


class CodexCliError(RuntimeError):
    pass


@dataclass
class CodexExecResult:
    text: str
    data: Optional[dict]
    tokens_used: int


def _write_auth_json(codex_home: str, access_token: str, refresh_token: str, account_id: str) -> str:
    os.makedirs(codex_home, exist_ok=True)
    path = os.path.join(codex_home, "auth.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump({"tokens": {"access_token": access_token,
                              "refresh_token": refresh_token,
                              "account_id": account_id}}, f)
    os.chmod(path, 0o600)
    return path


# The subprocess must NOT inherit bott's full environment. The build/review roles feed
# UNTRUSTED content (PR diffs, issue text) to a model that runs shell commands inside this
# process's child; the whole os.environ would hand that model every bott secret —
# BOTT_SECRET_KEY (decrypts the org token store), DATABASE_URL, GITHUB_APP_PRIVATE_KEY,
# JIRA_API_TOKEN, OPENROUTER_API_KEY, SLACK_BOT_TOKEN, ... — one `printenv` away from
# exfiltration via the review output. So we pass a MINIMAL, allowlisted env: only what the
# CLI genuinely needs to run (its scratch CODEX_HOME, a PATH to find node/itself, HOME, and
# a handful of locale/proxy/TLS vars that only matter when actually set).
_ENV_PASSTHROUGH = (
    "LANG", "LC_ALL", "LC_CTYPE", "TERM", "TMPDIR",
    "NODE_EXTRA_CA_CERTS", "HTTPS_PROXY", "HTTP_PROXY", "NO_PROXY",
    "SSL_CERT_FILE", "SSL_CERT_DIR",
)


def _subprocess_env(codex_home: str) -> dict:
    env = {
        "CODEX_HOME": codex_home,
        "PATH": os.environ.get("PATH", ""),
        "HOME": os.environ.get("HOME", ""),
    }
    for k in _ENV_PASSTHROUGH:
        if k in os.environ:
            env[k] = os.environ[k]
    return env


def _read_back_rotation(codex_home: str, started_refresh_token: str) -> None:
    path = os.path.join(codex_home, "auth.json")
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, json.JSONDecodeError):
        return
    toks = data.get("tokens") or {}
    new_refresh = toks.get("refresh_token")
    if not new_refresh or new_refresh == started_refresh_token:
        return
    # A genuine CLI-side rotation — but only persist a COMPLETE bundle. store_bundle rejects
    # missing fields (would raise ValueError), and a partial write would be worse than
    # skipping: it could clobber the org row with empties.
    access_token = toks.get("access_token")
    account_id = toks.get("account_id")
    if not access_token or not account_id:
        log.warning("codex CLI rotated the refresh token but the scratch auth.json is missing "
                    "access_token/account_id — skipping reconcile (cannot store a partial bundle).")
        return
    log.warning("codex CLI rotated the refresh token mid-run — reconciling into the org store "
                "(otherwise the next bott-initiated refresh would reuse the now-consumed token).")
    try:
        codex_tokens.store_bundle({
            "access_token": access_token,
            "refresh_token": new_refresh,
            "account_id": account_id,
        })
    except Exception as e:  # noqa: BLE001 — reconcile is best-effort; must never propagate
        # Must not raise out of the finally block: a raise here would skip scratch-dir
        # cleanup (leaving a live auth.json on disk). Redacted — never log token material.
        log.warning("failed to reconcile codex CLI token rotation into the org store: %s",
                    redact(str(e)))


def run_codex_exec(
    prompt: str,
    *,
    cwd: str,
    sandbox: str = "workspace-write",
    model_id: Optional[str] = None,
    output_schema: Optional[dict] = None,
    timeout_s: int = 900,
    binary: Optional[str] = None,
    runner: SubprocessRunner = subprocess.run,
) -> CodexExecResult:
    """Run one `codex exec` invocation against `cwd`. Feeds the org token via a fresh
    scratch CODEX_HOME per call (never a shared one another concurrent call might touch).

    `model_id`, when given, is passed via `-m` — callers MUST resolve it themselves (e.g.
    `bott.shared.model.resolve_model_id(role)`, with `_review_anti_affinity` for the review
    role) rather than leaving it unset, or every call silently falls back to whatever model
    the `codex` CLI defaults to, bypassing bott's per-role model selection entirely."""
    if sandbox not in _VALID_SANDBOXES:
        raise ValueError(f"unknown sandbox {sandbox!r} (use one of {_VALID_SANDBOXES})")

    tok = codex_tokens.get_valid_token()
    binary = binary or "codex"
    # Create both scratch temps inside the try so the finally always cleans them up — if
    # mkstemp raised while mkdtemp had already succeeded, the empty CODEX_HOME would leak.
    codex_home = ""
    out_path = ""
    schema_path: Optional[str] = None
    try:
        codex_home = tempfile.mkdtemp(prefix="bott-codex-home-")
        out_fd, out_path = tempfile.mkstemp(prefix="bott-codex-out-", suffix=".txt")
        os.close(out_fd)
        _write_auth_json(codex_home, tok.access_token, tok.refresh_token, tok.account_id)

        args = [binary, "exec", "--skip-git-repo-check"]
        # In a container, codex's bubblewrap sandbox needs unprivileged user namespaces,
        # which are often disabled (hardened kernels, restrictive container runtimes) — codex
        # exec would simply fail to start there. Docker is already the real isolation
        # boundary in that deploy, so swap `-s <sandbox>` for the CLI's own
        # "trust the environment" flag instead of asking it to sandbox itself again.
        if config.codex_cli_disable_sandbox():
            args += ["--dangerously-bypass-approvals-and-sandbox"]
        else:
            args += ["-s", sandbox]
        args += ["-C", cwd]
        if model_id:
            args += ["-m", model_id]
        args += ["--output-last-message", out_path]
        if output_schema is not None:
            schema_fd, schema_path = tempfile.mkstemp(prefix="bott-codex-schema-", suffix=".json")
            with os.fdopen(schema_fd, "w", encoding="utf-8") as sf:
                json.dump(output_schema, sf)
            args += ["--output-schema", schema_path]

        try:
            proc = runner(args, input=prompt, capture_output=True, text=True,
                          cwd=cwd, timeout=timeout_s, env=_subprocess_env(codex_home))
        except subprocess.TimeoutExpired as e:
            raise CodexCliError(f"codex exec timed out after {timeout_s}s") from e

        if proc.returncode != 0:
            raise CodexCliError(f"codex exec failed (exit {proc.returncode}): "
                                f"{redact((proc.stderr or '').strip()[-2000:])}")

        with open(out_path, encoding="utf-8") as f:
            text = f.read().strip()

        data = None
        if output_schema is not None:
            try:
                data = json.loads(text)
            except json.JSONDecodeError as e:
                raise CodexCliError(f"codex exec did not return valid JSON: {e}") from e

        m = _TOKENS_USED_RE.search(proc.stderr or "")
        tokens_used = int(m.group(1)) if m else 0
        return CodexExecResult(text=text, data=data, tokens_used=tokens_used)
    finally:
        # rmtree MUST run even if _read_back_rotation somehow raises — otherwise a scratch
        # dir with a LIVE auth.json (access+refresh token) would be left on disk.
        try:
            if codex_home:
                _read_back_rotation(codex_home, tok.refresh_token)
        finally:
            if codex_home:
                shutil.rmtree(codex_home, ignore_errors=True)
            if out_path:
                try:
                    os.unlink(out_path)
                except OSError:
                    pass
            if schema_path:
                try:
                    os.unlink(schema_path)
                except OSError:
                    pass
