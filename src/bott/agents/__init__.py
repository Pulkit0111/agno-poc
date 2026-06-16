"""Specialist agents the manager delegates to. Each is self-contained and exposes a
`build_*` factory that returns an Agno Agent (a Team member) plus any direct-trigger
surfaces (CLI, webhook) it owns.
"""
