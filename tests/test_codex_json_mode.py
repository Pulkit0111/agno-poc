"""Codex/Responses rejects text.format=json_object unless the input contains the word 'json'.

Regression cover for the 400 that made every PR review fail on the Codex backend:
`Response input messages must contain the word 'json' ... to use 'text.format' of type
'json_object'`. The adapter guarantees the word is present.
"""

from __future__ import annotations

from bott.shared.codex_model import _ensure_json_word


def test_json_object_mode_always_appends_instruction():
    msgs = [{"role": "developer",
             "content": [{"type": "input_text", "text": "Review the PR and output the fields."}]}]
    out = _ensure_json_word(msgs, {"type": "json_object"})
    assert len(out) == len(msgs) + 1          # a JSON instruction was appended
    assert "json" in str(out[-1]).lower()
    assert out[:1] == msgs[:1]                # originals untouched, only appended


def test_json_object_mode_appends_even_when_content_mentions_json():
    # Detection is unreliable (json can hide in package.json / schemas OpenAI doesn't count),
    # so we append unconditionally in json-object mode.
    msgs = [{"role": "developer",
             "content": [{"type": "input_text", "text": "The repo has a package.json file."}]}]
    out = _ensure_json_word(msgs, {"type": "json_object"})
    assert len(out) == len(msgs) + 1


def test_non_json_formats_are_untouched():
    msgs = [{"role": "user", "content": "hello"}]
    assert _ensure_json_word(msgs, None) == msgs
    assert _ensure_json_word(msgs, {"type": "json_schema", "name": "X"}) == msgs


def test_codex_error_carries_real_status_code():
    """Agno skips retries for 400/401/403/404/413/422 — but only when status_code is real.
    The adapter used to raise everything with the default 502, so deterministic 400s
    ("model not supported", json_object rule) were retried 6× (~93s wasted per failure)."""
    from bott.shared.codex_model import _provider_error

    class _Api(Exception):
        status_code = 400

    err = _provider_error(_Api("The 'x' model is not supported"), "name", "id")
    assert err.status_code == 400  # → Agno classifies as non-retryable

    err = _provider_error(RuntimeError("connection reset"), "name", "id")
    assert err.status_code == 502  # unknown/transport errors stay retryable


def test_review_user_trigger_mentions_json():
    # Belt-and-suspenders: the review's user message itself contains "json" so the request is
    # accepted even independent of the adapter guard.
    from bott.agents.code_review.core.runner import USER_TRIGGER
    assert "json" in USER_TRIGGER.lower()
