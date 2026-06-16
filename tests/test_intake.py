from pr_reviewer.intake import extract_pr_ref


def test_extract_url():
    assert extract_pr_ref("look at https://github.com/o/r/pull/42 please") == ("o", "r", 42)


def test_extract_slug():
    assert extract_pr_ref("review o/r#7") == ("o", "r", 7)


def test_extract_none():
    assert extract_pr_ref("hey what do you do?") is None


def test_extract_url_with_slack_angle_brackets():
    # Slack wraps URLs as <url>
    assert extract_pr_ref("<https://github.com/foo/bar/pull/9>") == ("foo", "bar", 9)
