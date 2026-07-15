"""MCP chat-tools server — flattening, identity-bound dispatch, and bearer auth.

No real HTTP server or codex binary: dispatch and the auth wrapper are exercised
directly (anyio for the async paths)."""
from __future__ import annotations

import anyio
import pytest
from agno.tools.function import Function
from agno.tools.toolkit import Toolkit

from bott.interfaces.mcp import server as mcp_server
from bott.interfaces.mcp.tickets import Identity, make_ticket
from bott.shared.secrets import generate_key


@pytest.fixture(autouse=True)
def _key(monkeypatch):
    monkeypatch.setenv("BOTT_SECRET_KEY", generate_key())


def _greet(name: str) -> str:
    """Say hello to someone."""
    return f"hello {name}"


def _whoami(run_context=None) -> str:
    """Report the calling user."""
    return f"user={getattr(run_context, 'user_id', None)}"


async def _async_echo(text: str) -> str:
    """Echo asynchronously."""
    return f"echo:{text}"


class _StubToolkit(Toolkit):
    def __init__(self):
        super().__init__(name="stub")
        self.register(_greet)


# --- flatten_functions -----------------------------------------------------------

def test_flatten_handles_toolkits_functions_and_callables():
    fns = mcp_server.flatten_functions([_StubToolkit(), Function.from_callable(_whoami), _async_echo])
    assert set(fns) == {"_greet", "_whoami", "_async_echo"}


def test_flatten_strips_reserved_params_from_schema():
    fns = mcp_server.flatten_functions([Function.from_callable(_whoami)])
    schema = fns["_whoami"].parameters
    assert "run_context" not in (schema.get("properties") or {})
    assert "run_context" not in (schema.get("required") or [])


def test_flatten_keeps_first_on_duplicate_names():
    first = Function(name="dup", description="first", entrypoint=_greet)
    second = Function(name="dup", description="second", entrypoint=_whoami)
    fns = mcp_server.flatten_functions([first, second])
    assert fns["dup"].description == "first"


# --- dispatch --------------------------------------------------------------------

def _with_identity(ident, coro_fn):
    async def runner():
        token = mcp_server._identity_var.set(ident)
        try:
            return await coro_fn()
        finally:
            mcp_server._identity_var.reset(token)
    return anyio.run(runner)


def test_dispatch_runs_sync_tool():
    fns = mcp_server.flatten_functions([_StubToolkit()])
    out = _with_identity(Identity("u@x", "s1"),
                         lambda: mcp_server.dispatch(fns, "_greet", {"name": "bob"}))
    assert out == "hello bob"


def test_dispatch_runs_async_tool():
    fns = mcp_server.flatten_functions([_async_echo])
    out = _with_identity(Identity("u@x", "s1"),
                         lambda: mcp_server.dispatch(fns, "_async_echo", {"text": "hi"}))
    assert out == "echo:hi"


def test_dispatch_injects_verified_identity_not_model_supplied():
    """run_context comes from the ticket; a model-supplied run_context arg is discarded."""
    fns = mcp_server.flatten_functions([Function.from_callable(_whoami)])
    out = _with_identity(Identity("real@x", "s1"),
                         lambda: mcp_server.dispatch(
                             fns, "_whoami", {"run_context": {"user_id": "forged@x"}}))
    assert out == "user=real@x"


def test_dispatch_without_identity_refuses():
    fns = mcp_server.flatten_functions([_StubToolkit()])
    with pytest.raises(Exception, match="identity"):
        anyio.run(lambda: mcp_server.dispatch(fns, "_greet", {"name": "bob"}))


def test_dispatch_unknown_tool():
    with pytest.raises(ValueError, match="unknown tool"):
        _with_identity(Identity("u@x", "s"),
                       lambda: mcp_server.dispatch({}, "nope", {}))


# --- bearer auth on the ASGI endpoint ---------------------------------------------

def _asgi_call(app, headers: list) -> int:
    """Drive the mounted /mcp endpoint with a minimal ASGI request; return the status.
    An authorized request will fail LATER in the MCP layer (417 from a bad session
    payload) — anything but 401 proves auth passed."""
    status = {}

    async def run():
        async def receive():
            return {"type": "http.request", "body": b"{}", "more_body": False}

        async def send(message):
            if message["type"] == "http.response.start":
                status["code"] = message["status"]

        scope = {"type": "http", "method": "POST", "path": "/mcp", "root_path": "",
                 "headers": headers, "query_string": b""}
        # Run under the app lifespan (starts the MCP session manager's task group), then
        # call the mounted endpoint directly (routing tested implicitly via build).
        async with app.router.lifespan_context(app):
            await app.routes[0].app(scope, receive, send)

    anyio.run(run)
    return status.get("code")


def test_asgi_rejects_missing_bearer():
    app = mcp_server.build_mcp_asgi_app({})
    assert _asgi_call(app, []) == 401


def test_asgi_rejects_bad_ticket():
    app = mcp_server.build_mcp_asgi_app({})
    assert _asgi_call(app, [(b"authorization", b"Bearer garbage")]) == 401


def test_asgi_accepts_valid_ticket():
    app = mcp_server.build_mcp_asgi_app({})
    tok = make_ticket("u@x", "s")
    code = _asgi_call(app, [(b"authorization", f"Bearer {tok}".encode()),
                            (b"content-type", b"application/json")])
    assert code is not None and code != 401


def test_on_call_observer_fires_with_identity():
    """The on_call seam replaces Agno's in-process tool traces for observability — the
    eval harness's routing suite depends on it."""
    import mcp.types as mcp_types

    recorded = []
    fns = mcp_server.flatten_functions([_StubToolkit()])
    server = mcp_server.build_mcp_server(fns, on_call=lambda name, ident: recorded.append(
        (name, getattr(ident, "user_id", None))))
    handler = server.request_handlers[mcp_types.CallToolRequest]

    async def run():
        token = mcp_server._identity_var.set(Identity("obs@x", "s"))
        try:
            req = mcp_types.CallToolRequest(
                method="tools/call",
                params=mcp_types.CallToolRequestParams(name="_greet",
                                                       arguments={"name": "bob"}))
            return await handler(req)
        finally:
            mcp_server._identity_var.reset(token)

    anyio.run(run)
    assert recorded == [("_greet", "obs@x")]


def test_on_call_observer_errors_never_break_the_call():
    import mcp.types as mcp_types

    def boom(name, ident):
        raise RuntimeError("observer exploded")

    fns = mcp_server.flatten_functions([_StubToolkit()])
    server = mcp_server.build_mcp_server(fns, on_call=boom)
    handler = server.request_handlers[mcp_types.CallToolRequest]

    async def run():
        token = mcp_server._identity_var.set(Identity("obs@x", "s"))
        try:
            req = mcp_types.CallToolRequest(
                method="tools/call",
                params=mcp_types.CallToolRequestParams(name="_greet",
                                                       arguments={"name": "bob"}))
            return await handler(req)
        finally:
            mcp_server._identity_var.reset(token)

    result = anyio.run(run)
    text = result.root.content[0].text if hasattr(result, "root") else str(result)
    assert "hello bob" in str(text)
