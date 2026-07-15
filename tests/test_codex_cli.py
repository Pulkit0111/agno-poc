"""Subprocess bridge to the official `codex` CLI — no real binary is spawned; `runner` is
injected so these tests exercise the argv/env/file-plumbing logic deterministically.

The bridge does NOT manage the Codex token: every call runs against the persistent
CODEX_HOME (config.codex_cli_home()) that an admin populated with `codex login`, and the CLI
owns the login there. So there is nothing here about writing/reading/reconciling auth.json."""
from __future__ import annotations

import json
import os
import subprocess

import pytest

from bott.shared import codex_cli as cc
from bott.shared import config


def _fake_ok_runner(output_text="hello", write_output=True):
    def runner(args, *, input, capture_output, text, cwd, timeout, env):
        # --output-last-message <path> is always the argument right after that flag.
        out_path = args[args.index("--output-last-message") + 1]
        if write_output:
            with open(out_path, "w", encoding="utf-8") as f:
                f.write(output_text)
        return subprocess.CompletedProcess(args, returncode=0, stdout="", stderr="tokens used: 42")
    return runner


def test_run_codex_exec_returns_text(tmp_path):
    result = cc.run_codex_exec("do the thing", cwd=str(tmp_path), sandbox="read-only",
                               runner=_fake_ok_runner("plan: do X"))
    assert result.text == "plan: do X"
    assert result.data is None
    assert result.tokens_used == 42


def test_run_codex_exec_parses_output_schema(tmp_path):
    payload = json.dumps({"verdict": "approve"})
    result = cc.run_codex_exec("review this", cwd=str(tmp_path), sandbox="read-only",
                               output_schema={"type": "object"},
                               runner=_fake_ok_runner(payload))
    assert result.data == {"verdict": "approve"}


def test_run_codex_exec_bad_json_raises(tmp_path):
    with pytest.raises(cc.CodexCliError, match="valid JSON"):
        cc.run_codex_exec("review this", cwd=str(tmp_path), sandbox="read-only",
                          output_schema={"type": "object"},
                          runner=_fake_ok_runner("not json"))


def test_run_codex_exec_nonzero_exit_raises(tmp_path):
    def runner(args, **kw):
        return subprocess.CompletedProcess(args, returncode=1, stdout="", stderr="boom")
    with pytest.raises(cc.CodexCliError, match="boom"):
        cc.run_codex_exec("x", cwd=str(tmp_path), runner=runner)


def test_run_codex_exec_invalid_sandbox_raises(tmp_path):
    with pytest.raises(ValueError, match="sandbox"):
        cc.run_codex_exec("x", cwd=str(tmp_path), sandbox="bogus")


def test_run_codex_exec_uses_persistent_codex_home(monkeypatch, tmp_path):
    """The child's CODEX_HOME is the shared persistent home (config.codex_cli_home()), NOT a
    per-call scratch dir — that shared login is what lets many users' calls reuse one
    subscription safely."""
    home = str(tmp_path / "codexhome")
    monkeypatch.setattr(config, "codex_cli_home", lambda: home)
    seen_env = {}
    def runner(args, *, env, **kw):
        seen_env.update(env)
        out_path = args[args.index("--output-last-message") + 1]
        with open(out_path, "w", encoding="utf-8") as f:
            f.write("ok")
        return subprocess.CompletedProcess(args, returncode=0, stdout="", stderr="")
    cc.run_codex_exec("x", cwd=str(tmp_path), runner=runner)
    assert seen_env["CODEX_HOME"] == home


def test_run_codex_exec_codex_home_override(tmp_path):
    """An explicit codex_home arg overrides the config default."""
    home = str(tmp_path / "explicit")
    seen_env = {}
    def runner(args, *, env, **kw):
        seen_env.update(env)
        out_path = args[args.index("--output-last-message") + 1]
        with open(out_path, "w", encoding="utf-8") as f:
            f.write("ok")
        return subprocess.CompletedProcess(args, returncode=0, stdout="", stderr="")
    cc.run_codex_exec("x", cwd=str(tmp_path), codex_home=home, runner=runner)
    assert seen_env["CODEX_HOME"] == home


