"""Shared pure data types (no I/O), used by the gate, fetcher, and runner.

Kept dependency-free so the verdict gate stays unit-testable without GitHub/LLM.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

CiOverall = Literal["pass", "fail", "pending", "none"]
FileStatus = Literal[
    "added", "modified", "removed", "renamed", "copied", "changed", "unchanged"
]


@dataclass
class CiCheck:
    name: str


@dataclass
class CiStatus:
    """Aggregated CI state for the PR head (port of CiStatus in git-provider.ts)."""

    overall: CiOverall
    failing: list[CiCheck] = field(default_factory=list)
    pending: list[CiCheck] = field(default_factory=list)
    passing: list[CiCheck] = field(default_factory=list)


@dataclass
class ToolCallTrace:
    """One recorded tool call (port of ToolCallTrace in agent.ts). The gate reads
    `name` + `args` to enforce lookup-ratio and claims-backed-by-tools."""

    name: str
    args: dict[str, Any]
    result_summary: str = ""


@dataclass
class FileChange:
    """A changed file in the PR."""

    filename: str
    status: FileStatus
    additions: int
    deletions: int
    patch: str | None = None
