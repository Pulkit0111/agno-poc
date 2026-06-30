"""Live end-to-end Build & Fix gate (spends tokens; opens a real draft PR).

Prereqs: GitHub App installed on the target repo WITH contents:write + pull_requests:write;
the repo in ALLOWED_POST_REPOS; MODEL backend reachable. Run on demand, never in CI.

Usage: python scripts/eval_build.py owner/repo "add a CONTRIBUTING.md with a one-line intro"
"""
from __future__ import annotations

import sys

from bott.agents.build_fix.pipeline import implement_task
from bott.agents.code_review.github.app_auth import app_token_for
from bott.shared.config import allowed_post_repos


def main() -> int:
    if len(sys.argv) < 3:
        print("usage: eval_build.py owner/repo \"<plan text>\"")
        return 2
    owner_repo, plan_text = sys.argv[1], sys.argv[2]
    owner, name = owner_repo.split("/", 1)
    if owner_repo.lower() not in allowed_post_repos():
        print(f"ERROR: {owner_repo} not in ALLOWED_POST_REPOS")
        return 1
    token = app_token_for(owner, name)
    if not token:
        print("ERROR: no GitHub App installation token — is the App installed on this repo "
              "with contents:write + pull_requests:write?")
        return 1
    res = implement_task(owner, name, plan_text, token=token, post=True)
    print(f"opened_pr={res.opened_pr} tests={res.tests} url={res.pr_url}\nnote={res.note}")
    return 0 if res.opened_pr else 1


if __name__ == "__main__":
    raise SystemExit(main())
