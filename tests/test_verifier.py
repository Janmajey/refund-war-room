import pytest

from war_room.config import TODAY
from war_room.contract import Claim, from_doc, from_sql
from war_room.tools import ToolCall, result_hash
from war_room.verifier import Verifier, numbers_in

SQL = "SELECT pincode_tier, COUNT(*) AS refunds FROM refunds r JOIN orders o USING (order_id) WHERE pincode_tier = 3"


def sql_call(rows, call_id=1):
    result = {"columns": ["pincode_tier", "refunds"], "rows": rows}
    return ToolCall(call_id, "run_sql", {"query": SQL}, True, result, result_hash(result))


def search_call(*doc_ids):
    hits = [{"doc_id": d} for d in doc_ids]
    return ToolCall(2, "search_docs", {"query": "x"}, True, hits, result_hash(hits))


@pytest.fixture
def verifier(docs):
    return Verifier(docs, TODAY)


def test_number_extraction_skips_ids_and_tiers():
    assert numbers_in("Tier-3 ticket T1041 rose from 5 to 19 (+280.0%) on 2026-10-27, cap ₹5,000") == [
        5, 19, 280.0, 2026, 5000]


def test_supported_sql_claim_passes(verifier):
    call = sql_call([[3, 19]])
    assert verifier.problem(from_sql("Tier-3 had 19 refund requests.", call), [call]) is None


def test_made_up_number_is_caught(verifier):
    call = sql_call([[3, 19]])
    reason = verifier.problem(from_sql("Tier-3 had 23 refund requests.", call), [call])
    assert "23" in reason


def test_zero_from_an_empty_result_is_caught(verifier):
    call = sql_call([])
    assert verifier.problem(from_sql("0 refund requests came from Tier-3.", call), [call])


def test_hash_must_match_a_recorded_run(verifier):
    call = sql_call([[3, 19]])
    claim = from_sql("Tier-3 had 19 refund requests.", call)
    claim.evidence["result_hash"] = "0000000000000000"
    assert "hash" in verifier.problem(claim, [call])


def test_exact_quote_passes(verifier):
    quote = "COD refunds are credited to the customer's bank account within 7 working days."
    claim = from_doc(f'Refund timelines says: "{quote}"', "policy-refund-sla", quote)
    assert verifier.problem(claim, [search_call("policy-refund-sla")]) is None


def test_altered_quote_is_caught(verifier):
    quote = "COD refunds are credited to the customer's bank account within 5 working days."
    claim = from_doc(f'Refund timelines says: "{quote}"', "policy-refund-sla", quote)
    assert "verbatim" in verifier.problem(claim, [search_call("policy-refund-sla")])


def test_document_must_have_been_retrieved(verifier):
    quote = "COD refunds are credited to the customer's bank account within 7 working days."
    claim = from_doc(quote, "policy-refund-sla", quote)
    assert "never retrieved" in verifier.problem(claim, [search_call("faq-sellers-2025")])


def test_superseded_policy_needs_a_flag(verifier):
    quote = "Bharat Bazaar sellers must honour a 7-day replacement window from the date of delivery."
    claim = from_doc(f'The policy in force says: "{quote}"', "policy-replacement-v1", quote)
    calls = [search_call("policy-replacement-v1")]
    assert "superseded" in verifier.problem(claim, calls)
    claim.flags.append("superseded")
    assert verifier.problem(claim, calls) is None


def test_fact_without_evidence_and_non_facts(verifier):
    assert verifier.problem(Claim("fact", "Refunds doubled."), []) == "fact has no evidence"
    assert verifier.problem(Claim("recommendation", "Call RapidKart."), []) is None
