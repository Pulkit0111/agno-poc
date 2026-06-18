"""Block Kit builders for the Home tab and the Add-schedule modals.

Pure functions returning Slack view dicts — no network, so they're unit-testable. The
router publishes/opens these and reads back the submitted values.
"""

from __future__ import annotations

from typing import Any

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


def build_home_view(rows: list[dict]) -> dict:
    """The App Home tab: one section per schedule with Run/Remove, then Add buttons.

    Each row dict carries: icon, label, channel, when, run_buttons (list of
    {text, action_id, value}) and remove_ids (list of schedule ids).
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
                _btn("+ Add DSM schedule", "add_dsm", "go"),
            ],
        }
    )
    return {"type": "home", "blocks": blocks}


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


def build_delivery_modal(engagements: list[dict], default_channel: str | None = None) -> dict:
    """Add-delivery form. `engagements` is the curated shortlist [{id, account, band}]."""
    eng_options = [
        (f"{band_icon(e.get('band'))} {e['account']} ({e.get('band', 'unknown')})",
         f"{e['id']}|{e['account'][:28]}|{e.get('band', '')}")
        for e in engagements
    ] or [("(no engagements found)", "none|none|")]

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
    """Add-DSM form: one channel, a pre-call and post-call time, and the days."""
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
            _input("precall", "Pre-call time",
                   {"type": "timepicker", "action_id": "v", "initial_time": "09:55"}),
            _input("postcall", "Post-call time",
                   {"type": "timepicker", "action_id": "v", "initial_time": "10:30"}),
            _input("days", "Days", _static_select("v", [("Weekdays", "weekdays"), ("Daily", "daily")],
                                                  initial="weekdays")),
        ],
    }
