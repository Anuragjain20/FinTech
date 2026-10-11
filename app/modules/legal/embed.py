"""Optional dense embeddings (sentence-transformers, Apache-2.0). Disabled unless FINTECH_EMBEDDING_MODEL is set."""
from functools import lru_cache

import numpy as np

from app.core.config import settings


@lru_cache(maxsize=1)
def _model():
    from sentence_transformers import SentenceTransformer
    return SentenceTransformer(settings.embedding_model)


def enabled() -> bool:
    return bool(settings.embedding_model)


def embed(texts: list[str]) -> np.ndarray | None:
    """L2-normalised float32 matrix (n, d), or None when dense retrieval is off."""
    if not enabled() or not texts:
        return None
    return np.asarray(_model().encode(texts, normalize_embeddings=True, batch_size=32), dtype=np.float32)
