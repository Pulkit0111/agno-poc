"""Device-auth bridge to the `codex` CLI for the console's admin "Connect ChatGPT" flow."""

from __future__ import annotations

import time

import pytest

from bott.shared import codex_login, codex_tokens, db


@pytest.fixture
def store(monkeypatch, tmp_path):
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.setenv("AGENTOS_DB_PATH", str(tmp_path / "cl.db"))
    from bott.shared.secrets import generate_key
    monkeypatch.setenv("BOTT_SECRET_KEY", generate_key())
    db.get_engine(fresh=True)
    from bott.shared.schema import init_schema
    init_schema()
    codex_login._login_proc = None
    codex_login._reader_thread = None
    yield


class _FakeProc:
    """Stands in for subprocess.Popen: `lines` is fed to the reader thread as stdout,
    `returncode` is what the process "exits" with once stdout is exhausted."""

    def __init__(self, lines, returncode=0):
        self.stdout = iter(lines)
        self.returncode = returncode
        self.killed = False
        self._waited = False

    def poll(self):
        return None if not self._waited else self.returncode

    def wait(self):
        self._waited = True
        return self.returncode

    def kill(self):
        self.killed = True


def _join_reader():
    t = codex_login._reader_thread
    if t is not None:
        t.join(timeout=2)


# ---- parse_device_login -----------------------------------------------------------------

def test_parse_extracts_url_and_code():
    raw = "Open https://auth.openai.com/device and enter code ABCD-1234 to continue."
    parsed = codex_login.parse_device_login(raw)
    assert parsed == {"url": "https://auth.openai.com/device", "code": "ABCD-1234"}


def test_parse_ignores_non_openai_urls():
    raw = "See https://example.com/help — code WXYZ-5678"
    parsed = codex_login.parse_device_login(raw)
    assert "url" not in parsed
    assert parsed["code"] == "WXYZ-5678"


def test_parse_strips_ansi_escapes():
    raw = "\x1b[32mOpen https://auth.openai.com/device\x1b[0m code \x1b[1mABCD-1234\x1b[0m"
    parsed = codex_login.parse_device_login(raw)
    assert parsed["url"] == "https://auth.openai.com/device"
    assert parsed["code"] == "ABCD-1234"


# ---- start_codex_login --------------------------------------------------------------------

def test_already_connected_returns_error(store, monkeypatch):
    monkeypatch.setattr(codex_tokens, "is_connected", lambda: True)
    assert codex_login.start_codex_login() == {"error": "already connected"}


def test_spawn_failure_is_reported(store):
    def boom(*a, **kw):
        raise OSError("not found")
    result = codex_login.start_codex_login(spawn_fn=boom)
    assert "error" in result and "not found" in result["error"]


def test_returns_url_and_code_once_printed(store):
    proc = _FakeProc([
        "Starting device login...\n",
        "Open https://auth.openai.com/device and enter code ABCD-1234\n",
    ])
    result = codex_login.start_codex_login(spawn_fn=lambda *a, **kw: proc)
    assert result["url"] == "https://auth.openai.com/device"
    assert result["code"] == "ABCD-1234"
    _join_reader()


def test_waits_for_code_printed_on_a_later_line(store):
    """Regression: the real CLI prints the URL and the one-time code on separate lines —
    "1. Open this link..." then, a line later, "2. Enter this one-time code...". Returning
    as soon as the URL line was seen surfaced a URL with no code to the admin, who then had
    nothing to type into OpenAI's device-code page."""
    proc = _FakeProc([
        "1. Open this link in your browser and sign in to your account\n",
        "   https://auth.openai.com/codex/device\n",
        "\n",
        "2. Enter this one-time code (expires in 15 minutes)\n",
        "   T49C-HRRVV\n",
    ])
    result = codex_login.start_codex_login(spawn_fn=lambda *a, **kw: proc)
    assert result["url"] == "https://auth.openai.com/codex/device"
    assert result["code"] == "T49C-HRRVV"
    _join_reader()


