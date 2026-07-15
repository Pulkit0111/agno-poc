# src/bott/interfaces/slack_home/models.py
"""App Home 'Models' panel — ADMIN ONLY.

Codex-only: the org ChatGPT subscription (via the codex CLI) is the single provider.
The panel shows the task→model matrix, whether the org login is usable right now, and
the codex model picker. Members never see this panel (``models_section`` returns []
for them)."""

from __future__ import annotations

import json
import os

from bott.shared import codex_cli, config
from bott.shared.persistence.records import set_setting


def _active() -> dict:
    """The task→model matrix as resolved right now. `heavy` remains as the legacy store
    fallback build/review inherit when they have no explicit setting. `provider` /
    `providers_by_role` are kept in the payload for API back-compat — they are always
    codex now."""
    from bott.shared.model import resolve_model_id
    return {
        "provider": "codex",
        "chat": resolve_model_id("chat"),
        "build": resolve_model_id("build"),
        "review": resolve_model_id("review"),
        "providers_by_role": {"chat": "codex", "build": "codex", "review": "codex"},
    }


def provider_key_status(provider: str) -> tuple[bool, str]:
    """(usable_now, human hint) — codex is the only provider left."""
    if provider == "codex":
        ok = codex_cli.is_logged_in()
        return ok, ("Org Codex connected" if ok else "Org Codex not connected — connect it below")
    return False, f"Unknown provider `{provider}` (codex-only)."


def available_models(provider: str = "codex") -> list[str]:
    """Models the admin can choose for a task (the codex account catalog)."""
    if provider == "codex":
        return list(config.FALLBACK_CODEX_MODELS)
    return []


_VALID_PROVIDERS = ("codex",)


def catalogs() -> dict:
    """Model-id catalogs for the console's picker — codex only."""
    return {"codex": list(config.FALLBACK_CODEX_MODELS)}


def models_section(is_admin: bool) -> list[dict]:
    """Admin-only panel body (the '🤖 Models' header is added by build_home_view). Returns []
    for non-admins so members never see model controls."""
    if not is_admin:
        return []
    a = _active()
    ok, hint = provider_key_status("codex")
    icon = "✅" if ok else "⚠️"
    # Review and build may share the strongest model (anti-affinity removed) — no conflict
    # to warn about.
    text = (f"*Task → model matrix* (codex)\n"
            f"chat `{a['chat']}`  ·  build `{a['build']}`  ·  review `{a['review']}`\n"
            f"{icon} {hint}")
    blocks: list[dict] = [{"type": "section", "text": {"type": "mrkdwn", "text": text}}]
    # CODEX-ONLY surface (product decision): App Home offers Codex connect/status and the
    # model picker only. The Bedrock/OpenRouter connect flows and the provider switcher are
    # hidden — the backend gateway still understands those providers; this is UI trimming.
    elements: list[dict] = [
        {"type": "button", "text": {"type": "plain_text", "text": "Connect Codex (org)"},
         "action_id": "models_connect_codex"},
        {"type": "button", "text": {"type": "plain_text", "text": "Change models"},
         "action_id": "models_set_models"},
    ]
    blocks.append({"type": "actions", "elements": elements})
    return blocks


def _is_admin(email: str) -> bool:
    from bott.shared import roles
    return roles.is_admin(email)


_OVERRIDE_KEYS = (
    # Codex-only: no provider overrides anymore, just per-role model ids
    # (model.heavy kept for back-compat — the legacy tier build/review fall back to).
    "model.chat", "model.build", "model.review", "model.heavy",
)


def apply_model_override(actor_email: str, key: str, value: str) -> str:
    # model.heavy kept for back-compat (legacy tier build/review fall back to).
    if key not in _OVERRIDE_KEYS:
        return f"Unknown setting `{key}`."
    if not _is_admin(actor_email):
        return "Sorry, that's not allowed — only an admin can change the model."
    set_setting(key, value)
    a = _active()
    return (f"Updated. Now provider=`{a['provider']}` · chat=`{a['chat']}` · "
            f"build=`{a['build']}` · review=`{a['review']}`.\n"
            "Reports, builds, reviews, and App-Home asks pick this up immediately. The "
            "always-on Slack chat assistant (the one that answers @-mentions/DMs) is built "
            "once at startup — it switches on Bott's next restart.")


def connect_codex(actor_email: str, auth_json: str) -> str:
    """Paste-an-auth.json fallback (for hosts where device-auth is awkward): the pasted
    file is written to the shared CODEX_HOME — the CLI's own store, the ONLY token store —
    and the CLI refreshes/rotates it in place from there."""
    if not _is_admin(actor_email):
        return "Sorry, that's not allowed — only an admin can connect the org Codex account."
    try:
        data = json.loads(auth_json)
        tokens = data.get("tokens", data)  # accept the raw auth.json or its tokens dict
        if not isinstance(tokens, dict) or not tokens.get("access_token"):
            raise ValueError("no access_token in that auth.json")
        home = config.codex_cli_home()
        os.makedirs(home, exist_ok=True)
        path = os.path.join(home, "auth.json")
        payload = data if "tokens" in data else {"tokens": tokens}
        with open(path, "w", encoding="utf-8") as f:
            json.dump(payload, f)
        os.chmod(path, 0o600)
    except (OSError, json.JSONDecodeError, ValueError) as e:
        return f"Couldn't read that auth.json: {e}"
    return "Org Codex connected ✓"
