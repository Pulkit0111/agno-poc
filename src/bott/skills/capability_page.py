"""capability_page tool — publish a hosted "what Bott can do here" page.

Gathers live connectors, skills from the SKILL.md library, accessible repos, and the
active model, then deploys a self-contained HTML summary to Spin and returns the link.
Gated on spin_configured() — returns a friendly message when publishing isn't set up.
"""

from __future__ import annotations

from pathlib import Path
from typing import Callable

from bott.shared import config
from bott.shared.observability.logging_setup import get_logger, redact

log = get_logger("bott.skills.capability_page")


def _read_skill_entries(skills_dir: str) -> list[dict[str, str]]:
    """Walk `skills_dir` and parse name + description from each SKILL.md frontmatter."""
    entries: list[dict[str, str]] = []
    root = Path(skills_dir)
    if not root.is_dir():
        return entries
    for skill_md in sorted(root.glob("*/SKILL.md")):
        try:
            text = skill_md.read_text(encoding="utf-8")
        except OSError:
            continue
        name, description = "", ""
        in_front = False
        for line in text.splitlines():
            stripped = line.strip()
            if stripped == "---":
                if not in_front:
                    in_front = True
                    continue
                else:
                    break  # end of frontmatter
            if in_front:
                if stripped.startswith("name:"):
                    name = stripped[len("name:"):].strip()
                elif stripped.startswith("description:"):
                    description = stripped[len("description:"):].strip()
        if name:
            entries.append({"name": name, "description": description})
    return entries


def _html_escape(s: str) -> str:
    return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _build_body(
    connector_names: dict[str, list[str]],
    skills: list[dict[str, str]],
    repos: set[str],
    model: dict,
) -> str:
    sections: list[str] = []

    # ── Connectors ──────────────────────────────────────────────────────────
    sections.append("<section>")
    sections.append('<h2 class="section-title">Connectors</h2>')

    org_names = connector_names.get("org", [])
    user_names = connector_names.get("user", [])

    if org_names:
        sections.append("<h3>Org-credential (shared, read-only)</h3>")
        sections.append("<ul>")
        for name in org_names:
            sections.append(f"  <li><strong>{_html_escape(name)}</strong></li>")
        sections.append("</ul>")

    if user_names:
        sections.append("<h3>Domain-delegated / read-only</h3>")
        sections.append("<ul>")
        for name in user_names:
            sections.append(f"  <li><strong>{_html_escape(name)}</strong></li>")
        sections.append("</ul>")

    if not org_names and not user_names:
        sections.append("<p><em>No connectors configured.</em></p>")

    sections.append("</section>")

    # ── Skills ───────────────────────────────────────────────────────────────
    sections.append("<section>")
    sections.append('<h2 class="section-title">Skills</h2>')
    if skills:
        sections.append('<ul class="skill-list">')
        for entry in skills:
            name = _html_escape(entry.get("name", ""))
            desc = _html_escape(entry.get("description", ""))
            row = f"  <li><strong>{name}</strong>"
            if desc:
                row += f" — {desc}"
            row += "</li>"
            sections.append(row)
        sections.append("</ul>")
    else:
        sections.append("<p><em>No skills found in the library.</em></p>")
    sections.append("</section>")

    # ── Repos ────────────────────────────────────────────────────────────────
    sections.append("<section>")
    sections.append('<h2 class="section-title">Repos I can build / fix</h2>')
    if repos:
        sections.append("<ul>")
        for repo in sorted(repos):
            sections.append(f"  <li><code>{_html_escape(repo)}</code></li>")
        sections.append("</ul>")
    else:
        sections.append("<p><em>No repos configured (set ALLOWED_POST_REPOS).</em></p>")
    sections.append("</section>")

    # ── Model ────────────────────────────────────────────────────────────────
    sections.append("<section>")
    sections.append('<h2 class="section-title">Model</h2>')
    provider = _html_escape(model.get("provider", "?"))
    chat = _html_escape(model.get("chat", "?"))
    heavy = _html_escape(model.get("heavy", "?"))
    sections.append(
        f"<p>Provider: <code>{provider}</code> &nbsp;·&nbsp; "
        f"Chat: <code>{chat}</code> &nbsp;·&nbsp; "
        f"Heavy: <code>{heavy}</code></p>"
    )
    sections.append("</section>")

    body = "\n".join(sections)
    return f"""<style>
h2.section-title{{font-size:1.1rem;font-weight:600;margin:2rem 0 .5rem;
  border-bottom:2px solid var(--orange,#FF5C00);padding-bottom:4px;color:var(--navy,#0D1B2A)}}
h3{{font-size:.95rem;font-weight:600;margin:1rem 0 .35rem;color:#374151}}
ul{{list-style:disc;padding-left:1.25rem;margin:.25rem 0 .75rem}}
ul.skill-list li{{margin-bottom:.35rem;line-height:1.45}}
code{{background:#f3f4f6;border-radius:3px;padding:1px 5px;font-size:.875rem}}
section{{margin-bottom:1.5rem}}
</style>
<h1 style="font-size:1.5rem;font-weight:700;margin-bottom:.25rem">What Bott can do here</h1>
<p style="color:#374151;margin-bottom:.5rem"><strong>Ask Bott for just about anything — it figures out how.</strong>
It composes the systems below (Slack, GitHub, Jira/Confluence, code, the web, Memra) to attempt
work it has never done before; risky changes always wait for a human Approve.</p>
<p style="color:#6B7280;margin-bottom:1.5rem">Below is a live snapshot of what it can reach and the
workflows it has practiced — <em>examples, not the boundary</em>.</p>
{body}"""


def capability_page() -> str:
    """Generate and publish a hosted "What Bott can do here" capability page.

    Gathers live connectors, skills from the SKILL.md library, accessible repos,
    and the active model, then deploys a self-contained HTML summary to Spin.
    Returns the public link, or a message explaining what's missing.
    """
    if not config.spin_configured():
        return (
            "Publishing isn't configured (set SPIN_API_TOKEN), "
            "so I can't host the capability page."
        )

    # ── Gather data ──────────────────────────────────────────────────────────
    from bott.skills.connectors.register_all import register_all
    from bott.skills.connectors.registry import REGISTRY

    register_all()
    connector_names = REGISTRY.list_names()

    skills_dir = config.bott_skills_dir()
    skills = _read_skill_entries(skills_dir)

    repos = config.allowed_post_repos()

    from bott.interfaces.slack_home.models import _active

    model = _active()

    # ── Build HTML ───────────────────────────────────────────────────────────
    body = _build_body(connector_names, skills, repos, model)

    from bott.skills.web_publish import _brand_wrap, publish_web_page

    full_html = _brand_wrap("What Bott can do here", body)

    # ── Publish ───────────────────────────────────────────────────────────────
    try:
        return publish_web_page(name="bott-capabilities", html=full_html)
    except Exception as e:  # noqa: BLE001
        log.error("capability_page publish failed: %s", redact(str(e)))
        return "Couldn't publish the capability page right now."


def capability_page_tools() -> list[Callable]:
    return [capability_page]
