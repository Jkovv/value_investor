"""38 · evals: do the research briefs say what their sources say?

a brief cites numbered sources. every sentence that cites one is checked against the
excerpts the writer was actually given for those sources, by a larger model than the
writer (groq's free gpt-oss-120b by default): supported, partly, not in the source, or
contradicted. verdicts are cached, so a run that hits the daily limit carries on the
next day. a sample of sentences can be marked by hand to see how far the judge itself
can be trusted.
"""

import csv
import hashlib
import json
import logging
import random
import re
import time
from collections import deque

import litellm

from value_investor import config
from value_investor.research import EVIDENCE_BUDGET, EXCERPT_CHARS, NAME
from value_investor.research_tools import RESEARCH_DIR

logger = logging.getLogger(__name__)

DIR = config.DATA_DIR / "evals"
VERDICTS = ("supported", "partly", "not_in_source", "contradicted")
TOKENS_PER_MINUTE = 7000            # groq's free tier allows 8,000; leave some room
FLAG = "*(not found in the cited source)*"
# places and titles everyone knows; not the kind of name a model makes up
COMMON = {"united states", "north america", "south america", "latin america", "central america", "southeast asia",
          "middle east", "asia pacific", "vice chairman"}

JUDGE = """You check one sentence from a research brief against the sources it cites.

Sources (the excerpts the writer was given):
{sources}

Sentence: {claim}

Is every factual statement in the sentence backed by these excerpts? Judge only against the
excerpts, not against what you know. Opinions and recommendations that follow reasonably from the
excerpts count as backed.

Answer with JSON only: {{"verdict": "supported" | "partly" | "not_in_source" | "contradicted",
"reason": "one short sentence"}}
- supported: every fact in the sentence is in the excerpts
- partly: some facts are, at least one is not
- not_in_source: the main fact isn't in the excerpts
- contradicted: the excerpts say something different"""


def briefs() -> list:
    """tickers whose brief was saved together with its evidence."""
    return sorted(p.name[: -len(".evidence.json")] for p in RESEARCH_DIR.glob("*.evidence.json")
                  if (RESEARCH_DIR / p.name.replace(".evidence.json", ".md")).exists())


def claims(report: str) -> list:
    """every sentence of a brief that cites a source, with its section and the sources it cites.
    the sources list at the end isn't part of the brief."""
    body = re.split(r"\n## Sources\b", report)[0]
    out, section = [], ""
    for block in body.split("\n"):
        heading = re.match(r"^#+\s+(.*)", block)
        if heading:
            section = heading.group(1).strip()
            continue
        text = re.sub(r"^\s*[-*]\s+", "", block).strip()
        for sentence in re.split(r"(?<=[.!?])\s+(?=[A-Z*\[(])", text):
            cited = sorted({int(n) for n in re.findall(r"\[(\d+)\]", sentence)})
            if cited and len(sentence) > 20:
                flagged = FLAG in sentence
                clean = sentence.replace(FLAG, "").strip()
                out.append({"section": section, "claim": clean, "cited": cited, "flagged": flagged})
    return out


def evidence(ticker: str) -> tuple:
    """the sources a brief was written from, and the numbers block the writer saw with them.
    briefs saved before the numbers were kept get them rebuilt from the stored data."""
    data = json.loads((RESEARCH_DIR / f"{ticker}.evidence.json").read_text(encoding="utf-8"))
    if isinstance(data, dict):
        return data["items"], data.get("numbers") or ""
    try:
        from value_investor.research_tools import company_numbers
        return data, company_numbers.invoke({"ticker": ticker})
    except Exception:
        return data, ""


def unsourced_names(report: str, items: list, numbers: str = "") -> list:
    """sentences that cite nothing and name someone or something no source mentions; a small
    model fills gaps with names it remembers."""
    body = re.split(r"\n## Sources\b", report)[0]
    haystack = numbers + " " + " ".join(e["title"] + " " + e["text"] for e in items)
    haystack = re.sub(r"\s+", " ", re.sub(r"[()]", "", haystack)).lower()     # "Zhang (Xiulan)"
    out = []
    for block in body.split("\n"):
        if block.startswith("#"):
            continue
        for sentence in re.split(r"(?<=[.!?])\s+", block):
            if re.search(r"\[\d+\]", sentence):
                continue
            missing = [n for n in NAME.findall(sentence) if n.lower() not in haystack and n.lower() not in COMMON]
            if missing:
                out.append({"sentence": sentence.strip()[:300], "names": missing})
    return out


