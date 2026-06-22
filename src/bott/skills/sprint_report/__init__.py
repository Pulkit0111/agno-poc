"""Sprint-report skill: live Jira sprint data -> a designed, self-contained HTML page
published to Spin (or posted to Slack as a fallback).

Layers:
  - template.py : the HTML+CSS chrome (code-owned design; the agent never writes HTML)
  - render.py   : pure metrics + HTML rendering (unit-tested, no I/O)
  - tool.py     : agent tools (build the dossier, then publish the report)

The deterministic data (metrics, the delivered-stories table, the next-sprint grid)
comes straight from Jira; the agent supplies only the *narrative* (highlights, risks,
client actions), which the renderer escapes and slots into the fixed template.
"""

from bott.skills.sprint_report.tool import sprint_report_tools

__all__ = ["sprint_report_tools"]
