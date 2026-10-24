from value_investor import research


def evidence(*items):
    e = research.Evidence()
    for title, where, text in items:
        e.add(title, where, text)
    return e


def test_evidence_skips_duplicates_and_failures():
    e = evidence(("A", "https://a.example", "one"), ("A again", "https://a.example", "two"),
                 ("B", "https://b.example", "Could not read the page: 404"), ("C", "page 1", "three"))
    assert [i["title"] for i in e.items] == ["A", "C"]


def test_search_output_is_parsed_into_hits():
    output = "[1] Title one\nhttps://one.example\nsnippet one\n\n[2] Title two\nhttps://two.example\nsnippet two"
    assert research._search_hits(output) == [
        ("Title one", "https://one.example", "snippet one"),
        ("Title two", "https://two.example", "snippet two"),
    ]


def test_finish_keeps_real_citations_and_replaces_the_source_list():
    e = evidence(("Annual report, business", "page 1", "text"), ("News", "https://n.example", "text"))
    out = research._finish("# Whatever\n\n**Verdict:** Pass [1][2][9] \u2014 maybe.\n\n## Sources\n1. made up",
                           e, "Coca-Cola: research brief")
    assert out.startswith("# Coca-Cola: research brief\n\n**Verdict:**")
    assert "[1][2]" in out and "[9]" not in out
    assert "made up" not in out
    assert "1. Annual report, business, page 1" in out
    assert "2. News <https://n.example>" in out
    assert "\u2014" not in out and "\u2013" not in out


def test_thinking_blocks_are_dropped():
    assert research._strip_thinking("<think>hmm\nlong</think>\nAnswer") == "Answer"


def test_display_name_cleans_sec_names():
    assert research.display_name("COCA COLA CO") == "Coca Cola Co"
    assert research.display_name("PROGRESSIVE CORP/OH/") == "Progressive Corp"
    assert research.display_name("Orlen S.A.") == "Orlen S.A."


def test_names_missing_from_the_cited_source_are_flagged():
    e = evidence(("Annual report, business", "page 1", "The Company sells beverages through bottling partners."),
                 ("CEO profile", "https://ceo.example", "James Quincey has been chief executive since 2017."))
    text = "The company is led by CEO James Quaker [1]. The chief executive is James Quincey [2]."
    out = research._flag_unsupported(text, e, numbers="")
    assert "James Quaker [1]. *(not found in the cited source)*" in out
    assert out.endswith("James Quincey [2].")


def test_evidence_is_trimmed_to_fit_the_writer():
    e = research.Evidence()
    for i in range(60):
        e.add(f"Page {i}", f"https://p{i}.example", "x" * 3000)
    prompt = e.as_prompt(budget=30_000)
    assert len(prompt) < 30_000 + 60 * 80
    assert prompt.count("[60]") == 1


def test_alternative_data_tools_become_evidence_with_their_links():
    e = research.Evidence()
    research.record(e, "attention_trend", {"topic": "Coca-Cola"},
                    "[Wikipedia pageviews: Coca-Cola]\nLast 12 months 1,000 views.\nSource: https://pageviews.example/x")
    research.record(e, "quarterly_results", {"ticker": "KO"}, "Latest quarter ...")
    assert e.items[0]["title"] == "Wikipedia pageviews: Coca-Cola"
    assert e.items[0]["where"] == "https://pageviews.example/x"
    assert e.items[1]["title"] == "Quarterly results, KO"


class FakeModel:
    def invoke(self, prompt):
        return type("Reply", (), {"content": "**Verdict:** Worth watching [1]."})()


def test_an_unfinished_run_resumes_after_the_last_saved_stage(tmp_path, monkeypatch):
    from contextlib import contextmanager
    from types import SimpleNamespace

    monkeypatch.setattr(research, "RESEARCH_DIR", tmp_path)

    @contextmanager
    def connect(read_only=True):
        yield None

    monkeypatch.setattr(research, "store", SimpleNamespace(connect=connect, find_cik=lambda con, t: None,
                                                           company=lambda con, cik: None))
    monkeypatch.setattr(research, "llm", SimpleNamespace(backends=lambda: ["fake"], tune=lambda p: p,
                                                         get_llm=lambda: FakeModel()))
    cp = research.Checkpoint("KO", resume=False)
    cp.numbers = "numbers"
    cp.evidence.add("Annual report, business", "page 1", "text")
    cp.save("gather")
    cp.save("competitors")
    assert research.resumable("KO") == ["gather", "competitors"]

    dug = []
    monkeypatch.setattr(research, "gather", lambda *a: (_ for _ in ()).throw(AssertionError("gathered again")))
    monkeypatch.setattr(research, "_dig", lambda role, *a, **k: dug.append(role) or f"{role} notes")
    text = research.run("KO", "Coca-Cola")
    assert dug == ["trends", "web"]
    assert text.startswith("# Coca-Cola: research brief")
    assert research.resumable("KO") is None
    assert research.status("KO")["state"] == "done"


def test_starting_over_drops_the_saved_work(tmp_path, monkeypatch):
    monkeypatch.setattr(research, "RESEARCH_DIR", tmp_path)
    research.Checkpoint("KO", resume=False).save("gather")
    assert research.Checkpoint("KO", resume=False).done == []
    assert research.resumable("KO") is None


def test_a_brief_opens_with_one_of_three_verdicts():
    from value_investor import research
    assert research.verdict("# X\n\n**Verdict:** Strong candidate. Durable brand, fair price.") == {
        "label": "Strong candidate", "reason": "Durable brand, fair price."}
    assert research.verdict("**Verdict:** worth watching, the price is high")["label"] == "Worth watching"
    assert research.verdict("**Verdict:** Buy now") is None
    assert research.verdict(None) is None


def test_queued_companies_wait_for_the_one_running(monkeypatch, tmp_path):
    import threading
    from value_investor import research
    monkeypatch.setattr(research, "RESEARCH_DIR", tmp_path)
    started, gate = [], threading.Event()
    monkeypatch.setattr(research, "run", lambda ticker, name=None: (started.append(ticker), gate.wait(5)))
    assert research.enqueue(["ma", "KO"]) == ["MA", "KO"]
    assert research.enqueue(["KO"]) == []                   # already waiting
    assert research.busy() == "MA" and research.waiting() == ["KO"]
    gate.set()
    research._running["queue"].join(5)
    assert started == ["MA", "KO"] and research.busy() is None


def test_news_without_a_tone_series_still_counts_articles(monkeypatch):
    import pandas as pd
    from value_investor import research_tools
    months = pd.date_range("2025-09-01", periods=13, freq="MS")
    volume = pd.DataFrame({"value": range(10, 23)}, index=months)
    monkeypatch.setattr(research_tools, "_gdelt",
                        lambda q, mode: volume if mode == "timelinevolraw" else pd.DataFrame())
    out = research_tools.news_trend.invoke({"query": '"Adobe"'})
    assert out.startswith('[GDELT news: "Adobe"]') and "Articles a month" in out
