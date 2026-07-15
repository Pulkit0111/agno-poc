"""Live connector health probes — one authenticated round-trip per connector, reusing the
SAME client constructors the read tools already build (no new auth paths, no new env vars).

``probe(name, subject_email=None) -> {"ok": bool, "message": str}`` is the only public
entry point. An unknown ``name`` raises ``KeyError`` (the console router turns that into a
404); every KNOWN probe is wrapped so a network/auth failure never raises past this
module — it comes back as ``{"ok": False, "message": <plain-language text incl. the
exception>}`` instead. Codex needs no network at all (``codex_cli.is_logged_in()``).

Gmail/Drive/Calendar are domain-delegated: the caller must pass the acting admin's email
as ``subject_email`` (the console router supplies the signed-in admin's own address) since
there is no single default mailbox to impersonate.
"""

from __future__ import annotations

import os
from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import TimeoutError as FutureTimeoutError
from types import SimpleNamespace
from typing import Any, Callable, Optional

from bott.shared import codex_cli, config
from bott.shared.observability.logging_setup import get_logger, redact

log = get_logger("bott.connectors.probes")

_TIMEOUT = 10.0
_DEADLINE = 15.0


def _with_deadline(fn: Callable[[], Any], seconds: Optional[float] = None) -> Any:
    """Run ``fn`` in a worker thread with a hard deadline. Some client stacks expose no
    timeout knob anywhere in their call chain (googleapiclient's discovery/build), so a
    hung socket would otherwise pin the console's Test endpoint indefinitely. On timeout
    this raises ``TimeoutError`` (the probe wrapper turns it into ``ok: False``) and
    abandons the worker — a bounded best-effort thread leak, one per timed-out probe.
    ``seconds`` resolves against the module's ``_DEADLINE`` at call time (patchable)."""
    seconds = _DEADLINE if seconds is None else seconds
    pool = ThreadPoolExecutor(max_workers=1)
    try:
        return pool.submit(fn).result(timeout=seconds)
    except FutureTimeoutError:
        raise TimeoutError(f"timed out after {seconds:.0f}s") from None
    finally:
        # wait=False: never block on a hung worker — that's the whole point of the deadline.
        pool.shutdown(wait=False, cancel_futures=True)


def _plain_message(e: Exception) -> str:
    """An exception's text, redacted. Probe messages are shown verbatim in the console's
    fix-setup drawer, so any token an SDK echoes back in its error text must be scrubbed
    here too — not only in the log line."""
    return redact(str(e).strip() or e.__class__.__name__)


def _jira() -> dict:
    if not config.jira_configured():
        return {"ok": False, "message": "Jira isn't configured (set JIRA_BASE_URL, JIRA_EMAIL, JIRA_API_TOKEN)."}
    from bott.shared.integrations.jira import JiraClient

    client = JiraClient(
        base_url=config.jira_base_url(),  # type: ignore[arg-type]
        email=config.jira_email(),  # type: ignore[arg-type]
        api_token=config.jira_api_token(),  # type: ignore[arg-type]
        story_points_field=config.jira_story_points_field(),
        timeout=_TIMEOUT,
    )
    me = client._get("/rest/api/3/myself")
    who = me.get("displayName") or me.get("emailAddress") or "the configured account"
    return {"ok": True, "message": f"Connected to Jira as {who}."}


def _confluence() -> dict:
    if not config.confluence_configured():
        return {"ok": False, "message": "Confluence isn't configured (set CONFLUENCE_URL + credentials)."}
    # Same credentials/env config the ConfluenceTools connector uses, but constructing the
    # underlying atlassian client directly: the toolkit exposes no timeout parameter and
    # the atlassian client's default is 75s — too long for a health probe.
    from atlassian import Confluence

    client = Confluence(
        url=config.confluence_url(),
        username=config.confluence_username(),
        password=config.confluence_api_key(),
        timeout=int(_TIMEOUT),
    )
    spaces = client.get_all_spaces(start=0, limit=1)
    count = len((spaces or {}).get("results") or [])
    return {"ok": True, "message": f"Reached Confluence ({count} space listed)."}


def _slack() -> dict:
    token = os.getenv("SLACK_BOT_TOKEN") or os.getenv("SLACK_TOKEN")
    if not token or not os.getenv("SLACK_SIGNING_SECRET"):
        return {"ok": False, "message": "Slack isn't configured (set SLACK_BOT_TOKEN + SLACK_SIGNING_SECRET)."}
    from slack_sdk import WebClient

    resp = WebClient(token=token, timeout=int(_TIMEOUT)).auth_test()
    team = resp.get("team") or "your workspace"
    return {"ok": True, "message": f"Connected to Slack as the bot in {team}."}


