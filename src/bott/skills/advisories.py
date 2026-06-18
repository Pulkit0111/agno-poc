"""Drupal security-advisory skill.

Fetches the latest advisories from Drupal.org's machine-readable feed and renders a
ready-to-post Slack digest (grouped by severity). Exposed as an agent tool so a scheduled
flow can post it daily AND so people can ask Bott for it in chat / follow up in-thread.

Feed: https://www.drupal.org/api-d7/node.json?type=sa  (core + contrib, JSON).
The numeric x/25 risk score is not in the feed (Drupal computes it from the criticality
vector); we surface the authoritative severity LABEL instead of guessing a number.
"""

from __future__ import annotations

import re
import time
from collections import Counter
from datetime import datetime, timezone
from typing import Any, Callable

import httpx

from bott.shared.observability.logging_setup import get_logger

log = get_logger("bott.skills.advisories")

ENDPOINT = "https://www.drupal.org/api-d7/node.json?type=sa&sort=created&direction=DESC"

# Drupal severity labels -> (sort rank, emoji). Lower rank = more severe.
_SEVERITY = {
    "highly critical": (0, "🔴"),
    "critical": (1, "🔴"),
    "moderately critical": (2, "🟠"),
    "less critical": (3, "🟡"),
    "not critical": (4, "⚪"),
}


def _text(value: Any) -> str:
    """Drupal fields like description/solution come as {'value': '<html>'}; flatten to
    plain text."""
    if isinstance(value, dict):
        value = value.get("value", "")
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", str(value or ""))).strip()


def _first_sentences(text: str, n: int = 2, cap: int = 320) -> str:
    if not text:
        return ""
    sentences = re.split(r"(?<=[.!?])\s+", text)
    out = " ".join(sentences[:n]).strip()
    return (out[: cap - 1] + "…") if len(out) > cap else out


# Words that signal the *impact* sentence (vs. the module's marketing blurb). Lowercase
# stems match as substrings; acronyms need word boundaries (else "source" matches "RCE").
_RISK_STEM = re.compile(
    r"(vulnerab|inject|attack|malicious|exploit|bypass|forger|redirect|disclos|escalat|"
    r"seriali|arbitrary|unauthor|poison|spoof|traversal|overflow)",
    re.IGNORECASE,
)
_RISK_ACRONYM = re.compile(r"\b(XSS|SQL|RCE|SSRF|CSRF)\b")  # case-sensitive, word-boundary


def _impact_sentence(text: str, cap: int = 200) -> str:
    """The sentence that describes the actual risk, skipping the 'The X module provides…'
    marketing lead-in. Falls back to the first sentence."""
    if not text:
        return ""
    sentences = re.split(r"(?<=[.!?])\s+", text)
    chosen = next(
        (s for s in sentences if _RISK_STEM.search(s) or _RISK_ACRONYM.search(s)),
        sentences[0] if sentences else "",
    )
    chosen = chosen.strip()
    return (chosen[: cap - 1] + "…") if len(chosen) > cap else chosen


def _severity_meta(label: str) -> tuple[int, str]:
    return _SEVERITY.get((label or "").strip().lower(), (9, "⚪"))


def _fix_summary(solution: str) -> str:
    """Pull just the upgrade target(s) out of Drupal's verbose solution text.

    '…upgrade to plotly_js-3.0.2.' -> 'plotly_js-3.0.2'
    multi-version core notes -> 'Drupal 11.3.12 / 11.2.14 / 10.6.11 / 10.5.12'
    """
    if not solution:
        return ""
    targets = re.findall(r"(?:upgrade|update) to (.+?)\s*\.(?=\s|$)", solution, flags=re.IGNORECASE)
    cleaned: list[str] = []
    seen: set[str] = set()
    for t in targets:
        t = t.strip().strip(",").strip()
        if t and t.lower() not in seen:
            seen.add(t.lower())
            cleaned.append(t)
    if not cleaned:
        # No clear target — drop the boilerplate preamble and return one sentence.
        s = re.sub(r"^\s*Install the latest version:?\s*", "", solution, flags=re.IGNORECASE)
        return _first_sentences(s, 1, 160)
    # Collapse repeated 'Drupal ' prefixes for readability.
    if len(cleaned) > 1 and all(c.startswith("Drupal ") for c in cleaned):
        return " / ".join([cleaned[0], *(c[len("Drupal "):] for c in cleaned[1:])])
    return " / ".join(cleaned)


