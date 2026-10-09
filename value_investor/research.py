"""22 · research: the deep research pipeline, one company at a time.

Small local models skip steps when left to plan everything themselves (an
early run answered from memory without opening a single source), so the
work is split into stages the model can't talk its way around:

    1. evidence   code gathers the basics: our numbers, the annual report
                  sections, three web searches and the best page for each
    2. dig        two deep agents (filings-reader, web-researcher) read
                  further with the same tools; every page they open is
                  recorded as evidence by a callback, not by the model
    3. write      one model call writes the brief from the numbered
                  evidence only; the source list is appended by code, and
                  citations that point at nothing are removed

Reports and run status are files in data/research/, not database rows: the
dashboard holds DuckDB open read-only and may start runs itself.
"""

import json
import logging
import os
import re
import threading
import time
from dataclasses import dataclass, field
from datetime import date, datetime

from deepagents import create_deep_agent
from langchain_core.callbacks import BaseCallbackHandler

from value_investor import llm, prompts, store
from value_investor.research_tools import (
    RESEARCH_DIR, annual_report_section, company_numbers, read_web_page, web_search,
)

logger = logging.getLogger(__name__)

AGENT_STEPS = 40
EXCERPT_CHARS = 2500
_running: dict = {}
_lock = threading.Lock()


def _safe(ticker: str) -> str:
    return re.sub(r"[^A-Za-z0-9._-]", "_", ticker.upper())


def report_path(ticker: str):
    return RESEARCH_DIR / f"{_safe(ticker)}.md"


def status_path(ticker: str):
    return RESEARCH_DIR / f"{_safe(ticker)}.json"


STALLED_AFTER = 45 * 60
_status_lock = threading.Lock()


def _read_status(path) -> dict:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def _write_status(ticker: str, **fields) -> dict:
    # Agent callbacks fire from worker threads; without the lock and the atomic
    # replace, two writers once interleaved and left half a JSON file behind.
    with _status_lock:
        RESEARCH_DIR.mkdir(parents=True, exist_ok=True)
        path = status_path(ticker)
        current = _read_status(path) if path.exists() else {}
        current.update(fields)
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps(current, default=str, indent=2), encoding="utf-8")
        os.replace(tmp, path)
        return current


def status(ticker: str) -> "dict | None":
    path = status_path(ticker)
    if not path.exists():
        return None
    current = _read_status(path)
    if current.get("state") in ("queued", "running") and time.time() - path.stat().st_mtime > STALLED_AFTER:
        current["state"] = "stalled"
    return current


def report(ticker: str) -> "str | None":
    path = report_path(ticker)
    return path.read_text(encoding="utf-8") if path.exists() else None


@dataclass
class Evidence:
    items: list = field(default_factory=list)   # dicts: title, where, text
    seen: set = field(default_factory=set)

    def add(self, title: str, where: str, text: str) -> None:
        key = where or title
        if not text or key in self.seen or text.startswith(("Could not", "Only public", "Not an HTML", "Search failed")):
            return
        self.seen.add(key)
        self.items.append({"title": title.strip()[:160], "where": where, "text": text.strip()[:EXCERPT_CHARS]})

    def as_prompt(self) -> str:
        return "\n\n".join(f"[{i}] {e['title']} ({e['where']})\n{e['text']}"
                           for i, e in enumerate(self.items, start=1))


def _search_hits(output: str) -> list:
    """(title, url, snippet) from web_search's numbered output."""
    hits = []
    for block in output.split("\n\n"):
        lines = block.strip().splitlines()
        if len(lines) >= 2 and lines[1].startswith("http"):
            hits.append((re.sub(r"^\[\d+\]\s*", "", lines[0]), lines[1].strip(), " ".join(lines[2:])))
    return hits


class Recorder(BaseCallbackHandler):
    """Turns every page and report section an agent reads into evidence."""

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
        text = text if isinstance(text, str) else str(text)
        if name == "read_web_page":
            self.evidence.add(text.split("\n", 1)[0].strip("[]"), inputs.get("url", ""), text)
        elif name == "annual_report_section":
            self.evidence.add(f"Annual report, {inputs.get('section', 'business')}",
                              f"page {inputs.get('page', 1)}", text)
        elif name == "web_search":
            for title, url, snippet in _search_hits(text)[:3]:
                self.evidence.add(title, url, snippet)


def gather(ticker: str, name: str, evidence: Evidence, is_sec: bool) -> str:
    numbers = company_numbers.invoke({"ticker": ticker})
    if is_sec:
        for section in ("business", "risk_factors"):
            text = annual_report_section.invoke({"ticker": ticker, "section": section, "page": 1})
            evidence.add(f"Annual report, {section}", "page 1", text)
    year = date.today().year
    queries = [
        f"{name} competitors market share",
        f"{name} CEO management insider buying",
        f"{name} news {year}",
    ]
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


