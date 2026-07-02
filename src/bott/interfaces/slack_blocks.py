"""Helpers for keeping Slack Block Kit payloads within API limits.

Slack rejects ``chat_postMessage`` / ``chat_update`` calls when any section
block's ``text.text`` field exceeds 3 000 characters or when the top-level
blocks list exceeds 50 items.  Long AI-generated content (plans, reviews,
triage reports) regularly trips these limits.

``split_long_blocks`` is the single defensive choke-point: call it in
``_post`` / ``_update`` before touching the Slack API.
"""

from __future__ import annotations

_SECTION = "section"
_TRUNCATION_NOTICE = "… _(truncated — message too long for Slack)_"


def _split_text(text: str, limit: int) -> list[str]:
    """Split *text* into chunks each ≤ *limit* characters.

    Splitting preference (most to least semantic):
    1. Paragraph boundary (``\\n\\n``)
    2. Line boundary (``\\n``)
    3. Hard slice (last resort when a single line > limit)

    The returned list is never empty; each element is non-empty.
    """
    if len(text) <= limit:
        return [text]

    chunks: list[str] = []
    remaining = text

    while remaining:
        if len(remaining) <= limit:
            chunks.append(remaining)
            break

        # Try paragraph boundary first.
        cut = remaining.rfind("\n\n", 0, limit + 1)
        if cut > 0:
            chunks.append(remaining[: cut + 2].rstrip("\n"))
            remaining = remaining[cut + 2 :]
            continue

        # Try line boundary.
        cut = remaining.rfind("\n", 0, limit + 1)
        if cut > 0:
            chunks.append(remaining[:cut])
            remaining = remaining[cut + 1 :]
            continue

        # Hard slice — no natural break within limit chars.
        chunks.append(remaining[:limit])
        remaining = remaining[limit:]

    return [c for c in chunks if c]  # drop empty strings that can arise from split points


def split_long_blocks(
    blocks: list[dict],
    limit: int = 2900,
    max_blocks: int = 45,
) -> list[dict]:
    """Expand any section block whose text exceeds *limit* into multiple blocks.

    Rules
    -----
    * Only ``{"type": "section", "text": {...}}`` blocks with a string
      ``text.text`` field are eligible for splitting.  All other block types
      (``actions``, ``header``, ``context``, ``divider``, …) are passed through
      unchanged and in the original order.
    * Splitting preserves ``text.type`` (``mrkdwn`` / ``plain_text``).
    * Any additional keys on the original section block (e.g. ``block_id``,
      ``accessory``) are copied only onto the *first* replacement block so
      they don't collide on duplicate ``block_id`` values.
    * If the resulting list exceeds *max_blocks*, the list is truncated to
      ``max_blocks - 1`` blocks.  A trailing truncation-notice section is
      appended.  If the original payload ended with an ``actions`` block, that
      block is preserved *after* the truncation notice (so Approve/Dismiss
      buttons survive) provided it still fits within *max_blocks*.

    Parameters
    ----------
    blocks:
        The original blocks list as built by a renderer.
    limit:
        Maximum characters for any single section block's ``text.text``.
        Defaults to 2900 (safety margin under Slack's 3 000-char hard limit).
    max_blocks:
        Maximum length of the returned blocks list (Slack caps at 50; default
        here is 45 to leave headroom).
    """
    expanded: list[dict] = []
    for block in blocks:
        if (
            block.get("type") == _SECTION
            and isinstance(block.get("text"), dict)
            and isinstance(block["text"].get("text"), str)
            and len(block["text"]["text"]) > limit
        ):
            text_obj = block["text"]
            text_type = text_obj.get("type", "mrkdwn")
            parts = _split_text(block["text"]["text"], limit)
            for i, part in enumerate(parts):
                if i == 0:
                    # First chunk: keep all original keys so block_id/accessory survive.
                    new_block = {**block, "text": {**text_obj, "text": part}}
                else:
                    # Subsequent chunks: bare section — no duplicated block_id etc.
                    new_block = {"type": _SECTION, "text": {"type": text_type, "text": part}}
                expanded.append(new_block)
        else:
            expanded.append(block)

    if len(expanded) <= max_blocks:
        return expanded

    # --- Truncation path ---
    # Preserve a trailing actions block if one exists so buttons survive.
    trailing_actions: dict | None = None
    if expanded and expanded[-1].get("type") == "actions":
        trailing_actions = expanded[-1]

    truncation_block: dict = {
        "type": _SECTION,
        "text": {"type": "mrkdwn", "text": _TRUNCATION_NOTICE},
    }

    if trailing_actions is not None:
        # Keep: first (max_blocks - 2) blocks + truncation notice + actions block.
        result = expanded[: max_blocks - 2] + [truncation_block, trailing_actions]
    else:
        result = expanded[: max_blocks - 1] + [truncation_block]

    return result
