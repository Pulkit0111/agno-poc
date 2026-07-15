"""MCP bearer tickets — the identity seam between codex exec and bott's tool server."""
from __future__ import annotations

import pytest

from bott.interfaces.mcp import tickets
from bott.shared import config
from bott.shared.secrets import generate_key


@pytest.fixture(autouse=True)
def _key(monkeypatch):
    monkeypatch.setenv("BOTT_SECRET_KEY", generate_key())


def test_ticket_roundtrip():
    tok = tickets.make_ticket("alice@x.com", "sess-1")
    ident = tickets.verify_ticket(tok)
    assert ident.user_id == "alice@x.com"
    assert ident.session_id == "sess-1"


def test_ticket_expires(monkeypatch):
    tok = tickets.make_ticket("alice@x.com", "s")
    monkeypatch.setattr(config, "bott_mcp_ticket_ttl_s", lambda: -1)
    with pytest.raises(tickets.TicketError, match="expired"):
        tickets.verify_ticket(tok)


def test_tampered_ticket_rejected():
    tok = tickets.make_ticket("alice@x.com", "s")
    with pytest.raises(tickets.TicketError, match="invalid"):
        tickets.verify_ticket(tok[:-4] + "AAAA")


def test_garbage_ticket_rejected():
    with pytest.raises(tickets.TicketError):
        tickets.verify_ticket("not-a-ticket")


def test_empty_user_refused():
    with pytest.raises(tickets.TicketError):
        tickets.make_ticket("")


def test_missing_key_fails_closed(monkeypatch):
    monkeypatch.delenv("BOTT_SECRET_KEY", raising=False)
    with pytest.raises(tickets.TicketError, match="BOTT_SECRET_KEY"):
        tickets.make_ticket("alice@x.com")
