"""Block Kit builders for the Home tab and the Add-schedule modals.

Pure functions returning Slack view dicts — no network, so they're unit-testable. The
router publishes/opens these and reads back the submitted values.
"""

from __future__ import annotations

import json
from typing import Any

# Configurable timing offsets for the DSM "Add" form (label, minutes-before-call).
_OPEN_OFFSETS = [("3 hours before", "180"), ("2 hours before", "120"), ("1 hour before", "60")]
_CLOSE_OFFSETS = [("1 hour before", "60"), ("30 minutes before", "30"), ("15 minutes before", "15")]

_BAND_ICON = {"high": "🔴", "medium": "🟡", "low": "🟢"}

_FREQ_OPTIONS = [
    ("Daily", "daily"),
    ("Weekdays", "weekdays"),
    ("Weekly (Mondays)", "weekly"),
    ("Every minute — for testing", "minutely"),
]


def band_icon(band: str | None) -> str:
    return _BAND_ICON.get((band or "").lower(), "📄")


def _btn(text: str, action_id: str, value: str, *, style: str | None = None) -> dict:
    el: dict[str, Any] = {
        "type": "button",
        "text": {"type": "plain_text", "text": text, "emoji": True},
        "action_id": action_id,
        "value": value,
    }
    if style:
        el["style"] = style
    return el


def _channel_display(channel: str | None) -> str:
    if channel and channel.startswith("C"):
        return f"<#{channel}>"
    return channel or "—"


def build_home_view(rows: list[dict], *, models_blocks: list[dict] | None = None) -> dict:
    """The App Home tab: one section per schedule with Run/Remove, then Add buttons.

    Each row dict carries: icon, label, channel, when, run_buttons (list of
    {text, action_id, value}) and remove_ids (list of schedule ids).

    ``models_blocks`` (from ``models.models_section``) is appended after the schedules
    panel when provided.
    """
    blocks: list[dict] = [
        {"type": "header", "text": {"type": "plain_text", "text": "📅 Scheduled digests", "emoji": True}},
    ]
    if not rows:
        blocks.append(
            {"type": "section", "text": {"type": "mrkdwn", "text": "_No schedules yet — add one below._"}}
        )
    for r in rows:
        blocks.append(
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": f"{r['icon']} *{r['label']}* → {_channel_display(r.get('channel'))}\n_{r['when']}_",
                },
            }
        )
        elements = [_btn(b["text"], b["action_id"], b["value"]) for b in r["run_buttons"]]
        elements.append(
            _btn("✖ Remove", f"remove:{r['remove_ids'][0]}", ",".join(r["remove_ids"]), style="danger")
        )
        blocks.append({"type": "actions", "elements": elements})
        blocks.append({"type": "divider"})

    blocks.append(
        {
            "type": "actions",
            "elements": [
                _btn("+ Add delivery digest", "add_delivery", "go", style="primary"),
                _btn("+ Add sprint report", "add_sprint", "go"),
                _btn("+ Add sentiment report", "add_sentiment", "go"),
                _btn("+ Add portfolio dashboard", "add_portfolio", "go"),
                _btn("+ Add DSM schedule", "add_dsm", "go"),
                _btn("+ Add security feed", "add_security", "go"),
            ],
        }
    )
    if models_blocks:
        blocks.append({"type": "divider"})
        blocks.append(
            {"type": "header", "text": {"type": "plain_text", "text": "🤖 Models", "emoji": True}}
        )
        blocks.extend(models_blocks)
    return {"type": "home", "blocks": blocks}


def build_connect_codex_modal() -> dict:
    """Modal to paste the org Codex auth.json and submit it."""
    return {
        "type": "modal",
        "callback_id": "models_connect_codex",
        "title": {"type": "plain_text", "text": "Connect org Codex"},
        "submit": {"type": "plain_text", "text": "Connect"},
        "close": {"type": "plain_text", "text": "Cancel"},
        "blocks": [
            {"type": "section", "text": {"type": "mrkdwn",
             "text": "Paste the full contents of your `~/.codex/auth.json` below."}},
            _input("auth_json", "auth.json contents",
                   {"type": "plain_text_input", "action_id": "v", "multiline": True,
                    "placeholder": {"type": "plain_text", "text": '{"tokens": {"access_token": "...", ...}}'}}),
        ],
    }


