"""Per-invocation MCP bearer tickets.

Each chat turn's `codex exec` child gets ONE short-lived signed token via env
(`--bearer-token-env-var`-style config); the MCP server verifies it and binds every tool
call in that invocation to the verified Slack identity. The model never chooses who it
is — identity travels out-of-band from Slack → CodexExecChat → ticket → MCP dispatch,
exactly like the old Agno run_context path (scripts/isolation_test.py's invariant).
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass

from bott.shared import config
from bott.shared.secrets import SecretBox


class TicketError(Exception):
    pass


@dataclass
class Identity:
    user_id: str
    session_id: str


def _box() -> SecretBox:
    key = config.bott_secret_key()
    if not key:
        raise TicketError("BOTT_SECRET_KEY is not set — cannot sign MCP tickets")
    return SecretBox(key)


def make_ticket(user_id: str, session_id: str = "") -> str:
    if not user_id:
        raise TicketError("cannot mint a ticket without a user_id")
    payload = json.dumps({"u": user_id, "s": session_id or "", "t": int(time.time())})
    return _box().encrypt(payload)


def verify_ticket(token: str) -> Identity:
    try:
        data = json.loads(_box().decrypt(token))
    except TicketError:
        raise
    except Exception as e:  # noqa: BLE001 — any decrypt/parse failure is one thing: invalid
        raise TicketError("invalid ticket") from e
    if int(time.time()) - int(data.get("t", 0)) > config.bott_mcp_ticket_ttl_s():
        raise TicketError("expired ticket")
    if not data.get("u"):
        raise TicketError("ticket missing user")
    return Identity(user_id=data["u"], session_id=data.get("s", ""))
