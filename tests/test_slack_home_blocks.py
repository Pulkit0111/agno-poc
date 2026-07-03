"""Block Kit builders for the Home tab + Add-schedule modals."""

from __future__ import annotations

from bott.interfaces.slack_home import blocks


def _action_ids(view: dict) -> list[str]:
    ids = []
    for b in view["blocks"]:
        for el in b.get("elements", []):
            if "action_id" in el:
                ids.append(el["action_id"])
    return ids


def test_empty_home_has_single_add_button_not_six():
    view = blocks.build_home_view([])
    assert view["type"] == "home"
    ids = _action_ids(view)
    # The six per-type add buttons are gone from the Home surface — one button opens a picker.
    assert "add_schedule" in ids
    for old in ("add_delivery", "add_sprint", "add_dsm", "add_security", "add_sentiment", "add_portfolio"):
        assert old not in ids
    # No schedules → an explanatory line, no run/remove buttons.
    assert not any(i.startswith("run_now") or i.startswith("remove") for i in ids)


def test_home_has_hero_and_quick_actions():
    view = blocks.build_home_view(
        [], viewer_name="Pulkit",
        connectors_blocks=[{"type": "section", "text": {"type": "mrkdwn", "text": "CONN-MARKER"}}],
    )
    text = str(view)
    assert "Bott" in text and "Pulkit" in text          # identity hero, personalized
    assert "figure out how" in text                       # posture hook, not a menu
    assert "CONN-MARKER" in text                          # connectors slot is composed in
    ids = _action_ids(view)
    assert "qa_sprint" in ids and "qa_ask" in ids         # quick actions present


def test_home_renders_action_items_with_done_and_snooze():
    view = blocks.build_home_view([], action_items=[{"id": "7", "text": "Follow up PADI SOW"}])
    text = str(view)
    ids = _action_ids(view)
    assert "Follow up PADI SOW" in text
    assert "ai_done:7" in ids and "ai_snooze:7" in ids


def test_models_and_system_are_admin_gated_slots():
    member = blocks.build_home_view([])
    assert "🤖 Models" not in str(member)   # members never see Models/System
    admin = blocks.build_home_view(
        [], models_blocks=[{"type": "section", "text": {"type": "mrkdwn", "text": "MODELS-MARKER"}}],
        system_blocks=[{"type": "section", "text": {"type": "mrkdwn", "text": "SYSTEM-MARKER"}}],
    )
    assert "MODELS-MARKER" in str(admin) and "SYSTEM-MARKER" in str(admin)


def test_home_hero_has_ask_bott_button():
    view = blocks.build_home_view([])
    assert "ask_bott" in _action_ids(view)
    assert "figure out how" in str(view)  # posture, not a menu


def test_waiting_on_you_renders_approve_dismiss():
    view = blocks.build_home_view([], approvals_pending=[
        {"id": 7, "action": "api:atlassian", "summary": "Comment on IRM-515"}])
    text = str(view)
    assert "Waiting on you" in text and "Comment on IRM-515" in text
    els = [el for b in view["blocks"] for el in b.get("elements", [])]
    pairs = [(el.get("action_id"), el.get("value")) for el in els if "action_id" in el]
    assert ("approval_approve", "7") in pairs and ("approval_dismiss", "7") in pairs


def test_waiting_hidden_when_empty():
    assert "Waiting on you" not in str(blocks.build_home_view([], approvals_pending=[]))


def test_recent_activity_renders_and_hides():
    view = blocks.build_home_view([], recent_activity=[
        {"kind": "review", "status": "done"}, {"kind": "implement", "status": "failed"}])
    text = str(view)
    assert "Recently, for you" in text and "Reviewed a PR" in text and "✗" in text
    assert "Recently, for you" not in str(blocks.build_home_view([]))


def test_skills_strip_renders_and_hides():
    view = blocks.build_home_view([], skills_line="`sprint-report` · `pr-review`")
    assert "Skills I've practiced" in str(view)
    assert "Skills I've practiced" not in str(blocks.build_home_view([]))


def test_ask_modal_shape():
    view = blocks.build_ask_modal()
    assert view["callback_id"] == "ask_bott"
    input_ids = [b.get("block_id") for b in view["blocks"] if b["type"] == "input"]
    assert input_ids == ["q"]


def test_set_models_modal_has_three_roles():
    view = blocks.build_set_models_modal("a", "b", "c", ["a", "b", "c"])
    input_ids = [b.get("block_id") for b in view["blocks"] if b["type"] == "input"]
    assert input_ids == ["chat", "build", "review"]


def test_quick_ask_modal_carries_kind_and_input():
    import json
    view = blocks.build_quick_ask_modal("sprint")
    assert view["callback_id"] == "quick_ask"
    assert json.loads(view["private_metadata"]) == {"kind": "sprint"}
    input_ids = [b.get("block_id") for b in view["blocks"] if b["type"] == "input"]
    assert input_ids == ["engagement"]


