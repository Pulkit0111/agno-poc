"""Tests for bott.interfaces.slack_blocks.split_long_blocks.

Covers:
- Long section block is split into multiple blocks each ≤ 2900 chars.
- Content is fully preserved (concatenation reconstructs original).
- A trailing actions block (Approve/Dismiss) survives unchanged and last.
- Short messages pass through unchanged (single-block identity).
- A single unbroken line > limit is hard-sliced into ≤ limit pieces.
- max_blocks cap: enormous text produces ≤ max_blocks blocks with a
  truncation notice appended.
- _post calls chat_postMessage with no section text > 3000 chars.
"""

from __future__ import annotations

from bott.interfaces.slack_blocks import _TRUNCATION_NOTICE, split_long_blocks

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _section(text: str, text_type: str = "mrkdwn") -> dict:
    return {"type": "section", "text": {"type": text_type, "text": text}}


def _actions(approval_id: int = 1) -> dict:
    return {
        "type": "actions",
        "elements": [
            {
                "type": "button",
                "text": {"type": "plain_text", "text": "Approve"},
                "style": "primary",
                "action_id": "approval_approve",
                "value": str(approval_id),
            },
            {
                "type": "button",
                "text": {"type": "plain_text", "text": "Dismiss"},
                "action_id": "approval_dismiss",
                "value": str(approval_id),
            },
        ],
    }


LIMIT = 2900


# ---------------------------------------------------------------------------
# 1. Long section block is split; content is fully reconstructed
# ---------------------------------------------------------------------------

def test_long_section_split_into_multiple_blocks():
    """A section whose text > LIMIT should be replaced with multiple sections."""
    # Build text made of short paragraphs totalling > 3000 chars.
    paragraph = "x" * 100 + "\n\n"
    long_text = paragraph * 35  # 35 * 102 = 3 570 chars
    assert len(long_text) > LIMIT

    blocks = [_section(long_text)]
    result = split_long_blocks(blocks, limit=LIMIT)

    assert len(result) > 1, "long block should be split into multiple blocks"
    for blk in result:
        assert blk["type"] == "section"
        assert len(blk["text"]["text"]) <= LIMIT, (
            f"chunk too long: {len(blk['text']['text'])} chars"
        )


def test_long_section_content_preserved():
    """Concatenating all chunks should reconstruct the original content."""
    paragraph = "abc " * 25 + "\n\n"
    long_text = paragraph * 40  # > 3000 chars
    blocks = [_section(long_text)]
    result = split_long_blocks(blocks, limit=LIMIT)

    # Join chunks — allow for trailing whitespace trimming at split boundaries.
    reconstructed = "".join(blk["text"]["text"] for blk in result)
    # Strip both to compare semantic content (split may drop leading/trailing \n).
    assert reconstructed.replace("\n", "").replace(" ", "") == long_text.replace("\n", "").replace(" ", "")


def test_text_type_preserved_across_chunks():
    """Each chunk should carry the original text.type."""
    long_text = "line\n" * 700  # 3500 chars
    blocks = [_section(long_text, text_type="plain_text")]
    result = split_long_blocks(blocks, limit=LIMIT)
    assert len(result) > 1
    for blk in result:
        assert blk["text"]["type"] == "plain_text"


# ---------------------------------------------------------------------------
# 2. Actions block (Approve/Dismiss) survives unchanged and stays last
# ---------------------------------------------------------------------------

def test_actions_block_preserved_after_long_section():
    """The actions block must be unchanged and remain last."""
    long_text = "step\n" * 700  # > 3000
    approval = _actions(approval_id=42)
    blocks = [_section(long_text), approval]
    result = split_long_blocks(blocks, limit=LIMIT)

    assert len(result) > 2, "should have multiple section chunks plus the actions block"
    last = result[-1]
    assert last["type"] == "actions", "last block must be the actions block"
    assert last == approval, "actions block must be bit-for-bit identical"


def test_actions_block_unchanged_when_no_split_needed():
    """Even without splitting, actions block must remain intact."""
    short_text = "Short plan text."
    approval = _actions(approval_id=7)
    blocks = [_section(short_text), approval]
    result = split_long_blocks(blocks, limit=LIMIT)
    assert result == blocks


# ---------------------------------------------------------------------------
# 3. Short message passes through unchanged
# ---------------------------------------------------------------------------

def test_short_message_unchanged():
    """A block list with no oversized section must be returned as-is."""
    blocks = [_section("Hello, world!"), _actions()]
    result = split_long_blocks(blocks, limit=LIMIT)
    assert result == blocks


