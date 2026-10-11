"""Minimal client for any OpenAI-compatible chat endpoint (Ollama, vLLM, llama.cpp server, hosted APIs)."""
import json
import re

import httpx

from app.core.config import settings


def enabled() -> bool:
    return bool(settings.llm_base_url and settings.llm_model)


def chat_json(system: str, user: str) -> dict | None:
    """Single deterministic call expecting a JSON object back. Returns None on any transport/parse failure."""
    headers = {"Authorization": f"Bearer {settings.llm_api_key}"} if settings.llm_api_key else {}
    try:
        r = httpx.post(settings.llm_base_url.rstrip("/") + "/chat/completions", headers=headers, timeout=settings.llm_timeout_s, json={
            "model": settings.llm_model, "temperature": 0, "response_format": {"type": "json_object"},
            "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}]})
        r.raise_for_status()
        content = r.json()["choices"][0]["message"]["content"]
    except (httpx.HTTPError, KeyError, IndexError, ValueError):
        return None
    m = re.search(r"\{.*\}", content, re.S)  # tolerate prose / code fences around the JSON
    try:
        out = json.loads(m.group(0)) if m else None
    except ValueError:
        return None
    return out if isinstance(out, dict) else None
