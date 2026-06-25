---
name: pr-review
description: Review a specific GitHub pull request — requires a PR URL or owner/repo#number. Not for release notes or general GitHub questions.
---

# PR Review

## When to use
Someone asks you to review a GitHub PR, or follows up on a review in-thread.

## How to do it
- Call `start_review` (or `start_rereview` for a follow-up) and then STOP — reply with an
  EMPTY message, no text at all. The review engine acknowledges with a reaction and posts
  live progress + the verdict in this thread. Do not narrate or summarize.
