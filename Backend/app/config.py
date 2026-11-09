from __future__ import annotations

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # Agent brain — defaults to Groq (free, no card required) via its
    # OpenAI-compatible endpoint. Override in .env for a paid provider.
    llm_provider: str = "openai_compatible"
    llm_model: str = "llama-3.3-70b-versatile"
    llm_api_key: str = ""
    llm_base_url: str | None = "https://api.groq.com/openai/v1"

    # Long-term memory
    memory_embeddings_provider: str = "local"  # "local" (free, no key) | "openai" (needs OPENAI_API_KEY)
    memory_embeddings_model: str = "sentence-transformers/all-MiniLM-L6-v2"
    openai_api_key: str = ""

    # Nylas
    nylas_api_key: str = ""
    nylas_grant_id: str = ""
    nylas_api_uri: str = "https://api.us.nylas.com"

    # Safety limits
    agent_max_steps: int = 15
    agent_tool_timeout_seconds: int = 30

    # Backend
    database_path: str = "../data/agent.db"
    cors_origins: str = "http://localhost:5173"
    python_executable: str = "python"


@lru_cache
def get_settings() -> Settings:
    return Settings()
