"""The HTML + CSS chrome for the sprint report — the code-owned design system, lifted
from the approved reference report so output matches it. Nothing here is model-authored;
render.py fills the slots with escaped data."""

from __future__ import annotations

# Verbatim from the reference report so the published page matches the approved design.
CSS = """
  :root {
    --ax-orange: #FF5C00;
    --ax-navy: #0D1B2A;
    --ax-navy-dark: #111827;
    --ax-white: #FFFFFF;
    --ax-off-white: #F5F5F5;
    --ax-slate: #4B5563;
    --ax-teal: #0D9488;
    --ax-yellow: #F5C518;
    --ax-cobalt: #1E3A8A;
    --ax-font-heading: 'Inter', sans-serif;
    --ax-font-display: 'Space Grotesk', sans-serif;
    --ax-radius: 8px;
    --ax-radius-lg: 16px;
  }
  *, *::before, *::after { box-sizing: border-box; margin: 0; padding: 0; }
  body { font-family: var(--ax-font-heading); background: var(--ax-off-white); color: var(--ax-navy); line-height: 1.6; }
  .header { background: var(--ax-navy); padding: 0; position: relative; overflow: hidden; }
  .header-inner { max-width: 900px; margin: 0 auto; padding: 48px 40px 56px; position: relative; z-index: 2; }
  .header-top { display: flex; align-items: center; justify-content: space-between; margin-bottom: 40px; }
  .logo { font-family: var(--ax-font-display); font-size: 20px; font-weight: 700; color: var(--ax-orange); letter-spacing: -0.3px; }
  .sprint-badge { background: var(--ax-orange); color: white; font-size: 12px; font-weight: 700; padding: 5px 14px; border-radius: 20px; letter-spacing: 0.5px; text-transform: uppercase; }
  .header h1 { font-family: var(--ax-font-display); font-size: 42px; font-weight: 700; color: var(--ax-white); line-height: 1.15; margin-bottom: 12px; letter-spacing: -0.5px; }
  .header h1 span { color: var(--ax-orange); }
  .header-meta { color: rgba(255,255,255,0.55); font-size: 14px; font-weight: 500; margin-bottom: 36px; }
  .header-stats { display: flex; gap: 16px; flex-wrap: nowrap; }
  .stat-card { background: rgba(255,255,255,0.07); border: 1px solid rgba(255,255,255,0.1); border-radius: var(--ax-radius); padding: 16px 20px; flex: 1; }
  .stat-card .num { font-family: var(--ax-font-display); font-size: 32px; font-weight: 700; color: var(--ax-orange); line-height: 1; margin-bottom: 4px; }
  .stat-card .label { font-size: 12px; color: rgba(255,255,255,0.5); font-weight: 500; text-transform: uppercase; letter-spacing: 0.5px; }
  .curve-divider { display: block; width: 100%; margin-top: -2px; }
  .main { max-width: 900px; margin: 0 auto; padding: 0 40px 60px; }
  .section { margin-top: 48px; }
  .section-label { display: flex; align-items: center; gap: 10px; margin-bottom: 20px; }
  .section-label .dot { width: 10px; height: 10px; background: var(--ax-orange); border-radius: 50%; flex-shrink: 0; }
  .section-label h2 { font-family: var(--ax-font-display); font-size: 20px; font-weight: 700; color: var(--ax-navy); letter-spacing: -0.2px; }
  .table-wrap { background: white; border-radius: var(--ax-radius-lg); overflow: hidden; border: 1px solid #e5e7eb; box-shadow: 0 1px 4px rgba(0,0,0,0.05); }
  table { width: 100%; border-collapse: collapse; }
  thead { background: var(--ax-navy); }
  thead th { color: white; font-size: 11px; font-weight: 600; text-transform: uppercase; letter-spacing: 0.8px; padding: 12px 18px; text-align: left; }
  tbody tr { border-bottom: 1px solid #f0f0f0; transition: background 0.15s; }
  tbody tr:last-child { border-bottom: none; }
  tbody tr:hover { background: #fafafa; }
  tbody td { padding: 13px 18px; font-size: 14px; color: var(--ax-slate); vertical-align: middle; }
  tbody td:first-child { color: var(--ax-navy); font-weight: 600; width: 44px; text-align: center; }
  .done-badge { display: inline-flex; align-items: center; gap: 5px; background: #ecfdf5; color: #065f46; font-size: 12px; font-weight: 600; padding: 3px 10px; border-radius: 20px; white-space: nowrap; }
  .done-badge::before { content: '✓'; font-weight: 700; }
  .impact-text { font-size: 13px; color: var(--ax-slate); line-height: 1.5; }
  .status-resolved { display: inline-block; background: #ecfdf5; color: #065f46; font-size: 11px; font-weight: 700; padding: 3px 10px; border-radius: 20px; white-space: nowrap; text-transform: uppercase; letter-spacing: 0.4px; }
  .status-monitored { display: inline-block; background: #fffbeb; color: #92400e; font-size: 11px; font-weight: 700; padding: 3px 10px; border-radius: 20px; white-space: nowrap; text-transform: uppercase; letter-spacing: 0.4px; }
  .status-inprogress { display: inline-block; background: #eff6ff; color: #1d4ed8; font-size: 11px; font-weight: 700; padding: 3px 10px; border-radius: 20px; white-space: nowrap; text-transform: uppercase; letter-spacing: 0.4px; }
  .stories-grid { display: grid; grid-template-columns: repeat(2, 1fr); gap: 12px; }
  .story-card { background: white; border: 1px solid #e5e7eb; border-radius: var(--ax-radius); padding: 14px 16px; display: flex; gap: 12px; align-items: flex-start; box-shadow: 0 1px 3px rgba(0,0,0,0.04); }
  .story-num { font-family: var(--ax-font-display); font-size: 13px; font-weight: 700; color: var(--ax-orange); min-width: 24px; padding-top: 1px; }
  .story-title { font-size: 13px; color: var(--ax-navy); font-weight: 500; line-height: 1.4; }
  .story-type-spike { display: inline-block; background: #fdf4ff; color: #7c3aed; font-size: 10px; font-weight: 700; padding: 1px 7px; border-radius: 10px; margin-right: 4px; text-transform: uppercase; letter-spacing: 0.4px; }
  .story-type-poc { display: inline-block; background: #eff6ff; color: #1d4ed8; font-size: 10px; font-weight: 700; padding: 1px 7px; border-radius: 10px; margin-right: 4px; text-transform: uppercase; letter-spacing: 0.4px; }
  .callout { background: #fff7ed; border-left: 4px solid var(--ax-orange); border-radius: 0 var(--ax-radius) var(--ax-radius) 0; padding: 16px 20px; margin-top: 16px; font-size: 13.5px; color: var(--ax-navy); line-height: 1.6; }
  .actions-list { display: flex; flex-direction: column; gap: 12px; }
  .action-card { background: white; border: 1px solid #e5e7eb; border-radius: var(--ax-radius-lg); padding: 18px 20px; display: flex; gap: 16px; align-items: flex-start; box-shadow: 0 1px 3px rgba(0,0,0,0.04); }
  .priority-dot { width: 10px; height: 10px; border-radius: 50%; flex-shrink: 0; margin-top: 5px; }
  .priority-high { background: #ef4444; }
  .priority-medium { background: #f59e0b; }
  .action-title { font-size: 14px; font-weight: 700; color: var(--ax-navy); margin-bottom: 4px; }
  .action-desc { font-size: 13px; color: var(--ax-slate); line-height: 1.5; }
  .action-meta { display: flex; align-items: center; gap: 12px; margin-top: 8px; flex-wrap: wrap; }
  .action-owner { font-size: 12px; font-weight: 600; color: var(--ax-slate); background: var(--ax-off-white); padding: 2px 10px; border-radius: 20px; }
  .priority-tag { font-size: 11px; font-weight: 700; letter-spacing: 0.4px; text-transform: uppercase; padding: 2px 10px; border-radius: 20px; }
  .priority-tag.high { background: #fef2f2; color: #b91c1c; }
  .priority-tag.medium { background: #fffbeb; color: #92400e; }
  .action-link { display: inline-flex; align-items: center; gap: 5px; color: var(--ax-orange); font-size: 12px; font-weight: 600; text-decoration: none; margin-top: 6px; }
  .action-link:hover { text-decoration: underline; }
  .footer { background: var(--ax-navy-dark); padding: 32px 40px; margin-top: 48px; }
  .footer-inner { max-width: 900px; margin: 0 auto; display: flex; justify-content: space-between; align-items: center; flex-wrap: wrap; gap: 16px; }
  .footer-logo { font-family: var(--ax-font-display); font-size: 18px; font-weight: 700; color: var(--ax-orange); }
  .footer-note { font-size: 12px; color: rgba(255,255,255,0.35); text-align: right; }
  .highlights { display: flex; flex-direction: column; gap: 10px; margin-top: 4px; }
  .highlight-item { display: flex; align-items: flex-start; gap: 12px; background: white; border: 1px solid #e5e7eb; border-radius: var(--ax-radius); padding: 12px 16px; font-size: 13.5px; color: var(--ax-slate); line-height: 1.5; }
  .highlight-item::before { content: '→'; color: var(--ax-orange); font-weight: 700; flex-shrink: 0; margin-top: 1px; }
  @media (max-width: 640px) {
    .header-inner { padding: 32px 20px 40px; }
    .header h1 { font-size: 28px; }
    .main { padding: 0 20px 40px; }
    .stories-grid { grid-template-columns: 1fr; }
    .header-stats { gap: 12px; }
    .footer { padding: 24px 20px; }
    .footer-inner { flex-direction: column; align-items: flex-start; }
    .footer-note { text-align: left; }
  }
"""

FONTS_LINK = (
    '<link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800'
    '&family=Space+Grotesk:wght@500;600;700&display=swap" rel="stylesheet">'
)

# The decorative navy curve under the header (matches the reference).
CURVE_DIVIDER = (
    '<svg class="curve-divider" viewBox="0 0 900 40" xmlns="http://www.w3.org/2000/svg" '
    'preserveAspectRatio="none"><path d="M0,0 C300,40 600,0 900,30 L900,0 Z" fill="#0D1B2A"/></svg>'
)


def page(title: str, body: str) -> str:
    """Wrap rendered body sections in the full self-contained HTML document."""
    return (
        "<!DOCTYPE html>\n<html lang=\"en\">\n<head>\n"
        '<meta charset="UTF-8">\n'
        '<meta name="viewport" content="width=device-width, initial-scale=1.0">\n'
        f"<title>{title}</title>\n{FONTS_LINK}\n<style>{CSS}</style>\n"
        "</head>\n<body>\n"
        f"{body}\n"
        "</body>\n</html>\n"
    )
