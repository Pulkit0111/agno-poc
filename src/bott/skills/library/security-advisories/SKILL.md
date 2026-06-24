---
name: security-advisories
description: Post or answer the Drupal security-advisory digest (severity-grouped, CVEs, fix versions) — on a schedule or when someone asks "any new Drupal CVEs?".
---

# Drupal Security Advisories

## When to use
A scheduled daily digest, or someone asking about new Drupal security advisories / CVEs.

## How to do it
- Use your `drupal_security_advisories` tool to fetch the latest digest.
- When a scheduled run tells you to post the digest verbatim, post the tool's output
  exactly — do not rewrite it.
- To post to a specific channel with link previews disabled, use
  `post_drupal_security_advisories(channel=...)` (the plain Slack post tool would unfurl
  every advisory URL).
