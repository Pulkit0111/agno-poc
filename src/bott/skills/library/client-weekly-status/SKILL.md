---
name: client-weekly-status
description: Create a client weekly status update for a single engagement using live status, risks, and latest sprint facts, then publish it as a hosted page or shareable deliverable.
---

# Client weekly status

Use this workflow when asked for a polished weekly status for one client engagement.

1. Gather current engagement context with `get_engagement_status`.
2. Gather the latest sprint facts with `build_sprint_dossier` for the engagement.
3. Compose a concise, client-ready update that covers:
   - delivery status
   - key risks / blockers
   - last sprint summary
   - any immediate next steps or asks
4. Publish the HTML with `publish_web_page` when the user asked for a deployed/shareable version.

Design guidance:
- Use Axelerant branding in the page: a clean hero, strong typography, and a restrained accent color palette.
- Prefer a modern, polished layout with card-based sections, rounded corners, soft shadows, and generous whitespace.
- Keep it client-facing: readable, concise, and visually balanced.
- Include a clear top-level title like `Weekly Status: <ENGAGEMENT>`.
- If you are generating HTML in the workflow, include inline CSS so the page renders consistently.

Content guidance:
- Do not restate raw Jira metric tables if the sprint tool will render them automatically.
- Prefer a short narrative with a small number of sections.
- Be explicit about open risks and mitigations.
- If useful, add a concise closing line with the immediate watch items.