_PROVIDER_OPTIONS = [
    ("Codex (ChatGPT)", "codex"),
    ("Amazon Bedrock", "bedrock"),
    ("OpenRouter", "openrouter"),
]


def build_set_provider_modal(current: str | None = None) -> dict:
    """Modal to pick the active model provider."""
    return {
        "type": "modal",
        "callback_id": "models_set_provider",
        "title": {"type": "plain_text", "text": "Change model provider"},
        "submit": {"type": "plain_text", "text": "Save"},
        "close": {"type": "plain_text", "text": "Cancel"},
        "blocks": [
            _input("provider", "Provider",
                   _static_select("v", _PROVIDER_OPTIONS, initial=current)),
        ],
    }


def _static_select(action_id: str, options: list[tuple[str, str]], initial: str | None = None) -> dict:
    opts = [{"text": {"type": "plain_text", "text": t[:75]}, "value": v[:75]} for t, v in options]
    el: dict[str, Any] = {"type": "static_select", "action_id": action_id, "options": opts}
    for o in opts:
        if initial is not None and o["value"] == initial:
            el["initial_option"] = o
    return el


def _input(block_id: str, label: str, element: dict, *, optional: bool = False) -> dict:
    return {
        "type": "input",
        "block_id": block_id,
        "optional": optional,
        "label": {"type": "plain_text", "text": label},
        "element": element,
    }


def build_delivery_modal(engagements: list[dict], default_channel: str | None = None,
                         loading: bool = False) -> dict:
    """Add-delivery form. `engagements` is the curated shortlist [{id, account, band}].

    `loading=True` (with no engagements yet) renders a placeholder so the modal can be
    opened instantly within Slack's 3s trigger window, then filled via views.update once
    the Memra shortlist is fetched."""
    if engagements:
        eng_options = [
            (f"{band_icon(e.get('band'))} {e['account']} ({e.get('band', 'unknown')})",
             f"{e['id']}|{e['account'][:28]}|{e.get('band', '')}")
            for e in engagements
        ]
    elif loading:
        eng_options = [("⏳ Loading engagements…", "none|loading|")]
    else:
        eng_options = [("(no engagements found)", "none|none|")]

    channel_el: dict[str, Any] = {"type": "channels_select", "action_id": "v",
                                  "placeholder": {"type": "plain_text", "text": "Pick a channel"}}
    if default_channel and default_channel.startswith("C"):
        channel_el["initial_channel"] = default_channel

    return {
        "type": "modal",
        "callback_id": "create_delivery",
        "title": {"type": "plain_text", "text": "Add delivery digest"},
        "submit": {"type": "plain_text", "text": "Save"},
        "close": {"type": "plain_text", "text": "Cancel"},
        "blocks": [
            _input("engagement", "Engagement", _static_select("v", eng_options)),
            _input("channel", "Post to channel", channel_el),
            _input("frequency", "How often", _static_select("v", _FREQ_OPTIONS, initial="weekdays")),
            _input("time", "Time", {"type": "timepicker", "action_id": "v", "initial_time": "09:00"}),
        ],
    }


