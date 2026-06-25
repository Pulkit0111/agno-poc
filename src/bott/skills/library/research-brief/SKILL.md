---
name: research-brief
description: Create a concise one-page research brief in HTML, deploy it to Spin, and share the link.
---

# Research Brief

Use this skill when the user asks for a one-page brief on a topic and wants it deployed as a shareable web page.

## Workflow

1. Clarify the topic if it is missing or ambiguous.
2. Create a single self-contained `.html` file in the workspace.
3. Write a concise, well-structured one-page brief:
   - clear title and short intro
   - 3–5 focused sections
   - practical takeaways or recommendations
   - restrained, readable styling with embedded CSS
4. Keep the writing grounded and avoid inventing facts. If the brief is meant to be researched, use the best available context and state uncertainty plainly.
5. Deploy the page with `publish_web_page` using the workspace file.
6. Share the hosted link with the user, and post it in the requested Slack channel/thread when provided.

## Style notes

- Use plain HTML and CSS only unless the user asks for scripts.
- Make it visually polished but simple: strong typography, good spacing, and mobile-friendly layout.
- Keep the page self-contained for portability.
- If the user asks for a specific audience or tone, adapt the brief accordingly.
