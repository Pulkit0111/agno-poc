"""AgentOS HTTP front door for Bott — the control-plane API the dashboard consumes.

Serves the same manager team + code-review agent as Slack, backed by the SAME SqliteDb
(agentos.db). Runs as a separate process from the Slack server.

Auth: when AGENT_OS_JWT_SECRET is set, a JWTMiddleware validates a short-lived HS256
token minted by the Next.js BFF (the only legitimate caller). When unset, the API runs
open — local dev only.

Run:  agentos-server   (or: python -m bott.interfaces.agentos)
"""

from __future__ import annotations

import os

from dotenv import load_dotenv

load_dotenv()

from agno.db.sqlite import SqliteDb
from agno.os import AgentOS

from bott.manager.manager import build_manager
from bott.shared.config import agentos_db_path, agentos_jwt_secret

_db = SqliteDb(db_file=agentos_db_path())
_team = build_manager(db=_db)
_code_review = _team.members[0]

agent_os = AgentOS(
    id="bott-os",
    name="Bott OS",
    description="Bott — a conversational engineering teammate.",
    agents=[_code_review],
    teams=[_team],
    db=_db,
    telemetry=False,
)
app = agent_os.get_app()

_secret = agentos_jwt_secret()
if _secret:
    from agno.os.middleware import JWTMiddleware

    app.add_middleware(
        JWTMiddleware,
        verification_keys=[_secret],
        algorithm="HS256",
        validate=True,
        user_id_claim="sub",
        dependencies_claims=["email", "name", "hd"],
        # /health, /docs, /openapi.json, etc. stay public by JWTMiddleware default.
    )


def main() -> None:
    agent_os.serve(
        app="bott.interfaces.agentos:app",
        host=os.getenv("AGENTOS_HOST", "localhost"),
        port=int(os.getenv("AGENTOS_PORT", "7777")),
    )


if __name__ == "__main__":
    main()
