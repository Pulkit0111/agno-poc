"""The optional reproducibility knob — only honored when explicitly set."""

from __future__ import annotations

from bott.shared.config import review_temperature


def test_unset_returns_none(monkeypatch):
    monkeypatch.delenv("REVIEW_TEMPERATURE", raising=False)
    assert review_temperature() is None


def test_blank_returns_none(monkeypatch):
    monkeypatch.setenv("REVIEW_TEMPERATURE", "")
    assert review_temperature() is None


def test_set_returns_float(monkeypatch):
    monkeypatch.setenv("REVIEW_TEMPERATURE", "0")
    assert review_temperature() == 0.0


def test_garbage_returns_none(monkeypatch):
    monkeypatch.setenv("REVIEW_TEMPERATURE", "hot")
    assert review_temperature() is None
