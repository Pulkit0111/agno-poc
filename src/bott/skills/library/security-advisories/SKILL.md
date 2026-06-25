---
name: security-advisories
description: Post or answer the Drupal security-advisory digest (severity-grouped, CVEs, fix versions) — on a schedule or when someone asks "any new Drupal CVEs?".
---

# Drupal Security Advisories

## When to use
A scheduled daily digest, or someone asking about new Drupal security advisories / CVEs.

## How to do it
- **In chat**: use your `drupal_security_advisories` tool to fetch the latest digest, then
  reply with it directly. Do NOT call `post_drupal_security_advisories` for chat responses.
- **Scheduled runs**: call `post_drupal_security_advisories(channel=...)` — that tool
  fetches the advisories and posts the digest to the channel (link previews disabled).
  Do not post anything else or add commentary.