def _dig(role: str, ticker: str, name: str, evidence: Evidence, recorder: Recorder) -> str:
    if role == "filings":
        system, tools = prompts.FILINGS_READER, [company_numbers, annual_report_section]
        task = (f"Read the annual report of {name} (ticker {ticker}) beyond page 1 of the business and "
                f"risk_factors sections, and the mda section. Summarise what matters for a long-term owner.")
    else:
        system, tools = prompts.WEB_RESEARCHER, [web_search, read_web_page]
        task = (f"Research {name} (ticker {ticker}) on the web: competitors and market share, management "
                f"and insider trades, recent news and controversies, why the share price moved. "
                f"Read at least three pages with read_web_page.")
    agent = create_deep_agent(model=llm.get_llm(), tools=tools, system_prompt=llm.tune(system),
                              name=f"{role}-reader")
    state = agent.invoke({"messages": [{"role": "user", "content": task}]},
                         config={"recursion_limit": AGENT_STEPS, "callbacks": [recorder]})
    for msg in reversed(state.get("messages") or []):
        if getattr(msg, "type", "") == "ai" and isinstance(msg.content, str) and msg.content.strip():
            return msg.content.strip()
    return ""


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
    """Mark sentences whose people or place names don't appear in the sources they cite.

    A small model once wrote "CEO James Quaker" and cited the annual report,
    which names no CEO at all. Two-word proper names are cheap to check.
    """
    def check(sentence: str) -> str:
        cited = [int(n) for n in re.findall(r"\[(\d+)\]", sentence)]
        if not cited:
            return sentence
        haystack = numbers.lower() + " " + " ".join(
            (evidence.items[n - 1]["title"] + " " + evidence.items[n - 1]["text"]).lower()
            for n in cited if 1 <= n <= len(evidence.items))
        missing = [name for name in NAME.findall(sentence) if name.lower() not in haystack]
        return sentence + " *(not found in the cited source)*" if missing else sentence

    parts = re.split(r"(?<=[.!?])(\s+)", text)
    return "".join(check(p) if not p.isspace() else p for p in parts)


def _finish(text: str, evidence: Evidence, title: str, numbers: str = "") -> str:
    text = _strip_thinking(text)
    text = re.split(r"\n#+\s*Sources\b", text)[0].rstrip()
    n = len(evidence.items)
    text = re.sub(r"\[(\d+)\]", lambda m: m.group(0) if 1 <= int(m.group(1)) <= n else "", text)
    text = _flag_unsupported(text, evidence, numbers)
    lines = text.splitlines()
    if lines and lines[0].startswith("# "):
        lines = lines[1:]
    lines = [f"# {title}", ""] + [line for line in lines if line.strip() or True]
    while len(lines) > 2 and not lines[2].strip():
        del lines[2]
    sources = [f"{i}. {e['title']}" + (f" <{e['where']}>" if e["where"].startswith("http") else f", {e['where']}")
               for i, e in enumerate(evidence.items, start=1)]
    body = "\n".join(lines) + "\n\n## Sources\n\n" + "\n".join(sources) + "\n"
    return _no_dashes(body)


def run(ticker: str, name: "str | None" = None, dig: bool = True) -> "str | None":
    """Research one company end to end. Blocks; returns the report text."""

    ticker = ticker.upper()
    started = datetime.now()
    steps = {"n": 0}

    def step(label):
        steps["n"] += 1
        _write_status(ticker, steps=steps["n"], last_step=label)

    _write_status(ticker, state="running", started_at=started, finished_at=None, steps=0,
                  last_step="gathering evidence", error=None, backends=llm.backends())
    try:
        with store.connect(read_only=True) as con:
            cik = store.find_cik(con, ticker)
            comp = (store.company(con, cik) or {}) if cik else {}
        name = display_name(name or comp.get("name") or ticker)
        is_sec = comp.get("source") == "sec" and (cik or 0) > 0

        evidence = Evidence()
        numbers = gather(ticker, name, evidence, is_sec)
        step(f"evidence: {len(evidence.items)} items")

        notes = []
        if dig:
            recorder = Recorder(evidence, on_step=step)
            for role in (["filings"] if is_sec else []) + ["web"]:
                _write_status(ticker, last_step=f"{role} agent reading")
                try:
                    found = _dig(role, ticker, name, evidence, recorder)
                    if found:
                        notes.append(f"{role.title()} analyst notes:\n{_strip_thinking(found)}")
                except Exception as exc:
                    logger.warning("%s agent failed for %s: %s", role, ticker, exc)

        _write_status(ticker, last_step=f"writing from {len(evidence.items)} sources")
        title = f"{name}: research brief"
        prompt = prompts.writer(title, numbers, evidence.as_prompt(), "\n\n".join(notes))
        reply = llm.get_llm().invoke(llm.tune(prompt))
        text = _finish(getattr(reply, "content", str(reply)), evidence, title, numbers)
        evidence_path = RESEARCH_DIR / f"{_safe(ticker)}.evidence.json"
        evidence_path.write_text(json.dumps(evidence.items, ensure_ascii=False, indent=1), encoding="utf-8")
        report_path(ticker).write_text(text, encoding="utf-8")
        _write_status(ticker, state="done", finished_at=datetime.now(), sources=len(evidence.items),
                      minutes=round((time.time() - started.timestamp()) / 60, 1))
        return text
    except Exception as exc:
        logger.exception("research failed for %s", ticker)
        try:
            _write_status(ticker, state="error", finished_at=datetime.now(), error=str(exc)[:500])
        except Exception:
            pass
        return None


def start_in_background(ticker: str, name: "str | None" = None) -> bool:
    """Kick off a run from the dashboard. One run at a time: a laptop model can't take two."""
    with _lock:
        if any(t.is_alive() for t in _running.values()):
            return False
        thread = threading.Thread(target=run, args=(ticker, name), daemon=True, name=f"research-{ticker}")
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
