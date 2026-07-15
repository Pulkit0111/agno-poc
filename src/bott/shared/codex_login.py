"""Bridge to the official `codex` CLI's device-auth login, for the admin "Connect ChatGPT"
button in the console.

Bott never speaks OAuth itself — the CLI owns the entire device-auth flow AND the token
store. We spawn `codex login --device-auth` with CODEX_HOME pointed at the persistent
shared home (config.codex_cli_home() — a mounted volume in prod), scrape the printed
verification URL + code to show the admin, and that's it: the CLI writes its login into
CODEX_HOME and refreshes/rotates it in place with its own file locking on every
`codex exec`. There is deliberately NO second copy of the token anywhere (the old
Postgres bundle + local-file dual-store is what raced the single-use refresh token and
kept invalidating the org login).
"""

from __future__ import annotations

import os
import re
import subprocess
import threading
from typing import Callable, Optional

from bott.shared import codex_cli, config
from bott.shared.observability.logging_setup import get_logger

log = get_logger("bott.codex_login")

_ANSI_RE = re.compile(r"\x1b\[[0-9;]*[A-Za-z]")
_URL_RE = re.compile(r"https?://[^\s\"'<>]+")
_CODE_RE = re.compile(r"\b[A-Z0-9]{3,}-[A-Z0-9]{3,}\b")
_START_TIMEOUT_S = 25

# The in-flight login child + its background reader thread. The console API is a
# long-lived process, so these module-level refs survive between the start/status/
# disconnect calls; the reader thread keeps draining the child's output after
# start_codex_login() has already returned to its caller.
_login_proc: Optional[subprocess.Popen] = None
_reader_thread: Optional[threading.Thread] = None
_lock = threading.Lock()


def _strip_ansi(s: str) -> str:
    return _ANSI_RE.sub("", s)


def _login_env() -> dict:
    """The login child gets the SAME persistent CODEX_HOME every codex exec call uses —
    one login, one store, one refresher (the CLI)."""
    env = dict(os.environ)
    env["CODEX_HOME"] = config.codex_cli_home()
    return env


def parse_device_login(raw: str) -> dict:
    """Pull the verification URL + code out of the CLI's (ANSI-stripped) login output.
    The URL is an openai.com link; device codes are hyphenated alnum blocks (ABCD-1234)."""
    text = _strip_ansi(raw)
    out: dict = {}
    url_m = _URL_RE.search(text)
    if url_m and "openai" in url_m.group(0).lower():
        out["url"] = url_m.group(0).rstrip(".,)")
    code_m = _CODE_RE.search(text)
    if code_m:
        out["code"] = code_m.group(0)
    return out


def _log_result(proc) -> None:
    """Once the login child exits, log the outcome. Nothing to import: the CLI already
    wrote the login into CODEX_HOME."""
    proc.wait()
    global _login_proc
    with _lock:
        if _login_proc is proc:
            _login_proc = None
    if proc.returncode == 0:
        if codex_cli.is_logged_in():
            log.info("codex device login succeeded — CODEX_HOME=%s.", config.codex_cli_home())
        else:
            log.warning("codex login exited 0 but the CLI still reports not logged in.")
    else:
        log.warning("codex login exited %s — not connected.", proc.returncode)


def start_codex_login(spawn_fn: Callable[..., subprocess.Popen] = subprocess.Popen) -> dict:
    """Spawn `codex login --device-auth`; return {url, code, raw} once the CLI has printed
    the verification URL (or {"raw": ...} / {"error": ...}). The child keeps polling OpenAI
    in the background after this returns — a daemon thread drains its output; on success
    the CLI itself writes the login into the shared CODEX_HOME. `spawn_fn` is injectable
    for tests."""
    global _login_proc, _reader_thread

    if codex_cli.is_logged_in():
        return {"error": "already connected"}

    with _lock:
        if _login_proc is not None and _login_proc.poll() is None:
            try:
                _login_proc.kill()
            except Exception:  # noqa: BLE001 — best-effort
                pass
        try:
            proc = spawn_fn(
                [config.codex_cli_binary(), "login", "--device-auth"],
                stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
                env=_login_env(),
            )
        except OSError as e:
            return {"error": f"could not start `codex login` — is the CLI installed? ({e})"}
        _login_proc = proc

    buf = ""
    result: dict = {}
    found = threading.Event()

    def reader() -> None:
        nonlocal buf
        stdout = proc.stdout
        if stdout is not None:
            for line in stdout:
                buf += line
                if not found.is_set():
                    parsed = parse_device_login(buf)
                    # Wait for BOTH: the CLI prints the verification URL and the one-time
                    # code on separate lines ("1. Open this link..." then, a line later,
                    # "2. Enter this one-time code..."). Firing on the URL alone returned
                    # before the code line had even arrived — the console showed a URL
                    # with no code to enter, and the OpenAI page requires one.
                    if "url" in parsed and "code" in parsed:
                        result.update(parsed)
                        result["raw"] = _strip_ansi(buf).strip()
                        found.set()
        if not found.is_set():
            # EOF without ever seeing both — either an error (e.g. rate-limited) or an
            # unexpected CLI output shape. Return whatever text we captured, and take the
            # URL/code if only one showed up, rather than silently succeeding with a code
            # missing from what the admin needs to type in.
            result.update(parse_device_login(buf))
            result["raw"] = _strip_ansi(buf).strip()
            found.set()
        _log_result(proc)

    _reader_thread = threading.Thread(target=reader, daemon=True)
    _reader_thread.start()

    if not found.wait(_START_TIMEOUT_S):
        return {"error": "timed out waiting for the device code"}
    # Require BOTH — a URL with no code isn't something the admin can act on (the OpenAI
    # page demands the code), and would otherwise show as a stuck, uncompletable login.
    if "url" not in result or "code" not in result:
        return {"error": result.get("raw") or "login exited before printing both a link and a code"}
    return result


def codex_login_status() -> dict:
    return {"connected": codex_cli.is_logged_in()}


def disconnect_codex_login() -> None:
    """Forget the login: kill any in-flight child, then `codex logout` against the shared
    CODEX_HOME (the CLI removes its own credential store — the only copy that exists)."""
    global _login_proc
    with _lock:
        proc, _login_proc = _login_proc, None
    if proc is not None:
        try:
            proc.kill()
        except Exception:  # noqa: BLE001
            pass
    try:
        subprocess.run([config.codex_cli_binary(), "logout"], timeout=15,
                       capture_output=True, env=_login_env())
    except Exception:  # noqa: BLE001 — best-effort, CLI may not be installed on this host
        pass
