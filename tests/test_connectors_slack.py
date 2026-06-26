from bott.skills.connectors import slack_read


def test_parse_permalink():
    ch, ts = slack_read._parse("https://axelerant.slack.com/archives/C0ATHDGRD1C/p1782369733805489")
    assert ch == "C0ATHDGRD1C" and ts == "1782369733.805489"


def test_parse_permalink_with_thread_ts():
    ch, ts = slack_read._parse(
        "https://x.slack.com/archives/C1/p1700000000000001?thread_ts=1699999999.000009")
    assert ch == "C1" and ts == "1699999999.000009"


def test_parse_bad():
    assert slack_read._parse("not a link") == (None, None)


def test_read_thread_renders(monkeypatch):
    monkeypatch.setenv("SLACK_BOT_TOKEN", "xoxb-x")

    class FakeWC:
        def __init__(self, token): pass
        def conversations_replies(self, channel, ts, limit):
            return {"messages": [
                {"user": "U1", "text": "parent"},
                {"user": "U2", "text": "reply"},
            ]}

    import slack_sdk
    monkeypatch.setattr(slack_sdk, "WebClient", FakeWC)
    out = slack_read.read_slack_thread("https://x.slack.com/archives/C1/p1782369733805489")
    assert "parent" in out and "reply" in out
