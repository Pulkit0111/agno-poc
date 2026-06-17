from bott.manager.manager import build_manager


def test_build_manager_has_id_and_member():
    team = build_manager()  # db=None is fine for a construction smoke test
    assert team.id == "bott-manager"
    assert any(getattr(m, "id", None) == "code-review" for m in team.members)
