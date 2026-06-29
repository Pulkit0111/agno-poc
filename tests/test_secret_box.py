import pytest

from bott.shared.secrets import SecretBox, generate_key


def test_round_trip():
    box = SecretBox(generate_key())
    token = box.encrypt("hunter2")
    assert token != "hunter2"  # ciphertext at rest
    assert box.decrypt(token) == "hunter2"


def test_wrong_key_cannot_decrypt():
    token = SecretBox(generate_key()).encrypt("secret")
    with pytest.raises(Exception):
        SecretBox(generate_key()).decrypt(token)


def test_from_env_requires_key(monkeypatch):
    monkeypatch.delenv("BOTT_SECRET_KEY", raising=False)
    with pytest.raises(RuntimeError):
        SecretBox.from_env()
