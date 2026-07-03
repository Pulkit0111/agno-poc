"""Review termination classification — a model error must be reported as model_error, not
masqueraded as no_submission ("PR may be large"). Agno RunStatus.error stringifies to
"RunStatus.error" (value "ERROR"), so the check must be case/format tolerant."""

from __future__ import annotations

from bott.agents.code_review.core.runner import _classify_termination


def test_error_status_is_model_error_regardless_of_format():
    assert _classify_termination("RunStatus.error", 0, False, 30) == "model_error"
    assert _classify_termination("ERROR", 0, False, 30) == "model_error"
    assert _classify_termination("error", 0, False, 30) == "model_error"


def test_budget_when_tool_calls_maxed():
    assert _classify_termination("RunStatus.completed", 30, False, 30) == "budget"


def test_natural_when_output_present():
    assert _classify_termination("COMPLETED", 3, True, 30) == "natural"


def test_no_submission_when_no_output_and_no_error():
    assert _classify_termination("COMPLETED", 2, False, 30) == "no_submission"
