"""Phase-1 dry-run harness.

    python -m pr_reviewer.interfaces.cli <PR-URL | owner/repo/number> [flags]

Runs the full review pipeline and PRINTS the rendered GitHub review + the 10-row
gate decision table + token/cost. Posts nothing unless --post is given (phase 3),
which is allowlist-guarded.
"""

from __future__ import annotations

import argparse
import os
import re
import sys

from dotenv import load_dotenv

from ..config import DEFAULT_MODEL, Budget
from ..core.pipeline import review_pr

_URL_RE = re.compile(r"github\.com/([^/]+)/([^/]+)/pull/(\d+)")
_SLUG_RE = re.compile(r"^([^/]+)/([^/]+)/(\d+)$")


def parse_pr_ref(ref: str) -> tuple[str, str, int]:
    m = _URL_RE.search(ref)
    if m:
        return m.group(1), m.group(2), int(m.group(3))
    m = _SLUG_RE.match(ref.strip())
    if m:
        return m.group(1), m.group(2), int(m.group(3))
    raise SystemExit(f"Could not parse PR reference: {ref!r} (use a PR URL or owner/repo/number)")


def _allowed_to_post(owner: str, name: str) -> bool:
    allow = os.getenv("ALLOWED_POST_REPOS", "")
    repos = {r.strip().lower() for r in allow.split(",") if r.strip()}
    return f"{owner}/{name}".lower() in repos


def main(argv: list[str] | None = None) -> int:
    load_dotenv()
    ap = argparse.ArgumentParser(description="Bott-POC PR review (dry-run by default).")
    ap.add_argument("pr", help="PR URL or owner/repo/number")
    ap.add_argument("--model", default=DEFAULT_MODEL)
    ap.add_argument("--max-tool-calls", type=int, default=30)
    ap.add_argument("--max-tokens", type=int, default=200_000)
    ap.add_argument("--max-usd", type=float, default=0.50)
    ap.add_argument("--json-mode", action="store_true", help="Use JSON mode instead of strict structured output.")
    ap.add_argument("--post", action="store_true", help="Actually post to GitHub (allowlist-guarded).")
    args = ap.parse_args(argv)

    owner, name, number = parse_pr_ref(args.pr)
    budget = Budget(
        max_tool_calls=args.max_tool_calls, max_tokens=args.max_tokens, max_usd=args.max_usd
    )

    if args.post and not _allowed_to_post(owner, name):
        raise SystemExit(
            f"Refusing to post to {owner}/{name}: not in ALLOWED_POST_REPOS. "
            "Set ALLOWED_POST_REPOS=owner/repo to enable (test repos only)."
        )

    print(f"Reviewing {owner}/{name}#{number}  (model={args.model}, "
          f"{'POST' if args.post else 'DRY-RUN'})\n")

    result = review_pr(
        owner,
        name,
        number,
        model_id=args.model,
        budget=budget,
        post=args.post,
        use_json_mode=args.json_mode,
    )

    r = result.run
    print("=" * 78)
    print(f"PR: {result.meta.title}")
    print(f"    {result.meta.url}")
    print(f"    +{result.meta.additions}/-{result.meta.deletions} across "
          f"{result.meta.changed_files} file(s); CI={result.essentials.ci.overall}")
    print("=" * 78)

    if r.output is None:
        print(f"\nNO VERDICT — termination={r.termination}"
              + (f"  error={r.error}" if r.error else ""))
        _print_usage(r)
        return 1

    gate = result.gate
    rendered = result.rendered
    assert gate and rendered

    print(f"\nVERDICT: {gate.original_verdict.upper()} (model) -> "
          f"{gate.final_verdict.upper()} (final)   [{gate.outcome}]")
    if gate.downgrade_reason:
        print(f"  downgrade reason: {gate.downgrade_reason}")
    if gate.soft_note:
        print(f"  soft note: {gate.soft_note}")

    print("\nGATE DECISIONS")
    for d in gate.decisions:
        mark = "PASS" if d.passed else "FAIL"
        print(f"  [{mark}] {d.precondition}: {d.detail}")

    print("\n" + "-" * 78)
    print(f"GITHUB REVIEW  (event = {rendered.event})")
    print("-" * 78)
    print(rendered.body)
    print("-" * 78)
    print(f"\nINLINE COMMENTS: {len(rendered.comments)} "
          f"({len(result.resolvable_comments)} anchorable, "
          f"{len(result.unresolvable_comments)} would fall back to body)")
    for c in rendered.comments:
        anchor = "ok " if c in result.resolvable_comments else "FB "
        print(f"  [{anchor}] {c['path']}:{c['line']}")

    _print_usage(r)
    if result.posted:
        print(f"\nPOSTED: {result.posted.get('html_url', '(review created)')}")
    return 0


def _print_usage(r) -> None:
    cost = f"${r.cost_usd:.4f}" if r.cost_usd is not None else "n/a"
    print(f"\nUSAGE: termination={r.termination}  tool_calls={len(r.tool_calls)}  "
          f"tokens(in/out/total)={r.input_tokens}/{r.output_tokens}/{r.total_tokens}  "
          f"cost={cost}  model={r.model_id}")


if __name__ == "__main__":
    sys.exit(main())
