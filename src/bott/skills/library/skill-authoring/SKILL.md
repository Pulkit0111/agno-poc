---
name: skill-authoring
description: How to learn a new reusable skill from the user by interviewing them, then saving it.
---

## When to use
When someone asks Bott to "learn", "remember how to", or "always do" a repeatable workflow — or when a useful multi-step routine keeps recurring.

## How to do it
Run a short, friendly interview (one or two turns) to capture:
1. **When to use it** — the trigger/situation (this becomes the description).
2. **The steps** — what Bott should do, in order, including which tools/connectors to use.
3. **Inputs / preconditions** — anything needed first (an engagement name, a channel, credentials).
4. **Done check** — how to know it worked.

Then call `author_skill` with `name` (a short title → kebab-case id), `description` (one line on when to use it), and `instructions` (the steps as a clear Markdown body). Confirm the saved skill name back. Don't ask more than a couple of questions — infer sensible defaults. Never author over a built-in skill; pick a distinct name.

## Curation
Use `list_skills` to review the library. Admins can `pin_skill` (protect) or `retire_skill` (remove) authored skills; built-ins are always kept.
