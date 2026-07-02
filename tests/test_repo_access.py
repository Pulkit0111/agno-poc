"""Tests for bott.skills.repo_access and the GitHubClient read methods."""

from __future__ import annotations

import base64
from types import SimpleNamespace
from unittest.mock import MagicMock

import httpx
import pytest

import bott.skills.repo_access as ra
from bott.agents.code_review.github.client import GitHubClient


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _b64(text: str) -> str:
    """Return base64-encoded text (as GitHub's API sends it)."""
    return base64.b64encode(text.encode()).decode()


# ---------------------------------------------------------------------------
# GitHubClient.get_readme
# ---------------------------------------------------------------------------

class TestGetReadme:
    def test_decodes_base64_content(self, monkeypatch):
        client = GitHubClient(token="tok")
        monkeypatch.setattr(
            client, "_get",
            lambda path, params=None: {"content": _b64("# Hello\nWorld")},
        )
        assert client.get_readme("o", "r") == "# Hello\nWorld"

    def test_returns_empty_on_404(self, monkeypatch):
        client = GitHubClient(token="tok")

        def _raise(path, params=None):
            raise httpx.HTTPStatusError("404", request=MagicMock(), response=MagicMock(status_code=404))

        monkeypatch.setattr(client, "_get", _raise)
        assert client.get_readme("o", "r") == ""

    def test_returns_empty_when_no_content_key(self, monkeypatch):
        client = GitHubClient(token="tok")
        monkeypatch.setattr(client, "_get", lambda path, params=None: {})
        assert client.get_readme("o", "r") == ""


# ---------------------------------------------------------------------------
# GitHubClient.get_tree
# ---------------------------------------------------------------------------

class TestGetTree:
    def _make_client(self, monkeypatch, tree_entries, *, default_branch="main"):
        client = GitHubClient(token="tok")
        calls = []

        def _get(path, params=None):
            calls.append(path)
            if path.endswith(f"/{default_branch}"):
                return {"tree": tree_entries}
            # default_branch() call
            return {"default_branch": default_branch}

        monkeypatch.setattr(client, "_get", _get)
        return client

    def test_returns_blob_paths(self, monkeypatch):
        entries = [
            {"path": "README.md", "type": "blob"},
            {"path": "src", "type": "tree"},
            {"path": "src/foo.py", "type": "blob"},
        ]
        client = self._make_client(monkeypatch, entries)
        paths = client.get_tree("o", "r")
        assert "README.md" in paths
        assert "src/foo.py" in paths
        assert "src" not in paths  # trees excluded

    def test_respects_max_entries(self, monkeypatch):
        entries = [{"path": f"file{i}.py", "type": "blob"} for i in range(300)]
        client = self._make_client(monkeypatch, entries)
        paths = client.get_tree("o", "r", max_entries=50)
        assert len(paths) == 50

    def test_returns_empty_on_error(self, monkeypatch):
        client = GitHubClient(token="tok")

        def _raise(path, params=None):
            raise RuntimeError("network error")

        monkeypatch.setattr(client, "_get", _raise)
        assert client.get_tree("o", "r") == []


# ---------------------------------------------------------------------------
# GitHubClient.get_file
# ---------------------------------------------------------------------------

class TestGetFile:
    def test_decodes_base64_content(self, monkeypatch):
        client = GitHubClient(token="tok")
        monkeypatch.setattr(
            client, "_get",
            lambda path, params=None: {"content": _b64("print('hello')\n")},
        )
        assert client.get_file("o", "r", "src/main.py") == "print('hello')\n"

    def test_returns_empty_on_404(self, monkeypatch):
        client = GitHubClient(token="tok")

        def _raise(path, params=None):
            raise httpx.HTTPStatusError("404", request=MagicMock(), response=MagicMock(status_code=404))

        monkeypatch.setattr(client, "_get", _raise)
        assert client.get_file("o", "r", "nonexistent.py") == ""

    def test_returns_empty_when_no_content_key(self, monkeypatch):
        client = GitHubClient(token="tok")
        monkeypatch.setattr(client, "_get", lambda path, params=None: {})
        assert client.get_file("o", "r", "empty.py") == ""


# ---------------------------------------------------------------------------
# repo_access.list_repos
# ---------------------------------------------------------------------------

