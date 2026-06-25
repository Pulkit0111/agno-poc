"""Central logging with secret redaction.

Production hygiene: one place configures logging, and a filter scrubs secrets from
every record — GitHub installation tokens leak into `git` clone URLs
(`https://x-access-token:<TOKEN>@github.com/...`) and error strings, and we never
want tokens (GitHub `gh*_`, Slack `xox*`) in logs.
"""

from __future__ import annotations

import logging
import os
import re
import sys

# x-access-token:<token>@  ->  x-access-token:***@   (clone URLs)
_CLONE_URL_RE = re.compile(r"(x-access-token:)[^@/\s]+(@)")
# bare provider tokens
_TOKEN_RES = [
    re.compile(r"gh[pousr]_[A-Za-z0-9]{20,}"),          # GitHub PAT / installation
    re.compile(r"xox[bapr]-[A-Za-z0-9-]{10,}"),          # Slack tokens
    re.compile(r"sk-[A-Za-z0-9_\-]{20,}"),               # OpenAI keys
    re.compile(r"ghs_[A-Za-z0-9]{20,}"),
]


def redact(text: str) -> str:
    """Scrub secrets from a string before it's logged or shown."""
    if not text:
        return text
    out = _CLONE_URL_RE.sub(r"\1***\2", text)
    for rx in _TOKEN_RES:
        out = rx.sub("***", out)
    return out


class _RedactFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        try:
            msg = record.getMessage()
        except Exception:
            return True
        red = redact(msg)
        if red != msg:
            record.msg = red
            record.args = ()
        return True


# ---------------------------------------------------------------------------
# Benign-noise filter — agno's best-effort channel-name resolution
# ---------------------------------------------------------------------------
# agno's Slack interface (agno/os/interfaces/slack/helpers.py ~L165) emits a
# WARNING on every message in a *private* channel when the Slack app is missing
# the `groups:read` scope.  The warning is benign: channel-name resolution is
# cosmetic and the bot continues to function normally.
#
# REAL FIX: add `groups:read` to the Slack app's bot token scopes in the
# Slack API dashboard, then reinstall the app to the workspace.  Once that
# scope is granted this filter can be removed.
#
# Until then we silence ONLY this specific substring so that all other
# WARNING (and above) records still surface in logs — the match is as narrow
# as possible so nothing unrelated is suppressed.
_CHANNEL_NAME_NOISE = "Failed to resolve channel name"


class _ChannelNameFilter(logging.Filter):
    """Drop agno's spurious 'Failed to resolve channel name' warnings.

    Returns False (drop) only for WARNING-or-above records whose rendered
    message contains the exact ``_CHANNEL_NAME_NOISE`` substring.  Every
    other record passes through unchanged.
    """

    def filter(self, record: logging.LogRecord) -> bool:
        # Only suppress at WARNING level or above; let INFO/DEBUG through
        # (INFO records with this substring are unlikely but shouldn't vanish).
        if record.levelno < logging.WARNING:
            return True
        try:
            msg = record.getMessage()
        except Exception:
            return True
        return _CHANNEL_NAME_NOISE not in msg


_configured = False


def setup_logging() -> None:
    """Idempotent root-logger setup. Level via LOG_LEVEL (default INFO)."""
    global _configured
    if _configured:
        return
    level = getattr(logging, os.getenv("LOG_LEVEL", "INFO").upper(), logging.INFO)
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(
        logging.Formatter("%(asctime)s %(levelname)-7s %(name)s — %(message)s", "%H:%M:%S")
    )
    handler.addFilter(_RedactFilter())
    handler.addFilter(_ChannelNameFilter())
    root = logging.getLogger()
    root.handlers.clear()
    root.addHandler(handler)
    root.setLevel(level)
    # Quiet noisy libraries.
    for noisy in ("httpx", "httpcore", "slack_bolt", "slack_sdk", "uvicorn.access"):
        logging.getLogger(noisy).setLevel(logging.WARNING)
    _configured = True


def get_logger(name: str) -> logging.Logger:
    return logging.getLogger(name)
