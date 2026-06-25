"""Engagement + people DATA tools (Memra-grounded). Return facts the agent composes into
whatever deliverable was asked — they do NOT render or publish anything."""

from __future__ import annotations

from typing import Any, Callable

from bott.shared.context import MemraClient
from bott.shared.observability.logging_setup import get_logger

log = get_logger("bott.skills.engagement_data")


def _summarize_memra(r: Any) -> str:
    """Flatten an ask_context response into readable, cited bullet lines."""
    if not isinstance(r, dict):
        return str(r)[:1500]
    ev = r.get("evidence") or []
    if not ev:
        return f"(No supporting context found; verdict: {r.get('verdict', 'unknown')}.)"
    out: list[str] = []
    for e in ev[:8]:
        text = (e.get("text") or "").strip()
        if not text:
            continue
        cit = e.get("citation") or {}
        url, title = cit.get("source_url"), (cit.get("source_title") or "source")
        out.append(f"- {text[:300]}" + (f" <{url}|{title}>" if url else ""))
    return "\n".join(out) or f"(No usable context; verdict: {r.get('verdict', 'unknown')}.)"


def get_engagement_status(engagement: str) -> str:
    """An engagement's current delivery status, open risks, and recent sentiment as DATA
    (cited from Memra). Compose the brief/page yourself; for sprint numbers also call
    build_sprint_dossier / get_sprint_history."""
    try:
        r = MemraClient().ask_context(
            f"Current delivery status, open risks, and recent sentiment for the "
            f"{engagement} engagement, with who from Axelerant is on it."
        )
    except Exception as e:  # noqa: BLE001
        log.error("engagement status failed for %s: %s", engagement, e)
        return f"Couldn't fetch status for '{engagement}' right now ({e})."
    return f"Status for {engagement} (from Memra):\n" + _summarize_memra(r)


def find_people(query: str) -> str:
    """Find Axelerant people by skill/expertise and the engagements they're on, as DATA
    (cited from Memra)."""
    try:
        r = MemraClient().ask_context(
            f"Which Axelerant people have experience with {query}? "
            "List the people and the engagements they are currently on."
        )
    except Exception as e:  # noqa: BLE001
        log.error("find_people failed for %s: %s", query, e)
        return f"Couldn't look up people for '{query}' right now ({e})."
    return f"People matching '{query}' (from Memra):\n" + _summarize_memra(r)


def engagement_data_tools() -> list[Callable]:
    return [get_engagement_status, find_people]