def test_run_codex_exec_passes_model_flag_when_given(tmp_path):
    seen_args = {}
    def runner(args, **kw):
        seen_args["args"] = args
        out_path = args[args.index("--output-last-message") + 1]
        with open(out_path, "w", encoding="utf-8") as f:
            f.write("ok")
        return subprocess.CompletedProcess(args, returncode=0, stdout="", stderr="")
    cc.run_codex_exec("x", cwd=str(tmp_path), model_id="gpt-5.5-codex", runner=runner)
    args = seen_args["args"]
    assert args[args.index("-m") + 1] == "gpt-5.5-codex"


def test_run_codex_exec_omits_model_flag_when_not_given(tmp_path):
    seen_args = {}
    def runner(args, **kw):
        seen_args["args"] = args
        out_path = args[args.index("--output-last-message") + 1]
        with open(out_path, "w", encoding="utf-8") as f:
            f.write("ok")
        return subprocess.CompletedProcess(args, returncode=0, stdout="", stderr="")
    cc.run_codex_exec("x", cwd=str(tmp_path), runner=runner)
    assert "-m" not in seen_args["args"]


def test_run_codex_exec_env_excludes_bott_secrets(monkeypatch, tmp_path):
    monkeypatch.setenv("BOTT_SECRET_KEY", "supersecret")
    monkeypatch.setenv("DATABASE_URL", "postgres://user:pw@host/db")
    monkeypatch.setenv("PATH", "/usr/bin:/bin")
    seen_env = {}
    def runner(args, *, env, **kw):
        seen_env.update(env)
        out_path = args[args.index("--output-last-message") + 1]
        with open(out_path, "w", encoding="utf-8") as f:
            f.write("ok")
        return subprocess.CompletedProcess(args, returncode=0, stdout="", stderr="")
    cc.run_codex_exec("x", cwd=str(tmp_path), runner=runner)
    assert "CODEX_HOME" in seen_env
    assert seen_env["PATH"] == "/usr/bin:/bin"
    assert "BOTT_SECRET_KEY" not in seen_env
    assert "DATABASE_URL" not in seen_env


def test_run_codex_exec_uses_sandbox_flag_by_default(monkeypatch, tmp_path):
    monkeypatch.setattr(config, "codex_cli_disable_sandbox", lambda: False)
    seen_args = {}
    def runner(args, **kw):
        seen_args["args"] = args
        out_path = args[args.index("--output-last-message") + 1]
        with open(out_path, "w", encoding="utf-8") as f:
            f.write("ok")
        return subprocess.CompletedProcess(args, returncode=0, stdout="", stderr="")
    cc.run_codex_exec("x", cwd=str(tmp_path), sandbox="read-only", runner=runner)
    args = seen_args["args"]
    assert args[args.index("-s") + 1] == "read-only"
    assert "--dangerously-bypass-approvals-and-sandbox" not in args


def test_run_codex_exec_bypasses_sandbox_when_disabled(monkeypatch, tmp_path):
    monkeypatch.setattr(config, "codex_cli_disable_sandbox", lambda: True)
    seen_args = {}
    def runner(args, **kw):
        seen_args["args"] = args
        out_path = args[args.index("--output-last-message") + 1]
        with open(out_path, "w", encoding="utf-8") as f:
            f.write("ok")
        return subprocess.CompletedProcess(args, returncode=0, stdout="", stderr="")
    cc.run_codex_exec("x", cwd=str(tmp_path), sandbox="read-only", runner=runner)
    args = seen_args["args"]
    assert "--dangerously-bypass-approvals-and-sandbox" in args
    assert "-s" not in args


