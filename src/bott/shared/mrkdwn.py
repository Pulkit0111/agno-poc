"""Convert the standard Markdown an LLM emits into Slack *mrkdwn* so it renders.

Slack doesn't use CommonMark: bold is `*x*` (not `**x**`), links are `<url|text>` (not
`[text](url)`), and there are no `#` headings. Models default to CommonMark, so without
this the user sees literal `**` etc. in the thread.
"""

from __future__ import annotations

import re

_LINK = re.compile(r"\[([^\]]+)\]\((https?://[^)\s]+)\)")
_HEADING = re.compile(r"^\s{0,3}#{1,6}\s+(.+?)\s*#*\s*$", re.MULTILINE)
_BOLD_ITALIC = re.compile(r"\*\*\*(.+?)\*\*\*", re.DOTALL)
_BOLD_STAR = re.compile(r"\*\*(.+?)\*\*", re.DOTALL)
_BOLD_UNDER = re.compile(r"__(.+?)__", re.DOTALL)


def to_mrkdwn(text: str) -> str:
    """Best-effort Markdown → Slack mrkdwn. Handles the common cases (bold, links,
    headings); leaves single `*`/`_` and code spans alone (Slack already accepts those)."""
    if not text:
        return text
    text = _LINK.sub(r"<\2|\1>", text)          # [text](url) -> <url|text>
    text = _HEADING.sub(r"*\1*", text)          # # Heading    -> *Heading*
    text = _BOLD_ITALIC.sub(r"*_\1_*", text)    # ***x***      -> *_x_*
    text = _BOLD_STAR.sub(r"*\1*", text)        # **x**        -> *x*
    text = _BOLD_UNDER.sub(r"*\1*", text)       # __x__        -> *x*
    return text
