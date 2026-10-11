"""Grounded legal review of contract text (orchestration; the workflow itself is in graph.py).

A valid citation does not prove the model's reading is correct. Treat output as a reviewer's aid, not legal advice.
"""
import re

from app.ai import chat
from app.modules.legal import graph, store

MAX_CLAUSES = 30
DISCLAIMER = ("Automated, retrieval-grounded screening. Citations show which provisions the analysis relied on and an "
              "independent check judged them supportive; neither guarantees the analysis is right. Not legal advice - "
              "have a qualified Indian lawyer review before signing.")


def split_clauses(text: str) -> list[dict]:
    clauses = []
    for block in re.split(r"\n\s*\n", text):
        block = block.strip()
        lines = block.split("\n")
        m = re.match(r"^(\d+)\.\s+(.*)$", lines[0]) if lines else None
        if m and len(lines) > 1:
            clauses.append({"number": m.group(1), "title": m.group(2), "text": "\n".join(lines[1:]).strip()})
        elif len(block) >= 60:
            clauses.append({"number": str(len(clauses) + 1), "title": "", "text": block})
    if any(c["title"] for c in clauses):  # numbered contract: drop the unnumbered title/DRAFT banner before clause 1
        first = next(i for i, c in enumerate(clauses) if c["title"])
        clauses = clauses[first:]
    return clauses[:MAX_CLAUSES]


def review(tenant_id: str, text: str) -> dict:
    results = graph.run(tenant_id, split_clauses(text))
    corpus = store.stats(None)
    llm_on = chat.enabled("review")
    notes = []
    if not corpus:
        notes.append("No public-law corpus is loaded, so there is nothing to ground a legal analysis in. Ingest bare Acts "
                     "(see README: python -m app.modules.legal.ingest).")
    if not llm_on:
        notes.append("No LLM configured: showing rule findings and the most relevant provisions only.")
    if any(r["llm"] == "failed" for r in results):
        notes.append("The LLM failed for some clauses; those show retrieval only.")
    if any(i for r in results for i in r["issues"] if not i["verified"]):
        notes.append("Some findings could not be independently verified (verifier unavailable); treat them with extra care.")
    models = {k: v for r in results for k, v in r["models"].items()}
    return {"engine": "langgraph", "mode": "grounded_llm" if llm_on else "retrieval_only", "clauses": results, "notes": notes,
            "issue_count": sum(len(r["issues"]) for r in results),
            "dropped_ungrounded": sum(r["dropped_ungrounded"] for r in results),
            "dropped_unsupported": sum(r["dropped_unsupported"] for r in results),
            "models": models, "corpus": corpus, "disclaimer": DISCLAIMER}
