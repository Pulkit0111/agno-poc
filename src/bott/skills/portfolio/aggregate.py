"""Pure aggregation of Memra ``engagements_at_risk`` rows into a portfolio summary.

No I/O — takes the raw engagement dicts and returns counts + a risk-ranked list, so it's
fully unit-testable. Matches Memra's real schema: numeric ``overall_sentiment`` and
``trend_vs_prior`` (direction derived from the sign), ``risk_band`` / ``risk_score``."""

from __future__ import annotations

from dataclasses import dataclass, field

_BAND_ORDER = {"high": 0, "medium": 1, "low": 2}
_TREND_EPS = 0.05  # deadband: |trend_vs_prior| <= this counts as flat


def _g(e: dict, *names: str, default=None):
    for n in names:
        v = e.get(n)
        if v is not None and v != "":
            return v
    return default


def _num(e: dict, *names: str) -> float:
    try:
        return float(_g(e, *names, default=0) or 0)
    except (TypeError, ValueError):
        return 0.0


@dataclass
class PortfolioRow:
    account: str
    engagement_id: str
    band: str  # high | medium | low | unknown
    score: float  # risk_score
    sentiment: float  # overall_sentiment (numeric, ~ -1..1)
    trend: float  # trend_vs_prior (numeric; sign = direction)
    velocity: str = "—"  # display string for the table (Jira last sprint, best-effort)
    vel_stories: int | None = None  # numeric, for the velocity chart
    vel_points: float | None = None
    detail: str = ""  # "N engagements" sub-label when an account rolls up >1 engagement
    children: list[dict] = field(default_factory=list)  # per-channel rows for the drill-down


@dataclass
class Portfolio:
    rows: list[PortfolioRow] = field(default_factory=list)
    total: int = 0
    high: int = 0
    medium: int = 0
    low: int = 0
    declining: int = 0
    improving: int = 0
    flat: int = 0
    avg_sentiment: float = 0.0


def is_declining(trend: float) -> bool:
    return trend < -_TREND_EPS


def is_improving(trend: float) -> bool:
    return trend > _TREND_EPS


def summarize(engagements: list[dict]) -> Portfolio:
    """Roll engagements up to ONE row per ACCOUNT (leadership view), ranked at-risk-first.

    An account can have several engagements (each a Slack channel); we combine them
    escalation-first: risk = the WORST engagement, sentiment = the WORST (lowest) channel,
    trend = activity-weighted average (busier channels count more), plus a 'N engagements'
    sub-label when >1."""
    parsed: list[dict] = []
    for e in engagements or []:
        if not isinstance(e, dict):
            continue
        parsed.append({
            "engagement_id": str(_g(e, "engagement_id", "id", default="")),
            "account": str(_g(e, "account", "name", "engagement_id", default="?")) or "?",
            "band": str(_g(e, "risk_band", "band", default="") or "").lower() or "unknown",
            "score": _num(e, "risk_score", "score"),
            "sentiment": _num(e, "overall_sentiment", "sentiment", "weekly_sentiment"),
            "trend": _num(e, "trend_vs_prior", "trend", "sentiment_trend"),
            "weight": _num(e, "recent_message_count", "sample_size") or 1.0,
        })

    groups: dict[str, list[dict]] = {}
    for p in parsed:
        groups.setdefault(p["account"], []).append(p)

    rows: list[PortfolioRow] = []
    for account, items in groups.items():
        wsum = sum(x["weight"] for x in items) or 1.0
        # Per-channel children for the drill-down (only when an account has >1 engagement);
        # 'channel' is filled in later (Memra+Slack) — kept as engagement_id for now.
        children = [{
            "engagement_id": x["engagement_id"], "channel": "", "band": x["band"],
            "sentiment": round(x["sentiment"], 3), "trend": round(x["trend"], 3),
        } for x in sorted(items, key=lambda x: _BAND_ORDER.get(x["band"], 3))] if len(items) > 1 else []
        rows.append(PortfolioRow(
            account=account,
            engagement_id="",
            band=min(items, key=lambda x: _BAND_ORDER.get(x["band"], 3))["band"],  # worst
            score=max(x["score"] for x in items),  # worst
            sentiment=round(min(x["sentiment"] for x in items), 3),  # worst (lowest) channel
            trend=round(sum(x["trend"] * x["weight"] for x in items) / wsum, 3),  # volume-weighted
            detail=(f"{len(items)} engagements" if len(items) > 1 else ""),
            children=children,
        ))
    rows.sort(key=lambda r: (_BAND_ORDER.get(r.band, 3), -r.score))
    total = len(rows)
    declining = sum(1 for r in rows if is_declining(r.trend))
    improving = sum(1 for r in rows if is_improving(r.trend))
    return Portfolio(
        rows=rows,
        total=total,
        high=sum(1 for r in rows if r.band == "high"),
        medium=sum(1 for r in rows if r.band == "medium"),
        low=sum(1 for r in rows if r.band == "low"),
        declining=declining,
        improving=improving,
        flat=max(0, total - declining - improving),
        avg_sentiment=round(sum(r.sentiment for r in rows) / total, 3) if total else 0.0,
    )
