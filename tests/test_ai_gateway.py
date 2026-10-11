import pytest
from pydantic import BaseModel

from app.ai import chat, embeddings, providers
from app.core import db
from app.core.config import settings
from tests.fake_llm import FakeLLM


class Out(BaseModel):
    answer: int


@pytest.fixture
def fake(monkeypatch):
    f = FakeLLM().start()
    chat._cache.clear()
    embeddings._cache.clear()
    yield f
    f.stop()
    chat._cache.clear()
    embeddings._cache.clear()


def use_deepseek(monkeypatch, fake):
    monkeypatch.setattr(settings, "llm_provider", "deepseek")
    monkeypatch.setattr(settings, "llm_api_key", "sk-test")
    monkeypatch.setattr(settings, "llm_base_url", fake.base_url)  # point the preset at the fake server


def test_deepseek_preset_defaults():
    c = providers.CHAT_PRESETS["deepseek"]
    assert c["base_url"] == "https://api.deepseek.com" and c["model"] == "deepseek-chat"
    assert providers.EMBED_PRESETS["jina"]["base_url"] == "https://api.jina.ai/v1"


def test_disabled_without_key_or_endpoint(monkeypatch):
    monkeypatch.setattr(settings, "llm_provider", "deepseek"); monkeypatch.setattr(settings, "llm_api_key", "")
    assert providers.chat_config() is None and chat.enabled() is False and chat.get_chat_model() is None
    assert chat.structured("extract", Out, "s", "u") is None
    monkeypatch.setattr(settings, "llm_provider", "openai_compat"); monkeypatch.setattr(settings, "llm_base_url", "")
    assert providers.chat_config() is None
    monkeypatch.setattr(settings, "llm_provider", "nope")
    with pytest.raises(ValueError, match="Unknown FINTECH_LLM_PROVIDER"):
        providers.chat_config()


def test_deepseek_call_shape_and_structured_parse(monkeypatch, fake):
    use_deepseek(monkeypatch, fake)
    fake.reply = lambda req: 'Sure! ```json\n{"answer": 42}\n```'
    r = chat.structured("extract", Out, "You answer.", "what?")
    assert r.value.answer == 42 and r.model == "deepseek-chat" and r.attempts == 1 and r.tokens == 10
    req, hdr = fake.requests[0], fake.headers[0]
    assert req["model"] == "deepseek-chat" and req["temperature"] == 0 and req["response_format"] == {"type": "json_object"}
    assert hdr["authorization"] == "Bearer sk-test"
    assert "json" in req["messages"][0]["content"].lower() and '"answer"' in req["messages"][0]["content"]  # schema is in the prompt


def test_corrective_retry_then_give_up(monkeypatch, fake):
    use_deepseek(monkeypatch, fake)
    replies = iter(['{"answer": "not-an-int"}', '{"answer": 7}'])
    fake.reply = lambda req: next(replies)
    r = chat.structured("extract", Out, "s", "u")
    assert r.value.answer == 7 and r.attempts == 2
    assert "invalid" in fake.requests[1]["messages"][-1]["content"].lower()  # validation error is fed back
    fake.reply = lambda req: "garbage"
    assert chat.structured("extract", Out, "s", "u") is None
    fake.fail = True
    assert chat.structured("extract", Out, "s", "u") is None  # provider failure degrades, never raises


def test_switching_is_config_only_and_task_overrides(monkeypatch, fake):
    use_deepseek(monkeypatch, fake)
    fake.reply = lambda req: {"answer": 1}
    monkeypatch.setattr(settings, "llm_task_models", {"verify": "deepseek-reasoner"})
    chat.structured("extract", Out, "s", "u")
    chat.structured("verify", Out, "s", "u")
    assert [r["model"] for r in fake.requests] == ["deepseek-chat", "deepseek-reasoner"]
    assert "response_format" in fake.requests[0] and "response_format" not in fake.requests[1]  # reasoner: no JSON mode
    # switch the whole provider to a local OpenAI-compatible server: only settings change
    monkeypatch.setattr(settings, "llm_provider", "openai_compat"); monkeypatch.setattr(settings, "llm_api_key", "")
    monkeypatch.setattr(settings, "llm_model", "llama3.1:8b"); monkeypatch.setattr(settings, "llm_task_models", {})
    assert chat.structured("extract", Out, "s", "u").model == "llama3.1:8b"
    assert fake.requests[-1]["model"] == "llama3.1:8b"


def test_token_usage_is_metered_per_tenant(client, monkeypatch, fake):
    use_deepseek(monkeypatch, fake)
    fake.reply = lambda req: {"answer": 1}
    chat.structured("extract", Out, "s", "u", tenant_id="t1")
    chat.structured("extract", Out, "s", "u", tenant_id="t1")
    assert db.usage_get("t1", "llm_tokens") == 20 and db.usage_get("t2", "llm_tokens") == 0


def test_embeddings_openai_compatible_and_model_id(monkeypatch, fake):
    monkeypatch.setattr(settings, "embedding_provider", "jina"); monkeypatch.setattr(settings, "embedding_api_key", "jk")
    monkeypatch.setattr(settings, "embedding_base_url", fake.base_url)
    vecs, mid = embeddings.embed_documents(["restraint of trade", "payment within 45 days"])
    assert vecs.shape == (2, 64) and mid == "jina:jina-embeddings-v3"
    assert abs(float((vecs[0] ** 2).sum()) - 1.0) < 1e-5  # normalised
    assert fake.embed_requests[0]["model"] == "jina-embeddings-v3" and fake.embed_requests[0]["_auth"] == "Bearer jk"
    q, _ = embeddings.embed_query("restraint trade")
    assert float(vecs[0] @ q) > float(vecs[1] @ q)  # similar text is closer
    monkeypatch.setattr(settings, "embedding_provider", "none")
    assert embeddings.embed_documents(["x"]) is None and embeddings.current_model_id() is None
    monkeypatch.setattr(settings, "embedding_provider", "jina"); monkeypatch.setattr(settings, "embedding_api_key", "")
    assert embeddings.embed_documents(["x"]) is None  # hosted provider without a key = off


def test_ai_status_endpoint(client, admin, role_headers, monkeypatch, fake):
    assert client.get("/ai/status", headers=role_headers("operator")).status_code == 403
    assert client.get("/ai/status", headers=admin).json()["chat"]["enabled"] is False
    use_deepseek(monkeypatch, fake)
    fake.reply = lambda req: {"ok": True}
    s = client.get("/ai/status?probe=true", headers=admin).json()
    assert s["chat"] == {"enabled": True, "provider": "deepseek", "model": "deepseek-chat", "probe": s["chat"]["probe"]}
    assert s["chat"]["probe"]["ok"] is True
