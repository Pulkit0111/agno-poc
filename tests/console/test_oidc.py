import pytest

from bott.interfaces.console import oidc


@pytest.fixture(autouse=True)
def _env(monkeypatch):
    monkeypatch.setenv("SLACK_CLIENT_ID", "123.456")
    monkeypatch.setenv("SLACK_CLIENT_SECRET", "shh")
    monkeypatch.setenv("CONSOLE_BASE_URL", "https://bott.example.com")


def test_authorize_url_contains_required_params():
    url = oidc.authorize_url(state="abc123")
    assert url.startswith("https://slack.com/openid/connect/authorize?")
    assert "client_id=123.456" in url
    assert "state=abc123" in url
    assert "scope=openid+email+profile" in url or "scope=openid%20email%20profile" in url
    assert "redirect_uri=https%3A%2F%2Fbott.example.com%2Fapi%2Fconsole%2Fauth%2Fcallback" in url


class _Resp:
    def __init__(self, data):
        self._data = data
    def json(self):
        return self._data


def test_exchange_code_happy_path(monkeypatch):
    calls = {}

    def fake_post(url, data=None, timeout=None):
        calls["token_url"] = url
        return _Resp({"ok": True, "access_token": "xoxp-at"})

    def fake_get(url, headers=None, timeout=None):
        calls["auth"] = headers["Authorization"]
        return _Resp({"ok": True, "email": "pulkit.tyagi@axelerant.com", "name": "Pulkit Tyagi"})

    monkeypatch.setattr(oidc.httpx, "post", fake_post)
    monkeypatch.setattr(oidc.httpx, "get", fake_get)
    out = oidc.exchange_code("the-code")
    assert out == {"email": "pulkit.tyagi@axelerant.com", "name": "Pulkit Tyagi"}
    assert calls["token_url"] == "https://slack.com/api/openid.connect.token"
    assert calls["auth"] == "Bearer xoxp-at"


def test_exchange_code_token_failure_returns_none(monkeypatch):
    monkeypatch.setattr(oidc.httpx, "post", lambda *a, **k: _Resp({"ok": False, "error": "invalid_code"}))
    assert oidc.exchange_code("bad") is None


def test_exchange_code_userinfo_without_email_returns_none(monkeypatch):
    monkeypatch.setattr(oidc.httpx, "post", lambda *a, **k: _Resp({"ok": True, "access_token": "t"}))
    monkeypatch.setattr(oidc.httpx, "get", lambda *a, **k: _Resp({"ok": True, "name": "No Email"}))
    assert oidc.exchange_code("c") is None


def test_exchange_code_network_error_returns_none(monkeypatch):
    def boom(*a, **k):
        raise oidc.httpx.ConnectError("network down")
    monkeypatch.setattr(oidc.httpx, "post", boom)
    assert oidc.exchange_code("c") is None