def build_dsm_modal(default_channel: str | None = None) -> dict:
    """Add-DSM form: the standup call time + configurable open/pre-read offsets + a post-call
    summary time. Open and pre-read crons are derived from call time minus the offsets."""
    channel_el: dict[str, Any] = {"type": "channels_select", "action_id": "v",
                                  "placeholder": {"type": "plain_text", "text": "Standup channel"}}
    if default_channel and default_channel.startswith("C"):
        channel_el["initial_channel"] = default_channel

    return {
        "type": "modal",
        "callback_id": "create_dsm",
        "title": {"type": "plain_text", "text": "Add DSM schedule"},
        "submit": {"type": "plain_text", "text": "Save"},
        "close": {"type": "plain_text", "text": "Cancel"},
        "blocks": [
            _input("team", "Team name (optional)",
                   {"type": "plain_text_input", "action_id": "v",
                    "placeholder": {"type": "plain_text", "text": "e.g. core"}}, optional=True),
            _input("channel", "Standup channel", channel_el),
            _input("call_time", "Standup call time",
                   {"type": "timepicker", "action_id": "v", "initial_time": "10:00"}),
            _input("open_offset", "Open collection", _static_select("v", _OPEN_OFFSETS, initial="120")),
            _input("close_offset", "Post pre-read", _static_select("v", _CLOSE_OFFSETS, initial="60")),
            _input("postcall_time", "Post-call summary time",
                   {"type": "timepicker", "action_id": "v", "initial_time": "10:30"}),
            _input("days", "Days", _static_select("v", [("Weekdays", "weekdays"), ("Daily", "daily")],
                                                  initial="weekdays")),
        ],
    }


def build_standup_modal(team: str, date: str) -> dict:
    """The per-person standup update form (opened from the channel button). Carries the
    team+date in private_metadata so the submit handler knows which round to store against."""
    def _ml(block_id: str, label: str) -> dict:
        return _input(block_id, label,
                      {"type": "plain_text_input", "action_id": "v", "multiline": True},
                      optional=True)

    return {
        "type": "modal",
        "callback_id": "submit_standup",
        "private_metadata": json.dumps({"team": team, "date": date}),
        "title": {"type": "plain_text", "text": "Standup update"},
        "submit": {"type": "plain_text", "text": "Submit"},
        "close": {"type": "plain_text", "text": "Cancel"},
        "blocks": [
            _ml("yesterday", "Yesterday"),
            _ml("today", "Today"),
            _ml("blockers", "Blockers"),
        ],
    }


def build_sprint_modal(
    boards: list[tuple[str, str]],
    *,
    selected_key: str | None = None,
    sprint_end_label: str | None = None,
    channel: str | None = None,
    time_initial: str = "17:00",
    loading: bool = False,
    empty_reason: str | None = None,
) -> dict:
    """Add-sprint-report form. ``boards`` is [(label, project_key)] discovered from Jira.

    The engagement selector is a SECTION ACCESSORY (not an input block) so changing it
    dispatches a block_action — the router then fetches that board's sprint end date and
    re-renders this modal with `sprint_end_label` filled. The schedule's weekday is derived
    from that sprint end date at submit; the user only picks the time."""
    if boards:
        opts = [{"text": {"type": "plain_text", "text": t[:75]}, "value": v[:75]} for t, v in boards]
    elif loading:
        opts = [{"text": {"type": "plain_text", "text": "⏳ Loading engagements…"}, "value": "none"}]
    else:
        opts = [{"text": {"type": "plain_text", "text": "(no engagements available)"}, "value": "none"}]

    select: dict[str, Any] = {"type": "static_select", "action_id": "sprint_eng_selected",
                              "placeholder": {"type": "plain_text", "text": "Pick an engagement"},
                              "options": opts}
    for o in opts:
        if selected_key is not None and o["value"] == selected_key:
            select["initial_option"] = o

    note = (
        f"⚠️ {empty_reason}" if (empty_reason and not boards)
        else sprint_end_label or "_Pick an engagement to see its current sprint's end date._"
    )

    channel_el: dict[str, Any] = {"type": "channels_select", "action_id": "v",
                                  "placeholder": {"type": "plain_text", "text": "Post the report to"}}
    if channel and channel.startswith("C"):
        channel_el["initial_channel"] = channel

    return {
        "type": "modal",
        "callback_id": "create_sprint",
        "title": {"type": "plain_text", "text": "Add sprint report"},
        "submit": {"type": "plain_text", "text": "Save"},
        "close": {"type": "plain_text", "text": "Cancel"},
        "blocks": [
            {"type": "section", "block_id": "engagement",
             "text": {"type": "mrkdwn", "text": "*Engagement*"}, "accessory": select},
            {"type": "context", "elements": [{"type": "mrkdwn", "text": f"🏁 {note}"}]},
            _input("channel", "Post to channel", channel_el),
            _input("time", "Time (on the sprint's end weekday)",
                   {"type": "timepicker", "action_id": "v", "initial_time": time_initial}),
            {"type": "context", "elements": [{"type": "mrkdwn",
             "text": "Runs weekly on the sprint's end weekday, but only publishes when a sprint "
                     "has newly closed — so different cadences won't double-post."}]},
        ],
    }


