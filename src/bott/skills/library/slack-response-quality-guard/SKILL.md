---
name: slack-response-quality-guard
description: Use before replying in Slack when responding with findings, citations, status, or published links; prevents duplicate/meta replies, weak evidence overclaiming, raw IDs, and unverified links.
---

Before posting a Slack reply:
1. Answer once. Do not add a separate “Done — I replied/checked/posted” confirmation after the substantive answer. If the work product is already posted, stop.
2. Lead with the user-facing result, not process narration. Avoid meta updates unless the task is genuinely asynchronous.
3. Do not expose raw system identifiers (Slack timestamps, thread_ts, IDs) as primary references. Convert them to human-readable links or names. Include raw IDs only if explicitly asked or diagnostically necessary.
4. If citing Memra/context findings, separate strong evidence from weak/inferred evidence. Use honest language like “the context supports…” or “thin signal…” when appropriate. Never make weak evidence sound definitive.
5. Never claim completion unless the tool result proves it. “Published,” “posted,” “checked,” or “deployed” must correspond to an actual successful tool response.
6. For any hosted/published link: share only the exact URL returned by the publishing tool. If it is malformed, incomplete, or suspicious, do not infer a likely URL. Republish with a safer/shorter name if possible; otherwise say plainly that a valid link was not returned.
7. Your reply is delivered once by the Slack interface itself — you do not post it with a Slack send tool. Produce a single final answer; never emit a separate confirmation or a duplicate top-level message alongside it.
8. Keep the reply short and specific. If there are multiple issues, group them into a compact list; avoid corporate cheerleading and unnecessary apologies.
