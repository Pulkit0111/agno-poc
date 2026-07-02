---
name: recognize-own-codebase
description: Use when asked to inspect, change, improve, or "fix yourself" / act on your own repo. How to figure out which accessible repo is Bott's own codebase and safely open a PR against it.
---

When someone asks you to look at, change, improve, or "fix" **your own repo / your own code / yourself**, you are NOT told which repo that is — you figure it out by looking.

## How to identify your own codebase
1. Call **`list_repos`** to see the repositories you can act on (and which you have write access to).
2. Use **`inspect_repo(owner/repo)`** on the likely candidate(s) and recognize your own codebase by its fingerprint — it is the repo that contains **you**:
   - a Python package `bott` (e.g. `src/bott/agents/bott_agent.py`, `src/bott/agents/personality.py`),
   - a `pyproject.toml` with a `bott-app` entry point,
   - a README describing an **Agno**-based, Slack-first agent named **Bott**.
   Reason from what you actually read — do not guess from the repo name alone.
3. If exactly one accessible repo matches, that's you. If none clearly match, say so and ask which repo is your codebase. If more than one looks plausible, inspect further or ask.

## Before you act
- **Confirm first:** "I believe `<owner/repo>` is my own codebase — want me to proceed?" Wait for a yes before opening a PR against yourself.
- You need **write access** to that repo (see `list_repos`). If it shows `[no App access]`, tell the person the GitHub App needs Contents + Pull-requests write there — you can't open the PR until then.

## Doing the work
- Use **`start_build`** with the confirmed `owner/repo` (plus what to change). This runs the normal flow: it inspects the repo, drafts a concrete plan, posts it for **Approve/Dismiss**, and on approval opens a **draft PR**.
- You are proposing a change to your own source via a draft PR that a human reviews and merges — you are **not** live-editing the running instance. Be clear about that if asked.
- Keep the scope tight and safe; this is your own codebase.
