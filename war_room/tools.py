import hashlib
import json
import re
import sqlite3
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

WRITE_WORDS = re.compile(
    r"\b(insert|update|delete|drop|alter|create|replace|attach|detach|pragma|vacuum|reindex)\b", re.I
)
SIDE_EFFECTS = {"send_seller_whatsapp"}


class ToolError(Exception):
    pass


class ToolTimeout(ToolError):
    pass


def result_hash(result):
    blob = json.dumps(result, sort_keys=True, default=str, ensure_ascii=False)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()[:16]


@dataclass
class ToolCall:
    id: int
    tool: str
    args: dict
    ok: bool
    result: object = None
    result_hash: str | None = None
    error: str | None = None

    def to_json(self):
        return {"id": self.id, "tool": self.tool, "args": self.args, "ok": self.ok,
                "result_hash": self.result_hash, "error": self.error}


class Tools:
    def __init__(self, db_path, docs, whatsapp_log):
        self.db_path = db_path
        self.docs = docs
        self.whatsapp_log = whatsapp_log

    def run_sql(self, query):
        sql = query.strip().rstrip(";")
        if ";" in sql:
            raise ToolError("only one statement per call")
        if not re.match(r"(?is)^\s*(select|with)\b", sql) or WRITE_WORDS.search(sql):
            raise ToolError("run_sql only accepts read-only SELECT queries")
        con = sqlite3.connect(f"{Path(self.db_path).resolve().as_uri()}?mode=ro", uri=True)
        try:
            cur = con.execute(sql)
            columns = [c[0] for c in cur.description]
            rows = [list(r) for r in cur.fetchmany(200)]
        except sqlite3.Error as e:
            raise ToolError(f"sql error: {e}") from e
        finally:
            con.close()
        return {"columns": columns, "rows": rows}

    def search_docs(self, query, k=4):
        return self.docs.search(query, k=k)

    def get_policy(self, name, as_of_date):
        doc = self.docs.policy(name, as_of_date)
        if doc is None:
            return None
        return {"doc_id": doc.id, "version": doc.meta.get("version"), "effective": doc.effective, "text": doc.text}

    def send_seller_whatsapp(self, seller_id, message):
        self.whatsapp_log.parent.mkdir(parents=True, exist_ok=True)
        entry = {"at": datetime.now().isoformat(timespec="seconds"), "seller_id": seller_id, "message": message}
        with open(self.whatsapp_log, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")
        return {"sent": True, "seller_id": seller_id}

    def call(self, tool, **args):
        if tool not in TOOL_NAMES:
            raise ToolError(f"unknown tool {tool}")
        return getattr(self, tool)(**args)


TOOL_NAMES = {"run_sql", "search_docs", "get_policy", "send_seller_whatsapp"}
