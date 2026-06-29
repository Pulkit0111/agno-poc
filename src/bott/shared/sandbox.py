"""Sandbox runner seam. Self-authored tools execute ONLY through a SandboxRunner —
isolated, resource-limited, no cross-user data. The real implementation lands in the
self-authored-tools phase; this declares the interface so the approval gate and tool
registry can be built against it now."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class SandboxResult:
    ok: bool
    stdout: str
    stderr: str


class SandboxRunner:
    def run(self, code: str, *, user_id: str, timeout: float) -> SandboxResult:
        raise NotImplementedError


class UnavailableSandbox(SandboxRunner):
    """Default until the sandbox is implemented — refuses to run code."""

    def run(self, code: str, *, user_id: str, timeout: float) -> SandboxResult:
        raise NotImplementedError(
            "No sandbox runner is configured — self-authored tool execution is disabled "
            "until the sandbox phase is implemented."
        )