def test_run_codex_exec_strictifies_output_schema(tmp_path):
    """codex exec runs strict structured-outputs: the written --output-schema file must have
    additionalProperties:false and required=all-props on every object, or the CLI 400s. The
    caller's dict must not be mutated."""
    caller_schema = {
        "type": "object",
        "properties": {
            "verdict": {"type": "string"},
            "nested": {"type": "object", "properties": {"a": {"type": "integer"}}},
        },
    }
    original = json.loads(json.dumps(caller_schema))  # snapshot
    written = {}
    def runner(args, **kw):
        sp = args[args.index("--output-schema") + 1]
        with open(sp, encoding="utf-8") as f:
            written.update(json.load(f))
        out_path = args[args.index("--output-last-message") + 1]
        with open(out_path, "w", encoding="utf-8") as f:
            f.write('{"verdict":"ok"}')
        return subprocess.CompletedProcess(args, returncode=0, stdout="", stderr="")
    cc.run_codex_exec("x", cwd=str(tmp_path), output_schema=caller_schema, runner=runner)
    assert written["additionalProperties"] is False
    assert set(written["required"]) == {"verdict", "nested"}
    assert written["properties"]["nested"]["additionalProperties"] is False
    assert written["properties"]["nested"]["required"] == ["a"]
    assert caller_schema == original  # caller's dict untouched


def test_run_codex_exec_extra_config_env_and_ephemeral(tmp_path):
    """Chat-path plumbing: -c overrides (MCP server wiring), extra env (the bearer ticket),
    and --ephemeral (no session files pile up on the shared server)."""
    captured = {}
    def runner(args, *, env, **kw):
        captured["args"] = args
        captured["env"] = env
        out_path = args[args.index("--output-last-message") + 1]
        with open(out_path, "w", encoding="utf-8") as f:
            f.write("ok")
        return subprocess.CompletedProcess(args, returncode=0, stdout="", stderr="tokens used: 5")
    res = cc.run_codex_exec("p", cwd=str(tmp_path), sandbox="read-only",
                            extra_config={"mcp_servers.bott.url": '"http://x/mcp"'},
                            extra_env={"BOTT_MCP_TICKET": "t1"}, ephemeral=True,
                            runner=runner)
    args = captured["args"]
    assert "--ephemeral" in args
    assert 'mcp_servers.bott.url="http://x/mcp"' in args
    assert args[args.index('mcp_servers.bott.url="http://x/mcp"') - 1] == "-c"
    assert captured["env"]["BOTT_MCP_TICKET"] == "t1"
    assert res.text == "ok"
    assert res.tokens_used == 5


def test_run_codex_exec_extra_env_cannot_leak_os_environ(monkeypatch, tmp_path):
    """extra_env adds ONLY the given keys — the minimal-allowlist env stays minimal."""
    monkeypatch.setenv("DATABASE_URL", "postgres://user:pw@host/db")
    seen_env = {}
    def runner(args, *, env, **kw):
        seen_env.update(env)
        out_path = args[args.index("--output-last-message") + 1]
        with open(out_path, "w", encoding="utf-8") as f:
            f.write("ok")
        return subprocess.CompletedProcess(args, returncode=0, stdout="", stderr="")
    cc.run_codex_exec("p", cwd=str(tmp_path), extra_env={"A": "1"}, runner=runner)
    assert seen_env["A"] == "1"
    assert "DATABASE_URL" not in seen_env


def test_run_codex_exec_quota_error_classified(tmp_path):
    """Rate-limit/usage-cap stderr on failure surfaces as CodexQuotaError so callers can
    tell 'the org subscription is throttled' apart from a generic failure."""
    def runner(args, **kw):
        return subprocess.CompletedProcess(args, returncode=1, stdout="",
                                           stderr="stream error: You've hit your usage limit.")
    with pytest.raises(cc.CodexQuotaError):
        cc.run_codex_exec("p", cwd=str(tmp_path), runner=runner)
    # And a quota error IS still a CodexCliError, so existing handlers keep working.
    assert issubclass(cc.CodexQuotaError, cc.CodexCliError)


def test_run_codex_exec_non_quota_failure_stays_cli_error(tmp_path):
    def runner(args, **kw):
        return subprocess.CompletedProcess(args, returncode=1, stdout="", stderr="boom")
    with pytest.raises(cc.CodexCliError) as ei:
        cc.run_codex_exec("p", cwd=str(tmp_path), runner=runner)
    assert not isinstance(ei.value, cc.CodexQuotaError)


