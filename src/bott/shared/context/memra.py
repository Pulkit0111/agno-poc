"""Memra — the read-only context layer, reached over MCP (streamable-http).

Auth is OAuth ``client_credentials`` (no refresh token), so the access token is
re-minted on expiry. The MCP session is initialized lazily and re-initialized if the
server drops it. ``MemraClient`` is the low-level client (token + MCP call); flows call
its convenience methods, and the agent gets plain callables via ``make_memra_tools``.

All tools are read-only retrieval (scope ``mcp:retrieve:internal``); the write-ish
``propose_alias`` tool is deliberately NOT exposed.
"""

from __future__ import annotations

import json
import threading
import time
from typing import Any, Callable, Optional

import httpx

from bott.shared.config import (
    memra_client_id,
    memra_client_secret,
    memra_mcp_endpoint,
    memra_scope,
    memra_token_endpoint,
)
from bott.shared.observability.logging_setup import get_logger

log = get_logger("context.memra")

_PROTOCOL_VERSION = "2025-06-18"


class MemraError(RuntimeError):
    pass


class MemraClient:
    """Thread-safe Memra MCP client with client-credentials token + lazy MCP session."""

    def __init__(
        self,
        *,
        client_id: Optional[str] = None,
        client_secret: Optional[str] = None,
        token_endpoint: Optional[str] = None,
        mcp_endpoint: Optional[str] = None,
        scope: Optional[str] = None,
        timeout: float = 60.0,
    ) -> None:
        self._client_id = client_id or memra_client_id()
        self._client_secret = client_secret or memra_client_secret()
        self._token_endpoint = token_endpoint or memra_token_endpoint()
        self._mcp_endpoint = mcp_endpoint or memra_mcp_endpoint()
        self._scope = scope or memra_scope()
        self._timeout = timeout

        self._lock = threading.Lock()
        self._token: Optional[str] = None
        self._token_exp: float = 0.0
        self._session_id: Optional[str] = None

    # ── auth ────────────────────────────────────────────────────────────────────
    def _ensure_token(self) -> str:
        with self._lock:
            if self._token and time.time() < self._token_exp:
                return self._token
            if not (self._client_id and self._client_secret and self._token_endpoint):
                raise MemraError("Memra credentials are not configured (MEMRA_* env).")
            resp = httpx.post(
                self._token_endpoint,
                data={
                    "grant_type": "client_credentials",
                    "client_id": self._client_id,
                    "client_secret": self._client_secret,
                    "scope": self._scope,
                },
                timeout=self._timeout,
            )
            if resp.status_code != 200:
                raise MemraError(f"Memra token request failed: {resp.status_code}")
            data = resp.json()
            self._token = data["access_token"]
            # No refresh token — re-mint a minute before expiry.
            self._token_exp = time.time() + int(data.get("expires_in", 3600)) - 60
            self._session_id = None  # a new token invalidates any prior session
            return self._token

    # ── MCP transport ─────────────────────────────────────────────────────────────
    def _headers(self) -> dict[str, str]:
        h = {
            "Authorization": f"Bearer {self._ensure_token()}",
            "Content-Type": "application/json",
            "Accept": "application/json, text/event-stream",
        }
        if self._session_id:
            h["Mcp-Session-Id"] = self._session_id
        return h

    @staticmethod
    def _parse(resp: httpx.Response) -> Optional[dict]:
        if "text/event-stream" in resp.headers.get("content-type", ""):
            for line in resp.text.splitlines():
                if line.startswith("data:"):
                    try:
                        return json.loads(line[5:].strip())
                    except json.JSONDecodeError:
                        continue
            return None
        try:
            return resp.json()
        except ValueError:
            return None

    def _rpc(self, payload: dict) -> httpx.Response:
        return httpx.post(self._mcp_endpoint, headers=self._headers(), json=payload, timeout=self._timeout)

    def _ensure_session(self) -> None:
        if self._session_id:
            return
        resp = self._rpc(
            {
                "jsonrpc": "2.0", "id": 1, "method": "initialize",
                "params": {
                    "protocolVersion": _PROTOCOL_VERSION,
                    "capabilities": {},
                    "clientInfo": {"name": "bott", "version": "0.1"},
                },
            }
        )
        if resp.status_code != 200:
            raise MemraError(f"Memra MCP initialize failed: {resp.status_code}")
        self._session_id = resp.headers.get("mcp-session-id")
        # Best-effort 'initialized' notification (some servers require it).
        try:
            self._rpc({"jsonrpc": "2.0", "method": "notifications/initialized"})
        except httpx.HTTPError:
            pass

    # ── public API ────────────────────────────────────────────────────────────────
    def call_tool(self, name: str, arguments: Optional[dict] = None) -> Any:
        """Call a Memra MCP tool and return the parsed result (dict if JSON, else text).
        Re-initializes the session once if the server reports it expired."""
        for attempt in range(2):
            self._ensure_session()
            resp = self._rpc(
                {
                    "jsonrpc": "2.0", "id": 2, "method": "tools/call",
                    "params": {"name": name, "arguments": arguments or {}},
                }
            )
            if resp.status_code in (400, 404) and attempt == 0:
                self._session_id = None  # stale session — re-init and retry
                continue
            data = self._parse(resp)
            if not data or "result" not in data:
                err = (data or {}).get("error") if isinstance(data, dict) else None
                raise MemraError(f"Memra tool '{name}' failed: {err or resp.status_code}")
            content = data["result"].get("content", [])
            text = content[0].get("text", "") if content else ""
            try:
                return json.loads(text)
            except (json.JSONDecodeError, TypeError):
                return text
        raise MemraError(f"Memra tool '{name}' failed after retry.")

    def list_tools(self) -> list[str]:
        self._ensure_session()
        data = self._parse(self._rpc({"jsonrpc": "2.0", "id": 3, "method": "tools/list"}))
        return [t["name"] for t in (data or {}).get("result", {}).get("tools", [])]

    # convenience wrappers (read-only) ----------------------------------------------
    def ask_context(self, question: str, **kw) -> Any:
        return self.call_tool("ask_context", {"question": question, **kw})

    def context_map(self, level: str, entity_id: Optional[str] = None) -> Any:
        args = {"level": level}
        if entity_id:
            args["entity_id"] = entity_id
        return self.call_tool("context_map", args)

    def engagements_at_risk(self, **kw) -> Any:
        return self.call_tool("engagements_at_risk", kw)

    def get_person(self, person_id: str) -> Any:
        return self.call_tool("get_person", {"person_id": person_id})

    def get_entity(self, entity_id: str, entity_type: str) -> Any:
        return self.call_tool("get_entity", {"entity_id": entity_id, "entity_type": entity_type})

    def entity_dataset(self, entity_id: str, entity_type: str) -> Any:
        return self.call_tool("entity_dataset", {"entity_id": entity_id, "entity_type": entity_type})

    def get_chunk(self, chunk_id: str) -> Any:
        return self.call_tool("get_chunk", {"chunk_id": chunk_id})

    def resolve_channel_entity(self, slack_channel_id: str) -> Any:
        return self.call_tool("resolve_channel_entity", {"slack_channel_id": slack_channel_id})


