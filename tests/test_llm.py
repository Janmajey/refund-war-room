import json

from war_room.docs import DocStore
from war_room.config import DOCS_DIR
from war_room.llm import HybridPlanner
from war_room.planner import RulePlanner
from war_room.setup import build_agent

QUESTION = "How many refund requests came from Tier-3 pincodes last week?"
SQL = ("SELECT COUNT(*) AS refunds FROM refunds r JOIN orders o ON o.order_id = r.order_id "
       "WHERE o.pincode_tier = 3 AND r.requested_on BETWEEN '2026-10-20' AND '2026-10-26'")


class FakeClient:
    def __init__(self, claimed_count):
        self.claimed_count = claimed_count
        self.hash = None

    def complete(self, system, user):
        if "plan tool calls" in system:
            return json.dumps({"steps": [{"tool": "run_sql", "args": {"query": SQL}, "purpose": "count",
                                          "intent": "refund_count"}]})
        self.hash = user.split("result_hash: ")[1].split()[0]
        return json.dumps({"claims": [{
            "type": "fact", "intent": "refund_count", "answers": True,
            "text": f"{self.claimed_count} refund requests came from Tier-3 pincodes last week.",
            "evidence": {"sql": SQL, "result_hash": self.hash}}]})


class BrokenClient:
    def complete(self, system, user):
        raise TimeoutError("model did not answer")


def hybrid(client):
    docs = DocStore(DOCS_DIR)
    return HybridPlanner(client, docs, RulePlanner(docs))


def test_llm_claim_with_the_right_number_survives(tmp_path):
    planner = hybrid(FakeClient(5))
    agent, _ = build_agent(fault_rate=0, planner=planner, log_path=tmp_path / "wa.log")
    out = agent.ask(QUESTION)
    assert planner.used_llm == {"plan": True, "draft": True}
    assert out["status"] == "answered"


def test_llm_hallucinated_number_is_dropped(tmp_path):
    agent, _ = build_agent(fault_rate=0, planner=hybrid(FakeClient(12)), log_path=tmp_path / "wa.log")
    out = agent.ask(QUESTION)
    assert out["status"] == "cannot_determine"
    assert "12 cannot be re-derived" in out["rejected_claims"][0]["reason"]


def test_rules_take_over_when_the_llm_fails(tmp_path):
    planner = hybrid(BrokenClient())
    agent, _ = build_agent(fault_rate=0, planner=planner, log_path=tmp_path / "wa.log")
    out = agent.ask(QUESTION)
    assert planner.used_llm == {"plan": False, "draft": False}
    assert out["status"] == "answered"
