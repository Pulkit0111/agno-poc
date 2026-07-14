"""Guard around Agno's vendored Slack send helper.

Regression cover for the ASGI 500 seen in production: a reply to a read-only channel
raised SlackApiError, the error-fallback tried to post to the same channel and raised
again, and the second raise was uncaught. The guard swallows non-postable-channel
errors (logging once) so neither the reply nor the error path can double-fault.
"""

from __future__ import annotations

import asyncio

import pytest
from slack_sdk.errors import SlackApiError

from bott.interfaces.slack_hardening import (
    NON_POSTABLE_ERRORS,
    guarded_send,
    install_slack_send_guard,
)


def _err(code: str) -> SlackApiError:
    return SlackApiError(code, {"ok": False, "error": code})


def test_guarded_send_passes_through_success_and_return_value():
    async def ok(*a, **k):
        return "posted"

    wrapped = guarded_send(ok)
    assert asyncio.run(wrapped(object(), channel="C1", message="hi", thread_ts="1")) == "posted"


def test_guarded_send_normalizes_markdown_to_mrkdwn_kwarg():
    """A weaker model's CommonMark (**bold**, [t](u)) is converted to Slack mrkdwn before
    it posts, so the thread never shows literal ** / [](). Covers the `message` kwarg path."""
    seen = {}

    async def capture(*a, **k):
        seen["message"] = k.get("message")
        return "ok"

    wrapped = guarded_send(capture)
    asyncio.run(wrapped(object(), channel="C1",
                        message="**Done** — see [PR](https://x/1)", thread_ts="1"))
    assert seen["message"] == "*Done* — see <https://x/1|PR>"


def test_guarded_send_normalizes_markdown_positional_message():
    """Covers the positional call shape: (async_client, channel, thread_ts, message)."""
    seen = {}

    async def capture(*a, **k):
        seen["args"] = a
        return "ok"

    wrapped = guarded_send(capture)
    asyncio.run(wrapped(object(), "C1", "1", "**bold**"))
    assert seen["args"][3] == "*bold*"


def test_guarded_send_leaves_correct_mrkdwn_untouched():
    """Idempotent for a model that already emits Slack mrkdwn — single * is not doubled."""
    seen = {}

    async def capture(*a, **k):
        seen["message"] = k.get("message")
        return "ok"

    wrapped = guarded_send(capture)
    asyncio.run(wrapped(object(), channel="C1", message="*already* `code`", thread_ts="1"))
    assert seen["message"] == "*already* `code`"


def test_guarded_send_swallows_read_only_channel():
    async def boom(*a, **k):
        raise _err("restricted_action_read_only_channel")

    wrapped = guarded_send(boom)
    # Must NOT raise — this is the exact production double-fault trigger.
    assert asyncio.run(wrapped(object(), channel="C1", message="hi", thread_ts="1")) is None


def test_guarded_send_swallows_all_non_postable_codes():
    for code in NON_POSTABLE_ERRORS:
        async def boom(*a, _code=code, **k):
            raise _err(_code)

        assert asyncio.run(guarded_send(boom)(object(), channel="C1", message="x", thread_ts="1")) is None


def test_guarded_send_reraises_unknown_slack_error():
    async def boom(*a, **k):
        raise _err("ratelimited")

    with pytest.raises(SlackApiError):
        asyncio.run(guarded_send(boom)(object(), channel="C1", message="hi", thread_ts="1"))


def test_guarded_send_reraises_non_slack_errors():
    async def boom(*a, **k):
        raise ValueError("unrelated")

    with pytest.raises(ValueError):
        asyncio.run(guarded_send(boom)())


def test_install_is_idempotent(monkeypatch):
    from agno.os.interfaces.slack import event_handler as eh

    async def sentinel(*a, **k):
        return "orig"

    monkeypatch.setattr(eh, "send_slack_message_async", sentinel)
    assert install_slack_send_guard() is True  # newly wrapped
    assert eh.send_slack_message_async is not sentinel
    assert install_slack_send_guard() is False  # already guarded — no double-wrap
