import json

from evaluate import QUESTIONS
from war_room.contract import schema_problems
from war_room.setup import build_agent

BIG = ("Tier-3 refunds kyun badh gaye, is the 7-day replacement policy still valid, which seller has the most "
       "Tier-3 refunds and do they have open tickets, how long do COD refunds take, and what is the COD order "
       "cap for Tier-3?")


def test_fact_without_evidence_fails_the_schema():
    out = {"status": "answered", "conflicts": [], "missing_evidence": [],
           "claims": [{"type": "fact", "text": "Refunds doubled."}]}
    assert schema_problems(out) == ["claims[0] is a fact without doc or sql evidence"]


def test_every_evaluation_answer_fits_the_schema(tmp_path):
    for i, q in enumerate(json.loads(QUESTIONS.read_text(encoding="utf-8"))):
        agent, _ = build_agent(seed=100 + i, forced=q.get("forced_faults"), log_path=tmp_path / "wa.log")
        assert schema_problems(agent.ask(q["question"])) == [], q["id"]


def test_question_needing_more_than_eight_calls_stops_with_a_partial_answer(tmp_path):
    agent, _ = build_agent(fault_rate=0, log_path=tmp_path / "wa.log")
    assert len(agent.planner.intents(BIG)) == 5
    out = agent.ask(BIG)
    assert out["tool_calls"] == 8
    assert out["status"] == "partial"
    assert any("budget was used up" in m for m in out["missing_evidence"])
