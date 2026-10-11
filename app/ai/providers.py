"""Provider presets and resolution of the active chat / embedding configuration."""
from dataclasses import dataclass

from app.core.config import settings


@dataclass(frozen=True)
class ChatConfig:
    provider: str
    model: str
    base_url: str | None
    api_key: str
    json_mode: bool


@dataclass(frozen=True)
class EmbedConfig:
    provider: str
    model: str
    base_url: str | None
    api_key: str
    kind: str  # openai (OpenAI-compatible /embeddings) | hf_endpoint | hf_local

    @property
    def model_id(self) -> str:
        """Stored with every vector: vectors from different models are not comparable."""
        return f"{self.provider}:{self.model}"


CHAT_PRESETS = {
    "deepseek": {"base_url": "https://api.deepseek.com", "model": "deepseek-chat", "needs_key": True, "json_mode": True},
    "openai": {"base_url": None, "model": "gpt-4o-mini", "needs_key": True, "json_mode": True},
    "anthropic": {"base_url": None, "model": "claude-sonnet-5-5", "needs_key": True, "json_mode": False},
    "openai_compat": {"base_url": "", "model": "", "needs_key": False, "json_mode": True},
}
EMBED_PRESETS = {
    "jina": {"base_url": "https://api.jina.ai/v1", "model": "jina-embeddings-v3", "needs_key": True, "kind": "openai"},
    "huggingface": {"base_url": None, "model": "BAAI/bge-m3", "needs_key": True, "kind": "hf_endpoint"},
    "openai_compat": {"base_url": "", "model": "", "needs_key": False, "kind": "openai"},
    "local": {"base_url": None, "model": "BAAI/bge-small-en-v1.5", "needs_key": False, "kind": "hf_local"},
}


def chat_config(task: str = "default") -> ChatConfig | None:
    """Active chat configuration for a task, or None when LLM features are not usable (no key / no endpoint)."""
    preset = CHAT_PRESETS.get(settings.llm_provider)
    if preset is None:
        raise ValueError(f"Unknown FINTECH_LLM_PROVIDER '{settings.llm_provider}'; choose one of {sorted(CHAT_PRESETS)}")
    model = settings.llm_task_models.get(task) or settings.llm_model or preset["model"]
    base_url = settings.llm_base_url or preset["base_url"] or None
    if not model or (preset["needs_key"] and not settings.llm_api_key) or (settings.llm_provider == "openai_compat" and not base_url):
        return None
    # DeepSeek's reasoning model does not accept response_format; rely on prompt + parser for it.
    json_mode = preset["json_mode"] and "reasoner" not in model.lower()
    return ChatConfig(settings.llm_provider, model, base_url, settings.llm_api_key, json_mode)


def embed_config() -> EmbedConfig | None:
    if settings.embedding_provider in ("", "none"):
        return None
    preset = EMBED_PRESETS.get(settings.embedding_provider)
    if preset is None:
        raise ValueError(f"Unknown FINTECH_EMBEDDING_PROVIDER '{settings.embedding_provider}'; choose one of {sorted(EMBED_PRESETS)} or none")
    model = settings.embedding_model or preset["model"]
    base_url = settings.embedding_base_url or preset["base_url"] or None
    if not model or (preset["needs_key"] and not settings.embedding_api_key) or (preset["kind"] == "openai" and not base_url):
        return None
    return EmbedConfig(settings.embedding_provider, model, base_url, settings.embedding_api_key, preset["kind"])
