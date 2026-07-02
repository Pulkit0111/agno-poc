"""Harden Agno's vendored Slack interface against unrecoverable post failures.

Agno's ``handle_non_streaming`` posts the agent's reply and, on ANY exception, falls
back to ``send_error`` — which posts again. When the target channel can't be posted to
(a read-only channel, the bot isn't in the channel, it's archived, ...) BOTH posts raise
``SlackApiError``, and the *second* raise is uncaught: it surfaces as an ASGI 500 and a
stack-trace flood in the logs (observed in production on a read-only channel).

Agno exposes no hook to intervene, but every post — reply, reasoning, re-review, and the
error fallback — routes through the module-level ``send_slack_message_async`` imported into
``event_handler``. We wrap that one attribute so the small set of non-retryable
"can't post here" errors are logged once and swallowed; retryable/unknown errors (and any
non-Slack error) propagate unchanged. Installed once at app startup.
"""

from __future__ import annotations

from typing import Any, Callable

from bott.shared.observability.logging_setup import get_logger

log = get_logger("bott.slack_hardening")

# Slack error codes meaning "this message will never post to this channel": retrying or
# bubbling the error cannot help, so a single warning is the correct outcome.
NON_POSTABLE_ERRORS = frozenset(
    {
        "restricted_action_read_only_channel",
        "not_in_channel",
        "channel_not_found",
        "is_archived",
        "restricted_action",
        "cant_reply_to_message",
    }
)

_GUARD_FLAG = "_bott_send_guarded"


def _error_code(exc: Exception) -> str:
    resp = getattr(exc, "response", None)
    if resp is None:
        return ""
    try:
        return (resp.get("error") if hasattr(resp, "get") else resp["error"]) or ""
    except Exception:  # noqa: BLE001 — response shape is not guaranteed
        return ""


def guarded_send(original: Callable) -> Callable:
    """Wrap an async Slack send fn so non-postable ``SlackApiError``s are logged+swallowed."""
    from slack_sdk.errors import SlackApiError

    async def _wrapped(*args: Any, **kwargs: Any) -> Any:
        try:
            return await original(*args, **kwargs)
        except SlackApiError as e:
            code = _error_code(e)
            if code in NON_POSTABLE_ERRORS:
                channel = kwargs.get("channel") or (args[1] if len(args) > 1 else "?")
                log.warning("Slack post skipped (%s) for channel %s", code, channel)
                return None
            raise

    setattr(_wrapped, _GUARD_FLAG, True)
    return _wrapped


def install_slack_send_guard() -> bool:
    """Idempotently wrap Agno's Slack send helper. Returns True only when newly installed."""
    try:
        from agno.os.interfaces.slack import event_handler as eh
    except Exception as e:  # noqa: BLE001 — never let hardening crash startup
        log.warning("Slack send guard not installed: %s", e)
        return False
    current = getattr(eh, "send_slack_message_async", None)
    if current is None or getattr(current, _GUARD_FLAG, False):
        return False
    eh.send_slack_message_async = guarded_send(current)
    log.info("Installed Slack send guard (swallows non-postable channel errors).")
    return True
