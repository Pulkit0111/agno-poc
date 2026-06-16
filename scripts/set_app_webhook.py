#!/usr/bin/env python
"""Point the GitHub App's webhook at a given URL (for local/tunnel dev).

GitHub Apps have a single webhook URL; a cloudflared/ngrok tunnel gives a fresh public
URL each run, so this updates the App's `hook/config` to match. Authenticates as the App
with a short-lived JWT (App ID + private key from the environment) and sets the shared
secret so signatures keep verifying.

Usage:
    python scripts/set_app_webhook.py https://<tunnel>.trycloudflare.com/webhook/github
"""

from __future__ import annotations

import sys

import httpx
from dotenv import load_dotenv

load_dotenv()

from bott.agents.code_review.github.app_auth import _app_jwt  # noqa: E402
from bott.shared.config import (  # noqa: E402
    github_app_id,
    github_app_private_key,
    github_webhook_secret,
)

API = "https://api.github.com"


def main(argv: list[str] | None = None) -> int:
    argv = argv if argv is not None else sys.argv[1:]
    if not argv:
        print("usage: set_app_webhook.py <full-webhook-url>")
        return 2
    url = argv[0]

    app_id, pem = github_app_id(), github_app_private_key()
    if not app_id or not pem:
        print("GitHub App not configured (GITHUB_APP_ID / GITHUB_APP_PRIVATE_KEY[_PATH]).")
        return 1

    headers = {
        "Authorization": f"Bearer {_app_jwt(app_id, pem)}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
        "User-Agent": "bott-poc-dev",
    }
    body: dict[str, str] = {"url": url, "content_type": "json", "insecure_ssl": "0"}
    secret = github_webhook_secret()
    if secret:
        body["secret"] = secret  # so X-Hub-Signature-256 keeps verifying

    with httpx.Client(timeout=30) as c:
        r = c.patch(f"{API}/app/hook/config", headers=headers, json=body)
        if r.status_code >= 400:
            print(f"PATCH /app/hook/config -> {r.status_code}: {r.text[:300]}")
            r.raise_for_status()
        cfg = c.get(f"{API}/app/hook/config", headers=headers).json()
    print(f"App webhook now -> {cfg.get('url')}  (content_type={cfg.get('content_type')})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
