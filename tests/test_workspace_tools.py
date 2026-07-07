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
    # isinstance, not exact type: the coding tool is bott's hardened CodingTools subclass
    # (workspace_tools._HardenedCodingTools), not the vendored class directly.
    assert any(isinstance(t, CodingTools) for t in tools)
    assert any(isinstance(t, PythonTools) for t in tools)


def test_shell_command_rejects_embedded_newline(monkeypatch, tmp_path):
    """Regression: a newline used to let a second, non-allowlisted command ride along
    with an allowlisted one, because shlex.split() treats '\\n' like whitespace (so only
    the allowlisted first token was ever checked) while `subprocess.run(..., shell=True)`
    treats '\\n' as a real statement separator, same as ';'."""
    monkeypatch.setenv("BOTT_WORKSPACE_DIR", str(tmp_path / "ws"))
    tools = workspace_tools.build_workspace_tools()
    coding = next(t for t in tools if isinstance(t, CodingTools))
    result = coding.run_shell("echo hi\nrm -rf /")
    assert "not allowed" in result.lower()


def test_shell_command_still_allows_plain_allowlisted_command(monkeypatch, tmp_path):
    monkeypatch.setenv("BOTT_WORKSPACE_DIR", str(tmp_path / "ws"))
    tools = workspace_tools.build_workspace_tools()
    coding = next(t for t in tools if isinstance(t, CodingTools))
    result = coding.run_shell("echo hi")
    assert "Error" not in result.splitlines()[0]


def test_no_user_control_flow_tool(monkeypatch, tmp_path):
    monkeypatch.setenv("BOTT_WORKSPACE_DIR", str(tmp_path / "ws"))
    from agno.tools.user_control_flow import UserControlFlowTools

    from bott.skills import workspace_tools
    tools = workspace_tools.build_workspace_tools()
    assert not any(isinstance(t, UserControlFlowTools) for t in tools)


def test_no_duplicate_file_tool_names(monkeypatch, tmp_path):
    monkeypatch.setenv("BOTT_WORKSPACE_DIR", str(tmp_path / "ws"))
    from bott.skills import workspace_tools
    names = []
    for t in workspace_tools.build_workspace_tools():
        fns = getattr(t, "functions", None)
        names += list(fns.keys()) if fns else [getattr(t, "name", "")]
    assert names.count("read_file") <= 1, f"duplicate read_file: {names}"
