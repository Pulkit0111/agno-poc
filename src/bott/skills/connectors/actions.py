"""General guarded primitives — the agent's real hands.

Instead of one bespoke tool per feature, Bott gets one general tool per connected system:
``slack_api`` (any Slack Web API method), ``github_api`` (any GitHub REST call),
``atlassian_api`` (any Jira/Confluence REST call), and ``http_request`` (read the public
web). The LLM composes the call — method AND arguments — from reasoning; the deterministic
**action policy** (shared/action_policy.py) authorizes it (allow / gate-on-approval / deny);
a thin executor performs it. That's the model: LLM composes → guard authorizes → executor
acts. Capability is open-ended; only the *blast radius* is bounded.

Gated writes reuse the existing human Approve/Dismiss gate: the tool files an approval row
(action="api:<system>") and posts the card; on Approve the Slack-home router calls
``dispatch_approved_api`` which executes the stored call and posts the result in-thread.
"""

from __future__ import annotations

import json
import os
from typing import Any, Callable, Optional

from agno.run import RunContext
from agno.tools import tool

from bott.shared import config
from bott.shared.action_policy import classify
from bott.shared.observability.logging_setup import get_logger, redact

log = get_logger("bott.connectors.actions")

_RESULT_CAP = 3000  # chars of API response surfaced back into the agent context


# ---------------------------------------------------------------------------
# Executors (thin, dumb hands — no decisions here)
# ---------------------------------------------------------------------------

def _slack_client():
    from slack_sdk import WebClient
    tok = os.getenv("SLACK_BOT_TOKEN") or os.getenv("SLACK_TOKEN")
    return WebClient(token=tok) if tok else None


def _github_token_for_path(path: str) -> Optional[str]:
    """Installation token when the path names an allow-listed repo; PAT fallback otherwise."""
    import re
    m = re.match(r"^/repos/([\w.-]+)/([\w.-]+)", path or "")
    if m:
        try:
            from bott.agents.code_review.github.app_auth import app_token_for
            tok = app_token_for(m.group(1), m.group(2))
            if tok:
                return tok
        except Exception:  # noqa: BLE001 — fall through to PAT
            pass
    return config.github_token()


def _truncate(value: Any) -> str:
    s = value if isinstance(value, str) else json.dumps(value, default=str)
    return s[:_RESULT_CAP] + ("…(truncated)" if len(s) > _RESULT_CAP else "")


def execute_action(payload: dict) -> str:
    """Perform one already-authorized action. Shared by the direct-allow path and the
    post-approval path — the ONLY place API calls are actually made."""
    system = payload.get("system")
    method = payload.get("method") or "GET"
    params = payload.get("params") or {}
    path = payload.get("path") or ""
    url = payload.get("url") or ""
    try:
        if system == "slack":
            client = _slack_client()
            if client is None:
                return "Slack isn't configured."
            resp = client.api_call(method, params=params)
            return _truncate(resp.data if hasattr(resp, "data") else dict(resp))
        if system == "github":
            import httpx
            tok = _github_token_for_path(path)
            headers = {"Accept": "application/vnd.github+json",
                       "X-GitHub-Api-Version": "2022-11-28"}
            if tok:
                headers["Authorization"] = f"Bearer {tok}"
            r = httpx.request(method, f"https://api.github.com{path}",
                              json=params or None if method != "GET" else None,
                              params=params if method == "GET" else None,
                              headers=headers, timeout=30)
            r.raise_for_status()
            return _truncate(r.json() if r.content else {"status": r.status_code})
        if system == "atlassian":
            import httpx
            base = (config.jira_base_url() or "").rstrip("/")
            if not base:
                return "Jira/Confluence isn't configured (set JIRA_BASE_URL)."
            r = httpx.request(method, f"{base}{path}",
                              json=params or None if method != "GET" else None,
                              params=params if method == "GET" else None,
                              auth=(config.jira_email(), config.jira_api_token()),
                              headers={"Accept": "application/json"}, timeout=30)
            r.raise_for_status()
            return _truncate(r.json() if r.content else {"status": r.status_code})
        if system == "http":
            import httpx
            r = httpx.get(url, params=params or None, timeout=20, follow_redirects=True)
            r.raise_for_status()
            ctype = r.headers.get("content-type", "")
            return _truncate(r.json() if "json" in ctype else r.text)
        return f"Unknown system '{system}'."
    except Exception as e:  # noqa: BLE001 — surface the real error to the agent, honestly
        log.warning("%s action failed: %s", system, e)
        return f"The {system} call failed: {redact(str(e))}"


