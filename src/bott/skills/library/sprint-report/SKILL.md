---
name: sprint-report
description: Publish an engagement's FULL sprint report from live Jira — requires a Jira project key (e.g. PADI). Not for ad-hoc/custom one-pagers or scorecards.
---

# Sprint Report

## When to use
Someone asks for an engagement's sprint report, or a scheduled run generates one. The
engagement is named by its Jira project key or name (e.g. "PADI") — no setup needed.

## How to do it
1. Call `build_sprint_dossier(engagement)` FIRST for the live Jira facts.
2. Compose a report tailored to the engagement as `report_json` — a `{"sections":[blocks]}`
   spec; pick the meaningful blocks (delivered / next-sprint tables, risks, highlights,
   client actions, notes). Do NOT restate metrics or story lists — those render from Jira
   automatically.
3. Call `publish_sprint_report(engagement, report_json, channel='<channel_id>', ...)`. The
   tool returns a link in its detail string.
4. Share that link once in your reply:
   - **Ad-hoc chat request**: post the link in-thread (with `thread_ts`) so it also
     broadcasts to the channel. Do NOT reply with an empty message.
   - **Scheduled run**: post the returned link to the configured channel using your Slack tool.
- Use `list_sprint_report_engagements` to find the right key. Resolve the engagement's
  Slack channel with your Memra tools (or use the current channel when asked ad-hoc).

## Custom artifacts (scorecard / one-pager / "not the full report")
For a CUSTOM artifact — a scorecard, executive one-pager, or any bespoke view that is NOT
the standard sprint report — do NOT call `publish_sprint_report`. Instead:
1. Call `build_sprint_dossier` for the exact numbers.
2. Compose your own HTML tailored to that artifact.
3. Publish it with `publish_web_page`.
