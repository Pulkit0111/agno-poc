"""Per-user isolation of the shared agent's workspace file/shell tools.

Background: build_workspace_tools() used to construct ONE CodingTools/PythonTools pair for
the single shared agent that serves every Slack user in the org, all pointed at the same
base_dir — any user's file/code activity could surface in another user's conversation. This
tests that scope_workspace_to_user (wired in as an agent-wide tool_hook) redirects each
user to their own subdirectory for the duration of their tool call, and that calls made with
no resolvable user (tests, background jobs) keep using the shared default directory.
"""

from types import SimpleNamespace

from agno.tools.coding import CodingTools

from bott.skills import workspace_tools


def _run_context(user_id):
    return SimpleNamespace(user_id=user_id)


def test_two_users_get_separate_directories(monkeypatch, tmp_path):
    monkeypatch.setenv("BOTT_WORKSPACE_DIR", str(tmp_path / "ws"))
    tools = workspace_tools.build_workspace_tools()
    coding = next(t for t in tools if isinstance(t, CodingTools))

    def write_as(user_id, contents):
        return workspace_tools.scope_workspace_to_user(
            run_context=_run_context(user_id),
            function_call=coding.write_file,
            args={"file_path": "secret.txt", "contents": contents},
        )

    write_as("U_ALICE", "alice's data")
    write_as("U_BOB", "bob's data")

    def read_as(user_id):
        return workspace_tools.scope_workspace_to_user(
            run_context=_run_context(user_id),
            function_call=coding.read_file,
            args={"file_path": "secret.txt"},
        )

    assert "alice's data" in read_as("U_ALICE")
    assert "bob's data" in read_as("U_BOB")
    # Bob's read must not see Alice's file — proves they landed in different directories,
    # not the same shared one.
    assert "alice's data" not in read_as("U_BOB")


def test_falls_back_to_shared_dir_when_no_user_id(monkeypatch, tmp_path):
    """Calls made outside a resolvable user turn (tests, scripts, background jobs) must
    keep working exactly as before — same shared directory, no crash."""
    monkeypatch.setenv("BOTT_WORKSPACE_DIR", str(tmp_path / "ws"))
    tools = workspace_tools.build_workspace_tools()
    coding = next(t for t in tools if isinstance(t, CodingTools))

    result = workspace_tools.scope_workspace_to_user(
        run_context=None,
        function_call=coding.write_file,
        args={"file_path": "shared.txt", "contents": "shared"},
    )
    assert "Error" not in result.splitlines()[0]
    assert coding.read_file("shared.txt") is not None


def test_user_directory_name_is_sanitized(tmp_path, monkeypatch):
    monkeypatch.setenv("BOTT_WORKSPACE_DIR", str(tmp_path / "ws"))
    path = workspace_tools._user_workspace_dir("../../etc/passwd")
    # Must resolve to a real subdirectory under the workspace root, not escape it.
    assert str(path).startswith(str((tmp_path / "ws").resolve()))
    assert ".." not in path.parts
