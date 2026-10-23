from dataclasses import dataclass, field

from .config import TODAY, TOOL_BUDGET
from .conflicts import resolve
from .tools import SIDE_EFFECTS, ToolCall, ToolError, result_hash

MAX_ATTEMPTS = 2


@dataclass
class Run:
    question: str
    intents: list = field(default_factory=list)
    calls: list = field(default_factory=list)
    by_purpose: dict = field(default_factory=dict)
    missing: list = field(default_factory=list)
    actions: list = field(default_factory=list)
    trace: list = field(default_factory=list)

    def call(self, purpose):
        return self.by_purpose.get(purpose)

    def result(self, purpose):
        call = self.by_purpose.get(purpose)
        return call.result if call and call.ok else None


class Agent:
    """plan -> act -> observe -> (act ...) -> draft -> verify -> answer | abstain"""

    def __init__(self, tools, docs, planner, gate, verifier=None, budget=TOOL_BUDGET, today=TODAY):
        self.tools = tools
        self.docs = docs
        self.planner = planner
        self.gate = gate
        self.verifier = verifier
        self.budget = budget
        self.today = today

    def ask(self, question):
        run = Run(question)
        queue, step, call, claims = [], None, None, []
        kept = rejected = resolved = conflicts = None
        state = "plan"
        while state != "done":
            run.trace.append(state)
            if state == "plan":
                run.intents = self.planner.intents(question)
                queue = self.planner.plan(question)
                state = "act"

            elif state == "act":
                if not queue:
                    state = "draft"
                    continue
                if len(run.calls) >= self.budget:
                    run.missing += [f"{s.purpose}: not run, the {self.budget}-call budget was used up" for s in queue]
                    queue = []
                    state = "draft"
                    continue
                step = queue.pop(0)
                if step.tool in SIDE_EFFECTS:
                    allowed, reason = self.gate.check(step, question)
                    run.actions.append({"tool": step.tool, "args": step.args, "origin": step.origin,
                                        "allowed": allowed, "reason": reason})
                    if not allowed:
                        continue
                call = self.execute(step, run)
                state = "observe"

            elif state == "observe":
                if call.tool in SIDE_EFFECTS:
                    run.actions[-1]["done"] = call.ok
                if not call.ok and step.attempts < MAX_ATTEMPTS and call.tool not in SIDE_EFFECTS:
                    queue.insert(0, step)
                else:
                    if not call.ok:
                        run.missing.append(f"{step.purpose}: {call.error}")
                    queue += self.planner.follow_up(step, call, run)
                state = "act"

            elif state == "draft":
                claims = self.planner.draft(question, run)
                state = "verify"

            elif state == "verify":
                if self.verifier:
                    kept, rejected = self.verifier.split(claims, run.calls)
                else:
                    kept, rejected = claims, []
                kept, resolved, conflicts = resolve(kept, self.docs)
                state = "answer" if self.satisfied(run, kept) else "abstain"

            elif state in ("answer", "abstain"):
                state = "done"

        self.last_run, self.last_claims = run, kept
        return self.output(run, kept, rejected, resolved, conflicts)

    def execute(self, step, run):
        step.attempts += 1
        call_id = len(run.calls) + 1
        try:
            result = self.tools.call(step.tool, **step.args)
            call = ToolCall(call_id, step.tool, step.args, True, result, result_hash(result))
        except ToolError as e:
            call = ToolCall(call_id, step.tool, step.args, False, error=str(e))
        run.calls.append(call)
        run.by_purpose[step.purpose] = call
        return call

    def satisfied(self, run, kept):
        return [i for i in run.intents if self.intent_done(i, run, kept)]

    def intent_done(self, intent, run, kept):
        if intent == "send":
            return any(a.get("done") and a["origin"] == "user" for a in run.actions)
        return any(c.intent == intent and c.answers for c in kept)

    def output(self, run, kept, rejected, resolved, conflicts):
        done = self.satisfied(run, kept)
        missing = list(run.missing)
        missing += [f"claim dropped by the verifier: {reason}" for _, reason in rejected]
        missing += [f"no supported answer for: {i}" for i in run.intents if i not in done]
        if not done:
            status = "cannot_determine"
        elif len(done) < len(run.intents) or run.missing or rejected:
            status = "partial"
        else:
            status = "answered"
        return {
            "question": run.question,
            "status": status,
            "planner": self.planner.name,
            "claims": [c.to_json() for c in kept],
            "conflicts": conflicts,
            "resolved_conflicts": resolved,
            "missing_evidence": missing,
            "rejected_claims": [{"claim": c.to_json(), "reason": r} for c, r in rejected],
            "actions": run.actions,
            "tool_calls": len(run.calls),
            "calls": [c.to_json() for c in run.calls],
            "trace": run.trace,
        }
