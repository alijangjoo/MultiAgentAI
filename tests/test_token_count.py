from shared.utils.token_count import count_text_tokens


def test_count_text_tokens_empty():
    assert count_text_tokens("") == 0


def test_count_text_tokens_increases_with_text():
    short = count_text_tokens("hello")
    long = count_text_tokens("hello world " * 50)
    assert short > 0
    assert long > short
