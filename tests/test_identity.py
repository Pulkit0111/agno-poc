import pytest

from bott.shared.identity import IsolationError, require_user_id


def test_returns_valid_user_id():
    assert require_user_id("alice@axelerant.com") == "alice@axelerant.com"


@pytest.mark.parametrize("bad", [None, "", "   "])
def test_rejects_missing_user_id(bad):
    with pytest.raises(IsolationError):
        require_user_id(bad)
