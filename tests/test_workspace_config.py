import os

from bott.shared import config


def test_skills_dir_default_points_into_repo():
    d = config.bott_skills_dir()
    assert d.endswith(os.path.join("bott", "skills", "library"))


def test_workspace_dir_default_is_local_runtime_dir():
    assert config.bott_workspace_dir().endswith(".bott_workspace")


def test_shell_allowlist_has_safe_readonly_commands():
    cmds = config.bott_shell_allowed_commands()
    assert "ls" in cmds and "cat" in cmds and "rm" not in cmds


def test_env_overrides(monkeypatch):
    monkeypatch.setenv("BOTT_WORKSPACE_DIR", "/tmp/ws")
    monkeypatch.setenv("BOTT_SHELL_ALLOWED_COMMANDS", "ls,echo")
    assert config.bott_workspace_dir() == "/tmp/ws"
    assert config.bott_shell_allowed_commands() == ["ls", "echo"]