def parse_advisories(raw: list[dict], now_epoch: int, window_days: int) -> list[dict]:
    """Filter to advisories published within the window and normalize to flat dicts,
    sorted most-severe first. Pure (no I/O) so it's unit-testable."""
    cutoff = now_epoch - window_days * 86_400
    out: list[dict] = []
    for it in raw:
        created = int(it.get("created") or 0)
        if created < cutoff:
            continue
        url = (it.get("url") or "").rstrip("/")
        sa_id = url.split("/")[-1].upper() if url else str(it.get("field_sa_advisory_id") or "")
        # Title shape: "{project} - {severity} - {type} - {SA-ID}".
        parts = [p.strip() for p in str(it.get("title") or "").split(" - ")]
        project = parts[0] if parts else ""
        severity = parts[1] if len(parts) > 1 else ""
        vtype = " - ".join(parts[2:-1]) if len(parts) > 3 else (
            _text(it.get("field_sa_type")) or (parts[2] if len(parts) > 2 else "")
        )
        cves = it.get("field_sa_cve") or []
        if isinstance(cves, str):
            cves = [cves]
        rank, icon = _severity_meta(severity)
        out.append({
            "sa_id": sa_id,
            "project": project,
            "severity": severity,
            "severity_rank": rank,
            "icon": icon,
            "type": vtype,
            "cve": ", ".join(c for c in cves if c),
            "summary": _impact_sentence(_text(it.get("field_sa_description"))),
            "fix": _fix_summary(_text(it.get("field_sa_solution"))),
            "url": url,
            "created": created,
        })
    out.sort(key=lambda a: (a["severity_rank"], a["sa_id"]))
    return out


def render_digest(advisories: list[dict]) -> str:
    """Render the Slack mrkdwn digest (grouped by severity). Pure/testable."""
    if not advisories:
        return "🔒 *Drupal Security Advisories* — no new advisories in the window. ✅"
    latest = max(a["created"] for a in advisories)
    date_label = datetime.fromtimestamp(latest, timezone.utc).strftime("%B %-d, %Y")
    counts = Counter(a["severity"] for a in advisories)
    counts_line = " · ".join(
        f"{n} {label}" for label, n in sorted(counts.items(), key=lambda kv: _severity_meta(kv[0])[0])
    )
    n = len(advisories)
    lines = [
        f"🔒 *Drupal Security Advisories — {date_label}*",
        f"_{n} advisor{'y' if n == 1 else 'ies'}: {counts_line}_",
        "",
    ]
    for a in advisories:
        lines.append(f"{a['icon']} *{a['severity']} — {a['project']}*")
        # Make the advisory ID the link (a labeled link, so there's no bare URL to unfurl).
        id_part = f"<{a['url']}|{a['sa_id']}>" if a["url"] else a["sa_id"]
        meta = " | ".join(x for x in (id_part, a["type"], a["cve"]) if x)
        if meta:
            lines.append(meta)
        if a["summary"]:
            lines.append(a["summary"])
        if a["fix"]:
            lines.append(f"✅ Fix: {a['fix']}")
        lines.append("")
    return "\n".join(lines).strip()


def _fetch_raw(timeout: float = 20.0) -> list[dict]:
    r = httpx.get(ENDPOINT, timeout=timeout, headers={"User-Agent": "bott-poc/1.0"})
    r.raise_for_status()
    return (r.json() or {}).get("list", [])


def drupal_security_advisories(window_days: int = 2) -> str:
    """Get the latest Drupal security advisories (core + contrib) as a ready-to-post Slack
    digest, grouped by severity.

    Args:
        window_days: How many days back to include (default 2 — catches the latest batch).
    """
    try:
        raw = _fetch_raw()
    except Exception as e:  # noqa: BLE001 — report, don't crash the run
        log.error("drupal advisories fetch failed: %s", e)
        return f"Couldn't fetch Drupal security advisories right now ({e})."
    now = int(time.time())
    return render_digest(parse_advisories(raw, now, window_days))


def post_drupal_security_advisories(channel: str, window_days: int = 2) -> str:
    """Fetch the latest Drupal advisories and POST the digest to a Slack channel WITH LINK
    PREVIEWS DISABLED. Use this for the scheduled security digest (not the plain Slack post
    tool, which would unfurl every advisory URL into a card).

    Args:
        channel: Slack channel id or name to post to.
        window_days: How many days back to include (default 2).
    """
    import os

    from slack_sdk import WebClient

    text = drupal_security_advisories(window_days)
    token = os.getenv("SLACK_BOT_TOKEN") or os.getenv("SLACK_TOKEN")
    if not token:
        return "No Slack token configured; couldn't post the advisories."
    try:
        WebClient(token=token).chat_postMessage(
            channel=channel, text=text, unfurl_links=False, unfurl_media=False
        )
    except Exception as e:  # noqa: BLE001
        log.error("post advisories to %s failed: %s", channel, e)
        return f"Couldn't post the advisories to {channel} ({e})."
    return f"Posted the Drupal security digest to {channel} (link previews off)."


def security_tools() -> list[Callable]:
    return [drupal_security_advisories, post_drupal_security_advisories]
