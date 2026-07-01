# src/bott/interfaces/slack_home/models.py
"""App Home 'Models' section: show the active model to everyone; let an admin override it
and connect the org Codex account. Admin-gated; the active model is always shown."""

from __future__ import annotations

import json

from bott.shared import codex_tokens
from bott.shared.config import bott_admins, model_provider, role_model_id
from bott.shared.persistence.records import get_setting, set_setting


def _active() -> dict:
    return {
        "provider": get_setting("model.provider") or model_provider(),
        "chat": get_setting("model.chat") or role_model_id("chat"),
        "heavy": get_setting("model.heavy") or role_model_id("heavy"),
    }


def models_section(is_admin: bool) -> list[dict]:
    a = _active()
    codex = "connected" if codex_tokens.is_connected() else "not connected"
    text = (f"*Models*\nprovider: `{a['provider']}`  ·  chat: `{a['chat']}`  ·  "
            f"heavy: `{a['heavy']}`\nOrg Codex: *{codex}*")
    blocks = [{"type": "section", "text": {"type": "mrkdwn", "text": text}}]
    if is_admin:
        blocks.append({"type": "actions", "elements": [
            {"type": "button", "text": {"type": "plain_text", "text": "Connect Codex (org)"},
             "action_id": "models_connect_codex"},
            {"type": "button", "text": {"type": "plain_text", "text": "Change provider"},
             "action_id": "models_set_provider"},
            {"type": "button", "text": {"type": "plain_text", "text": "Change models"},
             "action_id": "models_set_models"},
        ]})
    return blocks


def _is_admin(email: str) -> bool:
    return (email or "").lower() in bott_admins()


def apply_model_override(actor_email: str, key: str, value: str) -> str:
    if key not in ("model.provider", "model.chat", "model.heavy"):
        return f"Unknown setting `{key}`."
    if not _is_admin(actor_email):
        return "Sorry, that's not allowed — only an admin can change the model."
    set_setting(key, value)
    a = _active()
    return f"Updated. Now provider=`{a['provider']}` · chat=`{a['chat']}` · heavy=`{a['heavy']}`."


def connect_codex(actor_email: str, auth_json: str) -> str:
    if not _is_admin(actor_email):
        return "Sorry, that's not allowed — only an admin can connect the org Codex account."
    try:
        data = json.loads(auth_json)
        bundle = data.get("tokens", data)  # accept the raw auth.json or its tokens dict
        codex_tokens.store_bundle(bundle)
    except (json.JSONDecodeError, ValueError) as e:
        return f"Couldn't read that auth.json: {e}"
    return "Org Codex connected ✓"
