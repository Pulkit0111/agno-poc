"""Domain-delegated, read-only Google Drive connector. Each call impersonates the VERIFIED
caller (run_context.user_id) via Google Workspace domain-wide delegation — so a user only
ever reads their OWN Drive. The Drive identity is never a tool parameter and never
GOOGLE_DELEGATED_USER."""

from __future__ import annotations

from typing import Callable

from agno.run import RunContext
from agno.tools import tool

from bott.shared import config
from bott.shared.identity import IsolationError, require_user_id
from bott.shared.observability.logging_setup import get_logger, redact

log = get_logger("bott.connectors.drive")

# Module-level guarded import: importing this Agno submodule RAISES if the Google client
# libs are absent, so we swallow it here and gate on GoogleDriveTools being non-None. Tests
# patch this module attribute with a stub, so the import guard is transparent to them.
try:
    from agno.tools.google.drive import GoogleDriveTools
except Exception:  # noqa: BLE001 — libs missing → connector self-disables
    GoogleDriveTools = None

DRIVE_READONLY = "https://www.googleapis.com/auth/drive.readonly"
_NO_IDENTITY = "I couldn't tell who you are, so I won't read any Drive files."


def _impersonated(run_context):
    """Build a GoogleDriveTools impersonating the VERIFIED caller. The caller is
    run_context.user_id ONLY — never a model param or GOOGLE_DELEGATED_USER."""
    email = require_user_id(getattr(run_context, "user_id", None))  # raises IsolationError if blank
    if GoogleDriveTools is None:
        raise RuntimeError("Drive client unavailable (Google libs not installed).")
    return GoogleDriveTools(
        service_account_path=config.google_service_account_path(),
        delegated_user=email,
        scopes=[DRIVE_READONLY],
        # Read-only is structural: enable ONLY the two read methods Bott calls;
        # every other GoogleDriveTools function is disabled so the toolkit matches
        # drive.readonly scope.
        search_files=True,
        read_file=True,
        list_files=False,
        upload_file=False,
        download_file=False,
    )


def _drive_search_impl(run_context, query: str, limit: int = 10) -> str:
    try:
        gt = _impersonated(run_context)
    except IsolationError:
        return _NO_IDENTITY  # fail closed — never construct GoogleDriveTools, never a default user
    except Exception as e:  # noqa: BLE001 — e.g. RuntimeError when Google libs absent
        log.error("drive search failed: %s", redact(str(e)))
        return "Couldn't reach Drive right now."
    try:
        return gt.search_files(query, limit)
    except Exception as e:  # noqa: BLE001
        log.error("drive search failed: %s", redact(str(e)))
        return "Couldn't reach Drive right now."


def _drive_read_file_impl(run_context, file_id: str) -> str:
    try:
        gt = _impersonated(run_context)
    except IsolationError:
        return _NO_IDENTITY
    except Exception as e:  # noqa: BLE001 — e.g. RuntimeError when Google libs absent
        log.error("drive read_file failed: %s", redact(str(e)))
        return "Couldn't reach Drive right now."
    try:
        return gt.read_file(file_id)
    except Exception as e:  # noqa: BLE001
        log.error("drive read_file failed: %s", redact(str(e)))
        return "Couldn't reach Drive right now."


def drive_read_tools() -> list[Callable]:
    """Read-only Google Drive tools, gated at the factory (matches jira/confluence/slack): no tools
    unless the Google libs imported AND domain-wide delegation is configured."""
    if GoogleDriveTools is None or not config.google_delegation_configured():
        return []

    @tool(name="drive_search")
    def drive_search(run_context: RunContext, query: str, limit: int = 10) -> str:
        """Search YOUR Google Drive (read-only). `query` is Drive search syntax
        (e.g. 'title contains "report" and modifiedTime > "2024-01-01"'). Returns matching files."""
        return _drive_search_impl(run_context, query, limit)

    @tool(name="drive_read_file")
    def drive_read_file(run_context: RunContext, file_id: str) -> str:
        """Read the content/metadata of one of YOUR Drive files by id (read-only)."""
        return _drive_read_file_impl(run_context, file_id)

    return [drive_search, drive_read_file]
