---
name: portfolio
description: Leadership portfolio risk roll-up ACROSS ALL engagements (risk/sentiment + delivery velocity) as one dashboard. Not for a single engagement.
---

# Portfolio Risk Roll-up

## When to use
A leadership view of risk/health. Two paths:

## How to do it
- For a CUSTOM ask (top-N briefing, a focused scorecard, a question): call
  `get_portfolio_risk_data` for the data, compose exactly what was asked as HTML, and publish
  with `publish_web_page`. Share the returned link once.
- The FULL canonical roll-up dashboard is produced only by the scheduled run
  (`publish_portfolio_dashboard scheduled=true`) — don't call it for ad-hoc requests.
