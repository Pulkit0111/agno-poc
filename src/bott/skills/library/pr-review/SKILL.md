---
name: pr-review
description: Review a GitHub PR (or re-review on a thread follow-up) — enqueue the review and let the engine post the verdict.
---

# PR Review

## When to use
Someone asks you to review a GitHub PR, or follows up on a review in-thread.

## How to do it
- Call `start_review` (or `start_rereview` for a follow-up) and then STOP — reply with an
  EMPTY message, no text at all. The review engine acknowledges with a reaction and posts
  live progress + the verdict in this thread. Do not narrate or summarize.
