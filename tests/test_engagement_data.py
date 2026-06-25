from bott.skills import engagement_data as ed


def _fake_memra(monkeypatch, payload):
    class FakeMemra:
        def ask_context(self, q, **k):
            return payload
    monkeypatch.setattr(ed, "MemraClient", lambda: FakeMemra())


def test_get_engagement_status_summarizes_memra(monkeypatch):
    _fake_memra(monkeypatch, {"verdict": "sufficient", "evidence": [
        {"text": "PADI is on track; one risk on QA.", "citation": {"source_url": "u", "source_title": "notes"}},
    ]})
    out = ed.get_engagement_status("PADI")
    assert "on track" in out and "notes" in out

def test_find_people_summarizes_memra(monkeypatch):
    _fake_memra(monkeypatch, {"verdict": "sufficient", "evidence": [
        {"text": "Asha worked on Drupal commerce.", "citation": {}},
    ]})
    out = ed.find_people("Drupal commerce")
    assert "Asha" in out

def test_tools_factory_exposes_both():
    names = {getattr(f, "__name__", "") for f in ed.engagement_data_tools()}
    assert {"get_engagement_status", "find_people"} <= names