def test_notice_modal_shows_text():
    view = blocks.build_notice_modal("Add keys", "Set OPENROUTER_API_KEY first.")
    assert view["type"] == "modal"
    assert "OPENROUTER_API_KEY" in str(view)
    assert "submit" not in view  # informational only — no submit button


def test_schedule_picker_modal_has_all_six_types():
    view = blocks.build_schedule_picker_modal()
    assert view["type"] == "modal"
    ids = _action_ids(view)
    for a in ("add_delivery", "add_sprint", "add_sentiment", "add_portfolio", "add_dsm", "add_security"):
        assert a in ids


def test_home_renders_a_delivery_row_with_run_and_remove():
    row = {
        "icon": "🔴", "label": "wrap", "channel": "C123", "when": "Weekdays 9:00 AM",
        "run_buttons": [{"text": "▶ Run now", "action_id": "run_now:abc", "value": "abc"}],
        "remove_ids": ["abc"],
    }
    view = blocks.build_home_view([row])
    text = str(view)
    assert "wrap" in text and "<#C123>" in text and "Weekdays 9:00 AM" in text
    ids = _action_ids(view)
    assert "run_now:abc" in ids
    assert "remove:abc" in ids


def test_dsm_row_has_pre_and_post_run_buttons():
    row = {
        "icon": "👥", "label": "core", "channel": "C9", "when": "Pre 9:55 AM · Post 10:30 AM",
        "run_buttons": [
            {"text": "▶ Run pre", "action_id": "run_now:p1", "value": "p1"},
            {"text": "▶ Run post", "action_id": "run_now:p2", "value": "p2"},
        ],
        "remove_ids": ["p1", "p2"],
    }
    view = blocks.build_home_view([row])
    ids = _action_ids(view)
    assert "run_now:p1" in ids and "run_now:p2" in ids
    # Remove carries both ids so the whole DSM pair is deleted together.
    remove_el = next(
        el for b in view["blocks"] for el in b.get("elements", [])
        if el.get("action_id", "").startswith("remove")
    )
    assert remove_el["value"] == "p1,p2"


def test_delivery_modal_structure_and_engagement_options():
    engagements = [
        {"id": "uuid-1", "account": "wrap", "band": "high"},
        {"id": "uuid-2", "account": "wildstyle", "band": "medium"},
    ]
    view = blocks.build_delivery_modal(engagements, default_channel="C123")
    assert view["type"] == "modal"
    assert view["callback_id"] == "create_delivery"
    block_ids = [b.get("block_id") for b in view["blocks"]]
    assert block_ids == ["engagement", "channel", "frequency", "time"]
    # Engagement options encode id|account|band so the submit handler can recover them.
    eng_block = view["blocks"][0]
    opt_values = [o["value"] for o in eng_block["element"]["options"]]
    assert any(v.startswith("uuid-1|wrap|high") for v in opt_values)
    # Channel pre-filled with the default.
    assert view["blocks"][1]["element"]["initial_channel"] == "C123"


def test_delivery_modal_loading_placeholder_opens_without_engagements():
    # Opened instantly (no Memra) so the 3s trigger window isn't blown; the option is a
    # non-submittable placeholder (value resolves to engagement id "none").
    view = blocks.build_delivery_modal([], loading=True)
    opts = view["blocks"][0]["element"]["options"]
    assert len(opts) == 1
    assert opts[0]["value"].split("|")[0] == "none"
    assert "Loading" in opts[0]["text"]["text"]


def test_dsm_modal_structure():
    view = blocks.build_dsm_modal()
    assert view["callback_id"] == "create_dsm"
    input_ids = [b.get("block_id") for b in view["blocks"] if b["type"] == "input"]
    assert input_ids == ["team", "channel", "call_time", "open_offset", "close_offset",
                         "postcall_time", "days"]
    team_block = next(b for b in view["blocks"] if b.get("block_id") == "team")
    assert team_block["optional"] is True


def test_standup_modal_carries_team_and_date():
    import json
    view = blocks.build_standup_modal("core", "2026-06-18")
    assert view["callback_id"] == "submit_standup"
    assert json.loads(view["private_metadata"]) == {"team": "core", "date": "2026-06-18"}
    ids = [b["block_id"] for b in view["blocks"] if b["type"] == "input"]
    assert ids == ["yesterday", "today", "blockers"]


def test_security_modal_structure():
    view = blocks.build_security_modal(default_channel="C123")
    assert view["callback_id"] == "create_security"
    input_block_ids = [b.get("block_id") for b in view["blocks"] if b["type"] == "input"]
    assert input_block_ids == ["channel", "frequency", "time"]
    chan = next(b for b in view["blocks"] if b.get("block_id") == "channel")
    assert chan["element"]["initial_channel"] == "C123"
