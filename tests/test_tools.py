import pytest

from war_room.faults import FaultyTools
from war_room.tools import ToolError, ToolTimeout


@pytest.mark.parametrize("sql", [
    "DELETE FROM refunds",
    "UPDATE orders SET amount = 0",
    "PRAGMA table_info(orders)",
    "SELECT 1; DROP TABLE orders",
    "WITH x AS (SELECT 1) INSERT INTO sellers VALUES (1, 'x', 1)",
])
def test_run_sql_refuses_writes(tools, sql):
    with pytest.raises(ToolError):
        tools.run_sql(sql)


def test_run_sql_reads(tools):
    out = tools.run_sql("SELECT COUNT(*) AS n FROM refunds WHERE reason IS NULL")
    assert out == {"columns": ["n"], "rows": [[1]]}


@pytest.mark.parametrize("as_of, version", [("2026-03-01", "1"), ("2026-07-01", "2"), ("2026-11-03", "3")])
def test_get_policy_picks_version_in_force(tools, as_of, version):
    assert tools.get_policy("replacement", as_of)["version"] == version


def test_get_policy_before_first_version(tools):
    assert tools.get_policy("replacement", "2025-06-01") is None


def test_search_handles_hinglish(tools):
    hits = tools.search_docs("parcel toota hua")
    assert hits[0]["doc_id"] == "ticket-T1041"


def test_whatsapp_goes_to_log(tools):
    tools.send_seller_whatsapp(40218, "hello")
    assert "40218" in tools.whatsapp_log.read_text()


def test_fault_rate_and_seed(tools):
    def run(seed):
        faulty = FaultyTools(tools, rate=0.15, seed=seed)
        outcomes = []
        for _ in range(1000):
            try:
                outcomes.append("empty" if faulty.call("search_docs", query="refund") == [] else "ok")
            except ToolTimeout:
                outcomes.append("timeout")
            except ToolError:
                outcomes.append("error")
        return outcomes

    first = run(3)
    assert 0.12 < sum(o != "ok" for o in first) / len(first) < 0.18
    assert first == run(3)


def test_forced_faults_come_first(tools):
    faulty = FaultyTools(tools, rate=0, forced={"get_policy": ["timeout", "empty"]})
    with pytest.raises(ToolTimeout):
        faulty.call("get_policy", name="replacement", as_of_date="2026-11-03")
    assert faulty.call("get_policy", name="replacement", as_of_date="2026-11-03") is None
    assert faulty.call("get_policy", name="replacement", as_of_date="2026-11-03")["version"] == "3"