# ---------------------------------------------------------------------------
# Approval gating for "gate" verdicts
# ---------------------------------------------------------------------------

def _ctx_target(run_context) -> tuple[Optional[str], Optional[str], str]:
    deps = (getattr(run_context, "dependencies", None) or {}) if run_context else {}
    user_id = getattr(run_context, "user_id", None) or "system@axelerant.com"
    return deps.get("Slack channel_id"), deps.get("Slack thread_ts"), user_id


def _file_for_approval(run_context, payload: dict, summary: str) -> str:
    """Create the approval row and post the Approve/Dismiss card in-thread."""
    from bott.shared.approvals import create_request
    channel, thread_ts, user_id = _ctx_target(run_context)
    payload = {**payload, "channel": channel, "thread_ts": thread_ts}
    approval_id = create_request(user_id=user_id, action=f"api:{payload['system']}",
                                 summary=summary[:200], payload=json.dumps(payload))
    client = _slack_client()
    if client and channel:
        try:
            client.chat_postMessage(
                channel=channel, thread_ts=thread_ts,
                text=f"Approval needed: {summary}",
                blocks=[
                    {"type": "section", "text": {"type": "mrkdwn",
                     "text": f"*Approval needed* — {summary}\n_This changes shared state, so I need a human OK._"}},
                    {"type": "actions", "elements": [
                        {"type": "button", "style": "primary", "action_id": "approval_approve",
                         "text": {"type": "plain_text", "text": "Approve"}, "value": str(approval_id)},
                        {"type": "button", "style": "danger", "action_id": "approval_dismiss",
                         "text": {"type": "plain_text", "text": "Dismiss"}, "value": str(approval_id)},
                    ]},
                ],
            )
        except Exception as e:  # noqa: BLE001
            log.error("approval card post failed: %s", e)
    return ("I've posted an Approve/Dismiss for that (it changes shared state). "
            "I'll run it the moment it's approved.")


def dispatch_approved_api(approval_id: int) -> None:
    """Execute an APPROVED api:* action and post the result where it was requested.
    Called by the Slack-home router on Approve. Safe no-op for anything else."""
    from bott.shared.approvals import get_request
    row = get_request(approval_id)
    if not row or row.get("status") != "approved" or not str(row.get("action", "")).startswith("api:"):
        return
    payload = json.loads(row.get("payload") or "{}")
    result = execute_action(payload)
    client = _slack_client()
    channel = payload.get("channel")
    if client and channel:
        try:
            client.chat_postMessage(channel=channel, thread_ts=payload.get("thread_ts"),
                                    text=f"Done — {result[:500]}")
        except Exception as e:  # noqa: BLE001
            log.error("approved api result post failed: %s", e)


# ---------------------------------------------------------------------------
# The tools (LLM-facing)
# ---------------------------------------------------------------------------

def _parse_json(blob: str) -> tuple[Optional[dict], Optional[str]]:
    if not (blob or "").strip():
        return {}, None
    try:
        v = json.loads(blob)
        return (v, None) if isinstance(v, dict) else (None, "params must be a JSON object")
    except json.JSONDecodeError as e:
        return None, f"invalid JSON: {e}"


