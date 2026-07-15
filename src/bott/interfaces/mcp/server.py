"""bott's chat-tools MCP server.

Chat runs through `codex exec`, whose internal agent loop can't call in-process Agno
tools — so the SAME toolkits the Agno agent used to carry are served here over MCP
(streamable HTTP, loopback-only). codex is pointed at this server per invocation with a
signed bearer ticket (tickets.py) carrying the verified Slack user_id; every dispatch
builds a run_context from that ticket, so per-user isolation is enforced exactly where
it always was — in the tools, keyed by an identity the model cannot influence.

The server runs INSIDE the bott process (full env — secrets never enter the codex child
env or command line) on its own loopback uvicorn server, decoupled from AgentOS's
FastAPI lifespan.
"""

from __future__ import annotations

import contextvars
import inspect
import threading
from types import SimpleNamespace
from typing import Iterable, Optional

import anyio
import mcp.types as mcp_types
from agno.tools.function import Function
from agno.tools.toolkit import Toolkit
from mcp.server import Server
from mcp.server.streamable_http_manager import StreamableHTTPSessionManager

from bott.interfaces.mcp.tickets import Identity, TicketError, verify_ticket
from bott.shared import config
from bott.shared.observability.logging_setup import get_logger
from bott.skills.workspace_tools import workspace_scope

log = get_logger("bott.mcp")

# Identity of the request currently being served — set by the auth wrapper from the
# verified bearer ticket, read by the call_tool dispatcher. A ContextVar (not a module
# attribute) so concurrent requests can't see each other's identity.
_identity_var: "contextvars.ContextVar[Optional[Identity]]" = contextvars.ContextVar(
    "bott_mcp_identity", default=None
)

# Agno-reserved entrypoint params that must never be model-supplied: they're injected by
# the dispatcher (run_context) or simply not available outside an Agno run (the rest).
_RESERVED_PARAMS = ("run_context", "agent", "team", "session_state")


def _default_parameters(fn: Function) -> bool:
    props = (fn.parameters or {}).get("properties")
    return not props


def flatten_functions(tools: Iterable) -> dict[str, Function]:
    """Normalize the chat tool list (Agno Toolkits, bare Functions, raw callables) into a
    name → Function map with model-facing JSON schemas populated and reserved params
    stripped. Duplicate names keep the first registration (and log), matching Agno."""
    out: dict[str, Function] = {}

    def _add(fn: Function) -> None:
        if fn.entrypoint is not None and _default_parameters(fn):
            try:
                fn.process_entrypoint()
            except Exception as e:  # noqa: BLE001 — a bad schema shouldn't sink the rest
                log.warning("mcp: could not build schema for tool %s: %s", fn.name, e)
        params = fn.parameters or {"type": "object", "properties": {}, "required": []}
        props = params.get("properties") or {}
        for reserved in _RESERVED_PARAMS:
            if reserved in props:
                props.pop(reserved, None)
                if reserved in (params.get("required") or []):
                    params["required"] = [r for r in params["required"] if r != reserved]
        if fn.name in out:
            log.warning("mcp: duplicate tool name %s — keeping the first", fn.name)
            return
        out[fn.name] = fn

    for item in tools:
        if isinstance(item, Toolkit):
            for fn in item.functions.values():
                _add(fn)
        elif isinstance(item, Function):
            _add(item)
        elif callable(item):
            _add(Function.from_callable(item))
        else:
            log.warning("mcp: skipping unrecognized tool entry %r", item)
    return out


async def dispatch(functions: dict[str, Function], name: str, arguments: dict) -> str:
    """Run one tool call under the current request's verified identity."""
    ident = _identity_var.get()
    if ident is None:
        raise TicketError("no verified identity for this request")
    fn = functions.get(name)
    if fn is None or fn.entrypoint is None:
        raise ValueError(f"unknown tool: {name}")

    kwargs = dict(arguments or {})
    for reserved in _RESERVED_PARAMS:
        kwargs.pop(reserved, None)  # model-supplied identity/params are never honored
    entrypoint = fn.entrypoint
    sig_params = inspect.signature(entrypoint).parameters
    if "run_context" in sig_params:
        kwargs["run_context"] = SimpleNamespace(
            user_id=ident.user_id, session_id=ident.session_id
        )

    with workspace_scope(ident.user_id):
        if inspect.iscoroutinefunction(entrypoint):
            result = await entrypoint(**kwargs)
        else:
            # anyio propagates contextvars into the worker thread, so the workspace scope
            # and identity still apply inside sync tools.
            result = await anyio.to_thread.run_sync(lambda: entrypoint(**kwargs))
    return result if isinstance(result, str) else str(result)


def build_mcp_server(functions: dict[str, Function]) -> Server:
    server: Server = Server("bott")

    @server.list_tools()
    async def _list_tools() -> list[mcp_types.Tool]:
        return [
            mcp_types.Tool(
                name=fn.name,
                description=fn.description or "",
                inputSchema=fn.parameters
                or {"type": "object", "properties": {}, "required": []},
            )
            for fn in functions.values()
        ]

    @server.call_tool()
    async def _call_tool(name: str, arguments: dict) -> list[mcp_types.TextContent]:
        try:
            text = await dispatch(functions, name, arguments)
        except Exception as e:  # noqa: BLE001 — tool errors go back to the model as text
            log.warning("mcp: tool %s failed: %s", name, e)
            text = f"Error: {e}"
        return [mcp_types.TextContent(type="text", text=text)]

    return server


async def _unauthorized(send) -> None:
    await send({"type": "http.response.start", "status": 401,
                "headers": [(b"content-type", b"text/plain")]})
    await send({"type": "http.response.body", "body": b"unauthorized"})


def build_mcp_asgi_app(functions: dict[str, Function]):
    """Streamable-HTTP ASGI app: bearer-ticket auth wrapper around the MCP session
    manager. Stateless + JSON responses — each codex exec invocation initializes its own
    short-lived MCP session."""
    from starlette.applications import Starlette
    from starlette.routing import Mount

    server = build_mcp_server(functions)
    manager = StreamableHTTPSessionManager(app=server, json_response=True, stateless=True)

    async def endpoint(scope, receive, send):
        if scope["type"] != "http":
            await _unauthorized(send)
            return
        headers = {k.decode().lower(): v.decode() for k, v in scope.get("headers", [])}
        auth = headers.get("authorization", "")
        if not auth.lower().startswith("bearer "):
            await _unauthorized(send)
            return
        try:
            ident = verify_ticket(auth[7:].strip())
        except TicketError as e:
            log.warning("mcp: rejected request (%s)", e)
            await _unauthorized(send)
            return
        token = _identity_var.set(ident)
        try:
            await manager.handle_request(scope, receive, send)
        finally:
            _identity_var.reset(token)

    return Starlette(routes=[Mount("/mcp", app=endpoint)],
                     lifespan=lambda app: manager.run())


def start_mcp_server_thread(tools: Iterable) -> threading.Thread:
    """Serve the chat toolkits on 127.0.0.1:bott_mcp_port() in a daemon thread (its own
    event loop — independent of AgentOS's FastAPI lifespan)."""
    import uvicorn

    app = build_mcp_asgi_app(flatten_functions(tools))
    server = uvicorn.Server(uvicorn.Config(
        app, host="127.0.0.1", port=config.bott_mcp_port(), log_level="warning"))
    thread = threading.Thread(target=server.run, daemon=True, name="bott-mcp")
    thread.start()
    log.info("MCP chat-tools server listening on %s", config.bott_mcp_url())
    return thread
