from bott.shared import db


def test_engine_is_singleton():
    assert db.get_engine() is db.get_engine()


def test_sqlite_fallback_when_no_database_url(monkeypatch):
    monkeypatch.delenv("DATABASE_URL", raising=False)
    engine = db.get_engine(fresh=True)
    assert engine.url.get_backend_name() in ("sqlite",)
