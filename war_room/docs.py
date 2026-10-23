import math
import re
from collections import Counter
from dataclasses import dataclass
from pathlib import Path

HINGLISH = {
    "kyun": "why", "kyon": "why", "kyu": "why",
    "badh": "increase", "badhe": "increase", "badha": "increase", "badhi": "increase",
    "toota": "damaged", "tuta": "damaged", "tooti": "damaged", "toot": "damaged",
    "paisa": "money", "paise": "money", "rupaye": "rupees",
    "wapas": "refund", "bhej": "send", "bhejo": "send", "bhejiye": "send", "bheja": "sent",
    "din": "day", "mein": "in", "galat": "wrong",
}
STOP = {
    "the", "a", "an", "is", "are", "was", "were", "to", "of", "and", "or", "in", "on", "for", "with",
    "we", "our", "it", "this", "that", "be", "by", "at", "from", "as", "do", "does", "did", "what",
    "which", "how", "still", "gave", "ka", "ki", "ke", "hai", "ne", "se", "aur", "ko", "kar", "gaye",
}


def tokens(text):
    out = []
    for word in re.findall(r"[a-z0-9]+", text.lower()):
        word = HINGLISH.get(word, word)
        if word in STOP:
            continue
        if len(word) > 3 and word.endswith("s") and not word.endswith("ss"):
            word = word[:-1]
        out.append(word)
    return out


def sentences(text):
    return [s.strip() for s in re.split(r"(?<=[.!?])\s+", text) if s.strip()]


@dataclass
class Doc:
    id: str
    meta: dict
    text: str

    @property
    def title(self):
        return self.meta.get("title", self.id)

    @property
    def type(self):
        return self.meta.get("type", "")

    @property
    def date(self):
        return self.meta.get("date", "")

    @property
    def effective(self):
        return self.meta.get("effective", self.date)

    @property
    def authority(self):
        return self.meta.get("authority", "")


def parse(path):
    raw = Path(path).read_text(encoding="utf-8")
    _, header, body = raw.split("---\n", 2)
    meta = dict(line.split(": ", 1) for line in header.strip().splitlines())
    return Doc(meta["id"], meta, body.strip())


class DocStore:
    def __init__(self, folder):
        self.docs = {d.id: d for d in map(parse, sorted(Path(folder).glob("*.md")))}
        self.terms = {d.id: Counter(tokens(d.title + " " + d.text)) for d in self.docs.values()}
        self.avg_len = sum(sum(t.values()) for t in self.terms.values()) / len(self.terms)
        df = Counter(term for t in self.terms.values() for term in t)
        n = len(self.docs)
        self.idf = {term: math.log(1 + (n - c + 0.5) / (c + 0.5)) for term, c in df.items()}

    def get(self, doc_id):
        return self.docs.get(doc_id)

    def score(self, query_terms, doc_id, k1=1.4, b=0.75):
        tf = self.terms[doc_id]
        length = sum(tf.values())
        total = 0.0
        for term in set(query_terms):
            if term in tf:
                f = tf[term]
                total += self.idf[term] * f * (k1 + 1) / (f + k1 * (1 - b + b * length / self.avg_len))
        return total

    def search(self, query, k=4):
        q = tokens(query)
        ranked = sorted(((self.score(q, d), d) for d in self.docs), reverse=True)
        hits = []
        for score, doc_id in ranked[:k]:
            if score <= 0:
                break
            doc = self.docs[doc_id]
            best = max(sentences(doc.text), key=lambda s: len(set(tokens(s)) & set(q)))
            hits.append({"doc_id": doc_id, "title": doc.title, "type": doc.type, "date": doc.date,
                         "score": round(score, 2), "snippet": best})
        return hits

    def versions(self, policy):
        found = [d for d in self.docs.values() if d.type == "policy" and d.meta.get("policy") == policy]
        return sorted(found, key=lambda d: d.effective)

    def policy(self, name, as_of):
        current = [d for d in self.versions(name) if d.effective <= str(as_of)]
        return current[-1] if current else None

    def superseded_by(self, doc):
        later = [d for d in self.versions(doc.meta.get("policy")) if d.effective > doc.effective]
        return later[0] if later else None

    def in_force(self, doc, as_of):
        current = self.policy(doc.meta.get("policy"), as_of)
        return current is not None and current.id == doc.id
