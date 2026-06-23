"""Codex model backend — auto-start and supervise the local Codex-subscription proxy.

For the single-user POC, models run on the owner's ChatGPT/Codex subscription with no API
key. This module manages that automatically: it starts the `openai-oauth` proxy (which
reuses ``~/.codex/auth.json``), waits until it's ready, supervises it (restart on crash),
and shuts it down with the app. The proxy exposes an OpenAI-compatible endpoint that
``OpenAIChat(base_url=...)`` talks to.

Pluggable: ``MODEL_BACKEND=codex`` (default, dev) auto-starts the proxy and points the
model base URLs at it; ``MODEL_BACKEND=openai`` skips the proxy and uses a sanctioned
``api.openai.com`` key (for multi-user production). See [[codex-subscription-gateway]].
"""

from __future__ import annotations

import os
import shlex
import signal
import subprocess
import threading
import time
from typing import Optional

import httpx

from bott.shared.config import codex_proxy_cmd, codex_proxy_port, model_backend
from bott.shared.observability.logging_setup import get_logger

log = get_logger("model.codex")

CODEX_AUTH = os.path.expanduser("~/.codex/auth.json")
PROXY_LOG = os.getenv("CODEX_PROXY_LOG", "/tmp/bott-codex-proxy.log")


class CodexProxyManager:
    """Starts + supervises the local Codex proxy as a managed child process."""

    def __init__(self, port: Optional[int] = None, cmd: Optional[str] = None) -> None:
        self.port = port or codex_proxy_port()
        self._cmd = cmd or codex_proxy_cmd() or f"npx -y openai-oauth --port {self.port}"
        self._proc: Optional[subprocess.Popen] = None
        self._stop = threading.Event()
        self._watch: Optional[threading.Thread] = None

    @property
    def base_url(self) -> str:
        return f"http://127.0.0.1:{self.port}/v1"

    def is_ready(self, timeout: float = 8.0) -> bool:
        try:
            return httpx.get(f"{self.base_url}/models", timeout=timeout).status_code == 200
        except httpx.HTTPError:
            return False

    def _proc_alive(self) -> bool:
        return self._proc is not None and self._proc.poll() is None

    # Respawn thresholds (× the 5s health interval): a crashed process is replaced quickly;
    # an alive-but-unreachable one is given a long window (transient slowness must not kill it).
    CRASHED_THRESHOLD = 2  # ~10s
    HUNG_THRESHOLD = 24    # ~2min

    @classmethod
    def _should_respawn(cls, misses: int, proc_alive: bool) -> bool:
        return misses >= (cls.HUNG_THRESHOLD if proc_alive else cls.CRASHED_THRESHOLD)

    def _kill_port(self) -> None:
        """Kill any stale process holding the proxy port (so a respawn can bind)."""
        try:
            out = subprocess.run(
                ["lsof", "-ti", f"tcp:{self.port}"], capture_output=True, text=True, timeout=5
            ).stdout.split()
            for pid in out:
                try:
                    os.kill(int(pid), signal.SIGKILL)
                except (ProcessLookupError, ValueError):
                    pass
        except Exception:  # noqa: BLE001 — best-effort
            pass

    def _spawn_and_wait(self, wait_seconds: int) -> None:
        if self.is_ready():
            return
        if not os.path.exists(CODEX_AUTH):
            raise RuntimeError(
                f"No {CODEX_AUTH} — run `npx @openai/codex login` once before starting "
                "(the Codex backend needs your ChatGPT subscription login)."
            )
        self._kill_port()
        log.info("Starting Codex proxy: %s  -> %s", self._cmd, PROXY_LOG)
        logf = open(PROXY_LOG, "ab")  # noqa: SIM115 — handed to the child for its lifetime
        self._proc = subprocess.Popen(shlex.split(self._cmd), stdout=logf, stderr=logf)
        deadline = time.time() + wait_seconds
        while time.time() < deadline:
            if self._proc.poll() is not None:
                raise RuntimeError(f"Codex proxy exited during startup — see {PROXY_LOG}.")
            if self.is_ready():
                log.info("Codex proxy ready on :%s (using your ChatGPT subscription).", self.port)
                return
            time.sleep(1.0)
        raise RuntimeError(f"Codex proxy not ready within {wait_seconds}s — see {PROXY_LOG}.")

    def start(self, wait_seconds: int = 90) -> None:
        if self.is_ready():
            log.info("Codex proxy already up on :%s — reusing.", self.port)
        else:
            self._spawn_and_wait(wait_seconds)
        self._arm_supervisor()

    def _arm_supervisor(self) -> None:
        """Health-check loop. Respawn ONLY when the proxy is genuinely gone — never kill a
        proxy whose process is still alive just because a health check was slow.

        Two cases:
          • The managed child process has EXITED (crashed) -> respawn after a few misses.
          • The process is still alive but /v1/models isn't answering -> it's almost always
            transient slowness (token refresh, a busy tick). Leave it running; only force a
            respawn if it stays unreachable for a long sustained window (likely truly hung).
        A slow tick used to nuke a working proxy and cold-start npx, creating the very
        downtime that killed in-flight runs — this avoids that self-inflicted outage."""
        if self._watch is not None and self._watch.is_alive():
            return

        def loop() -> None:
            backoff = 2.0
            misses = 0
            while not self._stop.wait(5.0):
                if self.is_ready():
                    backoff = 2.0
                    misses = 0
                    continue
                misses += 1
                alive = self._proc_alive()
                if not self._should_respawn(misses, alive):
                    threshold = self.HUNG_THRESHOLD if alive else self.CRASHED_THRESHOLD
                    log.warning("Codex proxy health check missed (%d/%d, process %s) — not "
                                "respawning yet.", misses, threshold,
                                "alive" if alive else "exited")
                    continue
                log.warning("Codex proxy %s after %d misses — respawning.",
                            "hung" if alive else "exited", misses)
                try:
                    self._spawn_and_wait(60)
                    misses = 0
                    log.info("Codex proxy recovered.")
                except Exception as e:  # noqa: BLE001 — keep trying on the next tick
                    log.error("Codex proxy respawn failed: %s (retrying in %ss)", e, backoff)
                    self._stop.wait(backoff)
                    backoff = min(backoff * 2, 30.0)
        self._watch = threading.Thread(target=loop, daemon=True)
        self._watch.start()

    def stop(self) -> None:
        self._stop.set()
        if self._proc is not None and self._proc.poll() is None:
            self._proc.terminate()
            try:
                self._proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self._proc.kill()
        self._proc = None


def start_model_backend() -> Optional[CodexProxyManager]:
    """Bring the configured model backend online before any agent is built. Returns the
    proxy manager (to stop on shutdown) for the codex backend, else None."""
    backend = model_backend()
    if backend == "codex":
        mgr = CodexProxyManager()
        mgr.start()
        # Point both roles' model base URLs at the proxy (overrides any stale .env value).
        os.environ["REVIEW_MODEL_BASE_URL"] = mgr.base_url
        os.environ["MANAGER_MODEL_BASE_URL"] = mgr.base_url
        return mgr
    if backend == "openai":
        # Sanctioned key path — make sure no proxy base URL leaks in.
        os.environ.pop("REVIEW_MODEL_BASE_URL", None)
        os.environ.pop("MANAGER_MODEL_BASE_URL", None)
        return None
    raise RuntimeError(f"Unknown MODEL_BACKEND={backend!r} (use 'codex' or 'openai').")
