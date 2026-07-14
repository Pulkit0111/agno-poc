# src/bott/interfaces/slack_home/models.py
"""App Home 'Models' panel — ADMIN ONLY.

Provider-aware: shows the active provider + chat/heavy models, and whether the selected
provider is usable right now. Codex lists its known models; Bedrock/OpenRouter list their
live catalog once credentials are present, and prompt to add keys when they aren't — so an
admin can point any task (chat vs heavy) at any available model. Members never see this
panel (``models_section`` returns [] for them)."""

from __future__ import annotations

import json
import os

import httpx

from bott.shared import codex_tokens, config
from bott.shared.config import model_provider
from bott.shared.persistence.records import get_setting, set_setting

# Sensible fallbacks so the model picker is never empty even if a live catalog fetch fails
# (network hiccup, throttling). The live fetch is preferred; these are the safety net.
_OPENROUTER_FALLBACK = [
    "anthropic/claude-opus-4.8",
    "anthropic/claude-sonnet-4.6",
    "openai/gpt-5.5",
    "google/gemini-3-pro",
    "meta-llama/llama-4-70b-instruct",
]
_BEDROCK_FALLBACK = [
    "anthropic.claude-opus-4-1-v1:0",
    "anthropic.claude-sonnet-4-6-v1:0",
    "meta.llama4-70b-instruct-v1:0",
]


def _active() -> dict:
    """The task→model matrix as resolved right now. `heavy` remains as the legacy store
    fallback build/review inherit when they have no explicit setting. `providers_by_role`
    surfaces the per-role provider (chat/build/review may each sit on a different provider
    via `model.provider.<role>`) alongside the legacy global `provider` field, kept for
    back-compat with callers that only care about the single active provider."""
    from bott.shared.model import resolve_model_id, resolve_provider
    return {
        "provider": get_setting("model.provider") or model_provider(),
        "chat": resolve_model_id("chat"),
        "build": resolve_model_id("build"),
        "review": resolve_model_id("review"),
        "providers_by_role": {
            "chat": resolve_provider("chat"),
            "build": resolve_provider("build"),
            "review": resolve_provider("review"),
        },
    }


def _aws_configured() -> bool:
    return bool(os.getenv("AWS_ACCESS_KEY_ID") or os.getenv("AWS_PROFILE"))


def provider_key_status(provider: str) -> tuple[bool, str]:
    """(usable_now, human hint). 'Usable' means the provider has the credentials it needs to
    actually run and to list its models."""
    if provider == "codex":
        ok = codex_tokens.is_connected()
        return ok, ("Org Codex connected" if ok else "Org Codex not connected — connect it below")
    if provider == "openrouter":
        ok = bool(config.openrouter_api_key())
        return ok, ("OpenRouter key present" if ok else "Add `OPENROUTER_API_KEY` to list and use models")
    if provider == "bedrock":
        ok = _aws_configured()
        return ok, ("AWS credentials present" if ok else "Add AWS credentials to list and use Bedrock models")
    return False, f"Unknown provider `{provider}`"


def _is_text_to_text(model: dict) -> bool:
    """Mirrors personal_finance_organizer/lib/openrouter.ts's filter: read declared input/output
    modalities (defaulting to text when absent) and keep only models that both accept and
    produce text — so the picker excludes image/audio-only models."""
    arch = model.get("architecture") or {}
    modality = arch.get("modality")
    inputs = arch.get("input_modalities") or (modality.split("->")[:1] if modality else ["text"])
    outputs = arch.get("output_modalities") or ["text"]
    return "text" in inputs and "text" in outputs


def _fetch_openrouter_models() -> list[str]:
    """OpenRouter's live model catalog (ids), filtered to text→text models. Best-effort — falls
    back to a curated list."""
    try:
        r = httpx.get("https://openrouter.ai/api/v1/models", timeout=10)
        r.raise_for_status()
        data = r.json().get("data") or []
        ids = [m.get("id") for m in data if m.get("id") and _is_text_to_text(m)]
        return sorted(ids) or list(_OPENROUTER_FALLBACK)
    except Exception:  # noqa: BLE001 — never let a catalog fetch break the panel
        return list(_OPENROUTER_FALLBACK)


