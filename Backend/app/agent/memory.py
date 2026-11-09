"""Long-term memory for the agent, via langmem + a LangGraph store.

This gives the agent two extra tools — one to save/update/delete memories,
one to semantically search them — bound directly alongside the MCP tools.
Memory is a first-class LangGraph capability here, not something bolted on
as a fake "memory MCP server"; langmem already does this properly.

Two embeddings backends, picked by MEMORY_EMBEDDINGS_PROVIDER:

- "local" (the default): sentence-transformers running on-device. Free, no
  API key, no per-call cost — the trade-off is a one-time model download
  (~90MB for the default MiniLM model) and using some local CPU/RAM per
  embedding call.
- "openai": OpenAI's embeddings API. Needs OPENAI_API_KEY and costs money
  per call, but avoids the local model download/compute.

Either way, memory degrades gracefully instead of crashing the app: if the
configured provider can't be set up (missing key, missing package, etc.),
`build_memory` logs a warning and returns no tools — everything else still
works, just without persistent recall.
"""
from __future__ import annotations

import logging

from app.config import Settings

logger = logging.getLogger(__name__)

MEMORY_NAMESPACE = ("agent_memories",)

# Embedding dimensionality per known model, so InMemoryStore's index is sized
# correctly regardless of which provider/model the user picks.
_KNOWN_DIMS = {
    "sentence-transformers/all-MiniLM-L6-v2": 384,
    "text-embedding-3-small": 1536,
    "text-embedding-3-large": 3072,
}


def _build_embeddings(settings: Settings):
    provider = settings.memory_embeddings_provider.lower()

    if provider == "local":
        from langchain_huggingface import HuggingFaceEmbeddings

        return HuggingFaceEmbeddings(model_name=settings.memory_embeddings_model)

    if provider == "openai":
        if not settings.openai_api_key:
            raise ValueError("MEMORY_EMBEDDINGS_PROVIDER=openai requires OPENAI_API_KEY.")
        from langchain_openai import OpenAIEmbeddings

        return OpenAIEmbeddings(model=settings.memory_embeddings_model, api_key=settings.openai_api_key)

    raise ValueError(f"Unknown MEMORY_EMBEDDINGS_PROVIDER: {settings.memory_embeddings_provider!r}")


def build_memory(settings: Settings):
    """Returns (store, tools). `store` is None and `tools` is [] when disabled."""
    try:
        embeddings = _build_embeddings(settings)
    except Exception as exc:  # noqa: BLE001
        logger.warning("Long-term memory (langmem) disabled: %s", exc)
        return None, []

    from langgraph.store.memory import InMemoryStore
    from langmem import create_manage_memory_tool, create_search_memory_tool

    dims = _KNOWN_DIMS.get(settings.memory_embeddings_model, 384)
    store = InMemoryStore(index={"dims": dims, "embed": embeddings})
    tools = [
        create_manage_memory_tool(namespace=MEMORY_NAMESPACE, store=store),
        create_search_memory_tool(namespace=MEMORY_NAMESPACE, store=store),
    ]
    return store, tools
