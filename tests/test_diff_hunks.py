from pr_reviewer.agent.diff_hunks import anchorable_lines, is_anchor_in_diff

PATCH = "@@ -1,3 +1,4 @@\n ctx1\n+added2\n+added3\n-removed\n ctx4"


def test_anchorable_lines():
    # new side: ctx1=1, added2=2, added3=3, (removed has no new line), ctx4=4
    assert anchorable_lines(PATCH) == {1, 2, 3, 4}


def test_empty_patch():
    assert anchorable_lines(None) == set()
    assert anchorable_lines("") == set()


def test_is_anchor_in_diff():
    patches = {"a.py": PATCH}
    assert is_anchor_in_diff(patches, "a.py", 2) is True
    assert is_anchor_in_diff(patches, "a.py", 99) is False
    assert is_anchor_in_diff(patches, "missing.py", 1) is False
