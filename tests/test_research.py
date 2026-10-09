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
