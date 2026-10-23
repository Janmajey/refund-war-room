import re
from dataclasses import dataclass

from .config import LAST_WEEK, THIS_WEEK, TODAY
from .contract import Claim, from_doc, from_sql
from .docs import sentences, tokens

SELLER_ID = re.compile(r"\b(4\d{4})\b")
ASKS_TO_SEND = re.compile(r"\b(send|bhej\w*|confirm\w*|message)\b", re.I)
WHATSAPP = re.compile(r"whats\s?app", re.I)

TOPICS = {
    "cod_refund_days": re.compile(r"COD refunds?[^.?]*?within (\d+)", re.I),
    "tier3_cod_cap": re.compile(r"COD order cap[^.?]*?₹\s?([\d,]+)", re.I),
}


@dataclass
class Step:
    tool: str
    args: dict
    purpose: str
    intent: str
    origin: str = "user"
    attempts: int = 0


def tier_of(question):
    m = re.search(r"tier[- ]?([123])", question, re.I)
    return int(m.group(1)) if m else 3


def days_in(question):
    m = re.search(r"(\d+)[- ]?(?:day|din)", question, re.I)
    return int(m.group(1)) if m else None


def window_of(question):
    m = re.search(r"\b(20\d\d)\b", question)
    if m:
        return f"{m.group(1)}-01-01", f"{m.group(1)}-12-31"
    return LAST_WEEK if re.search(r"last week|pichle hafte", question, re.I) else THIS_WEEK


def refunds_join(where):
    return f"FROM refunds r JOIN orders o ON o.order_id = r.order_id WHERE {where}"


