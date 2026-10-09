"""22 · research: deep agents on one company, its competitors and its demand.

    gather   code collects our numbers, quarters, peers, insiders, the annual
             report, attention and news trends and a few web pages
    dig      four agents read further: filings, competitors, trends, web;
             every tool call they make is recorded as evidence
    write    one call writes the brief from numbered evidence; sources are
             added by code

the work is saved after each stage, so a run that dies picks up where it
stopped. questions go through the same machinery with one agent.
"""

import json
import logging
import os
import re
import threading
import time
import uuid
from dataclasses import dataclass, field
from datetime import date, datetime

from deepagents import create_deep_agent
from langchain_core.callbacks import BaseCallbackHandler

from value_investor import llm, prompts, store
from value_investor.research_tools import (
    RESEARCH_DIR, annual_report_section, attention_trend, company_numbers, insider_trades, news_trend,
    peer_table, quarterly_results, read_web_page, web_search,
)

logger = logging.getLogger(__name__)

AGENT_STEPS = 40
QUESTION_STEPS = 30
EXCERPT_CHARS = 2500
EVIDENCE_BUDGET = 30_000     # characters of evidence the writer sees; keeps a 16k context from overflowing
RESUME_DAYS = 7
STALLED_AFTER = 30 * 60
_running: dict = {}
_lock = threading.Lock()
_status_lock = threading.Lock()


def _safe(ticker: str) -> str:
    return re.sub(r"[^A-Za-z0-9._-]", "_", ticker.upper())


def report_path(ticker: str):
    return RESEARCH_DIR / f"{_safe(ticker)}.md"


def status_path(ticker: str):
    return RESEARCH_DIR / f"{_safe(ticker)}.json"


def partial_path(ticker: str):
    return RESEARCH_DIR / f"{_safe(ticker)}.partial.json"


def questions_path(ticker: str):
    return RESEARCH_DIR / f"{_safe(ticker)}.qa.json"


def _read_json(path, default):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return default


def _write_json(path, data) -> None:
    # agent callbacks fire from worker threads; the atomic replace keeps a reader
    # from ever seeing half a file
    RESEARCH_DIR.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(f".{uuid.uuid4().hex[:6]}.tmp")
    tmp.write_text(json.dumps(data, default=str, indent=1, ensure_ascii=False), encoding="utf-8")
    os.replace(tmp, path)


def _write_status(ticker: str, **fields) -> dict:
    with _status_lock:
        path = status_path(ticker)
        current = _read_json(path, {}) if path.exists() else {}
        current.update(fields)
        _write_json(path, current)
        return current


def status(ticker: str) -> "dict | None":
    path = status_path(ticker)
    if not path.exists():
        return None
    current = _read_json(path, {})
    if current.get("state") in ("queued", "running") and time.time() - path.stat().st_mtime > STALLED_AFTER:
        current["state"] = "stalled"
    partial = resumable(ticker)
    if partial:
        current["resumable"] = partial
    return current


def resumable(ticker: str) -> "list | None":
    """stages already done by a run that didn't finish, if it's recent enough to pick up."""
    path = partial_path(ticker)
    if not path.exists() or time.time() - path.stat().st_mtime > RESUME_DAYS * 86400:
        return None
    return _read_json(path, {}).get("done") or None


def report(ticker: str) -> "str | None":
    path = report_path(ticker)
    return path.read_text(encoding="utf-8") if path.exists() else None


