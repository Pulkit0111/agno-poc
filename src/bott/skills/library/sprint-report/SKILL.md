---
name: sprint-report
description: Generate an engagement's sprint/status report from live Jira and publish it (Spin), posting the link to Slack.
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
3. Publish:
   - **Ad-hoc chat request**: call `publish_sprint_report(engagement, report_json, channel='<channel_id>', thread_ts='<thread_ts from context>', broadcast=true)` — posts in-thread AND broadcasts to the channel. Then reply with an EMPTY message (the link post IS the reply).
   - **Scheduled run**: call `publish_sprint_report(engagement, report_json, channel='<channel_id>')` — only the channel is needed.
- Use `list_sprint_report_engagements` to find the right key. Resolve the engagement's
  Slack channel with your Memra tools (or use the current channel when asked ad-hoc).
- Report back the published URL (or draft status) and nothing else.
