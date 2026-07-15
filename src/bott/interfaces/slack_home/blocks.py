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


def _header(text: str) -> dict:
    return {"type": "header", "text": {"type": "plain_text", "text": text, "emoji": True}}


def _ctx(text: str) -> dict:
    return {"type": "context", "elements": [{"type": "mrkdwn", "text": text}]}


def _hero_blocks(viewer_name: str | None) -> list[dict]:
    greeting = f"Hi {viewer_name} — I'm Bott 👋" if viewer_name else "Hi — I'm Bott 👋"
    return [
        _header(greeting),
        {"type": "section", "text": {"type": "mrkdwn",
         "text": "*Ask me for just about anything — I'll figure out how.* Code, delivery, "
                 "context, reporting, or something nobody's built a feature for yet."}},
        {"type": "actions", "elements": [_btn("✨ Ask Bott…", "ask_bott", "go", style="primary")]},
        _ctx("e.g. sprint report · review a PR · “ping me in 20 min” · “who's on Ironman?” — "
             "examples, not the boundary. Everything below is scoped to you."),
    ]


def _waiting_blocks(approvals: list[dict]) -> list[dict]:
    """Pending approvals the viewer requested — Approve/Dismiss right from Home (the
    in-thread cards scroll away; this is the inbox). Hidden entirely when empty."""
    if not approvals:
        return []
    out: list[dict] = [_header("⏳ Waiting on you")]
    for a in approvals:
        out.append({"type": "section", "text": {"type": "mrkdwn",
                    "text": f"• `{a['action']}` — {(a['summary'] or '')[:120]}"}})
        out.append({"type": "actions", "elements": [
            {"type": "button", "style": "primary", "action_id": "approval_approve",
             "text": {"type": "plain_text", "text": "Approve"}, "value": str(a["id"])},
            {"type": "button", "style": "danger", "action_id": "approval_dismiss",
             "text": {"type": "plain_text", "text": "Dismiss"}, "value": str(a["id"])},
        ]})
    out.append({"type": "divider"})
    return out


_JOB_ICON = {"done": "✓", "failed": "✗", "running": "⚙", "pending": "⏳"}
_JOB_LABEL = {"plan": "Planned a change", "implement": "Implemented + PR",
              "review": "Reviewed a PR", "rereview": "Re-reviewed a PR",
              "triage": "Triaged an incident"}


def _recent_blocks(jobs: list[dict]) -> list[dict]:
    """The viewer's own recent jobs — 'what has Bott done for me lately'. Hidden when empty."""
    if not jobs:
        return []
    lines = [f"{_JOB_ICON.get(j['status'], '·')} {_JOB_LABEL.get(j['kind'], j['kind'])}"
             f" — {j['status']}" for j in jobs]
    return [_header("🕘 Recently, for you"),
            {"type": "section", "text": {"type": "mrkdwn", "text": "\n".join(lines)}},
            {"type": "divider"}]


def _skills_blocks(skills_line: str) -> list[dict]:
    """Compact strip of practiced skills — the growth loop made visible. Hidden when empty."""
    if not skills_line:
        return []
    return [_header("🧠 Skills I've practiced"),
            {"type": "section", "text": {"type": "mrkdwn", "text": skills_line}},
            _ctx('Teach me a new one anytime: `learn a new skill: …`')]


def build_ask_modal() -> dict:
    """The ✨ Ask Bott modal — free-text, routed to the real agent, result DM'd back."""
    return {
        "type": "modal",
        "callback_id": "ask_bott",
        "title": {"type": "plain_text", "text": "Ask Bott"},
        "submit": {"type": "plain_text", "text": "Ask"},
        "close": {"type": "plain_text", "text": "Cancel"},
        "blocks": [
            _input("q", "What do you need?",
                   {"type": "plain_text_input", "action_id": "v", "multiline": True,
                    "placeholder": {"type": "plain_text",
                                    "text": "Anything — a report, a question, a task…"}}),
            {"type": "context", "elements": [{"type": "mrkdwn",
             "text": "I'll work on it and DM you the result."}]},
        ],
    }


_QUICK_ACTIONS = [
    ("📊 Sprint report", "qa_sprint"),
    ("📈 PR review trends", "qa_pr_trends"),
    ("🔒 Security advisories", "qa_security"),
    ("🗂️ Portfolio risk", "qa_portfolio"),
    ("💬 Ask about an engagement…", "qa_ask"),
]


