"""LLM provider factory.

The agent's "brain" is any LangChain chat model. Swapping providers is a
config change (`LLM_PROVIDER` in .env), never a code change — this is the
only place that reads that setting.
"""
from __future__ import annotations

from app.config import Settings


def build_llm(settings: Settings):
    provider = settings.llm_provider.lower()

    if provider == "anthropic":
        from langchain_anthropic import ChatAnthropic

        return ChatAnthropic(model=settings.llm_model, api_key=settings.llm_api_key, temperature=0)

    if provider == "openai":
        from langchain_openai import ChatOpenAI

        return ChatOpenAI(model=settings.llm_model, api_key=settings.llm_api_key, temperature=0)

    if provider == "openai_compatible":
        # Mistral, Grok/xAI, Groq, Together, local vLLM, etc. — anything that
        # speaks the OpenAI chat-completions API shape at a custom base_url.
        from langchain_openai import ChatOpenAI

        if not settings.llm_base_url:
            raise ValueError("LLM_BASE_URL is required when LLM_PROVIDER=openai_compatible")
        return ChatOpenAI(
            model=settings.llm_model,
            api_key=settings.llm_api_key,
            base_url=settings.llm_base_url,
            temperature=0,
        )

    raise ValueError(f"Unknown LLM_PROVIDER: {settings.llm_provider!r}")
