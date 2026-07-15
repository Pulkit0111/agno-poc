from bott.shared import config


def test_codex_cli_enabled_defaults_on(monkeypatch):
    """codex exec is the only execution path now — the legacy flag defaults on."""
    monkeypatch.delenv("CODEX_CLI_EXEC", raising=False)
    assert config.codex_cli_enabled() is True


def test_codex_cli_enabled_true_values(monkeypatch):
    for v in ("1", "true", "YES"):
        monkeypatch.setenv("CODEX_CLI_EXEC", v)
        assert config.codex_cli_enabled() is True


def test_codex_cli_binary_default(monkeypatch):
    monkeypatch.delenv("CODEX_CLI_BIN", raising=False)
    assert config.codex_cli_binary() == "codex"


def test_codex_cli_timeout_default(monkeypatch):
    monkeypatch.delenv("CODEX_CLI_TIMEOUT_S", raising=False)
    assert config.codex_cli_timeout_s() == 900


def test_codex_cli_disable_sandbox_defaults_off(monkeypatch):
    monkeypatch.delenv("BOTT_CODEX_DISABLE_SANDBOX", raising=False)
    assert config.codex_cli_disable_sandbox() is False


def test_codex_cli_disable_sandbox_true_values(monkeypatch):
    for v in ("1", "true", "yes"):
        monkeypatch.setenv("BOTT_CODEX_DISABLE_SANDBOX", v)
        assert config.codex_cli_disable_sandbox() is True