def _quick_actions_blocks() -> list[dict]:
    return [
        _header("⚡ Quick actions"),
        _ctx("Tap one — I'll run it and DM you the result."),
        {"type": "actions", "elements": [_btn(t, a, "go") for t, a in _QUICK_ACTIONS]},
    ]


def _action_items_blocks(items: list[dict]) -> list[dict]:
    out: list[dict] = [_header("📌 Your action items")]
    if not items:
        out.append({"type": "section", "text": {"type": "mrkdwn",
                    "text": "_None yet — add one by messaging me:_ `add an action item: …`"}})
        return out
    for it in items:
        out.append({"type": "section", "text": {"type": "mrkdwn", "text": f"• {it['text']}"}})
        out.append({"type": "actions", "elements": [
            _btn("✓ Done", f"ai_done:{it['id']}", str(it["id"])),
            _btn("💤 Snooze", f"ai_snooze:{it['id']}", str(it["id"])),
        ]})
    return out


def _schedules_blocks(rows: list[dict]) -> list[dict]:
    out: list[dict] = [_header("📅 Your schedules")]
    if not rows:
        out.append({"type": "section", "text": {"type": "mrkdwn",
                    "text": "_No schedules yet — add one below._"}})
    for r in rows:
        suffix = "  _(Personal)_" if r.get("personal") else ""
        out.append({"type": "section", "text": {"type": "mrkdwn",
                    "text": f"{r['icon']} *{r['label']}*{suffix} → {_channel_display(r.get('channel'))}\n_{r['when']}_"}})
        elements = [_btn(b["text"], b["action_id"], b["value"]) for b in r["run_buttons"]]
        elements.append(
            _btn("✖ Remove", f"remove:{r['remove_ids'][0]}", ",".join(r["remove_ids"]), style="danger")
        )
        out.append({"type": "actions", "elements": elements})
        out.append({"type": "divider"})
    out.append({"type": "actions", "elements": [
        _btn("➕ Add a scheduled digest", "add_schedule", "go", style="primary")]})
    return out


def build_home_view(rows: list[dict], *, viewer_name: str | None = None,
                    connectors_blocks: list[dict] | None = None,
                    action_items: list[dict] | None = None,
                    approvals_pending: list[dict] | None = None,
                    recent_activity: list[dict] | None = None,
                    skills_line: str = "",
                    models_blocks: list[dict] | None = None,
                    system_blocks: list[dict] | None = None) -> dict:
    """The App Home tab, ordered actionable → personal → informational → admin:
    hero (+ ✨ Ask Bott) → ⏳ waiting-on-you approvals → 🕘 recent activity → your action
    items → your schedules → skills strip → ⚡ shortcuts → connectors, then the admin-only
    Models and System panels.

    Each schedule row dict carries: icon, label, channel, when, run_buttons (list of
    {text, action_id, value}) and remove_ids (list of schedule ids); an optional
    ``personal`` bool flags the viewer's own concierge schedules, rendered with a
    "(Personal)" suffix. ``action_items`` is the
    caller's own concierge items ([{id, text}]); ``approvals_pending`` their pending
    approvals ([{id, action, summary}]); ``recent_activity`` their recent jobs
    ([{kind, status}]). ``connectors_blocks``/``models_blocks``/``system_blocks`` are
    prebuilt sections; Models + System are admin-gated (the caller passes them only for
    admins, so members never see them).
    """
    blocks: list[dict] = []
    blocks += _hero_blocks(viewer_name)
    blocks.append({"type": "divider"})
    blocks += _waiting_blocks(approvals_pending or [])       # hidden when empty
    blocks += _recent_blocks(recent_activity or [])          # hidden when empty
    blocks += _action_items_blocks(action_items or [])
    blocks.append({"type": "divider"})
    blocks += _schedules_blocks(rows)
    blocks.append({"type": "divider"})
    blocks += _skills_blocks(skills_line)                    # hidden when empty
    blocks += _quick_actions_blocks()
    if connectors_blocks:
        blocks.append({"type": "divider"})
        blocks += connectors_blocks
    if models_blocks:
        blocks.append({"type": "divider"})
        blocks.append(_header("🤖 Models"))
        blocks.extend(models_blocks)
    if system_blocks:
        blocks.append({"type": "divider"})
        blocks.extend(system_blocks)
    return {"type": "home", "blocks": blocks}


_PICKER_TYPES = [
    ("📄 Delivery digest", "add_delivery"),
    ("📊 Sprint report", "add_sprint"),
    ("📈 Sentiment report", "add_sentiment"),
    ("🗂️ Portfolio dashboard", "add_portfolio"),
    ("👥 DSM schedule", "add_dsm"),
    ("🔒 Security feed", "add_security"),
]