def _fetch_bedrock_models() -> list[str]:
    """Bedrock foundation-model ids for the region. Best-effort — falls back to a curated list."""
    try:
        import boto3
        client = boto3.client("bedrock", region_name=os.getenv("AWS_REGION", "us-east-1"))
        summaries = client.list_foundation_models().get("modelSummaries", [])
        ids = [m.get("modelId") for m in summaries if m.get("modelId")]
        return sorted(ids) or list(_BEDROCK_FALLBACK)
    except Exception:  # noqa: BLE001
        return list(_BEDROCK_FALLBACK)


def available_models(provider: str) -> list[str]:
    """Models the admin can choose for a task under this provider. Empty when the provider's
    keys aren't present yet (the panel then shows the 'add keys' hint)."""
    if provider == "codex":
        return list(config.FALLBACK_CODEX_MODELS)
    ok, _ = provider_key_status(provider)
    if not ok:
        return []
    if provider == "openrouter":
        return _fetch_openrouter_models()
    if provider == "bedrock":
        return _fetch_bedrock_models()
    return []


_VALID_PROVIDERS = ("codex", "openrouter", "bedrock")


def catalogs() -> dict:
    """Per-provider model-id catalogs for the console's model picker, one call per
    provider (codex is always the static fallback list; openrouter/bedrock hit their
    live catalog — `available_models` already handles the fetch + fallback + missing-key
    empty-list behavior)."""
    return {
        "codex": list(config.FALLBACK_CODEX_MODELS),
        "openrouter": available_models("openrouter"),
        "bedrock": available_models("bedrock"),
    }


def models_section(is_admin: bool) -> list[dict]:
    """Admin-only panel body (the '🤖 Models' header is added by build_home_view). Returns []
    for non-admins so members never see model controls."""
    if not is_admin:
        return []
    a = _active()
    provider = a["provider"]
    ok, hint = provider_key_status(provider)
    icon = "✅" if ok else "⚠️"
    # The reviewer must differ from the builder — same model = same blind spots. The gateway
    # auto-swaps at run time, but surface the conflict so the admin can set it deliberately.
    affinity = ("✅ review differs from build" if a["review"] != a["build"]
                else "⚠️ review = build — I'll auto-swap the reviewer at run time; set a "
                     "distinct review model to choose which")
    text = (f"*Task → model matrix* · provider `{provider}`\n"
            f"chat `{a['chat']}`  ·  build `{a['build']}`  ·  review `{a['review']}`\n"
            f"{affinity}\n{icon} {hint}")
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
    "model.provider", "model.chat", "model.build", "model.review", "model.heavy",
    # Per-role provider overrides let an admin pin e.g. Chat to OpenRouter while
    # Build/Review stay on Codex — see bott.shared.model.resolve_provider.
    "model.provider.chat", "model.provider.build", "model.provider.review",
)


def apply_model_override(actor_email: str, key: str, value: str) -> str:
    # model.heavy kept for back-compat (legacy tier build/review fall back to).
    if key not in _OVERRIDE_KEYS:
        return f"Unknown setting `{key}`."
    if not _is_admin(actor_email):
        return "Sorry, that's not allowed — only an admin can change the model."
    if key.startswith("model.provider") and value not in _VALID_PROVIDERS:
        return f"Invalid provider `{value}` — must be one of {', '.join(_VALID_PROVIDERS)}."
    set_setting(key, value)
    a = _active()
    note = ("" if a["review"] != a["build"]
            else "\n⚠️ review = build — the reviewer would share the author's blind spots; "
                 "I'll auto-swap at run time, but consider a distinct review model.")
    return (f"Updated. Now provider=`{a['provider']}` · chat=`{a['chat']}` · "
            f"build=`{a['build']}` · review=`{a['review']}`.{note}")


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