@dataclass
class Evidence:
    items: list = field(default_factory=list)   # dicts: title, where, text
    seen: set = field(default_factory=set)

    def add(self, title: str, where: str, text: str) -> None:
        key = where or title
        if not text or key in self.seen or text.startswith(
                ("Could not", "Only public", "Not an HTML", "Search failed", "No ", "Too little")):
            return
        self.seen.add(key)
        self.items.append({"title": title.strip()[:160], "where": where, "text": text.strip()[:EXCERPT_CHARS]})

    def as_prompt(self, budget: int = EVIDENCE_BUDGET) -> str:
        if not self.items:
            return "(none)"
        each = max(400, min(EXCERPT_CHARS, budget // len(self.items)))
        return "\n\n".join(f"[{i}] {e['title']} ({e['where']})\n{e['text'][:each]}"
                           for i, e in enumerate(self.items, start=1))

    def dump(self) -> dict:
        return {"items": self.items, "seen": sorted(self.seen)}

    @classmethod
    def load(cls, data: dict) -> "Evidence":
        return cls(items=list(data.get("items", [])), seen=set(data.get("seen", [])))


def _search_hits(output: str) -> list:
    """(title, url, snippet) from web_search's numbered output."""
    hits = []
    for block in output.split("\n\n"):
        lines = block.strip().splitlines()
        if len(lines) >= 2 and lines[1].startswith("http"):
            hits.append((re.sub(r"^\[\d+\]\s*", "", lines[0]), lines[1].strip(), " ".join(lines[2:])))
    return hits


def _source_line(text: str) -> str:
    found = re.search(r"^Source: (\S+)", text, flags=re.M)
    return found.group(1) if found else ""


def record(evidence: Evidence, name: str, inputs: dict, text: str) -> None:
    """what a tool returned, as evidence the writer can cite."""
    ticker = inputs.get("ticker", "")
    if name == "read_web_page":
        evidence.add(text.split("\n", 1)[0].strip("[]"), inputs.get("url", ""), text)
    elif name == "annual_report_section":
        evidence.add(f"Annual report, {inputs.get('section', 'business')}", f"page {inputs.get('page', 1)}", text)
    elif name == "web_search":
        for title, url, snippet in _search_hits(text)[:3]:
            evidence.add(title, url, snippet)
    elif name == "quarterly_results":
        evidence.add(f"Quarterly results, {ticker}", "computed from 10-Q / Yahoo quarterly statements", text)
    elif name == "peer_table":
        evidence.add(f"Peer comparison, {ticker}", "computed from stored statements", text)
    elif name == "insider_trades":
        evidence.add(f"Insider trades, {ticker}", "SEC form 4 filings", text)
    elif name in ("attention_trend", "news_trend"):
        evidence.add(text.split("\n", 1)[0].strip("[]"), _source_line(text), text)


class Recorder(BaseCallbackHandler):
    """turns every tool call an agent makes into evidence."""

    def __init__(self, evidence: Evidence, on_step=None):
        self.evidence = evidence
        self.on_step = on_step
        self._pending: dict = {}

    def on_tool_start(self, serialized, input_str, *, run_id, inputs=None, **kwargs):
        self._pending[run_id] = ((serialized or {}).get("name") or kwargs.get("name"), inputs or {})
        if self.on_step:
            self.on_step(self._pending[run_id][0])

    def on_tool_end(self, output, *, run_id, **kwargs):
        name, inputs = self._pending.pop(run_id, (None, {}))
        text = getattr(output, "content", output)
        record(self.evidence, name, inputs, text if isinstance(text, str) else str(text))


def _call(tool, evidence: Evidence, **inputs) -> str:
    text = tool.invoke(inputs)
    record(evidence, tool.name, inputs, text)
    return text


def gather(ticker: str, name: str, evidence: Evidence, is_sec: bool) -> str:
    numbers = company_numbers.invoke({"ticker": ticker})
    _call(quarterly_results, evidence, ticker=ticker)
    _call(peer_table, evidence, ticker=ticker)
    if is_sec:
        _call(insider_trades, evidence, ticker=ticker)
        for section in ("business", "risk_factors"):
            _call(annual_report_section, evidence, ticker=ticker, section=section, page=1)
    _call(attention_trend, evidence, topic=name)
    _call(news_trend, evidence, query=f'"{name}"')
    year = date.today().year
    queries = [f"{name} competitors market share", f"{name} CEO management insider buying", f"{name} news {year}"]
    if not is_sec:
        queries.insert(0, f"{name} annual report {year - 1} business overview")
    for query in queries:
        output = web_search.invoke({"query": query, "max_results": 4})
        hits = _search_hits(output)
        for title, url, snippet in hits[:2]:
            evidence.add(title, url, snippet)
        for _, url, _ in hits[:2]:
            page = read_web_page.invoke({"url": url})
            if not page.startswith(("Could not", "Only public", "Not an HTML")):
                evidence.add(page.split("\n", 1)[0].strip("[]"), url, page)
                break
    return numbers


ROLES = {
    "filings": (prompts.FILINGS_READER, [company_numbers, annual_report_section],
                "Read the annual report of {name} (ticker {ticker}) beyond page 1 of the business and "
                "risk_factors sections, and the mda section. Summarise what matters for a long-term owner."),
    "competitors": (prompts.COMPETITOR_ANALYST, [peer_table, company_numbers, web_search, read_web_page],
                    "Size up {name} (ticker {ticker}) against its competitors. Start with peer_table, then "
                    "look up the main competitors on the web. Read at least three pages."),
    "trends": (prompts.TREND_ANALYST,
               [quarterly_results, attention_trend, news_trend, insider_trades, web_search, read_web_page],
               "Find out whether demand for {name} (ticker {ticker}) and its main products is rising or "
               "falling, using the alternative data tools and the web. Check at least two brands or products."),
    "web": (prompts.WEB_RESEARCHER, [web_search, read_web_page],
            "Research {name} (ticker {ticker}) on the web: management and how long they've been there, "
            "recent news and controversies, lawsuits or accounting questions, why the share price moved. "
            "Read at least three pages with read_web_page."),
}


def _agent_notes(state) -> str:
    for msg in reversed(state.get("messages") or []):
        if getattr(msg, "type", "") == "ai" and isinstance(msg.content, str) and msg.content.strip():
            return _strip_thinking(msg.content)
    return ""


def _dig(role: str, ticker: str, name: str, recorder: Recorder, task: "str | None" = None,
         steps: int = AGENT_STEPS) -> str:
    system, tools, default_task = ROLES[role] if role in ROLES else (prompts.QUESTION_RESEARCHER, ALL_TOOLS, "")
    agent = create_deep_agent(model=llm.get_llm(), tools=tools, system_prompt=llm.tune(system), name=f"{role}-agent")
    state = agent.invoke({"messages": [{"role": "user", "content": task or default_task.format(name=name, ticker=ticker)}]},
                         config={"recursion_limit": steps, "callbacks": [recorder]})
    return _agent_notes(state)


ALL_TOOLS = [company_numbers, quarterly_results, peer_table, insider_trades, annual_report_section,
             attention_trend, news_trend, web_search, read_web_page]


def display_name(name: str) -> str:
    """'COCA COLA CO' and 'PROGRESSIVE CORP/OH/' read badly in search queries and titles."""
    name = re.sub(r"\s*/[A-Z]{2,3}/?$", "", (name or "").strip())
    return name.title() if name.isupper() else name


def _no_dashes(text: str) -> str:
    text = re.sub("\\s*\u2014\\s*", ", ", text)
    return text.replace("\u2013", "-")


def _strip_thinking(text: str) -> str:
    return re.sub(r"<think>.*?</think>", "", text, flags=re.S).strip()


NAME = re.compile(r"(?<![.!?]\s)(?<!^)\b([A-Z][a-z]+(?:\s+[A-Z][a-z]+)+)\b")


def _flag_unsupported(text: str, evidence: Evidence, numbers: str) -> str:
    """mark sentences whose people or place names aren't in the sources they cite.
    a small model once wrote "CEO James Quaker" and cited a report that names no CEO."""
    def check(sentence: str) -> str:
        cited = [int(n) for n in re.findall(r"\[(\d+)\]", sentence)]
        if not cited:
            return sentence
        haystack = numbers.lower() + " " + " ".join(
            (evidence.items[n - 1]["title"] + " " + evidence.items[n - 1]["text"]).lower()
            for n in cited if 1 <= n <= len(evidence.items))
        missing = [found for found in NAME.findall(sentence) if found.lower() not in haystack]
        return sentence + " *(not found in the cited source)*" if missing else sentence

    parts = re.split(r"(?<=[.!?])(\s+)", text)
    return "".join(check(p) if not p.isspace() else p for p in parts)


def _clean(text: str, evidence: Evidence, numbers: str) -> str:
    text = _strip_thinking(text)
    text = re.split(r"\n#+\s*Sources\b", text)[0].rstrip()
    n = len(evidence.items)
    text = re.sub(r"\[(\d+)\]", lambda m: m.group(0) if 1 <= int(m.group(1)) <= n else "", text)
    return _flag_unsupported(text, evidence, numbers)


def _source(i: int, e: dict) -> str:
    where = e["where"]
    return f"{i}. {e['title']}" + (f" <{where}>" if where.startswith("http") else f", {where}" if where else "")


def _finish(text: str, evidence: Evidence, title: str, numbers: str = "") -> str:
    lines = _clean(text, evidence, numbers).splitlines()
    if lines and lines[0].startswith("# "):
        lines = lines[1:]
    lines = [f"# {title}", ""] + lines
    while len(lines) > 2 and not lines[2].strip():
        del lines[2]
    sources = [_source(i, e) for i, e in enumerate(evidence.items, start=1)]
    body = "\n".join(lines) + "\n\n## Sources\n\n" + "\n".join(sources) + "\n"
    return _no_dashes(body)


class Checkpoint:
    """the evidence and notes of a run in progress, saved after every stage."""

    def __init__(self, ticker: str, resume: bool):
        self.path = partial_path(ticker)
        data = _read_json(self.path, {}) if resume and resumable(ticker) else {}
        if not resume and self.path.exists():
            self.path.unlink()
        self.done = list(data.get("done", []))
        self.notes = list(data.get("notes", []))
        self.numbers = data.get("numbers", "")
        self.evidence = Evidence.load(data.get("evidence", {}))

    def save(self, stage: str) -> None:
        if stage not in self.done:
            self.done.append(stage)
        _write_json(self.path, {"done": self.done, "notes": self.notes, "numbers": self.numbers,
                                "evidence": self.evidence.dump(), "saved_at": datetime.now()})

    def clear(self) -> None:
        if self.path.exists():
            self.path.unlink()


def run(ticker: str, name: "str | None" = None, dig: bool = True, resume: bool = True) -> "str | None":
    """research one company end to end. blocks; returns the report text."""
    ticker = ticker.upper()
    started = datetime.now()
    steps = {"n": 0}

    def step(label):
        steps["n"] += 1
        _write_status(ticker, steps=steps["n"], last_step=label)

    try:
        with store.connect(read_only=True) as con:
            cik = store.find_cik(con, ticker)
            comp = (store.company(con, cik) or {}) if cik else {}
        name = display_name(name or comp.get("name") or ticker)
        is_sec = comp.get("source") == "sec" and (cik or 0) > 0

        cp = Checkpoint(ticker, resume)
        _write_status(ticker, state="running", started_at=started, finished_at=None, steps=0, error=None,
                      last_step="resuming after " + ", ".join(cp.done) if cp.done else "gathering evidence",
                      backends=llm.backends(), resumed=bool(cp.done))
        if "gather" not in cp.done:
            cp.numbers = gather(ticker, name, cp.evidence, is_sec)
            cp.save("gather")
        step(f"evidence: {len(cp.evidence.items)} items")

        if dig:
            recorder = Recorder(cp.evidence, on_step=step)
            for role in (["filings"] if is_sec else []) + ["competitors", "trends", "web"]:
                if role in cp.done:
                    continue
                _write_status(ticker, last_step=f"{role} agent reading")
                try:
                    found = _dig(role, ticker, name, recorder)
                    if found:
                        cp.notes.append(f"{role.title()} analyst notes:\n{found}")
                except Exception as exc:
                    logger.warning("%s agent failed for %s: %s", role, ticker, exc)
                cp.save(role)

        _write_status(ticker, last_step=f"writing from {len(cp.evidence.items)} sources")
        title = f"{name}: research brief"
        prompt = prompts.writer(title, cp.numbers, cp.evidence.as_prompt(), "\n\n".join(cp.notes))
        reply = llm.get_llm().invoke(llm.tune(prompt))
        text = _finish(getattr(reply, "content", str(reply)), cp.evidence, title, cp.numbers)
        evidence_path = RESEARCH_DIR / f"{_safe(ticker)}.evidence.json"
        evidence_path.write_text(json.dumps(cp.evidence.items, ensure_ascii=False, indent=1), encoding="utf-8")
        report_path(ticker).write_text(text, encoding="utf-8")
        cp.clear()
        _write_status(ticker, state="done", finished_at=datetime.now(), sources=len(cp.evidence.items),
                      minutes=round((time.time() - started.timestamp()) / 60, 1))
        return text
    except Exception as exc:
        logger.exception("research failed for %s", ticker)
        try:
            _write_status(ticker, state="error", finished_at=datetime.now(), error=str(exc)[:500])
        except Exception:
            pass
        return None


def start_in_background(ticker: str, name: "str | None" = None, resume: bool = True) -> bool:
    """kick off a run from the dashboard. one at a time: a laptop model can't take two."""
    with _lock:
        if any(t.is_alive() for t in _running.values()):
            return False
        thread = threading.Thread(target=run, args=(ticker, name), kwargs={"resume": resume}, daemon=True,
                                  name=f"research-{ticker}")
        _running[ticker.upper()] = thread
        _write_status(ticker.upper(), state="queued", started_at=datetime.now(), error=None)
        thread.start()
        return True


def busy() -> "str | None":
    with _lock:
        for ticker, thread in _running.items():
            if thread.is_alive():
                return ticker
    return None


# questions

_ask_lock = threading.Lock()


def questions(ticker: str) -> list:
    items = _read_json(questions_path(ticker), [])
    for q in items:
        if q.get("state") == "running" and time.time() - datetime.fromisoformat(q["asked_at"]).timestamp() > STALLED_AFTER:
            q["state"] = "stalled"
    return items


def _update_question(ticker: str, qid: str, **fields) -> None:
    with _ask_lock:
        items = _read_json(questions_path(ticker), [])
        for q in items:
            if q["id"] == qid:
                q.update(fields)
        _write_json(questions_path(ticker), items)


def ask(ticker: str, question: str, qid: str, name: "str | None" = None) -> "str | None":
    """answer one question about a company, with sources. blocks."""
    ticker = ticker.upper()
    try:
        with store.connect(read_only=True) as con:
            cik = store.find_cik(con, ticker)
            comp = (store.company(con, cik) or {}) if cik else {}
        name = display_name(name or comp.get("name") or ticker)
        evidence = Evidence()
        numbers = company_numbers.invoke({"ticker": ticker})
        recorder = Recorder(evidence, on_step=lambda label: _update_question(ticker, qid, last_step=label))
        task = f"Company: {name} (ticker {ticker}). Question: {question}"
        notes = _dig("question", ticker, name, recorder, task=task, steps=QUESTION_STEPS)
        prompt = prompts.answer(question, name, numbers, evidence.as_prompt(),
                                f"Research notes:\n{notes}" if notes else "")
        reply = llm.get_llm().invoke(llm.tune(prompt))
        text = _clean(getattr(reply, "content", str(reply)), evidence, numbers)
        cited = sorted({int(n) for n in re.findall(r"\[(\d+)\]", text)})
        sources = [_source(i, evidence.items[i - 1]) for i in cited]
        answer = _no_dashes(text + ("\n\n" + "\n".join(sources) if sources else ""))
        _update_question(ticker, qid, state="done", answer=answer, answered_at=datetime.now().isoformat())
        return answer
    except Exception as exc:
        logger.exception("question failed for %s", ticker)
        _update_question(ticker, qid, state="error", error=str(exc)[:300])
        return None


def start_question(ticker: str, question: str, name: "str | None" = None) -> "str | None":
    question = " ".join(question.split())[:500]
    if not question:
        return None
    ticker = ticker.upper()
    qid = uuid.uuid4().hex[:10]
    with _ask_lock:
        items = _read_json(questions_path(ticker), [])
        if any(q.get("state") == "running" for q in items):
            return None
        items.insert(0, {"id": qid, "question": question, "state": "running",
                         "asked_at": datetime.now().isoformat(), "backends": llm.backends()})
        _write_json(questions_path(ticker), items[:30])
    threading.Thread(target=ask, args=(ticker, question, qid, name), daemon=True, name=f"ask-{ticker}").start()
    return qid