def sentences(report: str) -> int:
    body = re.split(r"\n## Sources\b", report)[0]
    body = "\n".join(line for line in body.split("\n") if not line.startswith("#"))
    return len([s for s in re.split(r"(?<=[.!?])\s+", body) if len(s.strip()) > 20])


def excerpts(items: list, cited: list) -> str:
    """the cited sources cut to the length the writer saw them at."""
    each = max(400, min(EXCERPT_CHARS, EVIDENCE_BUDGET // max(len(items), 1)))
    return "\n\n".join(f"[{n}] {items[n - 1]['title']} ({items[n - 1]['where']})\n{items[n - 1]['text'][:each]}"
                       for n in cited if 1 <= n <= len(items))


def kind_of(item: dict) -> str:
    """what sort of source a piece of evidence is."""
    where, title = item.get("where", ""), item.get("title", "")
    if where.startswith("http"):
        return "web page or search result"
    if title.startswith("Annual report"):
        return "annual report"
    if "computed" in where or "form 4" in where.lower():
        return "our own numbers"
    return "attention and news trends"


def _key(ticker: str, claim: str, sources: str) -> str:
    return hashlib.sha1(f"{ticker}|{claim}|{sources}".encode()).hexdigest()[:16]


class Judge:
    """one model call per sentence, paced under the free tier's tokens a minute."""

    def __init__(self, model: "str | None" = None):
        self.model = model or f"groq/{config.GROQ_MODEL}"
        self.path = DIR / "verdicts.json"
        self.cache = json.loads(self.path.read_text(encoding="utf-8")) if self.path.exists() else {}
        self.spent: deque = deque()

    def _pace(self, tokens: int) -> None:
        while True:
            now = time.monotonic()
            while self.spent and now - self.spent[0][0] > 60:
                self.spent.popleft()
            if sum(t for _, t in self.spent) + tokens <= TOKENS_PER_MINUTE:
                self.spent.append((now, tokens))
                return
            time.sleep(2)

    def __call__(self, ticker: str, claim: str, sources: str) -> "dict | None":
        key = _key(ticker, claim, sources)
        if key in self.cache:
            return self.cache[key]
        prompt = JUDGE.format(sources=sources, claim=claim)
        for attempt in range(4):
            self._pace(len(prompt) // 3 + 400)
            try:
                reply = litellm.completion(model=self.model, api_key=config.GROQ_API_KEY,
                                           messages=[{"role": "user", "content": prompt}], temperature=0,
                                           reasoning_effort="low", response_format={"type": "json_object"})
                found = json.loads(reply.choices[0].message.content)
                if found.get("verdict") in VERDICTS:
                    self.cache[key] = {"verdict": found["verdict"], "reason": str(found.get("reason", ""))[:300]}
                    self._save()
                    return self.cache[key]
            except litellm.RateLimitError as exc:
                if "per day" in str(exc).lower() or "tokens per day" in str(exc).lower():
                    logger.warning("judge: daily limit reached, run again tomorrow")
                    return None
                time.sleep(30 * (attempt + 1))
            except Exception as exc:
                logger.warning("judge failed on a sentence from %s: %s", ticker, exc)
                time.sleep(5)
        return None

    def _save(self) -> None:
        DIR.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(self.cache, indent=1, ensure_ascii=False), encoding="utf-8")


def grade(tickers=None, judge: "Judge | None" = None) -> list:
    """one row per cited sentence, with the judge's verdict when it has one."""
    judge = judge or Judge()
    rows = []
    for ticker in tickers or briefs():
        report = (RESEARCH_DIR / f"{ticker}.md").read_text(encoding="utf-8")
        items, _ = evidence(ticker)
        for c in claims(report):
            sources = excerpts(items, c["cited"])
            verdict = judge(ticker, c["claim"], sources) if sources else None
            rows.append({"ticker": ticker, **c, "kinds": sorted({kind_of(items[n - 1]) for n in c["cited"]
                                                                  if 1 <= n <= len(items)}),
                         "id": _key(ticker, c["claim"], sources),
                         "verdict": verdict["verdict"] if verdict else None,
                         "reason": verdict["reason"] if verdict else None})
    return rows


def _shares(rows: list) -> dict:
    judged = [r for r in rows if r["verdict"]]
    n = len(judged)
    out = {"sentences": len(rows), "judged": n}
    for v in VERDICTS:
        out[v] = sum(r["verdict"] == v for r in judged) / n if n else None
    return out


def summarise(rows: list, tickers=None) -> dict:
    tickers = tickers or sorted({r["ticker"] for r in rows})
    cited_share, unsourced = {}, {}
    for t in tickers:
        report = (RESEARCH_DIR / f"{t}.md").read_text(encoding="utf-8")
        items, numbers = evidence(t)
        total = sentences(report)
        cited_share[t] = len([r for r in rows if r["ticker"] == t]) / total if total else None
        unsourced[t] = unsourced_names(report, items, numbers)
    by_kind = {}
    for r in rows:
        for k in r["kinds"]:
            by_kind.setdefault(k, []).append(r)
    flagged = [r for r in rows if r["verdict"]]
    name_check = {
        "flagged": sum(r["flagged"] for r in flagged),
        "flagged_and_judged_unsupported": sum(r["flagged"] and r["verdict"] in ("not_in_source", "contradicted")
                                              for r in flagged),
    }
    return {"overall": _shares(rows), "by_brief": {t: {**_shares([r for r in rows if r["ticker"] == t]),
                                                       "cited_share": cited_share[t],
                                                       "unsourced_names": len(unsourced[t])} for t in tickers},
            "unsourced_examples": {t: v[:5] for t, v in unsourced.items()},
            "by_section": {s: _shares([r for r in rows if r["section"] == s])
                           for s in sorted({r["section"] for r in rows})},
            "by_source": {k: _shares(v) for k, v in sorted(by_kind.items())}, "name_check": name_check,
            "judge": Judge().model, "writer": f"ollama/{config.OLLAMA_MODEL}"}


def write_sample(rows: list, n: int = 60, seed: int = 7) -> "str | None":
    """a random sample of judged sentences to mark by hand, without the judge's verdict."""
    judged = [r for r in rows if r["verdict"]]
    if not judged:
        return None
    sample = random.Random(seed).sample(judged, min(n, len(judged)))
    DIR.mkdir(parents=True, exist_ok=True)
    path = DIR / "labels.csv"
    if path.exists():
        return str(path)
    with path.open("w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(["id", "ticker", "claim", "sources", "your_verdict"])
        for r in sample:
            items, _ = evidence(r["ticker"])
            w.writerow([r["id"], r["ticker"], r["claim"], excerpts(items, r["cited"]), ""])
    return str(path)


def human_agreement(rows: list) -> "dict | None":
    """how often the judge agrees with the sentences marked by hand, and cohen's kappa."""
    path = DIR / "labels.csv"
    if not path.exists():
        return None
    with path.open(encoding="utf-8") as fh:
        marked = {r["id"]: r["your_verdict"].strip() for r in csv.DictReader(fh) if r["your_verdict"].strip()}
    pairs = [(marked[r["id"]], r["verdict"]) for r in rows if r["id"] in marked and r["verdict"]]
    pairs = [(h, j) for h, j in pairs if h in VERDICTS]
    if not pairs:
        return None
    n = len(pairs)
    agree = sum(h == j for h, j in pairs) / n
    expected = sum((sum(h == v for h, _ in pairs) / n) * (sum(j == v for _, j in pairs) / n) for v in VERDICTS)
    kappa = (agree - expected) / (1 - expected) if expected < 1 else None
    return {"marked": n, "agreement": agree, "kappa": kappa}


def save(result: dict, rows: list) -> None:
    DIR.mkdir(parents=True, exist_ok=True)
    (DIR / "results.json").write_text(json.dumps(result, indent=1, ensure_ascii=False), encoding="utf-8")
    (DIR / "sentences.json").write_text(json.dumps(rows, indent=1, ensure_ascii=False), encoding="utf-8")
