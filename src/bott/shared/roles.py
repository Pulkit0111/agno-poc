"""Single source of truth for "who is an admin" and "who's been invited ahead of their
first sign-in" — every console/Slack/skill authorization check routes through here.

Two admin sources, unioned:
  - env-seeded (BOTT_ADMINS): permanent for the life of the process. Whoever deploys Bott
    stays an admin no matter what happens in the console UI — this is the lockout guard.
  - KV-promoted (settings table, key `role:<email>`): admins/members set at runtime via
    the console. Can promote or demote freely, EXCEPT an env-seeded admin can never be
    demoted this way (set_role raises), and the last remaining admin can never be
    demoted to zero admins.

KV reads (kv_admins/invites) are tolerant of a missing/unreachable settings table — same
philosophy as records.get_setting — because is_admin() sits on the hot path of every single
console request (via sessions.verify_session); a transient DB hiccup must fail closed (no
KV admins recognized, env-seeded admins still work) rather than 500 the whole console.
Writes (set_role/add_invite/revoke_invite) are NOT tolerant — those are deliberate,
admin-gated mutations and any DB error there must surface, not be silently swallowed.

Only imports config + persistence.records — no imports from interfaces/* here, to avoid
circular imports (console/slack_home/skills all import THIS module).
"""

from __future__ import annotations

import json
import time
from typing import Optional

from bott.shared import config
from bott.shared.observability.logging_setup import get_logger
from bott.shared.persistence import records

log = get_logger("bott.roles")

_ROLE_PREFIX = "role:"
_INVITE_PREFIX = "invite:"
_VALID_ROLES = {"admin", "member"}


class RoleError(Exception):
    """Raised for a rejected role mutation. `slug` is a short machine-readable reason the
    console router maps to an HTTP status code (e.g. "locked" -> 403, "last_admin" -> 409,
    "wrong_domain"/"bad_role" -> 422)."""

    def __init__(self, slug: str, message: str):
        super().__init__(message)
        self.slug = slug


def _norm_email(email: str) -> str:
    return (email or "").strip().lower()


def _norm_role(role: str) -> str:
    return (role or "").strip().lower()


def _parse_role(raw: Optional[str]) -> Optional[str]:
    """A KV value is the JSON audit blob {"role","by","at"}; "" (revoked) or malformed
    values parse to None."""
    if not raw:
        return None
    try:
        role = json.loads(raw).get("role")
    except (ValueError, AttributeError, TypeError):
        return None
    return role if role in _VALID_ROLES else None


def env_admins() -> set[str]:
    """Emails seeded via BOTT_ADMINS — permanent, never demotable via set_role."""
    return config.bott_admins()


def kv_admins() -> set[str]:
    """Emails promoted to admin at runtime via the console (settings table)."""
    try:
        rows = records.list_settings_by_prefix(_ROLE_PREFIX)
    except Exception:  # noqa: BLE001 — is_admin must fail closed, never 500 the console
        log.warning("roles.kv_admins: settings read failed, treating as empty")
        return set()
    out = set()
    for key, raw in rows.items():
        if _parse_role(raw) == "admin":
            out.add(key[len(_ROLE_PREFIX):])
    return out


def is_admin(email: str) -> bool:
    """THE admin check — env ∪ KV. Used by the console session, Slack Home, and skill
    authoring; nothing outside this module should read BOTT_ADMINS for authorization."""
    email = _norm_email(email)
    if not email:
        return False
    return email in env_admins() or email in kv_admins()


def set_role(email: str, role: str, actor: str) -> None:
    """Promote/demote via KV. Raises RoleError (never silently no-ops) when:
      - role isn't "admin"/"member" (slug "bad_role")
      - demoting an env-seeded admin (slug "locked") — the lockout guard
      - the demotion would leave zero admins total, env ∪ KV (slug "last_admin")
    """
    email = _norm_email(email)
    role = _norm_role(role)
    if role not in _VALID_ROLES:
        raise RoleError("bad_role", f"'{role}' isn't a role — use admin or member.")
    if role == "member":
        if email in env_admins():
            raise RoleError("locked", "Server-seeded admins can't be demoted here.")
        current_admins = env_admins() | kv_admins()
        if email in current_admins and len(current_admins) <= 1:
            raise RoleError("last_admin", "Can't remove the last admin — promote someone else first.")
    records.set_setting(
        f"{_ROLE_PREFIX}{email}",
        json.dumps({"role": role, "by": _norm_email(actor), "at": time.time()}),
    )


def invites() -> dict[str, str]:
    """Pending invites: {email: role} for people pre-provisioned but never signed in."""
    try:
        rows = records.list_settings_by_prefix(_INVITE_PREFIX)
    except Exception:  # noqa: BLE001 — same fail-closed philosophy as kv_admins
        log.warning("roles.invites: settings read failed, treating as empty")
        return {}
    out: dict[str, str] = {}
    for key, raw in rows.items():
        role = _parse_role(raw)
        if role:
            out[key[len(_INVITE_PREFIX):]] = role
    return out


def add_invite(email: str, role: str, actor: str) -> None:
    """Pre-provision a role for someone who hasn't signed in yet. Domain-allowlisted —
    an invite can't be used to plant access for an outside email that OIDC login itself
    would reject at the domain check (RoleError slug "wrong_domain")."""
    email = _norm_email(email)
    role = _norm_role(role)
    if role not in _VALID_ROLES:
        raise RoleError("bad_role", f"'{role}' isn't a role — use admin or member.")
    domain = email.rsplit("@", 1)[-1] if "@" in email else ""
    allowed = config.allowed_email_domain().lower()
    if domain != allowed:
        raise RoleError("wrong_domain", f"Invites must use an @{allowed} address.")
    records.set_setting(
        f"{_INVITE_PREFIX}{email}",
        json.dumps({"role": role, "by": _norm_email(actor), "at": time.time()}),
    )


def revoke_invite(email: str) -> bool:
    """Cancel a pending invite. Returns False (no-op, no raise) if there wasn't one."""
    email = _norm_email(email)
    if email not in invites():
        return False
    records.set_setting(f"{_INVITE_PREFIX}{email}", "")
    return True


def consume_invite(email: str) -> str | None:
    """Called on first sign-in (before computing is_admin): if an invite is pending for
    this email, convert it into a real KV role entry and clear the invite, returning the
    role that was applied. Idempotent/safe when there's no invite — returns None, no-op,
    so every subsequent login for the same email is a cheap no-op read."""
    email = _norm_email(email)
    role = invites().get(email)
    if not role:
        return None
    set_role(email, role, actor="invite")
    records.set_setting(f"{_INVITE_PREFIX}{email}", "")
    return role
