"""Subprocess bridge to the official `codex` CLI binary (`codex exec`).

Used for the `build`/`review` roles, which need Codex's OWN agentic loop (shell + file
tools running inside its own sandbox against a repo checkout) — something the direct
Responses-API adapter (codex_model.py) cannot offer, since that path exists specifically
so Agno's tool-calling protocol stays in control for the `chat` role. Spawning the real,
officially-distributed binary also means every request has the same shape/telemetry as a
human running the CLI interactively — materially lower ban-risk on the shared org
subscription than hand-built calls to the undocumented Responses backend.

TOKEN OWNERSHIP: bott does NOT manage the Codex token here. Every `codex exec` call runs
against ONE persistent `CODEX_HOME` (config.codex_cli_home() — a mounted volume in prod,
`~/.codex` in dev) that an org admin populates once via `codex login`. The CLI reads,
refreshes, and rotates the login in place with its own file locking, so many users' calls
share one subscription safely and concurrently. This mirrors the reference deployment
exactly, and is why there is no per-call token copy / auth.json write / rotation-reconcile
here (an earlier design tried to seed each call from a Postgres-stored token — that created
a single-use-refresh-token race that revoked the login under concurrency).
"""

from __future__ import annotations

import copy
import json
import os
import re
import subprocess
import tempfile
from dataclasses import dataclass
from typing import Callable, Optional

from bott.shared import config
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


# The subprocess must NOT inherit bott's full environment. The build/review roles feed
# UNTRUSTED content (PR diffs, issue text) to a model that runs shell commands inside this
# process's child; the whole os.environ would hand that model every bott secret —
# BOTT_SECRET_KEY, DATABASE_URL, GITHUB_APP_PRIVATE_KEY, JIRA_API_TOKEN, OPENROUTER_API_KEY,
# SLACK_BOT_TOKEN, ... — one `printenv` away from exfiltration via the review output. So we
# pass a MINIMAL, allowlisted env: only what the CLI genuinely needs to run (its persistent
# CODEX_HOME, a PATH to find node/itself, HOME, and a handful of locale/proxy/TLS vars that
# only matter when actually set).
_ENV_PASSTHROUGH = (
    "LANG", "LC_ALL", "LC_CTYPE", "TERM", "TMPDIR",
    "NODE_EXTRA_CA_CERTS", "HTTPS_PROXY", "HTTP_PROXY", "NO_PROXY",
    "SSL_CERT_FILE", "SSL_CERT_DIR",
)


def _strictify_schema(node):
    """Make a JSON Schema acceptable to `codex exec --output-schema`, which runs OpenAI
    structured-outputs in STRICT mode: every object must set `additionalProperties: false`
    and list ALL its properties as `required`. Pydantic's `model_json_schema()` does neither,
    so `codex exec` rejects it with a 400 ("'additionalProperties' is required to be supplied
    and to be false"). We transform a deep copy in place and recurse through properties,
    array items, $defs, and anyOf/oneOf/allOf branches."""
    if isinstance(node, dict):
        if node.get("type") == "object" or "properties" in node:
            node["additionalProperties"] = False
            node["required"] = list((node.get("properties") or {}).keys())
        for v in node.values():
            _strictify_schema(v)
    elif isinstance(node, list):
        for v in node:
            _strictify_schema(v)
    return node


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


def is_logged_in(codex_home: Optional[str] = None, binary: Optional[str] = None) -> bool:
    """Whether the codex CLI has a usable login for this CODEX_HOME, per the CLI itself
    (`codex login status`). We ASK the binary rather than looking for a specific file because
    the auth-store layout differs across codex versions (older builds keep a flat auth.json;
    newer ones keep it in a state DB) — the CLI's own status is the version-proof signal.
    Note this only confirms a login is CONFIGURED locally; it can't detect a server-side
    revocation (only actually running `codex exec` surfaces that)."""
    home = codex_home or config.codex_cli_home()
    binary = binary or config.codex_cli_binary()
    try:
        proc = subprocess.run([binary, "login", "status"], capture_output=True, text=True,
                              timeout=15, env=_subprocess_env(home))
    except Exception:  # noqa: BLE001 — binary missing / timeout → treat as not logged in
        return False
    out = f"{proc.stdout}\n{proc.stderr}".lower()
    return "not logged in" not in out and "logged in" in out


def run_codex_exec(
    prompt: str,
    *,
    cwd: str,
    sandbox: str = "workspace-write",
    model_id: Optional[str] = None,
    output_schema: Optional[dict] = None,
    timeout_s: int = 900,
    binary: Optional[str] = None,
    codex_home: Optional[str] = None,
    runner: SubprocessRunner = subprocess.run,
) -> CodexExecResult:
    """Run one `codex exec` invocation against `cwd`, using the persistent CODEX_HOME login
    (config.codex_cli_home() unless `codex_home` is given). bott does not touch the token —
    the CLI manages it in that home.

    `model_id`, when given, is passed via `-m` — callers MUST resolve it themselves (e.g.
    `bott.shared.model.resolve_model_id(role)`, with `_review_anti_affinity` for the review
    role) rather than leaving it unset, or every call silently falls back to whatever model
    the `codex` CLI defaults to, bypassing bott's per-role model selection entirely."""
    if sandbox not in _VALID_SANDBOXES:
        raise ValueError(f"unknown sandbox {sandbox!r} (use one of {_VALID_SANDBOXES})")

    home = codex_home or config.codex_cli_home()
    binary = binary or "codex"
    # The temp files below are ONLY for the CLI's output (and the optional schema) — NOT for
    # its login. CODEX_HOME is the persistent, shared home and is never created or cleaned here.
    out_path = ""
    schema_path: Optional[str] = None
    try:
        out_fd, out_path = tempfile.mkstemp(prefix="bott-codex-out-", suffix=".txt")
        os.close(out_fd)

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
            strict_schema = _strictify_schema(copy.deepcopy(output_schema))
            schema_fd, schema_path = tempfile.mkstemp(prefix="bott-codex-schema-", suffix=".json")
            with os.fdopen(schema_fd, "w", encoding="utf-8") as sf:
                json.dump(strict_schema, sf)
            args += ["--output-schema", schema_path]

        try:
            proc = runner(args, input=prompt, capture_output=True, text=True,
                          cwd=cwd, timeout=timeout_s, env=_subprocess_env(home))
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