def test_single_short_block_identity():
    text = "A" * 100
    blocks = [_section(text)]
    assert split_long_blocks(blocks, limit=LIMIT) == blocks


# ---------------------------------------------------------------------------
# 4. Hard-slice: a single unbroken line > limit
# ---------------------------------------------------------------------------

def test_hard_slice_long_line():
    """A line with no newlines that exceeds limit must be hard-sliced."""
    long_line = "A" * (LIMIT * 3)  # 8700 chars, no newlines
    blocks = [_section(long_line)]
    result = split_long_blocks(blocks, limit=LIMIT)

    assert len(result) >= 3
    for blk in result:
        assert len(blk["text"]["text"]) <= LIMIT

    # Full content must be reconstructable.
    assert "".join(b["text"]["text"] for b in result) == long_line


# ---------------------------------------------------------------------------
# 5. max_blocks cap: truncation notice appended
# ---------------------------------------------------------------------------

def test_max_blocks_cap_with_truncation_notice():
    """Enormous text must produce ≤ max_blocks blocks with a truncation notice."""
    # Each paragraph is 90 chars + '\n\n' = 92 chars.
    paragraph = "B" * 90 + "\n\n"
    # 45 blocks * 2900 chars / 92 chars-per-para ≈ 1417 paragraphs needed.
    long_text = paragraph * 1500  # well over limit
    max_b = 10

    blocks = [_section(long_text)]
    result = split_long_blocks(blocks, limit=LIMIT, max_blocks=max_b)

    assert len(result) <= max_b, f"got {len(result)} blocks, expected ≤ {max_b}"
    last = result[-1]
    assert last["type"] == "section"
    assert _TRUNCATION_NOTICE in last["text"]["text"]


def test_max_blocks_cap_preserves_actions_block():
    """When truncation fires and the original list ended with actions, actions
    must survive after the truncation notice."""
    paragraph = "C" * 90 + "\n\n"
    long_text = paragraph * 1500
    approval = _actions(approval_id=99)
    max_b = 10

    blocks = [_section(long_text), approval]
    result = split_long_blocks(blocks, limit=LIMIT, max_blocks=max_b)

    assert len(result) <= max_b
    # Last block must be the actions block.
    assert result[-1]["type"] == "actions"
    assert result[-1] == approval
    # Second-to-last must be the truncation notice.
    assert _TRUNCATION_NOTICE in result[-2]["text"]["text"]


# ---------------------------------------------------------------------------
# 6. Non-section blocks pass through unchanged
# ---------------------------------------------------------------------------

def test_non_section_blocks_pass_through():
    """header, context, divider blocks must not be altered."""
    header = {"type": "header", "text": {"type": "plain_text", "text": "My Header"}}
    context = {"type": "context", "elements": [{"type": "mrkdwn", "text": "ctx"}]}
    divider = {"type": "divider"}
    short_section = _section("short")
    blocks = [header, short_section, context, divider]
    result = split_long_blocks(blocks, limit=LIMIT)
    assert result == blocks


# ---------------------------------------------------------------------------
# 7. Integration: _post calls chat_postMessage with safe block sizes
# ---------------------------------------------------------------------------

def test_post_splits_blocks_before_calling_slack(monkeypatch):
    """_post must pass split blocks to chat_postMessage; no section text > 3000."""
    monkeypatch.delenv("SLACK_BOT_TOKEN", raising=False)

    import bott.interfaces.slack_app as slack_app

    posted_blocks: list[list[dict]] = []

    def fake_post_message(**kwargs):
        posted_blocks.append(kwargs["blocks"])
        return {"ts": "1234.5678"}

    monkeypatch.setattr(slack_app.app.client, "chat_postMessage", fake_post_message)

    long_text = "line\n" * 700  # ~3500 chars
    long_block = _section(long_text)
    approval = _actions(approval_id=5)

    slack_app._post("C_TEST", "ts.001", [long_block, approval], "fallback")

    assert len(posted_blocks) == 1
    sent = posted_blocks[0]
    for blk in sent:
        if blk.get("type") == "section" and isinstance(blk.get("text"), dict):
            assert len(blk["text"].get("text", "")) <= 3000, (
                "chat_postMessage received a section block > 3000 chars"
            )
    # Actions block must still be present.
    assert any(b["type"] == "actions" for b in sent), "actions block missing from sent blocks"