def test_url_with_no_code_ever_printed_is_an_error(store):
    """A URL with no code isn't actionable — the OpenAI page requires the code. Must
    surface as an error, not a half-populated "connect" card the admin can't complete."""
    proc = _FakeProc([
        "1. Open this link in your browser and sign in to your account\n",
        "   https://auth.openai.com/codex/device\n",
    ], returncode=1)
    result = codex_login.start_codex_login(spawn_fn=lambda *a, **kw: proc)
    assert "error" in result
    _join_reader()


def test_no_code_printed_before_exit_is_an_error(store):
    proc = _FakeProc(["some unrelated CLI chatter\n"], returncode=1)
    result = codex_login.start_codex_login(spawn_fn=lambda *a, **kw: proc)
    assert "error" in result


def test_successful_login_imports_token_into_postgres(store, tmp_path, monkeypatch):
    """The whole point of this bridge: once the CLI exits 0, its local auth.json must land
    in the same Postgres bundle codex_tokens.py serves MODEL_PROVIDER=codex from."""
    auth_path = tmp_path / "auth.json"
    auth_path.write_text(
        '{"tokens": {"access_token": "tok-abc", "refresh_token": "ref-abc", '
        '"account_id": "acc-1"}}'
    )
    monkeypatch.setattr(codex_tokens, "bootstrap_from_local", lambda path="~/.codex/auth.json": (
        codex_tokens.store_bundle(
            __import__("json").loads(auth_path.read_text())["tokens"]
        ) or True
    ))
    proc = _FakeProc([
        "Open https://auth.openai.com/device and enter code ABCD-1234\n",
        "Approved!\n",
    ], returncode=0)
    codex_login.start_codex_login(spawn_fn=lambda *a, **kw: proc)
    _join_reader()
    assert codex_tokens.is_connected() is True


def test_failed_login_does_not_import_anything(store, monkeypatch):
    called = []
    monkeypatch.setattr(codex_tokens, "bootstrap_from_local", lambda **kw: called.append(1))
    proc = _FakeProc([
        "Open https://auth.openai.com/device and enter code ABCD-1234\n",
    ], returncode=1)
    codex_login.start_codex_login(spawn_fn=lambda *a, **kw: proc)
    _join_reader()
    assert called == []


def test_timeout_waiting_for_code(store, monkeypatch):
    """The reader thread is still blocked reading stdout (no code printed yet) when the
    caller's wait expires — must return a timeout error rather than hang."""
    monkeypatch.setattr(codex_login, "_START_TIMEOUT_S", 0.05)

    def _never_yields():
        time.sleep(1)  # long enough to outlast the 0.05s wait below
        yield "still nothing\n"

    proc = _FakeProc([])
    proc.stdout = _never_yields()
    result = codex_login.start_codex_login(spawn_fn=lambda *a, **kw: proc)
    assert result == {"error": "timed out waiting for the device code"}


# ---- codex_login_status / disconnect_codex_login ------------------------------------------

def test_status_reflects_connection(store):
    assert codex_login.codex_login_status() == {"connected": False}
    codex_tokens.store_bundle({
        "access_token": "a", "refresh_token": "r", "account_id": "acc",
    })
    assert codex_login.codex_login_status() == {"connected": True}


def test_disconnect_clears_postgres_bundle(store):
    codex_tokens.store_bundle({
        "access_token": "a", "refresh_token": "r", "account_id": "acc",
    })
    assert codex_tokens.is_connected() is True
    codex_login.disconnect_codex_login()
    assert codex_tokens.is_connected() is False


def test_disconnect_kills_in_flight_login(store):
    proc = _FakeProc(["no code yet\n"], returncode=1)
    codex_login._login_proc = proc
    codex_login.disconnect_codex_login()
    assert proc.killed is True
    assert codex_login._login_proc is None
