"""Read-only Confluence connector — wraps agno ConfluenceTools, exposing only read functions
via an include_tools allowlist (no create/update). Shared org data."""

from __future__ import annotations

from typing import Callable

from bott.shared import config
from bott.shared.observability.logging_setup import get_logger

log = get_logger("bott.connectors.confluence")

# Read-only allowlist (verified against agno ConfluenceTools): no create_page/update_page.
_READ_TOOLS = ["get_page_content", "get_all_space_detail", "get_space_key", "get_all_page_from_space"]


def confluence_read_tools() -> list[Callable]:
    if not config.confluence_configured():
        return []
    try:
        from agno.tools.confluence import ConfluenceTools

        return [ConfluenceTools(
            url=config.confluence_url(),
            username=config.confluence_username(),
            api_key=config.confluence_api_key(),
            include_tools=_READ_TOOLS,
        )]
    except Exception as e:  # noqa: BLE001 — missing lib/creds → just no Confluence tools
        log.warning("Confluence tools unavailable: %s", e)
        return []
