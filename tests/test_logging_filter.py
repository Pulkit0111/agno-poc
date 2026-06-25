"""Tests for the benign-noise filter that suppresses agno's best-effort
channel-name resolution warnings.

Background: agno's Slack interface emits a WARNING for every message in a
private channel because the Slack app lacks the `groups:read` scope.  The
warning is benign (channel-name resolution is cosmetic), but it floods logs.
We install a narrow filter that drops ONLY that specific substring so that all
other WARNING records still surface.

Real fix: add `groups:read` to the Slack app's bot scopes and reinstall.
"""

import logging

from bott.shared.observability.logging_setup import (
    _ChannelNameFilter,  # noqa: PLC2701 — tested internal
    setup_logging,
)


def _make_record(msg: str, level: int = logging.WARNING) -> logging.LogRecord:
    """Return a minimal LogRecord with the given message and level."""
    record = logging.LogRecord(
        name="agno.os.interfaces.slack.helpers",
        level=level,
        pathname="helpers.py",
        lineno=165,
        msg=msg,
        args=(),
        exc_info=None,
    )
    return record


class TestChannelNameFilter:
    def test_drops_channel_name_resolution_warning(self):
        """The filter must return False (drop) for agno's spurious warning."""
        f = _ChannelNameFilter()
        record = _make_record(
            "Failed to resolve channel name for C0ATHDGRD1C: "
            "The request to the Slack API failed. (url: ...) "
            "The server responded with: {'ok': False, 'error': 'missing_scope', "
            "'needed': 'groups:read', 'provided': '...'}"
        )
        assert f.filter(record) is False, "Filter should DROP the channel-name resolution warning"

    def test_drops_minimal_trigger_phrase(self):
        """Only the substring matters — short form must also be dropped."""
        f = _ChannelNameFilter()
        record = _make_record("Failed to resolve channel name for C123: some error")
        assert f.filter(record) is False

    def test_passes_unrelated_warning(self):
        """An unrelated WARNING must NOT be suppressed."""
        f = _ChannelNameFilter()
        record = _make_record("something real failed in the pipeline")
        assert f.filter(record) is True, "Filter must NOT drop unrelated warnings"

    def test_passes_info_record(self):
        """INFO records (even with the substring) must pass through."""
        f = _ChannelNameFilter()
        record = _make_record(
            "Failed to resolve channel name for C999: info-level noise",
            level=logging.INFO,
        )
        # We demote/drop at WARNING; INFO records should pass regardless
        assert f.filter(record) is True

    def test_filter_attached_after_setup(self):
        """After setup_logging(), the root handler must carry the filter."""
        import bott.shared.observability.logging_setup as ls

        ls._configured = False  # reset so setup re-runs
        setup_logging()

        root = logging.getLogger()
        assert root.handlers, "Root logger must have at least one handler"
        handler = root.handlers[0]
        filter_types = [type(f).__name__ for f in handler.filters]
        assert "_ChannelNameFilter" in filter_types, (
            f"_ChannelNameFilter not found in handler filters: {filter_types}"
        )
