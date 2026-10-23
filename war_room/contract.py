from dataclasses import dataclass, field

CLAIM_TYPES = {"fact", "assumption", "recommendation"}
STATUSES = {"answered", "partial", "cannot_determine"}


@dataclass
class Claim:
    type: str
    text: str
    evidence: dict | None = None
    flags: list = field(default_factory=list)
    topic: str | None = None
    value: float | None = None
    intent: str | None = None
    answers: bool = False

    def to_json(self):
        out = {"type": self.type, "text": self.text}
        if self.evidence:
            out["evidence"] = self.evidence
        if self.flags:
            out["flags"] = list(self.flags)
        return out


def from_sql(text, call, **kw):
    return Claim("fact", text, {"sql": call.args["query"], "result_hash": call.result_hash}, **kw)


def from_doc(text, doc_id, quote, **kw):
    return Claim("fact", text, {"doc_id": doc_id, "quote": quote}, **kw)


def schema_problems(output):
    problems = []
    if output.get("status") not in STATUSES:
        problems.append(f"bad status {output.get('status')!r}")
    for key in ("claims", "conflicts", "missing_evidence"):
        if not isinstance(output.get(key), list):
            problems.append(f"{key} must be a list")
    for i, claim in enumerate(output.get("claims", [])):
        if claim.get("type") not in CLAIM_TYPES:
            problems.append(f"claims[{i}] has bad type {claim.get('type')!r}")
        if claim.get("type") == "fact":
            ev = claim.get("evidence") or {}
            if not ({"doc_id", "quote"} <= ev.keys() or {"sql", "result_hash"} <= ev.keys()):
                problems.append(f"claims[{i}] is a fact without doc or sql evidence")
    return problems