class TestListRepos:
    def test_empty_allowlist_returns_friendly_message(self, monkeypatch):
        monkeypatch.setattr(ra.config, "allowed_post_repos", lambda: set())
        out = ra.list_repos()
        assert "allowlist" in out.lower()
        assert "ALLOWED_POST_REPOS" in out

    def test_write_access_annotated_when_token_returned(self, monkeypatch):
        monkeypatch.setattr(ra.config, "allowed_post_repos", lambda: {"owner/repo"})
        monkeypatch.setattr(ra, "app_token_for", lambda owner, name: "ghs_faketoken")
        out = ra.list_repos()
        assert "owner/repo" in out
        assert "write" in out.lower()

    def test_no_access_annotated_when_token_none(self, monkeypatch):
        monkeypatch.setattr(ra.config, "allowed_post_repos", lambda: {"owner/repo"})
        monkeypatch.setattr(ra, "app_token_for", lambda owner, name: None)
        out = ra.list_repos()
        assert "owner/repo" in out
        assert "no App access" in out

    def test_multiple_repos_all_listed(self, monkeypatch):
        monkeypatch.setattr(
            ra.config, "allowed_post_repos",
            lambda: {"org/alpha", "org/beta"},
        )
        monkeypatch.setattr(ra, "app_token_for", lambda owner, name: "tok" if name == "alpha" else None)
        out = ra.list_repos()
        assert "org/alpha" in out
        assert "org/beta" in out
        # alpha has write; beta has no access
        assert "write" in out.lower()
        assert "no App access" in out


# ---------------------------------------------------------------------------
# repo_access.inspect_repo
# ---------------------------------------------------------------------------

def _stub_client(monkeypatch, *, readme="# Readme", tree=None):
    """Return a fake GitHubClient class that returns preset data."""
    if tree is None:
        tree = ["README.md", "src/main.py", "tests/test_main.py"]

    class _FakeClient:
        def __init__(self, token=None, **kwargs):
            pass

        def get_readme(self, owner, name):
            return readme

        def get_tree(self, owner, name, max_entries=200):
            return tree[:max_entries]

    monkeypatch.setattr(ra, "GitHubClient", _FakeClient)


class TestInspectRepo:
    def test_returns_readme_and_tree_when_token_available(self, monkeypatch):
        monkeypatch.setattr(ra, "app_token_for", lambda owner, name: "ghs_faketoken")
        _stub_client(monkeypatch, readme="# My Project\nGreat stuff.")
        out = ra.inspect_repo("owner/repo")
        assert "owner/repo" in out
        assert "My Project" in out
        assert "README.md" in out

    def test_no_app_access_message_when_token_none(self, monkeypatch):
        monkeypatch.setattr(ra, "app_token_for", lambda owner, name: None)
        out = ra.inspect_repo("owner/repo")
        assert "don't have GitHub App access" in out
        assert "owner/repo" in out

    def test_parses_github_url_form(self, monkeypatch):
        monkeypatch.setattr(ra, "app_token_for", lambda owner, name: "ghs_faketoken")
        _stub_client(monkeypatch)
        out = ra.inspect_repo("https://github.com/myorg/myrepo")
        assert "myorg/myrepo" in out

    def test_parses_owner_slash_repo_form(self, monkeypatch):
        monkeypatch.setattr(ra, "app_token_for", lambda owner, name: "ghs_faketoken")
        _stub_client(monkeypatch)
        out = ra.inspect_repo("myorg/myrepo")
        assert "myorg/myrepo" in out

    def test_invalid_repo_ref_returns_friendly_message(self, monkeypatch):
        out = ra.inspect_repo("not-a-repo-ref!")
        assert "couldn't parse" in out.lower()

    def test_exception_during_client_returns_friendly_message(self, monkeypatch):
        monkeypatch.setattr(ra, "app_token_for", lambda owner, name: "ghs_faketoken")

        class _BrokenClient:
            def __init__(self, token=None, **kwargs):
                raise RuntimeError("network down")

        monkeypatch.setattr(ra, "GitHubClient", _BrokenClient)
        out = ra.inspect_repo("owner/repo")
        assert "couldn't read" in out.lower()

    def test_readme_truncated_at_1500_chars(self, monkeypatch):
        monkeypatch.setattr(ra, "app_token_for", lambda owner, name: "ghs_faketoken")
        long_readme = "A" * 2000
        _stub_client(monkeypatch, readme=long_readme)
        out = ra.inspect_repo("owner/repo")
        assert "truncated" in out.lower()


# ---------------------------------------------------------------------------
# repo_access_tools() factory + agent wiring
# ---------------------------------------------------------------------------

def test_repo_access_tools_returns_both_callables():
    tools = ra.repo_access_tools()
    names = {t.__name__ for t in tools}
    assert "list_repos" in names
    assert "inspect_repo" in names


def test_build_agent_includes_repo_tools():
    from bott.agents.bott_agent import build_agent

    agent = build_agent("alice@axelerant.com", db=None)
    # Collect tool names (handle both plain functions and Tool objects)
    tool_names = set()
    for t in agent.tools:
        tool_names.add(getattr(t, "__name__", None) or getattr(t, "name", None) or "")
    assert "list_repos" in tool_names, f"list_repos not in agent tools: {tool_names}"
    assert "inspect_repo" in tool_names, f"inspect_repo not in agent tools: {tool_names}"
