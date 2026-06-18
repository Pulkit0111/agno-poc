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


def test_empty_home_has_add_buttons():
    view = blocks.build_home_view([])
    assert view["type"] == "home"
    ids = _action_ids(view)
    assert "add_delivery" in ids
    assert "add_dsm" in ids
    assert "add_security" in ids
    # No schedules → an explanatory line, no run/remove buttons.
    assert not any(i.startswith("run_now") or i.startswith("remove") for i in ids)


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
    block_ids = [b.get("block_id") for b in view["blocks"]]
    assert block_ids == ["team", "channel", "precall", "postcall", "days"]
    # Team is optional; the rest required.
    team_block = next(b for b in view["blocks"] if b["block_id"] == "team")
    assert team_block["optional"] is True


def test_security_modal_structure():
    view = blocks.build_security_modal(default_channel="C123")
    assert view["callback_id"] == "create_security"
    input_block_ids = [b.get("block_id") for b in view["blocks"] if b["type"] == "input"]
    assert input_block_ids == ["channel", "frequency", "time"]
    chan = next(b for b in view["blocks"] if b.get("block_id") == "channel")
    assert chan["element"]["initial_channel"] == "C123"
