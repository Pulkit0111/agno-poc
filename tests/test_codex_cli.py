"""Subprocess bridge to the official `codex` CLI — no real binary is spawned; `runner` is
injected so these tests exercise the argv/env/file-plumbing logic deterministically."""
from __future__ import annotations

import json
import os
import subprocess

import pytest

from bott.shared import codex_cli as cc
from bott.shared import codex_tokens as ct
from bott.shared import config
from bott.shared.codex_tokens import CodexToken


def _fake_ok_runner(output_text="hello", write_output=True):
    def runner(args, *, input, capture_output, text, cwd, timeout, env):
        # --output-last-message <path> is always the argument right after that flag.
        out_path = args[args.index("--output-last-message") + 1]
        if write_output:
            with open(out_path, "w", encoding="utf-8") as f:
                f.write(output_text)
        return subprocess.CompletedProcess(args, returncode=0, stdout="", stderr="tokens used: 42")
    return runner


def test_run_codex_exec_returns_text(monkeypatch, tmp_path):
    monkeypatch.setattr(ct, "get_valid_token", lambda: CodexToken("tok", "acc", "rt"))
    result = cc.run_codex_exec("do the thing", cwd=str(tmp_path), sandbox="read-only",
                               runner=_fake_ok_runner("plan: do X"))
    assert result.text == "plan: do X"
    assert result.data is None
    assert result.tokens_used == 42


def test_run_codex_exec_parses_output_schema(monkeypatch, tmp_path):
    monkeypatch.setattr(ct, "get_valid_token", lambda: CodexToken("tok", "acc", "rt"))
    payload = json.dumps({"verdict": "approve"})
    result = cc.run_codex_exec("review this", cwd=str(tmp_path), sandbox="read-only",
                               output_schema={"type": "object"},
                               runner=_fake_ok_runner(payload))
    assert result.data == {"verdict": "approve"}


def test_run_codex_exec_bad_json_raises(monkeypatch, tmp_path):
    monkeypatch.setattr(ct, "get_valid_token", lambda: CodexToken("tok", "acc", "rt"))
    with pytest.raises(cc.CodexCliError, match="valid JSON"):
        cc.run_codex_exec("review this", cwd=str(tmp_path), sandbox="read-only",
                          output_schema={"type": "object"},
                          runner=_fake_ok_runner("not json"))


def test_run_codex_exec_nonzero_exit_raises(monkeypatch, tmp_path):
    monkeypatch.setattr(ct, "get_valid_token", lambda: CodexToken("tok", "acc", "rt"))
    def runner(args, **kw):
        return subprocess.CompletedProcess(args, returncode=1, stdout="", stderr="boom")
    with pytest.raises(cc.CodexCliError, match="boom"):
        cc.run_codex_exec("x", cwd=str(tmp_path), runner=runner)


def test_run_codex_exec_writes_auth_json_from_current_token(monkeypatch, tmp_path):
    # auth.json must be read back INSIDE the runner call, not after `run_codex_exec`
    # returns: the scratch CODEX_HOME is deleted in the `finally` block (it holds live
    # credentials, so it must not survive the call, on success or on error).
    monkeypatch.setattr(ct, "get_valid_token", lambda: CodexToken("tok-A", "acc-1", "rt-A"))
    seen = {}
    def runner(args, *, env, **kw):
        out_path = args[args.index("--output-last-message") + 1]
        with open(out_path, "w", encoding="utf-8") as f:
            f.write("ok")
        with open(os.path.join(env["CODEX_HOME"], "auth.json"), encoding="utf-8") as f:
            seen["written"] = json.load(f)
        return subprocess.CompletedProcess(args, returncode=0, stdout="", stderr="")
    cc.run_codex_exec("x", cwd=str(tmp_path), runner=runner)
    written = seen["written"]
    assert written["tokens"]["access_token"] == "tok-A"
    assert written["tokens"]["refresh_token"] == "rt-A"
    assert written["tokens"]["account_id"] == "acc-1"


def test_run_codex_exec_reconciles_rotated_refresh_token(monkeypatch, tmp_path):
    monkeypatch.setattr(ct, "get_valid_token", lambda: CodexToken("tok-A", "acc-1", "rt-A"))
    stored = []
    monkeypatch.setattr(ct, "store_bundle", lambda b: stored.append(b))

    def runner(args, *, env, **kw):
        out_path = args[args.index("--output-last-message") + 1]
        with open(out_path, "w", encoding="utf-8") as f:
            f.write("ok")
        # Simulate the CLI itself refreshing mid-run and rotating the refresh token.
        auth_path = os.path.join(env["CODEX_HOME"], "auth.json")
        with open(auth_path, "w", encoding="utf-8") as f:
            json.dump({"tokens": {"access_token": "tok-B", "refresh_token": "rt-B",
                                  "account_id": "acc-1"}}, f)
        return subprocess.CompletedProcess(args, returncode=0, stdout="", stderr="")

    cc.run_codex_exec("x", cwd=str(tmp_path), runner=runner)
    assert stored == [{"access_token": "tok-B", "refresh_token": "rt-B", "account_id": "acc-1"}]


def test_run_codex_exec_no_reconcile_when_refresh_token_unchanged(monkeypatch, tmp_path):
    monkeypatch.setattr(ct, "get_valid_token", lambda: CodexToken("tok-A", "acc-1", "rt-A"))
    stored = []
    monkeypatch.setattr(ct, "store_bundle", lambda b: stored.append(b))
    cc.run_codex_exec("x", cwd=str(tmp_path), runner=_fake_ok_runner("ok"))
    assert stored == []


def test_run_codex_exec_invalid_sandbox_raises(tmp_path):
    with pytest.raises(ValueError, match="sandbox"):
        cc.run_codex_exec("x", cwd=str(tmp_path), sandbox="bogus")


def test_run_codex_exec_passes_model_flag_when_given(monkeypatch, tmp_path):
    monkeypatch.setattr(ct, "get_valid_token", lambda: CodexToken("tok", "acc", "rt"))
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


def test_run_codex_exec_omits_model_flag_when_not_given(monkeypatch, tmp_path):
    monkeypatch.setattr(ct, "get_valid_token", lambda: CodexToken("tok", "acc", "rt"))
    seen_args = {}
    def runner(args, **kw):
        seen_args["args"] = args
        out_path = args[args.index("--output-last-message") + 1]
        with open(out_path, "w", encoding="utf-8") as f:
            f.write("ok")
        return subprocess.CompletedProcess(args, returncode=0, stdout="", stderr="")
    cc.run_codex_exec("x", cwd=str(tmp_path), runner=runner)
    assert "-m" not in seen_args["args"]


def test_run_codex_exec_uses_sandbox_flag_by_default(monkeypatch, tmp_path):
    monkeypatch.setattr(ct, "get_valid_token", lambda: CodexToken("tok", "acc", "rt"))
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
    monkeypatch.setattr(ct, "get_valid_token", lambda: CodexToken("tok", "acc", "rt"))
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
