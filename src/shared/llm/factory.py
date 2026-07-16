from langchain_core.language_models import BaseChatModel
from langchain_openai import ChatOpenAI

from core.config import get_settings


def _chat_openai(model: str, temperature: float) -> BaseChatModel:
    settings = get_settings()
    return ChatOpenAI(
        model=model,
        api_key=settings.llm_api_key or "mock-key",
        base_url=settings.llm_base_url,
        temperature=temperature,
    )


def _chat_anthropic(model: str, temperature: float) -> BaseChatModel:
    settings = get_settings()
    try:
        from langchain_anthropic import ChatAnthropic
    except ImportError as exc:
        raise RuntimeError(
            "Install langchain-anthropic for LLM_PROVIDER=anthropic"
        ) from exc
    return ChatAnthropic(
        model=model,
        api_key=settings.anthropic_api_key or settings.llm_api_key,
        temperature=temperature,
    )


def create_llm(model: str | None = None, temperature: float = 0.1) -> BaseChatModel:
    settings = get_settings()
    resolved = model or settings.llm_model
    if settings.llm_provider.lower() == "anthropic":
        return _chat_anthropic(resolved, temperature)
    return _chat_openai(resolved, temperature)


def create_coding_llm() -> BaseChatModel:
    settings = get_settings()
    return create_coding_llm_for_provider(settings.forge_executor)


def create_code_review_llm() -> BaseChatModel:
    settings = get_settings()
    return create_code_review_llm_for_provider(settings.sentinel_executor)


def create_coding_llm_for_provider(provider: str) -> BaseChatModel:
    settings = get_settings()
    if provider == "claude":
        return _chat_anthropic(settings.coding_model, 0.2)
    return _chat_openai(settings.coding_model, 0.2)


def create_code_review_llm_for_provider(provider: str) -> BaseChatModel:
    settings = get_settings()
    if provider == "claude":
        return _chat_anthropic(settings.code_review_model, 0.0)
    return _chat_openai(settings.code_review_model, 0.0)


def create_pm_llm() -> BaseChatModel:
    settings = get_settings()
    return create_llm(model=settings.pm_model, temperature=0.3)
