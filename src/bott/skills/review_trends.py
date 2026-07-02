"""review_trends tool — descriptive statistics from stored PR-review traces.

These are raw counts over the review_traces table (verdict distribution, volume
over time, per-repo counts, re-review verdict changes). There are NO ground-truth
labels in the data, so accuracy / false-positive / missed-blocker metrics cannot
be derived — the output is explicitly labelled as descriptive counts only.
"""

from __future__ import annotations

import time
from typing import Callable

from agno.tools import tool

from bott.shared.persistence.records import trace_stats

_DISCLAIMER = (
    "Note: these are descriptive counts from stored review traces, "
    "not accuracy or quality metrics. No ground-truth labels exist in the data."
)


def _format_stats(stats: dict, days: int) -> str:
    """Format a trace_stats dict into a human-readable summary string."""
    total = stats["total"]
    if total == 0:
        return (
            f"No review traces found in the last {days} day(s).\n\n{_DISCLAIMER}"
        )

    lines: list[str] = [
        _DISCLAIMER,
        "",
        f"*PR Review Trends — last {days} day(s)*",
        f"Total reviews: {total}",
        "",
    ]

    # Verdict distribution
    by_verdict = stats["by_verdict"]
    if by_verdict:
        lines.append("*Verdict distribution:*")
        for verdict, count in sorted(by_verdict.items(), key=lambda x: -x[1]):
            pct = round(100.0 * count / total) if total else 0
            lines.append(f"  {verdict}: {count} ({pct}%)")
        lines.append("")

    # Top repos
    by_repo = stats["by_repo"]
    if by_repo:
        lines.append("*Top repos by review volume:*")
        for repo, count in by_repo[:10]:
            lines.append(f"  {repo}: {count}")
        lines.append("")

    # Re-review verdict changes
    rereview_changed = stats["rereview_changed"]
    lines.append(
        f"*Re-reviews that changed verdict:* {rereview_changed}"
    )
    lines.append("")

    # Volume over time (weekly buckets)
    by_week = stats["by_week"]
    if by_week:
        lines.append("*Volume by week (ISO):*")
        for week, count in by_week.items():
            bar = "█" * min(count, 20)
            lines.append(f"  {week}: {count:>4}  {bar}")

    return "\n".join(lines)


def review_trends_impl(days: int = 30) -> str:
    """Compute and format descriptive PR-review trend statistics.

    Summarises verdict distribution, volume over time, per-repo counts, and
    how often a re-review changed the verdict — all within the last `days` days.

    *These are descriptive counts, not accuracy or quality metrics.*
    """
    since = time.time() - days * 86400
    stats = trace_stats(since_epoch=since)
    return _format_stats(stats, days)


def review_trends_tools() -> list[Callable]:
    """Return the review_trends tool (read-only, no self-gating needed)."""

    @tool(name="review_trends")
    def review_trends(days: int = 30) -> str:
        """Show descriptive PR-review statistics from stored traces (last N days).

        Reports verdict distribution, top repos by volume, how many re-reviews
        changed the verdict, and a weekly volume chart. These are raw counts —
        not accuracy or quality metrics (no ground-truth labels exist).
        """
        return review_trends_impl(days)

    return [review_trends]