def test_run_codex_exec_user_id_routes_through_concurrency(monkeypatch, tmp_path):
    """When user_id is given the call runs inside the org/per-user concurrency guard —
    the whole org shares ONE subscription, so CLI calls must queue like shim calls did."""
    entered = {}
    class _Guard:
        def __init__(self, uid): entered["user_id"] = uid
        def __enter__(self): entered["entered"] = True
        def __exit__(self, *a): entered["exited"] = True
    monkeypatch.setattr(cc, "acquire_sync", _Guard)
    def runner(args, **kw):
        assert entered.get("entered"), "subprocess must run inside the concurrency guard"
        out_path = args[args.index("--output-last-message") + 1]
        with open(out_path, "w", encoding="utf-8") as f:
            f.write("ok")
        return subprocess.CompletedProcess(args, returncode=0, stdout="", stderr="")
    cc.run_codex_exec("p", cwd=str(tmp_path), user_id="u@x.com", runner=runner)
    assert entered == {"user_id": "u@x.com", "entered": True, "exited": True}


def test_codex_chat_timeout_config(monkeypatch):
    monkeypatch.delenv("CODEX_CHAT_TIMEOUT_S", raising=False)
    assert config.codex_chat_timeout_s() == 300
    monkeypatch.setenv("CODEX_CHAT_TIMEOUT_S", "120")
    assert config.codex_chat_timeout_s() == 120


def test_is_logged_in(monkeypatch, tmp_path):
    """is_logged_in asks the CLI (`codex login status`) rather than checking a file, since
    the auth-store layout is version-dependent."""
    calls = {}
    def fake_status(args, *, capture_output, text, timeout, env):
        calls["args"] = args
        calls["codex_home"] = env["CODEX_HOME"]
        return subprocess.CompletedProcess(args, returncode=0,
                                           stdout=calls["out"], stderr="")
    monkeypatch.setattr(cc.subprocess, "run", fake_status)

    calls["out"] = "Logged in using ChatGPT"
    assert cc.is_logged_in(str(tmp_path)) is True
    assert calls["args"][:3] == ["codex", "login", "status"]
    assert calls["codex_home"] == str(tmp_path)

    calls["out"] = "Not logged in"
    assert cc.is_logged_in(str(tmp_path)) is False


def test_is_logged_in_false_when_binary_errors(monkeypatch, tmp_path):
    def boom(*a, **k):
        raise FileNotFoundError("codex not found")
    monkeypatch.setattr(cc.subprocess, "run", boom)
    assert cc.is_logged_in(str(tmp_path)) is False


def test_run_codex_exec_auth_error_classified(tmp_path):
    """A logged-out CLI falls back to unauthenticated api.openai.com calls — 401 stderr
    must classify as CodexAuthError (non-retryable upstream), not a generic failure.
    Observed live: without this, Agno retried a dead login 4× with reconnect spam."""
    def runner(args, **kw):
        return subprocess.CompletedProcess(
            args, returncode=1, stdout="",
            stderr="ERROR: unexpected status 401 Unauthorized: Missing bearer or basic "
                   "authentication in header, url: https://api.openai.com/v1/responses")
    with pytest.raises(cc.CodexAuthError):
        cc.run_codex_exec("p", cwd=str(tmp_path), runner=runner)
    assert issubclass(cc.CodexAuthError, cc.CodexCliError)


def test_auth_classification_beats_quota(tmp_path):
    """'401' appears in auth markers; if stderr somehow carries both, auth wins — a dead
    login must never be retried as if it were a transient rate limit."""
    def runner(args, **kw):
        return subprocess.CompletedProcess(args, returncode=1, stdout="",
                                           stderr="401 Unauthorized after rate limit check")
    with pytest.raises(cc.CodexAuthError):
        cc.run_codex_exec("p", cwd=str(tmp_path), runner=runner)
