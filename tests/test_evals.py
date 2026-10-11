"""Pipeline-machinery checks at scale. The 'LLM' here is a scripted fake with injected errors: this proves the repair loop,
validators and confidence logic behave, NOT how accurate any real model is (measure that with `python -m evals.invoices`)."""
import json
from pathlib import Path

import pytest

from app.ai import chat
from app.core.config import settings
from evals import invoices as ev
from evals import retrieval
from evals.make_synthetic import make
from tests.fake_llm import FakeLLM
from tests.test_rag import TEST_ACT


def rows(n=40):
    import random
    rng = random.Random(3)
    return [make(i, rng) for i in range(n)]


def test_synthetic_dataset_is_valid_and_deterministic():
    a, b = rows(10), rows(10)
    assert a == b and all(r["text"] and r["expected"]["supplier_gstin"] for r in a)
    committed = [json.loads(line) for line in Path("evals/data/invoices_synthetic.jsonl").read_text().splitlines()]
    assert len(committed) == 60 and {r["layout"] for r in committed} == set("ABCDE")


def test_rules_baseline_is_safe_but_low_throughput(client):
    r = ev.evaluate(rows(60), mode="rules")
    assert r["silent_error_rate"] == 0.0           # wrong fields are always routed to review, never passed silently
    assert r["invoice_all_fields_correct"] < 0.7   # ...but the regex alone cannot handle messy layouts (hence the LLM path)


@pytest.fixture
def noisy_llm(monkeypatch):
    f = FakeLLM().start()
    chat._cache.clear()
    monkeypatch.setattr(settings, "llm_provider", "deepseek"); monkeypatch.setattr(settings, "llm_api_key", "k")
    monkeypatch.setattr(settings, "llm_base_url", f.base_url)
    data = {r["text"]: r for r in rows(40)}
    calls: dict[str, int] = {}

    def reply(req):
        user = req["messages"][1]["content"]
        text = next(t for t in data if t in user)
        exp = dict(data[text]["expected"])
        n = calls[text] = calls.get(text, 0) + 1
        idx = list(data).index(text)
        if n == 1:  # first attempt is wrong in a way the validators can see
            if idx % 3 == 0:
                exp["total"] = round(exp["total"] + 100, 2)
            elif idx % 5 == 0:
                exp["supplier_gstin"] = exp["supplier_gstin"][:4] + "4" + exp["supplier_gstin"][5:]
        return {k: v for k, v in exp.items()}

    f.reply = reply
    yield f
    f.stop()
    chat._cache.clear()


def test_noisy_llm_through_graph_keeps_silent_errors_at_zero(client, noisy_llm):
    r = ev.evaluate(rows(40), mode="auto")
    assert r["llm_used"] == 40
    assert r["silent_error_rate"] == 0.0
    assert r["invoice_all_fields_correct"] >= 0.9   # injected errors are repaired via validator feedback
    assert noisy_llm.requests and any("AUTOMATIC CHECKS FAILED" in q["messages"][1]["content"] for q in noisy_llm.requests)


def test_retrieval_recall_harness(client, tmp_path):
    from app.modules.legal import store
    store.add_document(None, "Synthetic Test Act", TEST_ACT)
    p = tmp_path / "q.jsonl"
    p.write_text("\n".join(json.dumps(x) for x in [
        {"query": "agreement restraining a lawful profession trade or business is void", "expected": [{"source": "Synthetic Test Act", "section": "2"}]},
        {"query": "pay a micro enterprise within forty five days", "expected": [{"source": "Synthetic Test Act", "section": "3"}]},
        {"query": "totally unrelated astronomy question", "expected": [{"source": "Synthetic Test Act", "section": "4"}]}]))
    r = retrieval.recall_at_k([json.loads(line) for line in p.read_text().splitlines()], k=2)
    assert r["recall_at_k"] == pytest.approx(2 / 3, abs=0.01) and r["misses"] == ["totally unrelated astronomy question"]
