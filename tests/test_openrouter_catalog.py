# tests/test_openrouter_catalog.py
"""_fetch_openrouter_models filters OpenRouter's live catalog down to text→text models
(mirrors personal_finance_organizer/lib/openrouter.ts's filter) so the admin model picker
isn't cluttered with image/audio models. Falls back to _OPENROUTER_FALLBACK on any error."""

from bott.interfaces.slack_home import models


class _FakeResp:
    def __init__(self, json_body):
        self._json = json_body

    def raise_for_status(self):
        pass

    def json(self):
        return self._json


def _catalog():
    return {
        "data": [
            {"id": "text/text-model", "architecture": {"input_modalities": ["text"], "output_modalities": ["text"]}},
            {"id": "image/input-model", "architecture": {"input_modalities": ["image"], "output_modalities": ["text"]}},
            {"id": "image/output-model", "architecture": {"input_modalities": ["text"], "output_modalities": ["image"]}},
            {"id": "legacy/modality-model", "architecture": {"modality": "text->text"}},
            {"id": "bare/no-architecture-model"},
        ]
    }


def test_filters_to_text_to_text_models_only(monkeypatch):
    monkeypatch.setattr(models.httpx, "get", lambda url, timeout=None: _FakeResp(_catalog()))
    result = models._fetch_openrouter_models()
    assert result == sorted([
        "text/text-model",
        "legacy/modality-model",
        "bare/no-architecture-model",
    ])


def test_httpx_error_falls_back(monkeypatch):
    def boom(url, timeout=None):
        raise RuntimeError("network down")

    monkeypatch.setattr(models.httpx, "get", boom)
    assert models._fetch_openrouter_models() == list(models._OPENROUTER_FALLBACK)
