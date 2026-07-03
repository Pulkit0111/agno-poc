"""Channel → engagement mapping.

Lets a user pin "this channel is about engagement X" so follow-ups like "the engagement" or
"who's on this?" resolve without re-asking. Stored in the settings KV (keyed by channel id),
so no new table/migration. The channel id comes from the Slack interface via run_context
dependencies (same source the build tool uses)."""

from __future__ import annotations

from typing import Callable, Optional

from agno.run import RunContext
from agno.tools import tool

from bott.shared.persistence.records import get_setting, set_setting

_KEY = "channel_engagement:{}"


def _channel(run_context) -> Optional[str]:
    deps = (getattr(run_context, "dependencies", None) or {}) if run_context else {}
    return deps.get("Slack channel_id")


def _map_impl(run_context, engagement: str) -> str:
    cid = _channel(run_context)
    if not cid:
        return "I couldn't tell which channel this is, so I can't map it."
    eng = (engagement or "").strip()
    if not eng:
        return "Tell me which engagement to map this channel to (a name or Jira key)."
    set_setting(_KEY.format(cid), eng)
    return f"Mapped this channel to *{eng}*. I'll take “this engagement” here to mean {eng}."


def _resolve_impl(run_context) -> str:
    cid = _channel(run_context)
    return (get_setting(_KEY.format(cid)) if cid else None) or ""


def _unmap_impl(run_context) -> str:
    cid = _channel(run_context)
    if not cid:
        return "I couldn't tell which channel this is."
    set_setting(_KEY.format(cid), "")
    return "Cleared this channel's engagement mapping."


def channel_map_tools() -> list[Callable]:
    @tool(name="map_channel_to_engagement")
    def map_channel_to_engagement(run_context: RunContext, engagement: str) -> str:
        """Map THIS Slack channel to an engagement (name or Jira key) so future asks like
        "the engagement" / "who's on this?" resolve here without re-asking."""
        return _map_impl(run_context, engagement)

    @tool(name="channel_engagement")
    def channel_engagement(run_context: RunContext) -> str:
        """The engagement this channel is mapped to (if any). Consult this BEFORE asking the
        user "which engagement?" when they refer to "this"/"the" engagement in a channel."""
        return _resolve_impl(run_context) or "(this channel isn't mapped to an engagement)"

    @tool(name="unmap_channel_engagement")
    def unmap_channel_engagement(run_context: RunContext) -> str:
        """Remove this channel's engagement mapping."""
        return _unmap_impl(run_context)

    return [map_channel_to_engagement, channel_engagement, unmap_channel_engagement]
