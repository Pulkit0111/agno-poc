---
name: portfolio
description: Leadership portfolio risk roll-up ACROSS ALL engagements (risk/sentiment + delivery velocity) as one dashboard. Not for a single engagement.
---

# Portfolio Risk Roll-up

## When to use
Someone asks how the portfolio/accounts are doing overall, or a scheduled run says so.

## How to do it
- Call `publish_portfolio_dashboard` — it aggregates risk/sentiment (Memra) + last-sprint
  velocity (Jira) and publishes the dashboard to Spin. The tool returns a link.
- Share that link once in your reply (for ad-hoc chat requests, post it in the thread so
  it broadcasts to the channel). Do NOT reply with an empty message — the tool no longer
  posts the link itself; you do.
- For scheduled runs, post the returned link to the configured channel using your Slack tool.
