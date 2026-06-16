"""GitHub App authentication (Phase 3) — port of Bott's app-auth.

App ID + private key → short-lived app JWT → per-installation access token (cached,
~1h). The installation token authenticates clone (x-access-token), PR reads, and
posting the review as the app's own identity. This also gives 5000 req/hr (vs the
60/hr unauthenticated limit).
"""

from __future__ import annotations

import threading
import time
from typing import Optional

import httpx
import jwt

from bott.shared.config import github_app_id, github_app_private_key

API = "https://api.github.com"
_lock = threading.Lock()
# (owner/name) -> (token, expires_epoch)
_cache: dict[str, tuple[str, float]] = {}


def _app_jwt(app_id: str, private_key_pem: str) -> str:
    now = int(time.time())
    return jwt.encode(
        {"iat": now - 60, "exp": now + 540, "iss": str(app_id)},
        private_key_pem,
        algorithm="RS256",
    )


def _mint(app_id: str, private_key_pem: str, owner: str, name: str) -> tuple[str, float]:
    j = _app_jwt(app_id, private_key_pem)
    h = {
        "Authorization": f"Bearer {j}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
        "User-Agent": "bott-poc-review",
    }
    with httpx.Client(timeout=30) as c:
        inst = c.get(f"{API}/repos/{owner}/{name}/installation", headers=h)
        inst.raise_for_status()
        iid = inst.json()["id"]
        tok = c.post(f"{API}/app/installations/{iid}/access_tokens", headers=h)
        tok.raise_for_status()
        d = tok.json()
    # expires_at is ISO; just cache for ~55 min from now to be safe.
    return d["token"], time.time() + 55 * 60


def app_token_for(owner: str, name: str) -> Optional[str]:
    """Installation token for owner/name, or None if the App isn't configured.
    Cached and refreshed ~5 min before expiry."""
    app_id = github_app_id()
    pem = github_app_private_key()
    if not app_id or not pem:
        return None
    key = f"{owner}/{name}".lower()
    with _lock:
        cached = _cache.get(key)
        if cached and cached[1] - 300 > time.time():
            return cached[0]
        token, exp = _mint(app_id, pem, owner, name)
        _cache[key] = (token, exp)
        return token
