"""The ONLY surface other modules (e-signature, legal review) may use to touch contracts.

Contracts own their data and state machine; callers ask for views and request transitions here instead of
reading or writing contract rows themselves (enforced by import-linter in CI).
"""
from dataclasses import dataclass

from app.core import db
from app.modules.contracts import risk

KIND = "contract"


class ContractStateError(RuntimeError):
    pass


@dataclass(frozen=True)
class ContractView:
    id: str
    title: str
    status: str
    version: int
    text: str


def get_contract(tenant_id: str, contract_id: str) -> ContractView | None:
    d = db.get(tenant_id, KIND, contract_id)
    if not d:
        return None
    versions = d["data"]["versions"]
    return ContractView(d["id"], d["data"]["title"], d["status"], len(versions), versions[-1]["text"])


def _transition(tenant_id: str, contract_id: str, allowed_from: set[str], to: str) -> None:
    d = db.get(tenant_id, KIND, contract_id)
    if not d:
        raise LookupError(contract_id)
    if d["status"] not in allowed_from:
        raise ContractStateError(f"Contract is {d['status']}; expected one of {sorted(allowed_from)}")
    db.put(tenant_id, KIND, d["data"], to, contract_id)


def begin_signature(tenant_id: str, contract_id: str) -> None:
    _transition(tenant_id, contract_id, {"approved"}, "out_for_signature")


def signature_cancelled(tenant_id: str, contract_id: str) -> None:
    """Signing was cancelled/declined: the contract returns to approved (idempotent otherwise)."""
    d = db.get(tenant_id, KIND, contract_id)
    if d and d["status"] == "out_for_signature":
        db.put(tenant_id, KIND, d["data"], "approved", contract_id)


def signature_completed(tenant_id: str, contract_id: str) -> None:
    _transition(tenant_id, contract_id, {"out_for_signature"}, "signed")


def screen_text(text: str) -> dict:
    """Deterministic rule screening (missing clauses / risky language) for arbitrary contract text."""
    return risk.review(text)
