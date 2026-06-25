---
name: poem-page-deployer
description: Create a visually polished HTML page for a poem using plain HTML/CSS and deploy it to Spin, returning the hosted link.
---

# Poem Page Deployer

Use this skill when the user asks to turn a poem into a beautiful standalone HTML page and deploy it as a shareable Spin link.

## Workflow

1. Write a single self-contained `.html` file in the workspace.
2. Use plain HTML and CSS only unless the user explicitly asks for scripts.
3. Prefer a polished, theatrical layout:
   - centered hero/title
   - atmospheric gradients or subtle textures
   - a framed poem card or stage-like panel
   - responsive typography
   - restrained ornamentation
4. Keep the poem text unchanged unless the user asks for edits.
5. Deploy the page with `publish_web_page`, using the workspace file.
6. Return only the hosted link unless the user asks for more.

## Style notes

- Use semantic HTML.
- Make the page readable on mobile.
- Keep the CSS embedded in the file for portability.
- Avoid external assets and JS unless necessary.

## Deliverable

A shareable Spin URL to the published HTML page.