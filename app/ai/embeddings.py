"""Embedding models via LangChain `Embeddings` (hosted free tiers, any OpenAI-compatible server, or local)."""
from dataclasses import dataclass

import numpy as np
from langchain_core.embeddings import Embeddings

from app.ai.providers import EmbedConfig, embed_config

_cache: dict[tuple, Embeddings] = {}
BATCH = 64


@dataclass
class Embedder:
    model_id: str
    client: Embeddings


def _build(cfg: EmbedConfig) -> Embeddings:
    if cfg.kind == "openai":  # Jina, Together, TEI/HF endpoints, Ollama, vLLM ... anything serving /v1/embeddings
        from langchain_openai import OpenAIEmbeddings
        return OpenAIEmbeddings(model=cfg.model, base_url=cfg.base_url, api_key=cfg.api_key or "not-needed",
                                check_embedding_ctx_length=False, tiktoken_enabled=False)
    try:
        from langchain_huggingface import HuggingFaceEmbeddings, HuggingFaceEndpointEmbeddings
    except ImportError as e:
        raise RuntimeError("This embedding provider needs: pip install '.[hf]'") from e
    if cfg.kind == "hf_endpoint":
        return HuggingFaceEndpointEmbeddings(model=cfg.model, huggingfacehub_api_token=cfg.api_key)
    return HuggingFaceEmbeddings(model_name=cfg.model, encode_kwargs={"normalize_embeddings": True})


def get_embedder() -> Embedder | None:
    cfg = embed_config()
    if cfg is None:
        return None
    key = (cfg.provider, cfg.model, cfg.base_url, cfg.api_key)
    if key not in _cache:
        _cache[key] = _build(cfg)
    return Embedder(cfg.model_id, _cache[key])


def current_model_id() -> str | None:
    cfg = embed_config()
    return cfg.model_id if cfg else None


def _norm(a: np.ndarray) -> np.ndarray:
    n = np.linalg.norm(a, axis=1, keepdims=True)
    n[n == 0] = 1
    return (a / n).astype(np.float32)


def embed_documents(texts: list[str]) -> tuple[np.ndarray, str] | None:
    """(L2-normalised matrix, model_id) or None when no embedder is configured. Raises on provider failure."""
    e = get_embedder()
    if e is None or not texts:
        return None
    vecs = []
    for i in range(0, len(texts), BATCH):
        vecs += e.client.embed_documents(texts[i:i + BATCH])
    return _norm(np.asarray(vecs, dtype=np.float32)), e.model_id


def embed_query(text: str) -> tuple[np.ndarray, str] | None:
    e = get_embedder()
    if e is None:
        return None
    return _norm(np.asarray([e.client.embed_query(text)], dtype=np.float32))[0], e.model_id
