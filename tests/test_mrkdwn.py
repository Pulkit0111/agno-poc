"""Markdown → Slack mrkdwn conversion (so model output renders in Slack)."""

from bott.interfaces.mrkdwn import to_mrkdwn


def test_bold_double_asterisks_to_single():
    assert to_mrkdwn("a **Path traversal risk**: bad") == "a *Path traversal risk*: bad"


def test_bold_underscores_to_single_asterisks():
    assert to_mrkdwn("__strong__ point") == "*strong* point"


def test_bold_italic():
    assert to_mrkdwn("***wow***") == "*_wow_*"


def test_markdown_link_to_slack():
    assert to_mrkdwn("see [the PR](https://github.com/o/r/pull/1)") == \
        "see <https://github.com/o/r/pull/1|the PR>"


def test_heading_to_bold():
    assert to_mrkdwn("## Summary") == "*Summary*"


def test_plain_and_code_untouched():
    assert to_mrkdwn("use `read_file` and _stay_ calm") == "use `read_file` and _stay_ calm"


def test_multiple_bolds_in_a_line():
    assert to_mrkdwn("**one** then **two**") == "*one* then *two*"