class RulePlanner:
    name = "rules"

    def __init__(self, docs, today=TODAY):
        self.docs = docs
        self.today = str(today)

    def intents(self, question):
        t = set(tokens(question))
        if "whatsapp" in t and ("send" in t or "message" in t):
            return ["send"]
        found = []
        if "why" in t and "refund" in t:
            found.append("refund_trend")
        if "policy" in t or "replacement" in t:
            found.append("policy")
        if "cod" in t and "cap" in t:
            found.append("doc_fact:tier3_cod_cap")
        if "cod" in t and "refund" in t and ("day" in t or "long" in t):
            found.append("doc_fact:cod_refund_days")
        if "seller" in t and "ticket" in t:
            found.append("seller_tickets")
        elif "ticket" in t:
            found.append("tickets")
        if not found and "refund" in t and "rate" in t:
            found.append("refund_rate")
        if not found and "refund" in t and "many" in t:
            found.append("refund_count")
        return found or ["unknown"]

    def plan(self, question):
        steps = []
        tier = tier_of(question)
        for intent in self.intents(question):
            steps += getattr(self, "plan_" + intent.split(":")[0])(question, intent, tier)
        return steps

    def plan_refund_trend(self, question, intent, tier):
        (la, lb), (ta, tb) = LAST_WEEK, THIS_WEEK
        last = f"SUM(r.requested_on BETWEEN '{la}' AND '{lb}')"
        this = f"SUM(r.requested_on BETWEEN '{ta}' AND '{tb}')"
        trend = (f"SELECT o.pincode_tier AS tier, {last} AS last_week, {this} AS this_week, "
                 f"ROUND(100.0 * ({this} - {last}) / {last}, 1) AS change_pct "
                 + refunds_join(f"r.requested_on BETWEEN '{la}' AND '{tb}'")
                 + " GROUP BY o.pincode_tier ORDER BY tier")
        groups = ("SELECT o.courier, COALESCE(r.reason, 'unknown') AS reason, COUNT(*) AS refunds "
                  + refunds_join(f"o.pincode_tier = {tier} AND r.requested_on BETWEEN '{ta}' AND '{tb}'")
                  + " GROUP BY o.courier, reason ORDER BY refunds DESC LIMIT 5")
        return [Step("run_sql", {"query": trend}, "tier_trend", intent),
                Step("run_sql", {"query": groups}, "refund_groups", intent)]

    def plan_policy(self, question, intent, tier):
        name = "refund_sla" if re.search(r"refund (sla|timeline)", question, re.I) else "replacement"
        steps = [Step("get_policy", {"name": name, "as_of_date": self.today}, "policy_current", intent)]
        days = days_in(question)
        if days:
            steps.append(Step("search_docs", {"query": f"{days}-day {name} policy"}, "policy_referenced", intent))
        return steps

    def plan_doc_fact(self, question, intent, tier):
        return [Step("search_docs", {"query": question}, intent, intent)]

    def plan_seller_tickets(self, question, intent, tier):
        m = SELLER_ID.search(question)
        if m:
            return [Step("search_docs", {"query": f"seller {m.group(1)} ticket"}, "seller_docs", intent)]
        ta, tb = THIS_WEEK
        top = ("SELECT o.seller_id, COUNT(*) AS refunds "
               + refunds_join(f"o.pincode_tier = {tier} AND r.requested_on BETWEEN '{ta}' AND '{tb}'")
               + " GROUP BY o.seller_id ORDER BY refunds DESC LIMIT 3")
        return [Step("run_sql", {"query": top}, "top_seller", intent)]

    def plan_tickets(self, question, intent, tier):
        return [Step("search_docs", {"query": question, "k": 6}, "tickets", intent)]

    def plan_refund_rate(self, question, intent, tier):
        a, b = window_of(question)
        rate = ("SELECT COUNT(DISTINCT o.order_id) AS orders, COUNT(r.refund_id) AS refunds, "
                "ROUND(100.0 * COUNT(r.refund_id) / NULLIF(COUNT(DISTINCT o.order_id), 0), 2) AS refund_rate_pct "
                "FROM orders o LEFT JOIN refunds r ON r.order_id = o.order_id "
                f"WHERE o.pincode_tier = {tier} AND o.order_date BETWEEN '{a}' AND '{b}'")
        coverage = "SELECT MIN(order_date) AS first_order, MAX(order_date) AS last_order FROM orders"
        return [Step("run_sql", {"query": rate}, "refund_rate", intent),
                Step("run_sql", {"query": coverage}, "data_coverage", intent)]

    def plan_refund_count(self, question, intent, tier):
        a, b = window_of(question)
        count = ("SELECT COUNT(*) AS refunds "
                 + refunds_join(f"o.pincode_tier = {tier} AND r.requested_on BETWEEN '{a}' AND '{b}'"))
        return [Step("run_sql", {"query": count}, "refund_count", intent)]

    def plan_send(self, question, intent, tier):
        seller = SELLER_ID.search(question)
        message = re.search(r"(?:saying|that|:)\s*(.+)$", question)
        if not seller or not message:
            return []
        args = {"seller_id": int(seller.group(1)), "message": message.group(1).strip(" '\"")}
        return [Step("send_seller_whatsapp", args, "send", intent)]

    def plan_unknown(self, question, intent, tier):
        return [Step("search_docs", {"query": question}, "lookup", intent)]

    def follow_up(self, step, call, run):
        steps = []
        if step.purpose == "policy_current" and not call.ok:
            name = step.args["name"]
            steps.append(Step("search_docs", {"query": f"{name} policy"}, "policy_fallback", step.intent))
        if not call.ok or not call.result:
            return steps
        if step.purpose == "refund_groups" and call.result["rows"]:
            courier = call.result["rows"][0][0]
            query = f"{courier} courier Tier-3 change damaged"
            steps.append(Step("search_docs", {"query": query}, "courier_note", step.intent))
        if step.purpose == "top_seller" and call.result["rows"]:
            seller = call.result["rows"][0][0]
            steps.append(Step("search_docs", {"query": f"seller {seller} ticket"}, "seller_docs", step.intent))
        if step.tool == "search_docs":
            steps += self.requests_in(call.result)
        return steps

    def requests_in(self, hits):
        """Support documents often ask for a seller to be contacted; those become proposed actions."""
        steps = []
        for hit in hits:
            doc = self.docs.get(hit["doc_id"])
            for sentence in sentences(doc.text):
                if not (WHATSAPP.search(sentence) and ASKS_TO_SEND.search(sentence)):
                    continue
                sellers = SELLER_ID.findall(sentence) or ["all"]
                for seller in sellers:
                    args = {"seller_id": seller, "message": sentence}
                    steps.append(Step("send_seller_whatsapp", args, "doc_request", "doc_request", origin=f"doc:{doc.id}"))
        return steps

    def draft(self, question, run):
        claims = []
        for intent in run.intents:
            claims += getattr(self, "draft_" + intent.split(":")[0])(question, intent, run)
        return claims

    def draft_refund_trend(self, question, intent, run):
        claims = []
        tier = tier_of(question)
        trend = run.call("tier_trend")
        if trend and trend.ok and trend.result["rows"]:
            rows = {r[0]: r for r in trend.result["rows"]}
            if tier in rows:
                _, last, this, pct = rows[tier]
                verb = "rose" if this > last else "fell"
                claims.append(from_sql(
                    f"Tier-{tier} refund requests {verb} from {last} last week to {this} this week ({pct:+}%).",
                    trend, intent=intent, answers=True))
            others = [f"Tier-{t} went from {r[1]} to {r[2]}" for t, r in rows.items() if t != tier]
            if others:
                claims.append(from_sql(f"Over the same weeks {' and '.join(others)}.", trend, intent=intent))
        groups = run.call("refund_groups")
        if groups and groups.ok and groups.result["rows"]:
            courier, reason, n = groups.result["rows"][0]
            claims.append(from_sql(
                f"The largest group of Tier-{tier} refunds this week is '{reason}' on {courier} orders: {n} requests.",
                groups, intent=intent, answers=True))
            note = run.call("courier_note")
            for hit in (note.result if note and note.ok and note.result else []):
                doc = self.docs.get(hit["doc_id"])
                if doc.type not in ("warehouse_note", "ops_note"):
                    continue
                for s in [s for s in sentences(doc.text) if courier in s][:2]:
                    claims.append(from_doc(f"{doc.title} ({doc.date}): \"{s}\"", doc.id, s, intent=intent,
                                           answers=True))
                break
            claims.append(Claim("recommendation",
                                f"Ask {courier} for proof of the packing fix before the sale peak and track "
                                f"Tier-{tier} damage refunds daily until then.", intent=intent))
        (la, lb), (ta, tb) = LAST_WEEK, THIS_WEEK
        claims.append(Claim("assumption", f"\"This week\" is {ta} to {tb} and \"last week\" is {la} to {lb}, "
                                          "counted by the date the refund was requested.", intent=intent))
        return claims

    def draft_policy(self, question, intent, run):
        claims = []
        days = days_in(question)
        current = run.result("policy_current")
        if current:
            doc = self.docs.get(current["doc_id"])
        else:
            fallback = run.result("policy_fallback") or []
            doc = next((self.docs.get(h["doc_id"]) for h in fallback if h["type"] == "policy"), None)
        if doc is None:
            if run.call("policy_current") and run.call("policy_current").ok:
                name = run.call("policy_current").args["name"]
                run.missing.append(f"policy_current: get_policy returned no {name} policy in force on {self.today}")
            return claims

        window = " ".join(s for s in sentences(doc.text) if "window" in s)
        claims.append(from_doc(f"{doc.title} is the one in force (effective {doc.effective}): \"{window}\"",
                               doc.id, window, intent=intent, answers=True))
        for hit in run.result("policy_referenced") or []:
            old = self.docs.get(hit["doc_id"])
            newer = self.docs.superseded_by(old) if old.type == "policy" else None
            if old.id == doc.id or newer is None or not current:
                continue
            quote = next((s for s in sentences(old.text) if f"{days}-day" in s or f"{days} days" in s), None)
            if quote:
                claims.append(from_doc(
                    f"The {days}-day rule comes from {old.title} (effective {old.effective}), which was replaced "
                    f"on {newer.effective}: \"{quote}\"", old.id, quote, flags=["superseded"], intent=intent))
                claims.append(Claim("recommendation", f"Update any seller guidance that still quotes the {days}-day "
                                                      f"rule from {old.title}.", intent=intent))
                break
        return claims

    def draft_doc_fact(self, question, intent, run):
        topic = intent.split(":")[1]
        claims = []
        for hit in run.result(intent) or []:
            doc = self.docs.get(hit["doc_id"])
            for s in sentences(doc.text):
                m = TOPICS[topic].search(s)
                if m:
                    value = float(m.group(1).replace(",", ""))
                    claims.append(from_doc(f"{doc.title} ({doc.date}) says: \"{s}\"", doc.id, s,
                                           topic=topic, value=value, intent=intent, answers=True))
        return claims

    def draft_seller_tickets(self, question, intent, run):
        claims = []
        m = SELLER_ID.search(question)
        seller = m.group(1) if m else None
        top = run.call("top_seller")
        if top and top.ok and top.result["rows"]:
            seller, n = top.result["rows"][0]
            claims.append(from_sql(f"Seller {seller} has the most Tier-{tier_of(question)} refund requests this "
                                   f"week: {n}.", top, intent=intent, answers=True))
        for hit in run.result("seller_docs") or []:
            doc = self.docs.get(hit["doc_id"])
            quote = next((s for s in sentences(doc.text) if str(seller) in s), None)
            if quote and doc.type in ("ticket", "seller_note"):
                claims.append(from_doc(f"{doc.title} ({doc.date}): \"{quote}\"", doc.id, quote,
                                       intent=intent, answers=True))
        return claims

    def draft_tickets(self, question, intent, run):
        claims = []
        hits = [h for h in run.result("tickets") or [] if h["type"] == "ticket"]
        for hit in hits[:4]:
            doc = self.docs.get(hit["doc_id"])
            quote = sentences(doc.text)[0]
            claims.append(from_doc(f"{doc.title} ({doc.date}): \"{quote}\"", doc.id, quote,
                                   intent=intent, answers=True))
        return claims

    def draft_refund_rate(self, question, intent, run):
        claims = []
        rate = run.call("refund_rate")
        a, b = window_of(question)
        tier = tier_of(question)
        if rate and rate.ok and rate.result["rows"]:
            orders, refunds, pct = rate.result["rows"][0]
            if pct is None:
                run.missing.append(f"refund_rate: there are no Tier-{tier} orders between {a} and {b}")
            else:
                claims.append(from_sql(f"Between {a} and {b}, {refunds} of {orders} Tier-{tier} orders "
                                       f"were refunded ({pct}%).", rate, intent=intent, answers=True))
        coverage = run.call("data_coverage")
        if coverage and coverage.ok and coverage.result["rows"]:
            first, last = coverage.result["rows"][0]
            claims.append(from_sql(f"The order data covers {first} to {last}.", coverage, intent=intent))
        return claims

    def draft_refund_count(self, question, intent, run):
        count = run.call("refund_count")
        if not count or not count.ok:
            return []
        rows = count.result["rows"]
        n = rows[0][0] if rows else 0
        a, b = window_of(question)
        return [from_sql(f"{n} refund requests came from Tier-{tier_of(question)} pincodes between {a} and {b}.",
                         count, intent=intent, answers=True)]

    def draft_send(self, question, intent, run):
        return []

    def draft_unknown(self, question, intent, run):
        hits = run.result("lookup") or []
        wanted = set(tokens(question))
        for hit in hits[:1]:
            doc = self.docs.get(hit["doc_id"])
            covered = len(wanted & set(tokens(doc.title + " " + doc.text))) / max(len(wanted), 1)
            if covered >= 0.6:
                return [from_doc(f"{doc.title} ({doc.date}): \"{hit['snippet']}\"", doc.id, hit["snippet"],
                                 intent=intent, answers=True)]
        return []