def build_sentiment_modal(default_channel: str | None = None) -> dict:
    """Add a scheduled portfolio sentiment / delivery-health digest — just a channel, how
    often, and a time (it rolls up ALL engagements, so there's no engagement to pick)."""
    channel_el: dict[str, Any] = {"type": "channels_select", "action_id": "v",
                                  "placeholder": {"type": "plain_text", "text": "Post the digest to"}}
    if default_channel and default_channel.startswith("C"):
        channel_el["initial_channel"] = default_channel
    return {
        "type": "modal",
        "callback_id": "create_sentiment",
        "title": {"type": "plain_text", "text": "Add sentiment report"},
        "submit": {"type": "plain_text", "text": "Save"},
        "close": {"type": "plain_text", "text": "Cancel"},
        "blocks": [
            {"type": "section", "text": {"type": "mrkdwn",
             "text": "📈 Portfolio delivery-health digest — sentiment & risk across all engagements."}},
            _input("channel", "Post to channel", channel_el),
            _input("frequency", "How often", _static_select("v", _FREQ_OPTIONS, initial="weekly")),
            _input("time", "Time", {"type": "timepicker", "action_id": "v", "initial_time": "09:00"}),
        ],
    }


def build_portfolio_modal(default_channel: str | None = None) -> dict:
    """Add a scheduled leadership portfolio risk roll-up — channel, frequency, time. It rolls
    up ALL engagements (Memra risk/sentiment + Jira velocity), so there's no engagement to pick."""
    channel_el: dict[str, Any] = {"type": "channels_select", "action_id": "v",
                                  "placeholder": {"type": "plain_text", "text": "Post the dashboard link to"}}
    if default_channel and default_channel.startswith("C"):
        channel_el["initial_channel"] = default_channel
    return {
        "type": "modal",
        "callback_id": "create_portfolio",
        "title": {"type": "plain_text", "text": "Add portfolio dashboard"},
        "submit": {"type": "plain_text", "text": "Save"},
        "close": {"type": "plain_text", "text": "Cancel"},
        "blocks": [
            {"type": "section", "text": {"type": "mrkdwn",
             "text": "🗂️ Leadership portfolio risk roll-up — risk & sentiment (Memra) + delivery "
                     "velocity (Jira), published as a dashboard link."}},
            _input("channel", "Post link to channel", channel_el),
            _input("frequency", "How often", _static_select("v", _FREQ_OPTIONS, initial="weekly")),
            _input("time", "Time", {"type": "timepicker", "action_id": "v", "initial_time": "09:00"}),
        ],
    }


def build_security_modal(default_channel: str | None = None) -> dict:
    """Add a scheduled Drupal security-advisory digest: just a channel, how often, and a
    time (no engagement to pick, so it opens instantly)."""
    channel_el: dict[str, Any] = {"type": "channels_select", "action_id": "v",
                                  "placeholder": {"type": "plain_text", "text": "Post advisories to"}}
    if default_channel and default_channel.startswith("C"):
        channel_el["initial_channel"] = default_channel
    return {
        "type": "modal",
        "callback_id": "create_security",
        "title": {"type": "plain_text", "text": "Add security feed"},
        "submit": {"type": "plain_text", "text": "Save"},
        "close": {"type": "plain_text", "text": "Cancel"},
        "blocks": [
            {"type": "section", "text": {"type": "mrkdwn",
             "text": "🔒 Daily Drupal security advisories (core + contrib)."}},
            _input("channel", "Post to channel", channel_el),
            _input("frequency", "How often", _static_select("v", _FREQ_OPTIONS, initial="daily")),
            _input("time", "Time", {"type": "timepicker", "action_id": "v", "initial_time": "09:00"}),
        ],
    }
