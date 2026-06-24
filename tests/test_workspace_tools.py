import os

from agno.tools.coding import CodingTools
from agno.tools.python import PythonTools

from bott.skills import workspace_tools


def test_ensure_workspace_creates_dir(tmp_path, monkeypatch):
    monkeypatch.setenv("BOTT_WORKSPACE_DIR", str(tmp_path / "ws"))
    d = workspace_tools.ensure_workspace()
    assert os.path.isdir(d)


def test_build_returns_hands(monkeypatch, tmp_path):
    monkeypatch.setenv("BOTT_WORKSPACE_DIR", str(tmp_path / "ws"))
    tools = workspace_tools.build_workspace_tools()
    types = {type(t) for t in tools}
    assert CodingTools in types
    assert PythonTools in types


def test_no_user_control_flow_tool(monkeypatch, tmp_path):
    monkeypatch.setenv("BOTT_WORKSPACE_DIR", str(tmp_path / "ws"))
    from agno.tools.user_control_flow import UserControlFlowTools
    from bott.skills import workspace_tools
    tools = workspace_tools.build_workspace_tools()
    assert not any(isinstance(t, UserControlFlowTools) for t in tools)
