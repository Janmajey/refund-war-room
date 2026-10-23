from collections import defaultdict

AUTHORITY = {"policy": 4, "finance": 3, "operations": 2, "seller_support": 1, "customer": 0}
RULE = "effective date, then source authority, then recency"


def side(claim, docs):
    doc = docs.get(claim.evidence["doc_id"])
    return {"doc_id": doc.id, "value": claim.value, "quote": claim.evidence["quote"],
            "effective": doc.effective, "authority": doc.authority, "date": doc.date}


def pick(group, docs):
    keys = [
        ("effective date", lambda c: docs.get(c.evidence["doc_id"]).effective),
        ("source authority", lambda c: AUTHORITY.get(docs.get(c.evidence["doc_id"]).authority, 0)),
        ("recency", lambda c: docs.get(c.evidence["doc_id"]).date),
    ]
    candidates = group
    for rule, key in keys:
        best = max(key(c) for c in candidates)
        candidates = [c for c in candidates if key(c) == best]
        if len({c.value for c in candidates}) == 1:
            return candidates[0], rule
    return None, None


def resolve(claims, docs):
    """Doc facts that share a topic but disagree on the value are settled by RULE, or reported."""
    kept, resolved, conflicts = [], [], []
    groups = defaultdict(list)
    for claim in claims:
        if claim.topic and claim.evidence and "doc_id" in claim.evidence:
            groups[claim.topic].append(claim)
        else:
            kept.append(claim)

    for topic, group in groups.items():
        if len({c.value for c in group}) == 1:
            kept.extend(group)
            continue
        winner, rule = pick(group, docs)
        if winner is None:
            conflicts.append({"topic": topic, "rule": RULE, "result": "unresolved",
                              "sides": [side(c, docs) for c in group]})
            continue
        winner.flags.append(f"conflict resolved by {rule}")
        kept.append(winner)
        resolved.append({"topic": topic, "rule": rule, "kept": side(winner, docs),
                         "dropped": [side(c, docs) for c in group if c.value != winner.value]})
    return kept, resolved, conflicts
