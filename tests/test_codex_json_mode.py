"""Codex/Responses rejects text.format=json_object unless the input contains the word 'json'.

Regression cover for the 400 that made every PR review fail on the Codex backend:
`Response input messages must contain the word 'json' ... to use 'text.format' of type
'json_object'`. The adapter guarantees the word is present.
"""

from __future__ import annotations

from bott.shared.codex_model import _ensure_json_word


def test_json_object_mode_without_json_word_gets_instruction():
    msgs = [{"role": "developer",
             "content": [{"type": "input_text", "text": "Review the PR and output the fields."}]}]
    out = _ensure_json_word(msgs, {"type": "json_object"})
    assert len(out) == len(msgs) + 1          # a JSON instruction was appended
    assert "json" in str(out[-1]).lower()
    assert out[:1] == msgs[:1]                # originals untouched, only appended


def test_json_object_mode_with_json_word_unchanged():
    msgs = [{"role": "developer",
             "content": [{"type": "input_text", "text": "Return your answer as JSON, please."}]}]
    assert _ensure_json_word(msgs, {"type": "json_object"}) == msgs


def test_non_json_formats_are_untouched():
    msgs = [{"role": "user", "content": "hello"}]
    assert _ensure_json_word(msgs, None) == msgs
    assert _ensure_json_word(msgs, {"type": "json_schema", "name": "X"}) == msgs