def _as_text(value: Any) -> str:
    return value if isinstance(value, str) else json.dumps(value, ensure_ascii=False)


def make_memra_tools(client: MemraClient) -> list[Callable]:
    """Plain callables the agent can use to read Axelerant context from Memra. Each
    returns a JSON/text string for the model. Read-only — no write tools exposed."""

    def memra_ask_context(question: str) -> str:
        """Ask the Axelerant context layer a natural-language question and get a grounded,
        cited answer (delivery status, action items, risks, who-owns-what).

        Args:
            question: The question to answer from internal context.
        """
        return _as_text(client.ask_context(question))

    def memra_engagements_at_risk() -> str:
        """List active engagements ranked by delivery risk, with weekly sentiment bands."""
        return _as_text(client.engagements_at_risk())

    def memra_context_map(level: str, entity_id: str = "") -> str:
        """Get a structured context map for an entity.

        Args:
            level: One of 'organization', 'account', 'engagement', or 'person'.
            entity_id: The entity id (omit for the organization level).
        """
        return _as_text(client.context_map(level, entity_id or None))

    def memra_get_person(person_id: str) -> str:
        """Get a person's canonical identity and cross-source ids.

        Args:
            person_id: The Memra person id.
        """
        return _as_text(client.get_person(person_id))

    def memra_get_entity(entity_id: str, entity_type: str) -> str:
        """Get a single entity record.

        Args:
            entity_id: The entity id.
            entity_type: The entity type (e.g. 'account', 'engagement').
        """
        return _as_text(client.get_entity(entity_id, entity_type))

    def memra_entity_dataset(entity_id: str, entity_type: str) -> str:
        """Get the coverage/inventory dataset for an entity.

        Args:
            entity_id: The entity id.
            entity_type: The entity type.
        """
        return _as_text(client.entity_dataset(entity_id, entity_type))

    def memra_get_chunk(chunk_id: str) -> str:
        """Fetch the full source chunk (with citation) behind a cited claim.

        Args:
            chunk_id: The source chunk id from a prior result.
        """
        return _as_text(client.get_chunk(chunk_id))

    def memra_resolve_channel_entity(slack_channel_id: str) -> str:
        """Resolve a Slack channel id to the engagement/account entity it maps to.

        Args:
            slack_channel_id: The Slack channel id (e.g. 'C0123ABCD').
        """
        return _as_text(client.resolve_channel_entity(slack_channel_id))

    return [
        memra_ask_context,
        memra_engagements_at_risk,
        memra_context_map,
        memra_get_person,
        memra_get_entity,
        memra_entity_dataset,
        memra_get_chunk,
        memra_resolve_channel_entity,
    ]
