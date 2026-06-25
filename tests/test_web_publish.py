from bott.skills import web_publish


def test_publish_web_page_does_not_call_post_link(monkeypatch):
    """publish_web_page must NOT call _post_link even when channel is set.

    The sentinel list is checked after the call — if _post_link was invoked the
    test fails, regardless of whether any exception was swallowed internally.
    """

    class FakeResult:
        mode = "spin"
        url = "https://x.public.spin.axelerant.tech/"
        detail = "Published: https://x.public.spin.axelerant.tech/"

    class FakePub:
        def publish(self, slug, title, html, channel=""):
            return FakeResult()

    called = []

    def _post_link_sentinel(**k):
        called.append(k)

    monkeypatch.setattr(web_publish, "get_publisher", lambda: FakePub())
    monkeypatch.setattr(web_publish, "_post_link", _post_link_sentinel)
    out = web_publish.publish_web_page(
        name="Test Page", html="<h1>hi</h1>", channel="C1", thread_ts="1.2", broadcast=True
    )
    assert called == [], "_post_link must not be called by publish_web_page"
    assert "spin.axelerant.tech" in out


def test_publish_web_page_deploys_html(monkeypatch, tmp_path):
    calls = {}

    class FakeResult:
        mode = "spin"
        url = "https://x.public.spin.axelerant.tech/"
        detail = "Published: https://x.public.spin.axelerant.tech/"

    class FakePub:
        def publish(self, slug, title, html, channel=""):
            calls["slug"] = slug
            calls["title"] = title
            calls["html"] = html
            return FakeResult()

    monkeypatch.setattr(web_publish, "get_publisher", lambda: FakePub())
    monkeypatch.setattr(web_publish, "_post_link", lambda **k: None)
    out = web_publish.publish_web_page(
        name="My Poem", html="<h1>hi</h1>", channel="C1", thread_ts="1.2", broadcast=True
    )
    assert calls["slug"].startswith("bott-") and "my-poem" in calls["slug"]
    assert "<h1>hi</h1>" == calls["html"]
    assert "spin.axelerant.tech" in out


def test_publish_web_page_reads_workspace_file(monkeypatch, tmp_path):
    ws = tmp_path / "ws"
    ws.mkdir()
    (ws / "p.html").write_text("<p>file</p>")
    monkeypatch.setenv("BOTT_WORKSPACE_DIR", str(ws))
    captured = {}

    class FakeResult:
        mode = "spin"
        url = "u"
        detail = "Published: u"

    class FakePub:
        def publish(self, slug, title, html, channel=""):
            captured["html"] = html
            return FakeResult()

    monkeypatch.setattr(web_publish, "get_publisher", lambda: FakePub())
    monkeypatch.setattr(web_publish, "_post_link", lambda **k: None)
    web_publish.publish_web_page(name="x", workspace_file="p.html")
    assert captured["html"] == "<p>file</p>"
