"""Retrieval recall@k on a labelled JSONL set, against the LIVE corpus and configured embedding model.

    python -m evals.retrieval --data my_queries.jsonl --k 4
    # each line: {"query": "non-compete after employment ends", "expected": [{"source": "Indian Contract Act, 1872", "section": "27"}]}

Run it before and after switching FINTECH_EMBEDDING_* (then `--reindex`) to see whether the switch helped.
"""
import argparse
import json
import sys
from pathlib import Path

from app.modules.legal import store


def recall_at_k(rows: list[dict], k: int, tenant_id: str = "eval") -> dict:
    hit = 0
    misses = []
    for r in rows:
        got = {(p["source"], p["section"]) for p in store.search(tenant_id, r["query"], k=k)}
        want = {(e["source"], e.get("section")) for e in r["expected"]}
        if got & want:
            hit += 1
        else:
            misses.append(r["query"])
    return {"n": len(rows), "k": k, "recall_at_k": round(hit / len(rows), 3) if rows else 0.0, "misses": misses}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--data", required=True)
    ap.add_argument("--k", type=int, default=4)
    a = ap.parse_args(argv)
    rows = [json.loads(line) for line in Path(a.data).read_text().splitlines() if line.strip()]
    r = recall_at_k(rows, a.k)
    print(f"recall@{r['k']} = {r['recall_at_k'] * 100:.1f}% over {r['n']} queries")
    for q in r["misses"]:
        print("  MISS:", q)
    return 0


if __name__ == "__main__":
    sys.exit(main())