def _memra() -> dict:
    if not config.memra_configured():
        return {"ok": False, "message": "Memra isn't configured (set MEMRA_CLIENT_ID + MEMRA_CLIENT_SECRET)."}
    from bott.shared.context.memra import MemraClient

    tool_names = MemraClient(timeout=_TIMEOUT).list_tools()
    return {"ok": True, "message": f"Reached Memra ({len(tool_names)} tool(s) available)."}


def _sentry() -> dict:
    if not config.sentry_configured():
        return {"ok": False, "message": "Sentry isn't configured (set SENTRY_ORG_SLUG + SENTRY_API_TOKEN)."}
    from bott.shared.integrations.sentry import SentryClient

    client = SentryClient(
        base_url=config.sentry_base_url(),  # type: ignore[arg-type]
        org_slug=config.sentry_org_slug(),  # type: ignore[arg-type]
        api_token=config.sentry_api_token(),  # type: ignore[arg-type]
        timeout=int(_TIMEOUT),
    )
    client.list_issues(limit=1)
    return {"ok": True, "message": f"Reached Sentry org '{config.sentry_org_slug()}'."}


def _codex() -> dict:
    if codex_cli.is_logged_in():
        return {"ok": True, "message": "Codex is connected — using the org's ChatGPT subscription."}
    return {"ok": False, "message": "Codex isn't connected. An admin can connect it from the Models page."}


# ── Google (Gmail/Drive/Calendar) — domain-delegated, needs the acting admin's email ──

def _gmail_probe(subject_email: Optional[str]) -> dict:
    if not config.google_delegation_configured():
        return {"ok": False, "message": "Google delegation isn't configured (set GOOGLE_SERVICE_ACCOUNT_PATH)."}
    if not subject_email:
        return {"ok": False, "message": "No signed-in email to test delegated Gmail access with."}
    from bott.skills.connectors import gmail as gmail_mod

    def _run():
        gt = gmail_mod._impersonated(SimpleNamespace(user_id=subject_email))
        gt.search_emails("", 1)

    # googleapiclient's build/discovery chain has no timeout parameter — enforce one here.
    _with_deadline(_run)
    return {"ok": True, "message": f"Delegated Gmail read succeeded for {subject_email}."}


def _drive_probe(subject_email: Optional[str]) -> dict:
    if not config.google_delegation_configured():
        return {"ok": False, "message": "Google delegation isn't configured (set GOOGLE_SERVICE_ACCOUNT_PATH)."}
    if not subject_email:
        return {"ok": False, "message": "No signed-in email to test delegated Drive access with."}
    from bott.skills.connectors import drive as drive_mod

    def _run():
        gt = drive_mod._impersonated(SimpleNamespace(user_id=subject_email))
        gt.search_files("", 1)

    # googleapiclient's build/discovery chain has no timeout parameter — enforce one here.
    _with_deadline(_run)
    return {"ok": True, "message": f"Delegated Drive read succeeded for {subject_email}."}


def _calendar_probe(subject_email: Optional[str]) -> dict:
    if not config.google_delegation_configured():
        return {"ok": False, "message": "Google delegation isn't configured (set GOOGLE_SERVICE_ACCOUNT_PATH)."}
    if not subject_email:
        return {"ok": False, "message": "No signed-in email to test delegated Calendar access with."}
    from bott.skills.connectors import calendar as calendar_mod

    def _run():
        gt = calendar_mod._impersonated(SimpleNamespace(user_id=subject_email))
        gt.list_calendars()

    # googleapiclient's build/discovery chain has no timeout parameter — enforce one here.
    _with_deadline(_run)
    return {"ok": True, "message": f"Delegated Calendar read succeeded for {subject_email}."}


_GOOGLE_SERVICES: dict[str, Callable[[Optional[str]], dict]] = {
    "gmail": _gmail_probe,
    "drive": _drive_probe,
    "calendar": _calendar_probe,
}


def _google(subject_email: Optional[str]) -> dict:
    """The console's single 'Google' card runs all three delegated scopes and reports the
    combined result — a Workspace admin can misconfigure any one of them independently."""
    if not config.google_delegation_configured():
        return {"ok": False, "message": "Google delegation isn't configured (set GOOGLE_SERVICE_ACCOUNT_PATH)."}
    if not subject_email:
        return {"ok": False, "message": "No signed-in email to test Google delegation with."}
    parts: list[str] = []
    ok = True
    for kind, fn in _GOOGLE_SERVICES.items():
        try:
            result = fn(subject_email)
        except Exception as e:  # noqa: BLE001 — one scope failing shouldn't crash the others
            result = {"ok": False, "message": _plain_message(e)}
        ok = ok and bool(result.get("ok"))
        parts.append(f"{kind}: {'ok' if result.get('ok') else result.get('message')}")
    return {"ok": ok, "message": "; ".join(parts)}


