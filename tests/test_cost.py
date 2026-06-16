from pr_reviewer.config import calculate_cost


def test_gpt4o_mini_cost():
    # 1M input + 1M output at $0.15 / $0.60 per 1M.
    c = calculate_cost("gpt-4o-mini", 1_000_000, 1_000_000)
    assert abs(c - (0.15 + 0.60)) < 1e-9


def test_cached_input_discounted():
    # 1M input of which 1M is cached-read -> billed at cached rate, no output.
    c = calculate_cost("gpt-4o-mini", 1_000_000, 0, cache_read_tokens=1_000_000)
    assert abs(c - 0.075) < 1e-9


def test_unknown_model_returns_none():
    assert calculate_cost("some-unknown-model", 100, 100) is None
