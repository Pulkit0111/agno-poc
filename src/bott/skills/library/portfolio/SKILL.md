---
name: portfolio
description: Publish the leadership portfolio risk roll-up (risk/sentiment + velocity) as a dashboard and post the link.
---

# Portfolio Risk Roll-up

## When to use
Someone asks how the portfolio/accounts are doing overall, or a scheduled run says so.

## How to do it
- Call `publish_portfolio_dashboard` — it aggregates risk/sentiment (Memra) + last-sprint
  velocity (Jira), publishes the dashboard to Spin, and posts the link itself.
- For an ad-hoc chat request, pass `channel='<the Slack channel_id from context>'`,
  `thread_ts='<the Slack thread_ts from context>'` and `broadcast=true` — the tool posts the
  link in that thread AND on the channel — then reply with an EMPTY message (no text), since
  the tool already posted it. (Scheduled runs pass only the channel.)
