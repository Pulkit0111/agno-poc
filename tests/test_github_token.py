"""github_token() resolves a token from env vars, falling back to the local `gh` CLI."""

from bott.shared import config


def _clear_env(monkeypatch):
    monkeypatch.delenv("GITHUB_TOKEN", raising=False)
    monkeypatch.delenv("BOTT_POC_GITHUB_TOKEN", raising=False)


def test_env_var_takes_precedence_over_gh(monkeypatch):
    monkeypatch.setenv("GITHUB_TOKEN", "env-tok")
    # gh must NOT be consulted when an env var is present.
    monkeypatch.setattr(config, "_gh_cli_token", lambda: (_ for _ in ()).throw(AssertionError("gh consulted")))
    assert config.github_token() == "env-tok"


def test_poc_env_var_also_works(monkeypatch):
    _clear_env(monkeypatch)
    monkeypatch.setenv("BOTT_POC_GITHUB_TOKEN", "poc-tok")
    assert config.github_token() == "poc-tok"


def test_falls_back_to_gh_cli_token(monkeypatch):
    _clear_env(monkeypatch)
    monkeypatch.setattr(config, "_gh_cli_token", lambda: "gh-tok")
    assert config.github_token() == "gh-tok"


def test_none_when_no_env_and_no_gh(monkeypatch):
    _clear_env(monkeypatch)
    monkeypatch.setattr(config, "_gh_cli_token", lambda: None)
    assert config.github_token() is None


def test_gh_cli_token_returns_none_when_gh_absent(monkeypatch):
    # Reset the process cache and simulate gh not installed.
    monkeypatch.setattr(config, "_gh_cli_token_cache", config._GH_CLI_TOKEN_SENTINEL)
    monkeypatch.setattr(config.shutil, "which", lambda _name: None)
    assert config._gh_cli_token() is None
