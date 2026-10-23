import re

NUMBER = re.compile(r"(?<![\w.\-])₹?\s?(\d[\d,]*(?:\.\d+)?)")


def numbers_in(text):
    return [float(n.replace(",", "")) for n in NUMBER.findall(str(text))]


def same(a, b):
    return abs(a - b) <= 0.051 or abs(a - b) <= 1e-6 * max(abs(a), abs(b))


def retrieved_docs(calls):
    seen = set()
    for call in calls:
        if not call.ok or not call.result:
            continue
        if call.tool == "search_docs":
            seen.update(hit["doc_id"] for hit in call.result)
        elif call.tool == "get_policy":
            seen.add(call.result["doc_id"])
    return seen


class Verifier:
    """Plain-code checks on every fact claim. No model is involved."""

    def __init__(self, docs, today):
        self.docs = docs
        self.today = str(today)

    def problem(self, claim, calls):
        if claim.type != "fact":
            return None
        ev = claim.evidence or {}
        if "sql" in ev:
            return self.check_sql(claim, ev, calls)
        if "doc_id" in ev:
            return self.check_doc(claim, ev, calls)
        return "fact has no evidence"

    def check_sql(self, claim, ev, calls):
        runs = [c for c in calls if c.tool == "run_sql" and c.args.get("query") == ev["sql"] and c.ok]
        run = next((c for c in runs if c.result_hash == ev.get("result_hash")), None)
        if not runs:
            return "no successful run of this query was recorded"
        if run is None:
            return "result hash does not match any recorded run of this query"
        allowed = [n for row in run.result["rows"] for cell in row for n in numbers_in(cell)]
        allowed += numbers_in(ev["sql"])
        for n in numbers_in(claim.text):
            if not any(same(n, a) for a in allowed):
                return f"{n:g} cannot be re-derived from the query result"
        return None

    def check_doc(self, claim, ev, calls):
        doc = self.docs.get(ev["doc_id"])
        if doc is None:
            return f"unknown document {ev['doc_id']}"
        if ev["doc_id"] not in retrieved_docs(calls):
            return f"{ev['doc_id']} was never retrieved in this run"
        if ev.get("quote", "") not in doc.text:
            return f"quote not found verbatim in {doc.id}"
        allowed = numbers_in(ev["quote"]) + numbers_in(" ".join(doc.meta.values()))
        for n in numbers_in(claim.text):
            if not any(same(n, a) for a in allowed):
                return f"{n:g} is not in the quoted text of {doc.id}"
        if doc.type == "policy" and not self.docs.in_force(doc, self.today) and "superseded" not in claim.flags:
            newer = self.docs.superseded_by(doc)
            when = f" by {newer.id} on {newer.effective}" if newer else ""
            return f"{doc.id} was superseded{when} but the claim does not say so"
        return None

    def split(self, claims, calls):
        kept, rejected = [], []
        for claim in claims:
            reason = self.problem(claim, calls)
            if reason:
                rejected.append((claim, reason))
            else:
                kept.append(claim)
        return kept, rejected
