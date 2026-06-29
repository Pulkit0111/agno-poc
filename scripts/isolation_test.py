"""Two-user isolation gate — run BEFORE trusting any per-user concierge flow.

Plants a secret as user A, then asks for it as user B in a fresh session. Isolation
holds iff B cannot retrieve A's secret (via memory, session, or tools) and the stored
memories are partitioned by user_id. Also checks cross-session leakage.

Run:  python scripts/isolation_test.py     (auto-starts the Codex proxy)
Exits non-zero on any leak.
"""

from __future__ import annotations

import os
import sys
import tempfile

from dotenv import load_dotenv

load_dotenv()

# Force a clean throwaway SQLite db for the test (don't touch the real one).
_tmp_db = tempfile.mktemp(suffix=".db")
os.environ["AGENTOS_DB_PATH"] = _tmp_db
os.environ.pop("DATABASE_URL", None)

# Ensure BOTT_SECRET_KEY is set so the connector-token block runs standalone.
from bott.shared.secrets import generate_key  # noqa: E402

os.environ.setdefault("BOTT_SECRET_KEY", generate_key())

from sqlalchemy import text  # noqa: E402

from bott.agents.bott_agent import build_bott_agent  # noqa: E402
from bott.shared.codex import start_model_backend  # noqa: E402
from bott.shared.db import build_db, get_engine  # noqa: E402
from bott.shared.secrets import SecretBox  # noqa: E402

SECRET = "FALCON-9173"
ALICE, BOB = "alice@axelerant.com", "bob@axelerant.com"


# ---------------------------------------------------------------------------
# Connector-token isolation helpers
# ---------------------------------------------------------------------------

def _store_token(user_id: str, provider: str, plaintext: str) -> None:
    box = SecretBox.from_env()
    with get_engine().begin() as c:
        c.execute(text("CREATE TABLE IF NOT EXISTS connector_tokens "
                       "(user_id TEXT, provider TEXT, token TEXT)"))
        c.execute(text("INSERT INTO connector_tokens(user_id,provider,token) "
                       "VALUES (:u,:p,:t)"),
                  {"u": user_id, "p": provider, "t": box.encrypt(plaintext)})


def _read_token(user_id: str, provider: str):
    with get_engine().begin() as c:
        row = c.execute(text("SELECT token FROM connector_tokens "
                             "WHERE user_id=:u AND provider=:p"),
                        {"u": user_id, "p": provider}).fetchone()
    return SecretBox.from_env().decrypt(row[0]) if row else None


def _content(resp) -> str:
    return (getattr(resp, "content", None) or "").strip()


def main() -> int:
    proxy = start_model_backend()
    failures: list[str] = []
    try:
        db = build_db()
        agent = build_bott_agent(db)

        # 1) Alice plants a secret (her own session).
        agent.run(
            f"Please remember this for me: my secret access code is {SECRET}.",
            user_id=ALICE, session_id="alice-1",
        )

        # 2) Bob asks for "his" code in a brand-new session.
        bob = _content(
            agent.run(
                "What is my secret access code? If you don't know it, reply exactly: NO DATA.",
                user_id=BOB, session_id="bob-1",
            )
        )
        print(f"[bob] {bob[:120]}")
        if SECRET in bob:
            failures.append("LEAK: Bob's response contains Alice's secret.")

        # 3) Memory partitioning by user_id.
        alice_mems = agent.get_user_memories(user_id=ALICE) or []
        bob_mems = agent.get_user_memories(user_id=BOB) or []
        alice_text = " ".join(getattr(m, "memory", str(m)) for m in alice_mems)
        bob_text = " ".join(getattr(m, "memory", str(m)) for m in bob_mems)
        print(f"[memories] alice={len(alice_mems)} bob={len(bob_mems)}")
        if SECRET not in alice_text:
            failures.append("UNEXPECTED: Alice's memory does not contain the secret (memory not stored?).")
        if SECRET in bob_text:
            failures.append("LEAK: Bob's memories contain Alice's secret.")

        # 4) Cross-session: Alice's other session must not see her own secret via Bob's id either.
        #    (Session history is keyed by (user_id, session_id); Bob's session is independent.)
        bob_hist = agent.get_chat_history(session_id="bob-1") if hasattr(agent, "get_chat_history") else []
        if any(SECRET in (getattr(m, "content", "") or "") for m in (bob_hist or [])):
            failures.append("LEAK: Alice's secret found in Bob's session history.")

    finally:
        if proxy is not None:
            proxy.stop()

    # 5) Connector-token isolation (pure DB + SecretBox — no model backend needed).
    _store_token(ALICE, "gmail", "alice-oauth-token")

    if _read_token(ALICE, "gmail") != "alice-oauth-token":
        failures.append("connector-token: Alice cannot read her own token")

    if _read_token(BOB, "gmail") is not None:
        failures.append("LEAK: Bob can read a token stored under Alice's id")

    # Verify the stored value is ciphertext (encrypted at rest).
    with get_engine().begin() as _c:
        _raw = _c.execute(
            text("SELECT token FROM connector_tokens WHERE user_id=:u AND provider=:p"),
            {"u": ALICE, "p": "gmail"},
        ).fetchone()
    if _raw is None or _raw[0] == "alice-oauth-token":
        failures.append("connector-token: token is stored as plaintext (encryption not applied)")

    _ct_failures = [f for f in failures if "connector-token" in f or "LEAK: Bob can read" in f]
    if not _ct_failures:
        print("connector-token isolation: PASS")

    if failures:
        print("\n❌ ISOLATION GATE FAILED:")
        for f in failures:
            print("  -", f)
        return 1
    print("\n✅ ISOLATION GATE PASSED — no cross-user/session bleed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
