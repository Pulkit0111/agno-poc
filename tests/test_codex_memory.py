"""CodexExecMemoryManager — memory ops extracted via codex exec, applied via Agno's own
db tools. No real binary; run_codex_exec is monkeypatched."""
from __future__ import annotations

from agno.db.in_memory import InMemoryDb
from agno.models.message import Message

from bott.shared import codex_memory as cm
from bott.shared.codex_cli import CodexCliError, CodexExecResult


def _manager(db):
    return cm.CodexExecMemoryManager(
        memory_capture_instructions="Capture location and name facts.", db=db)


def _ops_result(ops):
    return CodexExecResult(text="", data={"operations": ops}, tokens_used=1)


def test_add_operation_persists_memory(monkeypatch):
    db = InMemoryDb()
    mgr = _manager(db)
    captured = {}

    def fake(prompt, **kw):
        captured["prompt"] = prompt
        captured.update(kw)
        return _ops_result([{"op": "add", "memory": "Lives in Srinagar",
                             "topics": ["location"], "memory_id": None}])

    monkeypatch.setattr(cm, "run_codex_exec", fake)
    out = mgr.create_user_memories(message="I live in Srinagar", user_id="alice@x.com")
    assert "1 memory operation" in out
    memories = mgr.get_user_memories("alice@x.com")
    assert any("Srinagar" in m.memory for m in memories)
    assert mgr.memories_updated is True
    assert captured["output_schema"] is not None
    assert "I live in Srinagar" in captured["prompt"]
    assert "Capture location and name facts." in captured["prompt"]


def test_update_and_delete_operations(monkeypatch):
    db = InMemoryDb()
    mgr = _manager(db)

    monkeypatch.setattr(cm, "run_codex_exec",
                        lambda prompt, **kw: _ops_result(
                            [{"op": "add", "memory": "Name is Bob", "memory_id": None,
                              "topics": None}]))
    mgr.create_user_memories(message="call me Bob", user_id="u@x")
    existing = mgr.get_user_memories("u@x")
    mem_id = existing[0].memory_id

    monkeypatch.setattr(cm, "run_codex_exec",
                        lambda prompt, **kw: _ops_result(
                            [{"op": "update", "memory_id": mem_id,
                              "memory": "Name is Robert", "topics": ["name"]}]))
    mgr.create_user_memories(message="actually it's Robert", user_id="u@x")
    assert any("Robert" in m.memory for m in mgr.get_user_memories("u@x"))

    monkeypatch.setattr(cm, "run_codex_exec",
                        lambda prompt, **kw: _ops_result(
                            [{"op": "delete", "memory_id": mem_id, "memory": None,
                              "topics": None}]))
    mgr.create_user_memories(message="forget my name", user_id="u@x")
    assert not mgr.get_user_memories("u@x")


def test_existing_memories_shown_to_extractor(monkeypatch):
    db = InMemoryDb()
    mgr = _manager(db)
    monkeypatch.setattr(cm, "run_codex_exec",
                        lambda prompt, **kw: _ops_result(
                            [{"op": "add", "memory": "Based in Pune", "memory_id": None,
                              "topics": None}]))
    mgr.create_user_memories(message="I'm based in Pune", user_id="u@x")

    seen = {}

    def fake(prompt, **kw):
        seen["prompt"] = prompt
        return _ops_result([])

    monkeypatch.setattr(cm, "run_codex_exec", fake)
    out = mgr.create_user_memories(message="what's the weather", user_id="u@x")
    assert "Based in Pune" in seen["prompt"]  # extractor sees existing memories with ids
    assert out == "no memory updates"


def test_codex_failure_never_breaks_the_turn(monkeypatch):
    db = InMemoryDb()
    mgr = _manager(db)

    def boom(prompt, **kw):
        raise CodexCliError("exit 1")

    monkeypatch.setattr(cm, "run_codex_exec", boom)
    out = mgr.create_user_memories(message="I live in Srinagar", user_id="u@x")
    assert out == "memory capture skipped"
    assert not mgr.get_user_memories("u@x")


def test_malformed_ops_are_skipped_not_fatal(monkeypatch):
    db = InMemoryDb()
    mgr = _manager(db)
    monkeypatch.setattr(cm, "run_codex_exec",
                        lambda prompt, **kw: _ops_result(
                            [{"op": "update", "memory_id": None, "memory": "x", "topics": None},
                             {"op": "add", "memory": "Valid fact", "memory_id": None,
                              "topics": None}]))
    out = mgr.create_user_memories(message="hi", user_id="u@x")
    assert "1 memory operation" in out
    assert any("Valid fact" in m.memory for m in mgr.get_user_memories("u@x"))


def test_async_path_wraps_sync(monkeypatch):
    import anyio

    db = InMemoryDb()
    mgr = _manager(db)
    monkeypatch.setattr(cm, "run_codex_exec",
                        lambda prompt, **kw: _ops_result(
                            [{"op": "add", "memory": "Async fact", "memory_id": None,
                              "topics": None}]))
    out = anyio.run(lambda: mgr.acreate_or_update_memories(
        messages=[Message(role="user", content="hello")],
        existing_memories=[], user_id="u@x", db=db))
    assert "1 memory operation" in out


def test_bott_agent_uses_codex_memory_manager():
    from bott.agents.bott_agent import build_memory_manager
    mgr = build_memory_manager(InMemoryDb())
    assert isinstance(mgr, cm.CodexExecMemoryManager)
    assert "durable facts" in (mgr.memory_capture_instructions or "")
