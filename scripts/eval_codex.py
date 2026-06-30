"""Live, on-demand check that the org Codex token drives one real completion (spends a call).

Gray-area: uses the undocumented ChatGPT backend. Run manually, never in CI.

Usage: python scripts/eval_codex.py            # bootstraps from ~/.codex/auth.json
"""
from __future__ import annotations

from dotenv import load_dotenv

load_dotenv()


def main() -> int:
    from agno.agent import Agent

    from bott.shared import codex_tokens
    from bott.shared.codex_model import build_codex_model
    from bott.shared.config import role_model_id

    if not codex_tokens.is_connected():
        if not codex_tokens.bootstrap_from_local():
            print("No org Codex token and no ~/.codex/auth.json to bootstrap from.")
            return 1
        print("Bootstrapped org Codex token from ~/.codex/auth.json.")
    model = build_codex_model(role_model_id("chat"))
    agent = Agent(model=model, telemetry=False, markdown=False)
    resp = agent.run("Reply with exactly: codex gateway ok")
    print("RESPONSE:", (getattr(resp, "content", "") or "").strip())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
