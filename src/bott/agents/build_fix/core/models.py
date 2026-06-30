from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class BuildRequest:
    kind: str  # "request" | "github_issue" | "jira"
    text: str = ""
    owner: str | None = None
    repo: str | None = None
    issue: int | None = None
    jira_key: str | None = None


@dataclass
class ImplementPlan:
    summary: str
    steps: list[str] = field(default_factory=list)
    files_touched: list[str] = field(default_factory=list)
    test_plan: str = ""
    risks: str = ""


@dataclass
class ImplementResult:
    opened_pr: bool
    tests: str  # "green" | "failing" | "not_run"
    pr_url: str | None = None
    branch: str | None = None
    note: str = ""
    diff_summary: str = ""
