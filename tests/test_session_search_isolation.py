from agno.db.sqlite import SqliteDb
from agno.run import RunContext

from bott.skills import workspace_tools


def _find_session_search(tools):
    for t in tools:
        name = getattr(t, "name", getattr(t, "__name__", ""))
        if "session_search" in name:
            return t
    return None


def test_session_search_present_when_db_given(monkeypatch, tmp_path):
    monkeypatch.setenv("BOTT_WORKSPACE_DIR", str(tmp_path / "ws"))
    db = SqliteDb(db_file=str(tmp_path / "s.db"))
    tools = workspace_tools.build_workspace_tools(db=db)
    assert _find_session_search(tools) is not None


def test_session_search_scopes_to_run_context_user(monkeypatch, tmp_path):
    monkeypatch.setenv("BOTT_WORKSPACE_DIR", str(tmp_path / "ws"))
    db = SqliteDb(db_file=str(tmp_path / "s.db"))
    captured = {}

    # Patch db.get_sessions to record the user_id it was called with.
    def fake_get_sessions(*args, user_id=None, **kwargs):
        captured["user_id"] = user_id
        return []

    monkeypatch.setattr(db, "get_sessions", fake_get_sessions)
    fn = workspace_tools._session_search_impl  # the underlying impl
    rc = RunContext(run_id="r1", session_id="s1", user_id="alice@x.com")
    fn(db, rc, query="deploy decision")
    assert captured["user_id"] == "alice@x.com"
