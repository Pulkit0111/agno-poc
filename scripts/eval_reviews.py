#!/usr/bin/env python
"""Score the reviewer against a manifest of known PRs.

LIVE: actually clones + reviews each PR using whatever model endpoint is configured
(your OpenAI key, or the Codex proxy if REVIEW_MODEL_BASE_URL is set), so it SPENDS
tokens. Run on demand, not in CI.

    python scripts/eval_reviews.py [path/to/eval_cases.json]

Compares the gate's final verdict to each case's `expected` and prints a PASS/FAIL table
+ accuracy + cost, and writes a markdown report to /tmp/bott-eval-report.md.
"""

from __future__ import annotations

import sys
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

import json  # noqa: E402

from bott.agents.code_review.core.pipeline import review_pr  # noqa: E402
from bott.agents.code_review.github.app_auth import app_token_for  # noqa: E402
from bott.shared.config import default_budget  # noqa: E402

DEFAULT_MANIFEST = Path(__file__).parent / "eval_cases.json"
REPORT_PATH = Path("/tmp/bott-eval-report.md")


def main(argv: list[str] | None = None) -> int:
    argv = argv if argv is not None else sys.argv[1:]
    manifest = Path(argv[0]) if argv else DEFAULT_MANIFEST
    data = json.loads(manifest.read_text())
    repo = data["repo"]
    owner, name = repo.split("/")
    cases = data["cases"]

    try:
        token = app_token_for(owner, name)
    except Exception as e:  # noqa: BLE001 — App may not be installed; fall back
        print(f"(no App token for {repo}: {e}; using PAT/unauthenticated)")
        token = None

    rows = []
    print(f"Evaluating {len(cases)} case(s) against {repo}…\n")
    for c in cases:
        num, expected, scenario = c["number"], c["expected"], c.get("scenario", "")
        try:
            r = review_pr(owner, name, num, token=token, budget=default_budget(), post=False)
            actual = r.gate.final_verdict if r.gate else f"no-verdict:{r.run.termination}"
            tools, cost = len(r.run.tool_calls), r.run.cost_usd
        except Exception as e:  # noqa: BLE001 — one bad case shouldn't abort the run
            actual, tools, cost = f"error:{e}", 0, None
        ok = actual == expected
        rows.append({"scenario": scenario, "number": num, "expected": expected,
                     "actual": actual, "ok": ok, "tools": tools, "cost": cost})
        cost_s = f"${cost:.4f}" if isinstance(cost, (int, float)) else "n/a"
        print(f"  {'PASS' if ok else 'FAIL'}  #{num} {scenario}: "
              f"expected={expected} actual={actual} (tools={tools} cost={cost_s})")

    passed = sum(1 for r in rows if r["ok"])
    total = len(rows)
    total_cost = sum(r["cost"] for r in rows if isinstance(r["cost"], (int, float)))
    print(f"\n{passed}/{total} passed · total cost ${total_cost:.4f}")

    lines = [f"# Eval report — {repo}", "", f"**{passed}/{total} passed** · cost ${total_cost:.4f}", "",
             "| result | PR | scenario | expected | actual | tools | cost |",
             "|---|---|---|---|---|---|---|"]
    for r in rows:
        cost_s = f"${r['cost']:.4f}" if isinstance(r["cost"], (int, float)) else "n/a"
        lines.append(f"| {'✅' if r['ok'] else '❌'} | #{r['number']} | {r['scenario']} | "
                     f"{r['expected']} | {r['actual']} | {r['tools']} | {cost_s} |")
    REPORT_PATH.write_text("\n".join(lines) + "\n")
    print(f"report: {REPORT_PATH}")
    return 0 if passed == total else 1


if __name__ == "__main__":
    raise SystemExit(main())
