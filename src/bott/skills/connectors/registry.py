"""Modular connector registry. Org connectors are shared (configured once); user
connectors read one person's account (token resolved at call time). New connectors
register here without core changes. User-connector OAuth flows land in a later phase —
this is the seam they plug into."""

from __future__ import annotations

from typing import Callable


class Connector:
    name: str = ""
    scope: str = ""  # "org" | "user"
    auth: str = ""   # "org_credential" | "domain_delegated" | "user_oauth"

    def tools(self) -> list[Callable]:
        raise NotImplementedError


class OrgConnector(Connector):
    scope = "org"


class UserConnector(Connector):
    scope = "user"


class FunctionConnector(Connector):
    """Wraps an existing tools-list factory as a registry entry. Internals untouched.
    Gating stays inside the factory, so tools() reflects current config on every call."""

    def __init__(self, name: str, auth: str, tools_fn: Callable[[], list[Callable]]):
        self.name = name
        self.auth = auth
        self.scope = "user" if auth in ("domain_delegated", "user_oauth") else "org"
        self._tools_fn = tools_fn

    def tools(self) -> list[Callable]:
        return self._tools_fn()


class Registry:
    def __init__(self) -> None:
        self._items: list[Connector] = []

    def register(self, connector: Connector) -> None:
        self._items.append(connector)

    def all_connectors(self) -> list[Connector]:
        return list(self._items)

    def all_tools(self) -> list[Callable]:
        out: list[Callable] = []
        for c in self._items:
            out.extend(c.tools())
        return out

    def org_connectors(self) -> list[Connector]:
        return [c for c in self._items if c.scope == "org"]

    def user_connectors(self) -> list[Connector]:
        return [c for c in self._items if c.scope == "user"]

    def list_names(self) -> dict[str, list[str]]:
        return {"org": [c.name for c in self.org_connectors()],
                "user": [c.name for c in self.user_connectors()]}


# Process-wide registry the agent builder reads.
REGISTRY = Registry()
