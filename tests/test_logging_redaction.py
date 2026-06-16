from bott.shared.observability.logging_setup import redact


def test_redacts_clone_url_token():
    s = "fetch failed: https://x-access-token:ghs_ABC123def456ghi789jklmno@github.com/o/r.git"
    r = redact(s)
    assert "ghs_ABC123" not in r
    assert "x-access-token:***@" in r


def test_redacts_slack_token():
    assert "xoxb-" not in redact("bot token xoxb-111-222-abcDEFghijklmno")


def test_redacts_openai_key():
    assert "sk-proj-" not in redact("key=sk-proj-abcdefghijklmnopqrstuvwxyz0123")


def test_passthrough_non_secret():
    assert redact("nothing secret here, just text") == "nothing secret here, just text"
