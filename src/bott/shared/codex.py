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

    def is_ready(self, timeout: float = 3.0) -> bool:
        try:
            return httpx.get(f"{self.base_url}/models", timeout=timeout).status_code == 200
        except httpx.HTTPError:
            return False

    def start(self, wait_seconds: int = 90) -> None:
        if self.is_ready():
            log.info("Codex proxy already up on :%s — reusing.", self.port)
            return
        if not os.path.exists(CODEX_AUTH):
            raise RuntimeError(
                f"No {CODEX_AUTH} — run `npx @openai/codex login` once before starting "
                "(the Codex backend needs your ChatGPT subscription login)."
            )
        log.info("Starting Codex proxy: %s  -> %s", self._cmd, PROXY_LOG)
        logf = open(PROXY_LOG, "ab")  # noqa: SIM115 — handed to the child for its lifetime
        self._proc = subprocess.Popen(shlex.split(self._cmd), stdout=logf, stderr=logf)
        deadline = time.time() + wait_seconds
        while time.time() < deadline:
            if self._proc.poll() is not None:
                raise RuntimeError(f"Codex proxy exited during startup — see {PROXY_LOG}.")
            if self.is_ready():
                log.info("Codex proxy ready on :%s (using your ChatGPT subscription).", self.port)
                self._arm_watchdog()
                return
            time.sleep(1.0)
        raise RuntimeError(f"Codex proxy not ready within {wait_seconds}s — see {PROXY_LOG}.")

    def _arm_watchdog(self) -> None:
        def loop() -> None:
            while not self._stop.wait(5.0):
                if self._proc is not None and self._proc.poll() is not None and not self._stop.is_set():
                    log.warning("Codex proxy died — restarting.")
                    try:
                        self._proc = None
                        self.start()
                    except Exception as e:  # noqa: BLE001
                        log.error("Codex proxy restart failed: %s", e)
                    return  # start() re-arms a fresh watchdog
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
