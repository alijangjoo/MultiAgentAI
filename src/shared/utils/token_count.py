"""Estimate input token count for LLM prompts."""

from functools import lru_cache


@lru_cache(maxsize=1)
def _encoding():
    import tiktoken

    return tiktoken.get_encoding("cl100k_base")


def count_text_tokens(text: str) -> int:
    if not text:
        return 0
    return len(_encoding().encode(text))