_PROBES: dict[str, Callable[[Optional[str]], dict]] = {
    "jira": lambda subject: _jira(),
    "confluence": lambda subject: _confluence(),
    "slack": lambda subject: _slack(),
    "memra": lambda subject: _memra(),
    "sentry": lambda subject: _sentry(),
    "codex": lambda subject: _codex(),
    "gmail": _gmail_probe,
    "drive": _drive_probe,
    "calendar": _calendar_probe,
    "google": _google,
}


def probe(name: str, subject_email: Optional[str] = None) -> dict:
    """Run one connector's live health check. Raises ``KeyError`` for an unknown name
    (the console router 404s on that); every known probe always returns a
    ``{"ok": bool, "message": str}`` dict, even when the round-trip itself blows up.

    Names not in the static ``_PROBES`` table are looked up in the console's credential
    store (``connector_credentials`` — see ``_stored_kind``/``_stored_probe`` below):
    connectors added from the console (a second Sentry org, a custom HTTP API, the GitHub
    App) aren't wired into a fixed name here, so this re-derives which validation probe to
    re-run from the name's own convention (``github-app`` / ``sentry-<org>`` /
    ``http-<slug>``) and re-probes with the STORED credentials."""
    key = (name or "").strip().lower()
    if key in _PROBES:
        try:
            result = _PROBES[key](subject_email)
            return {"ok": bool(result.get("ok")), "message": str(result.get("message") or "")}
        except Exception as e:  # noqa: BLE001 — a probe must NEVER raise past this point
            log.warning("connector probe %r failed: %s", key, redact(str(e)))
            return {"ok": False, "message": f"Couldn't reach {key} ({_plain_message(e)})."}

    stored = _stored_probe(key)
    if stored is not None:
        return stored
    raise KeyError(name)


# ── Store-backed connectors (added from the console — no static name here) ───────────
#
# SSRF — a documented, accepted risk. _sentry_org_candidate and _http_api_candidate GET an
# ADMIN-supplied base_url from the server, which makes the probe a reachability oracle
# into the server's network. Accepted because (a) the add flow is strictly admin-gated —
# only the operators already trusted to run Bott's deployment (and its env/secrets) can
# point it anywhere, and (b) probing internal APIs on private ranges is a LEGITIMATE,
# intended use of the custom-HTTP-API connector, so a blanket RFC-1918 block would break
# the feature for its primary audience. The one hard line drawn (_reject_metadata_host):
# the link-local/metadata range — no connector has any business there, and the cloud
# metadata service is the single highest-value SSRF target (instance credentials).

_METADATA_HOSTNAMES = {"metadata.google.internal", "metadata.goog"}


def _reject_metadata_host(base_url: str) -> None:
    """Refuse URLs whose host is the link-local/metadata range (169.254.0.0/16, IPv6
    fe80::/10) or a well-known metadata hostname. A plain pre-check on the URL's own
    host literal — deliberately NO DNS resolution (a resolving guard can be TOCTOU'd
    anyway; this is a tripwire for the obvious case, not a full egress policy — see the
    SSRF note above). Raises ValueError with a user-facing message; runs BEFORE any
    network round-trip, so a refused URL is never probed."""
    from ipaddress import ip_address
    from urllib.parse import urlsplit

    host = (urlsplit(base_url).hostname or "").lower()
    if host in _METADATA_HOSTNAMES:
        raise ValueError("That host is the cloud metadata service — not allowed.")
    try:
        addr = ip_address(host)
    except ValueError:
        return  # a hostname, not an IP literal — allowed (no DNS resolution by design)
    # An IPv4-mapped IPv6 literal (::ffff:a.b.c.d) is link-local iff the MAPPED v4 address
    # is — .is_link_local on the v6 wrapper itself doesn't see through the mapping, so
    # `http://[::ffff:169.254.169.254]/` would otherwise sail past this check straight to
    # the metadata service. Evaluate the mapped v4 address when present.
    effective = getattr(addr, "ipv4_mapped", None) or addr
    if effective.is_link_local:
        raise ValueError("Link-local addresses (169.254.0.0/16) aren't allowed.")


