import pytest

from bott.shared.sandbox import SandboxResult, UnavailableSandbox


def test_result_shape():
    r = SandboxResult(ok=True, stdout="hi", stderr="")
    assert r.ok and r.stdout == "hi"


def test_unavailable_sandbox_raises_clearly():
    with pytest.raises(NotImplementedError) as e:
        UnavailableSandbox().run("print(1)", user_id="u", timeout=5)
    assert "sandbox" in str(e.value).lower()
