---
name: sprint-report
description: Publish an engagement's FULL sprint report from live Jira — requires a Jira project key (e.g. PADI). Not for ad-hoc/custom one-pagers or scorecards.
---

# Sprint Report

## When to use
An engagement's sprint/delivery picture (needs a Jira project key, e.g. PADI).

## How to do it
- For a CUSTOM ask (a scorecard, one-pager, "not the full report", a status/weekly update):
  call `build_sprint_dossier` (and `get_sprint_history` for trends) for the exact numbers,
  compose the HTML you need, and publish with `publish_web_page`. Share the link once.
- The FULL canonical report is produced only by the scheduled run
  (`publish_sprint_report scheduled=true`) — don't call it for ad-hoc requests.