def _github_app_candidate(fields: dict) -> dict:
    """Probe CANDIDATE (or stored) GitHub App credentials directly — mints an App JWT
    with the given key and hits GET /app (validates the app identity itself; no
    installation needed). Reused by both the add-connector validation gate (candidate,
    unsaved fields) and re-testing an already-stored GitHub App from the console."""
    from bott.agents.code_review.github import app_auth

    app_id = str(fields.get("app_id") or "")
    private_key = str(fields.get("private_key") or "")
    token = app_auth._app_jwt(app_id, private_key)
    import httpx

    r = httpx.get(f"{app_auth.API}/app", headers={
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
        "User-Agent": "bott-poc-review",
    }, timeout=_TIMEOUT)
    r.raise_for_status()
    data = r.json()
    return {"ok": True, "message": f"Connected to GitHub App '{data.get('name') or app_id}'."}


def _sentry_org_candidate(fields: dict) -> dict:
    """Probe CANDIDATE (or stored) Sentry org credentials — same client the primary
    org's probe uses, constructed with explicit (not env-sourced) args."""
    from bott.shared.integrations.sentry import SentryClient

    org = str(fields.get("org") or "")
    _reject_metadata_host(str(fields.get("base_url") or "https://sentry.io"))
    client = SentryClient(
        base_url=str(fields.get("base_url") or "https://sentry.io"),
        org_slug=org,
        api_token=str(fields.get("auth_token") or ""),
        timeout=int(_TIMEOUT),
    )
    client.list_issues(limit=1)
    return {"ok": True, "message": f"Reached Sentry org '{org}'."}


def _http_api_candidate(fields: dict) -> dict:
    """Probe a custom read-only HTTP API: GET base_url with the optional header, treat
    anything under 500 as reachable (many APIs 401/403/404 on an unauthenticated/wrong-
    path GET but are still clearly UP — 5xx is the "this thing is actually broken" signal)."""
    import httpx

    base_url = str(fields.get("base_url") or "")
    _reject_metadata_host(base_url)
    headers = {}
    if fields.get("header_name"):
        headers[str(fields["header_name"])] = str(fields.get("header_value") or "")
    r = httpx.get(base_url, headers=headers, timeout=_TIMEOUT)
    if r.status_code >= 500:
        raise RuntimeError(f"server error (HTTP {r.status_code})")
    return {"ok": True, "message": f"Reached {base_url} (HTTP {r.status_code})."}


_CANDIDATE_PROBES: dict[str, Callable[[dict], dict]] = {
    "github_app": _github_app_candidate,
    "sentry_org": _sentry_org_candidate,
    "http_api": _http_api_candidate,
}


def probe_candidate(kind: str, fields: dict) -> dict:
    """Probe a CANDIDATE connector's credentials directly from caller-supplied fields,
    before anything is stored — the add-connector flow's "test before you trust it" gate.
    ``kind`` is one of ``"github_app"``/``"sentry_org"``/``"http_api"``. Raises ``KeyError``
    for an unknown kind; otherwise never raises — same ``{"ok", "message"}`` contract as
    ``probe()``, and the same redaction on exception-derived messages."""
    fn = _CANDIDATE_PROBES.get(kind)
    if fn is None:
        raise KeyError(kind)
    try:
        result = fn(fields)
        return {"ok": bool(result.get("ok")), "message": str(result.get("message") or "")}
    except Exception as e:  # noqa: BLE001 — never raise past this point
        log.warning("candidate probe %r failed: %s", kind, redact(str(e)))
        return {"ok": False, "message": _plain_message(e)}


def _stored_kind(key: str) -> Optional[str]:
    """Which candidate-probe kind a store-backed connector NAME implies, from the naming
    convention the console router's add-flow itself assigns (see router.py). ``None`` for
    a name that doesn't match any known store-backed convention."""
    if key == "github-app":
        return "github_app"
    if key.startswith("sentry-"):
        return "sentry_org"
    if key.startswith("http-"):
        return "http_api"
    return None


def _stored_probe(key: str) -> Optional[dict]:
    """Re-run the add-time validation probe for an already-STORED, console-added
    connector. Returns ``None`` (not a probe failure) when ``key`` isn't a recognized
    store-backed name or nothing's stored under it — the caller (``probe()``) treats that
    as "truly unknown connector", not "unreachable"."""
    kind = _stored_kind(key)
    if kind is None:
        return None
    from bott.shared import connector_credentials
    creds = connector_credentials.load(key)
    if creds is None:
        return None
    return probe_candidate(kind, creds)
