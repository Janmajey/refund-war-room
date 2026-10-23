import random

from .tools import SIDE_EFFECTS, ToolError, ToolTimeout

KINDS = ["error", "timeout", "empty"]


def empty_like(tool, result):
    if tool == "run_sql":
        return {"columns": result["columns"], "rows": []}
    if tool == "search_docs":
        return []
    return None


class FaultyTools:
    """Wraps Tools so that about `rate` of calls fail, time out or come back empty.

    `forced` maps a tool name to the faults its next calls must hit, e.g. {"get_policy": ["timeout"]}.
    The agent never sees `injected`; it is only there so the evaluation can report what happened.
    """

    def __init__(self, tools, rate=0.15, seed=0, forced=None):
        self.tools = tools
        self.rate = rate
        self.rng = random.Random(seed)
        self.forced = {k: list(v) for k, v in (forced or {}).items()}
        self.injected = []

    def pick(self, tool):
        if self.forced.get(tool):
            return self.forced[tool].pop(0)
        if tool in SIDE_EFFECTS:
            return None
        if self.rng.random() < self.rate:
            return self.rng.choice(KINDS)
        return None

    def call(self, tool, **args):
        kind = self.pick(tool)
        if kind:
            self.injected.append((tool, kind))
        if kind == "error":
            raise ToolError(f"{tool} failed: upstream returned 502")
        if kind == "timeout":
            raise ToolTimeout(f"{tool} timed out after 10 s")
        result = self.tools.call(tool, **args)
        return empty_like(tool, result) if kind == "empty" else result
