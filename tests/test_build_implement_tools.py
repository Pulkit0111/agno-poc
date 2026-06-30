from bott.agents.build_fix.agent.tools import build_implement_tools


def test_tools_fenced_to_clone_path(tmp_path):
    tools = build_implement_tools(str(tmp_path))
    assert tools  # non-empty
    # The first tool is a CodingTools instance fenced to the clone dir.
    coding = tools[0]
    assert str(tmp_path) in str(getattr(coding, "base_dir", ""))
