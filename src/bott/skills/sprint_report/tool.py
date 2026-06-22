"""Agent tools for the sprint-report skill.

Works for ANY engagement with no per-engagement config: given a Jira project key or name
(e.g. "PADI"), Bott discovers the board, derives the title/slug from the project, and uses
the site-wide story-points field. The optional SPRINT_REPORT_OVERRIDES dict only customises
the rare engagement that wants a bespoke title/slug/channel.

Two-step by design (Approach A): the agent reads a deterministic *dossier* of Jira facts,
then hands back only the narrative to publish. Metrics and story tables are recomputed from
Jira at publish time, so the agent can never alter a number.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from typing import Callable

from bott.shared import config
from bott.shared.integrations.jira import JiraClient
from bott.shared.integrations.spin import get_publisher
from bott.shared.observability.logging_setup import get_logger
from bott.shared.persistence import store
from bott.skills.sprint_report import render

log = get_logger("bott.skills.sprint_report")


@dataclass
class Engagement:
    """A resolved engagement: its board + the presentation metadata derived from Jira
    (and any optional overrides)."""

    client: JiraClient
    board_id: int
    project_key: str
    title: str
    client_name: str
    org: str
    slug_tmpl: str
    board_url: str


@dataclass
class Dossier:
    meta: render.ReportMeta
    metrics: render.Metrics
    done_issues: list[dict]
    next_issues: list[dict]
    incomplete: list[dict]  # in-sprint issues that didn't finish — candidate risks
    slug: str
    sprint_id: int  # the closed sprint this report covers — used by the new-sprint guard


def _jira() -> JiraClient:
    return JiraClient(
        base_url=config.jira_base_url(),  # type: ignore[arg-type]
        email=config.jira_email(),  # type: ignore[arg-type]
        api_token=config.jira_api_token(),  # type: ignore[arg-type]
        story_points_field=config.jira_story_points_field(),
    )


def _board_url(base_url: str, board: dict) -> str:
    key = board.get("project_key") or ""
    if key and board.get("id"):
        return f"{base_url}/jira/software/c/projects/{key}/boards/{board['id']}"
    return ""


def _resolve_engagement(query: str) -> Engagement | None:
    """Discover the Jira board for an engagement (by project key or name) and build its
    presentation metadata. Returns None if no board matches."""
    client = _jira()
    board = client.find_board(query)
    if board is None:
        return None
    key = (board.get("project_key") or query).upper()
    ov = config.sprint_report_override(key)
    client.ensure_story_points_field()  # cache the site-wide SP field on the client
    if ov.get("story_points_field"):
        client.story_points_field = ov["story_points_field"]
    project_name = board.get("project_name") or board.get("name") or key
    client_name = ov.get("client", project_name)
    return Engagement(
        client=client,
        board_id=board["id"],
        project_key=key,
        title=ov.get("title", client_name),
        client_name=client_name,
        org=ov.get("org", "Axelerant"),
        slug_tmpl=ov.get("slug", f"{key.lower()}-sprint-{{n}}-report"),
        board_url=ov.get("uat_board_url") or _board_url(client.base_url, board),
    )


def _build_dossier(eng: Engagement) -> Dossier:
    """Fetch + compute everything deterministic for the report. Raises on no closed sprint."""
    client = eng.client
    sprint = client.latest_closed_sprint(eng.board_id)
    if sprint is None:
        raise LookupError(f"No closed sprint on the {eng.project_key} board — nothing to report yet.")

    issues = client.sprint_issues(sprint["id"])
    metrics = render.compute_metrics(issues)
    done_issues = [i for i in issues if i.get("is_done")]
    incomplete = [i for i in issues if not i.get("is_done")]

    n = render.sprint_number(sprint["name"])
    sprint_label = f"Sprint {n}" if n is not None else (sprint["name"] or "Sprint")
    next_label = f"Sprint {n + 1}" if n is not None else "Next Sprint"

    next_sprint = client.next_future_sprint(eng.board_id)
    next_issues = client.sprint_issues(next_sprint["id"]) if next_sprint else []

    meta = render.ReportMeta(
        title=eng.title,
        client=eng.client_name,
        org=eng.org,
        sprint_label=sprint_label,
        next_sprint_label=next_label,
        period=render.format_period(sprint.get("start"), sprint.get("end")),
    )
    slug = eng.slug_tmpl.format(n=n if n is not None else "")
    return Dossier(meta=meta, metrics=metrics, done_issues=done_issues,
                   next_issues=next_issues, incomplete=incomplete, slug=slug,
                   sprint_id=sprint["id"])


def _not_found(query: str) -> str:
    try:
        keys = sorted({b["project_key"] for b in _jira().list_boards() if b.get("project_key")})
        listing = ", ".join(keys) if keys else "(no boards visible)"
    except Exception:  # noqa: BLE001
        listing = "(couldn't list boards)"
    return f"Couldn't find a Jira board for '{query}'. Known projects: {listing}."


def list_sprint_report_engagements() -> str:
    """List the engagements you can build a sprint report for — every Jira board, by project
    key and name. Use this to discover the right key, or to report on each in turn.
    """
    if not config.jira_configured():
        return "Jira isn't configured (set JIRA_BASE_URL, JIRA_EMAIL, JIRA_API_TOKEN)."
    try:
        boards = _jira().list_boards()
    except Exception as e:  # noqa: BLE001
        log.error("list boards failed: %s", e)
        return f"Couldn't list Jira boards ({e})."
    if not boards:
        return "No Jira boards are visible to this account."
    lines = [f"  {b['project_key'] or '?'} — {b['project_name'] or b['name']}" for b in boards]
    return "Engagements (Jira project key — name):\n" + "\n".join(lines)


def build_sprint_dossier(engagement: str) -> str:
    """Gather the live Jira facts for an engagement's most recent CLOSED sprint, so you can
    write the sprint report's narrative. ``engagement`` is a Jira project key or name (e.g.
    'PADI'); the board is discovered automatically. Returns metrics, the delivered-stories
    list, the next-sprint story list, and the incomplete/carry-over issues (risk candidates).

    After reading this, call publish_sprint_report with the narrative you compose. Do NOT
    restate the metrics or story lists — those render from Jira automatically.

    Args:
        engagement: Jira project key or name (e.g. 'PADI').
    """
    if not config.jira_configured():
        return "Jira isn't configured (set JIRA_BASE_URL, JIRA_EMAIL, JIRA_API_TOKEN)."
    try:
        eng = _resolve_engagement(engagement)
        if eng is None:
            return _not_found(engagement)
        d = _build_dossier(eng)
    except LookupError as e:
        return str(e)
    except Exception as e:  # noqa: BLE001 — report, don't crash the run
        log.error("dossier build failed for %s: %s", engagement, e)
        return f"Couldn't gather Jira data for '{engagement}' ({e})."

    m = d.metrics
    pts = (
        f"{render._num(m.points_achieved)}/{render._num(m.points_planned)} pts, "
        f"velocity {m.velocity_pct}%" if m.has_points else "story points not tracked on this board"
    )
    lines = [
        f"DOSSIER — {d.meta.title} [{eng.project_key}], {d.meta.sprint_label} ({d.meta.period})",
        f"Metrics: {m.stories_delivered} stories delivered, {pts}.",
        "",
        "DELIVERED STORIES (rendered into the report automatically — do not restate):",
        *([f"  {n}. {i['summary']}" for n, i in enumerate(d.done_issues, 1)] or ["  (none)"]),
        "",
        f"{d.meta.next_sprint_label} STORIES (rendered automatically):",
        *([f"  {n}. {i['summary']}" + (f" [{i['tag']}]" if i.get("tag") else "")
           for n, i in enumerate(d.next_issues, 1)] or ["  (none planned yet)"]),
        "",
        "INCOMPLETE / CARRY-OVER (your risk & blocker candidates — synthesize, don't dump):",
        *([f"  - {i['summary']} (status: {i['status']})" for i in d.incomplete] or ["  (none)"]),
        "",
        f"UAT / board link for client actions: {eng.board_url or '(none)'}",
        "",
        f"NEXT: call publish_sprint_report(engagement='{eng.project_key}', narrative_json, channel) "
        'where narrative_json is a JSON object: {"highlights": [str], "risks": [{"issue","impact",'
        '"status":"resolved|monitored|inprogress"}], "actions": [{"title","desc","link"?,"owner"?,'
        '"priority":"high|medium"}], "priorities_note": str}. Resolve the engagement\'s Slack '
        "channel with your Memra tools and pass it as channel.",
    ]
    return "\n".join(lines)


def publish_sprint_report(
    engagement: str, narrative_json: str, channel: str = "", only_if_new: bool = False
) -> str:
    """Render the sprint report (live Jira metrics + your narrative) as a hosted HTML page and
    publish it. ``engagement`` is a Jira project key or name. Metrics and story tables come
    straight from Jira — only the narrative is yours.

    Args:
        engagement: Jira project key or name (e.g. 'PADI').
        narrative_json: JSON object with keys highlights[], risks[], actions[], priorities_note.
            See build_sprint_dossier's output for the exact shape.
        channel: Slack channel to post the published link (or draft) to. Resolve it for the
            engagement with your Memra tools when it isn't obvious from context.
        only_if_new: scheduled runs pass true — publish only if this sprint hasn't been reported
            yet (skip duplicates). Leave false for ad-hoc requests so they always generate.
    """
    if not config.jira_configured():
        return "Jira isn't configured (set JIRA_BASE_URL, JIRA_EMAIL, JIRA_API_TOKEN)."

    try:
        data = json.loads(narrative_json) if narrative_json else {}
        if not isinstance(data, dict):
            raise ValueError("narrative_json must be a JSON object")
    except (json.JSONDecodeError, ValueError) as e:
        return (
            f"narrative_json wasn't valid ({e}). Expected an object with keys: highlights[], "
            "risks[], actions[], priorities_note."
        )

    narrative = render.Narrative(
        highlights=list(data.get("highlights") or []),
        risks=list(data.get("risks") or []),
        actions=list(data.get("actions") or []),
        priorities_note=str(data.get("priorities_note") or ""),
    )

    try:
        eng = _resolve_engagement(engagement)
        if eng is None:
            return _not_found(engagement)
        d = _build_dossier(eng)
    except LookupError as e:
        return str(e)
    except Exception as e:  # noqa: BLE001
        log.error("dossier build failed for %s: %s", engagement, e)
        return f"Couldn't gather Jira data for '{engagement}' ({e})."

    # New-sprint guard: scheduled runs skip a sprint already reported (avoids duplicates
    # across any cadence). Ad-hoc runs (only_if_new=False) always publish.
    marker_key = f"sprint_report_last:{eng.project_key}"
    if only_if_new and store.get_setting(marker_key) == str(d.sprint_id):
        return f"Already reported {d.meta.sprint_label} for {eng.project_key}; skipping (no new sprint)."

    html = render.render_html(d.meta, d.metrics, d.done_issues, d.next_issues, narrative)
    title = f"{d.meta.title} — {d.meta.sprint_label} Report"

    publisher = get_publisher()
    try:
        result = publisher.publish(d.slug, title, html, channel=channel)
    except Exception as e:  # noqa: BLE001 — fall back to a Slack draft on any Spin failure
        log.error("spin publish failed for %s, falling back to Slack: %s", engagement, e)
        from bott.shared.integrations.spin import SlackDraftPublisher

        token = os.getenv("SLACK_BOT_TOKEN") or os.getenv("SLACK_TOKEN") or ""
        try:
            result = SlackDraftPublisher(token).publish(d.slug, title, html, channel=channel)
        except Exception as e2:  # noqa: BLE001
            return f"Couldn't publish the report and the Slack fallback failed too ({e2})."

    if result.mode == "spin" and result.url and channel:
        try:
            from slack_sdk import WebClient

            token = os.getenv("SLACK_BOT_TOKEN") or os.getenv("SLACK_TOKEN")
            if token:
                WebClient(token=token).chat_postMessage(
                    channel=channel,
                    text=f"📊 *{title}* is ready: {result.url}",
                    unfurl_links=False, unfurl_media=False,
                )
        except Exception as e:  # noqa: BLE001 — the report is published; posting is best-effort
            log.warning("posted report but Slack link post failed: %s", e)

    # Remember the sprint we just reported so a later scheduled run won't duplicate it.
    try:
        store.set_setting(marker_key, str(d.sprint_id))
    except Exception as e:  # noqa: BLE001 — marker is best-effort
        log.warning("couldn't record last-reported sprint for %s: %s", eng.project_key, e)

    return result.detail


def sprint_report_tools() -> list[Callable]:
    return [list_sprint_report_engagements, build_sprint_dossier, publish_sprint_report]