def build_schedule_picker_modal() -> dict:
    """The single '+ Add a scheduled digest' button opens this — a picker whose buttons carry
    the existing per-type action_ids, so clicking one opens that type's form via the handlers
    that already exist (no duplicated modal logic)."""
    return {
        "type": "modal",
        "callback_id": "schedule_picker",
        "title": {"type": "plain_text", "text": "Add a digest"},
        "close": {"type": "plain_text", "text": "Cancel"},
        "blocks": [
            {"type": "section", "text": {"type": "mrkdwn", "text": "*What would you like to schedule?*"}},
            {"type": "actions", "elements": [_btn(t, a, "go") for t, a in _PICKER_TYPES[:5]]},
            {"type": "actions", "elements": [_btn(t, a, "go") for t, a in _PICKER_TYPES[5:]]},
        ],
    }


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


# CODEX-ONLY (product decision): Bedrock/OpenRouter are deliberately absent from the App
# Home provider picker. The backend gateway still understands them; the UI offers Codex only.
_PROVIDER_OPTIONS = [
    ("Codex (ChatGPT)", "codex"),
]


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


def build_set_models_modal(chat_current: str, build_current: str, review_current: str,
                           chat_options: list[str], build_options: list[str],
                           review_options: list[str]) -> dict:
    """The task→model matrix modal: chat / build / review. Each role's picker is fed from
    THAT role's own provider catalog (chat/build/review may each sit on a different
    provider via a per-role override) — never a shared/global catalog. Offering e.g. a
    Codex model id for a role pinned to OpenRouter would let an admin assign a
    cross-provider id that looks valid but breaks every call for that role. Review should
    also DIFFER from build (the reviewer must not be the model that wrote the code — the
    gateway auto-swaps if they match, but picking distinct models here makes the choice
    deliberate)."""
    chat_opts = [(m, m) for m in chat_options]
    build_opts = [(m, m) for m in build_options]
    review_opts = [(m, m) for m in review_options]
    return {
        "type": "modal",
        "callback_id": "models_set_models",
        "title": {"type": "plain_text", "text": "Change models"},
        "submit": {"type": "plain_text", "text": "Save"},
        "close": {"type": "plain_text", "text": "Cancel"},
        "blocks": [
            _input("chat", "Chat model (conversation)",
                   _static_select("v", chat_opts,
                                  initial=chat_current if chat_current in chat_options else None)),
            _input("build", "Build model (plan / implement / triage)",
                   _static_select("v", build_opts,
                                  initial=build_current if build_current in build_options else None)),
            _input("review", "Review model (PR review — pick a DIFFERENT model than build)",
                   _static_select("v", review_opts,
                                  initial=review_current if review_current in review_options else None)),
            {"type": "context", "elements": [{"type": "mrkdwn",
             "text": "Each picker only lists models for that role's current provider. "
                     "If review = build, the reviewer shares the author's blind spots — "
                     "Bott will auto-swap the reviewer at run time."}]},
        ],
    }


_QUICK_ASK_TITLES = {"ask": "Ask about an engagement", "sprint": "Sprint snapshot"}


def build_quick_ask_modal(kind: str) -> dict:
    """A one-field modal for the engagement-scoped quick actions (Ask / Sprint). The submit
    handler reads ``kind`` from private_metadata and DMs the caller the result."""
    return {
        "type": "modal",
        "callback_id": "quick_ask",
        "private_metadata": json.dumps({"kind": kind}),
        "title": {"type": "plain_text", "text": _QUICK_ASK_TITLES.get(kind, "Ask Bott")[:24]},
        "submit": {"type": "plain_text", "text": "Run"},
        "close": {"type": "plain_text", "text": "Cancel"},
        "blocks": [
            _input("engagement", "Engagement (name or Jira key)",
                   {"type": "plain_text_input", "action_id": "v",
                    "placeholder": {"type": "plain_text", "text": "e.g. PADI"}}),
        ],
    }


def build_notice_modal(title: str, text: str) -> dict:
    """An informational modal (no submit) — used to explain why an action can't proceed yet."""
    return {
        "type": "modal",
        "callback_id": "notice",
        "title": {"type": "plain_text", "text": title[:24]},
        "close": {"type": "plain_text", "text": "OK"},
        "blocks": [{"type": "section", "text": {"type": "mrkdwn", "text": text}}],
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
