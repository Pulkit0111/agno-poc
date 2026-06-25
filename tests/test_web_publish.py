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
    # fragment is wrapped — published HTML is a full document, not the bare fragment
    assert "<!doctype" in calls["html"].lower() or "<html" in calls["html"].lower()
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
    # fragment from file gets wrapped in branded shell
    assert "<!doctype" in captured["html"].lower() or "<html" in captured["html"].lower()
    assert "<p>file</p>" in captured["html"]


# ---------------------------------------------------------------------------
# Task 6: brand-wrap tests
# ---------------------------------------------------------------------------


def _make_fake_pub_capturing(calls: dict):
    class FakeResult:
        mode = "spin"
        url = "https://x.public.spin.axelerant.tech/"
        detail = "Published: https://x.public.spin.axelerant.tech/"

    class FakePub:
        def publish(self, slug, title, html, channel=""):
            calls["html"] = html
            return FakeResult()

    return FakePub()


def test_fragment_is_wrapped_with_brand(monkeypatch):
    """A bare HTML fragment must be wrapped in a branded full-document shell."""
    calls: dict = {}
    monkeypatch.setattr(web_publish, "get_publisher", lambda: _make_fake_pub_capturing(calls))
    monkeypatch.setattr(web_publish, "_post_link", lambda **k: None)

    web_publish.publish_web_page(name="My Page", html="<h1>Hi</h1>")

    published = calls["html"]
    assert "<!doctype" in published.lower() or "<html" in published.lower(), (
        "published HTML must be a full document"
    )
    assert "Axelerant" in published, "brand name must appear in wrapped output"
    assert "#FF5C00" in published, "brand orange must appear in wrapped output"


def test_full_document_published_as_is(monkeypatch):
    """A full HTML document (starts with <!doctype html>) must be published unchanged."""
    calls: dict = {}
    monkeypatch.setattr(web_publish, "get_publisher", lambda: _make_fake_pub_capturing(calls))
    monkeypatch.setattr(web_publish, "_post_link", lambda **k: None)

    full_doc = "<!doctype html><html><head></head><body><p>already full</p></body></html>"
    web_publish.publish_web_page(name="Full Doc", html=full_doc)

    assert calls["html"] == full_doc, "full document must not be modified"


def test_brand_wrap_helper_directly():
    """_brand_wrap must return a full document containing brand markers."""
    result = web_publish._brand_wrap("Test Title", "<p>body content</p>")
    assert "<!doctype" in result.lower() or "<html" in result.lower()
    assert "Axelerant" in result
    assert "#FF5C00" in result
    assert "<p>body content</p>" in result
