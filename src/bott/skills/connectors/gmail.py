"""Domain-delegated, read-only Gmail connector. Each call impersonates the VERIFIED
caller (run_context.user_id) via Google Workspace domain-wide delegation — so a user only
ever reads their OWN mail. The mailbox is never a tool parameter and never GOOGLE_DELEGATED_USER."""

from __future__ import annotations

from typing import Callable

from agno.run import RunContext
from agno.tools import tool

from bott.shared import config
from bott.shared.identity import IsolationError, require_user_id
from bott.shared.observability.logging_setup import get_logger, redact

log = get_logger("bott.connectors.gmail")

# Module-level guarded import: importing this Agno submodule RAISES if the Google client
# libs are absent, so we swallow it here and gate on GmailTools being non-None. Tests patch
# this module attribute with a stub, so the import guard is transparent to them.
try:
    from agno.tools.google.gmail import GmailTools
except Exception:  # noqa: BLE001 — libs missing → connector self-disables
    GmailTools = None

GMAIL_READONLY = "https://www.googleapis.com/auth/gmail.readonly"
_NO_IDENTITY = "I couldn't tell who you are, so I won't read any mail."


def _impersonated(run_context):
    """Build a GmailTools impersonating the VERIFIED caller. The caller is
    run_context.user_id ONLY — never a model param or GOOGLE_DELEGATED_USER."""
    if GmailTools is None:
        raise RuntimeError("Gmail client unavailable (Google libs not installed).")
    email = require_user_id(getattr(run_context, "user_id", None))  # raises IsolationError if blank
    return GmailTools(
        service_account_path=config.google_service_account_path(),
        delegated_user=email,
        scopes=[GMAIL_READONLY],
        # Read-only is structural: enable ONLY the two read methods Bott calls;
        # every other GmailTools function is disabled so the toolkit matches gmail.readonly
        # (leaving compose/modify defaults on makes GmailTools.__init__ raise ValueError).
        search_emails=True,
        get_thread=True,
        get_latest_emails=False,
        get_emails_from_user=False,
        get_unread_emails=False,
        get_starred_emails=False,
        get_emails_by_context=False,
        get_emails_by_date=False,
        get_emails_by_thread=False,
        get_message=False,
        search_threads=False,
        mark_email_as_read=False,
        mark_email_as_unread=False,
        star_email=False,
        unstar_email=False,
        archive_email=False,
        create_draft_email=False,
        send_email=False,
        send_email_reply=False,
        list_custom_labels=False,
        apply_label=False,
        remove_label=False,
        delete_custom_label=False,
        modify_thread_labels=False,
        trash_thread=False,
        get_draft=False,
        list_drafts=False,
        send_draft=False,
        update_draft=False,
        list_labels=False,
        modify_message_labels=False,
        trash_message=False,
        download_attachment=False,
    )


def _gmail_search_impl(run_context, query: str, limit: int = 10) -> str:
    try:
        gt = _impersonated(run_context)
    except IsolationError:
        return _NO_IDENTITY  # fail closed — never construct GmailTools, never a default mailbox
    except Exception as e:  # noqa: BLE001 — e.g. RuntimeError when Google libs absent
        log.error("gmail search failed: %s", redact(str(e)))
        return "Couldn't reach Gmail right now."
    try:
        return gt.search_emails(query, limit)
    except Exception as e:  # noqa: BLE001
        log.error("gmail search failed: %s", redact(str(e)))
        return "Couldn't reach Gmail right now."


def _gmail_read_thread_impl(run_context, thread_id: str) -> str:
    try:
        gt = _impersonated(run_context)
    except IsolationError:
        return _NO_IDENTITY
    except Exception as e:  # noqa: BLE001 — e.g. RuntimeError when Google libs absent
        log.error("gmail read_thread failed: %s", redact(str(e)))
        return "Couldn't reach Gmail right now."
    try:
        return gt.get_thread(thread_id)
    except Exception as e:  # noqa: BLE001
        log.error("gmail read_thread failed: %s", redact(str(e)))
        return "Couldn't reach Gmail right now."


def gmail_read_tools() -> list[Callable]:
    """Read-only Gmail tools, gated at the factory (matches jira/confluence/slack): no tools
    unless the Google libs imported AND domain-wide delegation is configured."""
    if GmailTools is None or not config.google_delegation_configured():
        return []

    @tool(name="gmail_search")
    def gmail_search(run_context: RunContext, query: str, limit: int = 10) -> str:
        """Search YOUR Gmail (read-only). `query` uses Gmail search syntax
        (e.g. 'from:alice newer_than:7d'). Returns matching messages."""
        return _gmail_search_impl(run_context, query, limit)

    @tool(name="gmail_read_thread")
    def gmail_read_thread(run_context: RunContext, thread_id: str) -> str:
        """Read one of YOUR Gmail threads by id (read-only)."""
        return _gmail_read_thread_impl(run_context, thread_id)

    return [gmail_search, gmail_read_thread]
