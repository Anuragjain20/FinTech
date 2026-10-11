"""Chat models via LangChain, plus a validated structured-output helper with one corrective retry.

Everything returns None / raises AIError-free results on provider failure so callers can degrade to their
deterministic path; a failing LLM must never take a feature down.
"""
import json
import logging
import re
from dataclasses import dataclass
from typing import TypeVar

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
from pydantic import BaseModel, ValidationError

from app.ai.providers import ChatConfig, chat_config
from app.core import db
from app.core.config import settings

log = logging.getLogger("fintech.ai")
T = TypeVar("T", bound=BaseModel)
_cache: dict[tuple, BaseChatModel] = {}


def enabled(task: str = "default") -> bool:
    return chat_config(task) is not None


def _build(cfg: ChatConfig) -> BaseChatModel:
    if cfg.provider == "anthropic":
        try:
            from langchain_anthropic import ChatAnthropic
        except ImportError as e:  # optional extra
            raise RuntimeError("Anthropic provider needs: pip install '.[anthropic]'") from e
        return ChatAnthropic(model=cfg.model, api_key=cfg.api_key, temperature=0, timeout=settings.llm_timeout_s, max_retries=2)
    from langchain_openai import ChatOpenAI  # DeepSeek, OpenAI and every OpenAI-compatible server
    return ChatOpenAI(model=cfg.model, base_url=cfg.base_url, api_key=cfg.api_key or "not-needed", temperature=0,
                      timeout=settings.llm_timeout_s, max_retries=2)


def get_chat_model(task: str = "default") -> BaseChatModel | None:
    cfg = chat_config(task)
    if cfg is None:
        return None
    key = (cfg.provider, cfg.model, cfg.base_url, cfg.api_key, settings.llm_timeout_s)
    if key not in _cache:
        _cache[key] = _build(cfg)
    return _cache[key]


@dataclass
class Structured:
    value: BaseModel
    model: str
    attempts: int
    tokens: int


def _parse(content: str, schema: type[T]) -> T:
    m = re.search(r"\{.*\}", content, re.S)  # tolerate prose or code fences around the JSON
    if not m:
        raise ValueError("no JSON object in the reply")
    return schema.model_validate(json.loads(m.group(0)))


def structured(task: str, schema: type[T], system: str, user: str, tenant_id: str | None = None,
               max_attempts: int = 2) -> Structured | None:
    """Ask the task's model for one JSON object matching `schema`. Retries once with the validation error fed back.
    Returns None when no model is configured or the provider keeps failing/returning invalid output."""
    cfg, model = chat_config(task), get_chat_model(task)
    if cfg is None or model is None:
        return None
    runnable = model.bind(response_format={"type": "json_object"}) if cfg.json_mode else model
    contract = f"{system}\n\nReply with ONE JSON object only (no prose) matching this JSON Schema:\n{json.dumps(schema.model_json_schema())}"
    messages: list = [SystemMessage(contract), HumanMessage(user)]
    tokens = 0
    for attempt in range(1, max_attempts + 1):
        try:
            reply = runnable.invoke(messages)
        except Exception as e:  # transport/auth/rate-limit: degrade, don't crash the caller
            log.warning("llm_call_failed", extra={"task": task, "model": cfg.model, "error": str(e)[:200]})
            return None
        tokens += int((getattr(reply, "usage_metadata", None) or {}).get("total_tokens", 0))
        text = reply.content if isinstance(reply.content, str) else json.dumps(reply.content)
        try:
            value = _parse(text, schema)
        except (ValueError, ValidationError) as e:
            messages += [AIMessage(text), HumanMessage(f"That reply was invalid ({str(e)[:300]}). Return the corrected JSON object only.")]
            continue
        if tenant_id and tokens:
            db.usage_incr(tenant_id, "llm_tokens", tokens)
        return Structured(value, cfg.model, attempt, tokens)
    return None