def _run(run_context, system: str, method: str, *, path: str = "", url: str = "",
         params_json: str = "", summary: str = "") -> str:
    params, err = _parse_json(params_json)
    if err:
        return f"Couldn't parse params — {err}."
    decision = classify(system, method, path=path, url=url, params=params)
    payload = {"system": system, "method": method, "path": path, "url": url, "params": params}
    if decision.verdict == "deny":
        return f"I won't run that: {decision.reason}"
    if decision.verdict == "gate":
        what = summary or f"{system} {method} {path or url}"
        return _file_for_approval(run_context, payload, what)
    # Convenience: Slack posts default to the current channel when none was given.
    if system == "slack" and "channel" not in (params or {}) and method.startswith(("chat.", "reactions.", "pins.")):
        channel, _, _ = _ctx_target(run_context)
        if channel:
            payload["params"] = {**params, "channel": channel}
    return execute_action(payload)


def actions_tools() -> list[Callable]:
    @tool(name="slack_api")
    def slack_api(run_context: RunContext, method: str, params_json: str = "",
                  summary: str = "") -> str:
        """Call ANY Slack Web API method — this is how you act on Slack: send or schedule a
        message, react, pin, read a channel, look up a user, and anything else Slack's API
        offers. Compose the method + params yourself.

        Args:
            method: the Slack Web API method, e.g. "chat.postMessage", "reactions.add",
                "chat.scheduleMessage" (use post_at epoch seconds for timed sends).
            params_json: the method's arguments as a JSON object string, e.g.
                '{"channel": "C123", "text": "hi"}'. For chat/reactions/pins methods the
                current channel is used when you omit "channel".
            summary: one human line describing the action (shown on the approval card if
                this needs a human OK).

        Reads and safe writes run immediately; shared-state changes post an Approve/Dismiss;
        destructive/admin calls are refused. Don't spam (no rapid repeated pings).
        """
        return _run(run_context, "slack", method, params_json=params_json, summary=summary)

    @tool(name="github_api")
    def github_api(run_context: RunContext, method: str, path: str,
                   params_json: str = "", summary: str = "") -> str:
        """Call the GitHub REST API — read anything; comment/label/open issues on
        allow-listed repos; bigger writes ask for approval. Code changes still go through
        your build tool (plan → approve → PR), never raw contents writes.

        Args:
            method: HTTP verb — GET, POST, PATCH, PUT.
            path: REST path, e.g. "/repos/owner/repo/issues/5/comments".
            params_json: query (GET) or body (writes) as a JSON object string.
            summary: one human line for the approval card when a write needs an OK.
        """
        return _run(run_context, "github", method, path=path, params_json=params_json,
                    summary=summary)

    @tool(name="atlassian_api")
    def atlassian_api(run_context: RunContext, method: str, path: str,
                      params_json: str = "", summary: str = "") -> str:
        """Call the Jira/Confluence REST API on the org site — read anything (issues, JQL,
        pages, spaces); writes (comments, transitions, edits) post an Approve/Dismiss first
        because they can be client-visible.

        Args:
            method: HTTP verb — GET, POST, PUT.
            path: REST path from the site root, e.g. "/rest/api/3/issue/IRM-515" or
                "/wiki/rest/api/content/12345".
            params_json: query (GET) or body (writes) as a JSON object string.
            summary: one human line for the approval card when a write needs an OK.
        """
        return _run(run_context, "atlassian", method, path=path, params_json=params_json,
                    summary=summary)

    @tool(name="http_request")
    def http_request(run_context: RunContext, url: str, params_json: str = "") -> str:
        """Fetch a public https URL (GET only) — docs, APIs, feeds, release notes: when you
        need information from the web that no connector covers, read it yourself.

        Args:
            url: the https URL to fetch.
            params_json: optional query params as a JSON object string.
        """
        return _run(run_context, "http", "GET", url=url, params_json=params_json)

    return [slack_api, github_api, atlassian_api, http_request]
