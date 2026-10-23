import sqlite3
from pathlib import Path

from .agent import Agent
from .config import DB_PATH, DOCS_DIR, FAULT_RATE, TODAY, WHATSAPP_LOG
from .docs import DocStore
from .faults import FaultyTools
from .gate import Gate
from .llm import make_planner
from .tools import Tools
from .verifier import Verifier


def active_sellers(db_path=DB_PATH):
    con = sqlite3.connect(f"{Path(db_path).resolve().as_uri()}?mode=ro", uri=True)
    try:
        return [r[0] for r in con.execute("SELECT seller_id FROM sellers WHERE active = 1")]
    finally:
        con.close()


def build_agent(verify=True, fault_rate=FAULT_RATE, seed=0, forced=None, planner=None, log_path=WHATSAPP_LOG):
    docs = DocStore(DOCS_DIR)
    tools = FaultyTools(Tools(DB_PATH, docs, log_path), rate=fault_rate, seed=seed, forced=forced)
    agent = Agent(
        tools=tools,
        docs=docs,
        planner=planner or make_planner(docs),
        gate=Gate(active_sellers()),
        verifier=Verifier(docs, TODAY) if verify else None,
    )
    return agent, tools
