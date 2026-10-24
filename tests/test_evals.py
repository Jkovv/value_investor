import json

import pytest

from value_investor import evals

BRIEF = """# Acme: research brief

**Verdict:** Strong candidate.

## Competitive advantage
Acme owns the only licence in its market [1]. Margins held at 30% for ten years [2]. It is cheap.
- CEO John Smith leads it [1] *(not found in the cited source)*

## Sources

1. Annual report, business, page 1
2. Peer comparison, ACME, computed from stored statements
"""


def test_only_sentences_that_cite_a_source_are_checked():
    found = evals.claims(BRIEF)
    assert [c["claim"] for c in found] == ["Acme owns the only licence in its market [1].",
                                           "Margins held at 30% for ten years [2].",
                                           "CEO John Smith leads it [1]"]
    assert found[0]["section"] == "Competitive advantage" and found[1]["cited"] == [2]
    assert [c["flagged"] for c in found] == [False, False, True]


def test_the_judge_sees_the_sources_as_short_as_the_writer_did():
    items = [{"title": "Annual report", "where": "page 1", "text": "x" * 3000}] * 40
    text = evals.excerpts(items, [1])
    assert text.count("x") == max(400, evals.EVIDENCE_BUDGET // 40)


def test_a_cached_verdict_needs_no_model_call(monkeypatch, tmp_path):
    monkeypatch.setattr(evals, "DIR", tmp_path)
    judge = evals.Judge(model="groq/test")
    judge.cache[evals._key("ACME", "claim [1]", "src")] = {"verdict": "supported", "reason": "in the text"}
    monkeypatch.setattr(evals.litellm, "completion", lambda **kw: pytest.fail("called the model"))
    assert judge("ACME", "claim [1]", "src")["verdict"] == "supported"


def test_a_brief_is_graded_sentence_by_sentence(monkeypatch, tmp_path):
    monkeypatch.setattr(evals, "RESEARCH_DIR", tmp_path)
    (tmp_path / "ACME.md").write_text(BRIEF, encoding="utf-8")
    items = [{"title": "Annual report, business", "where": "page 1", "text": "Acme holds the only licence."},
             {"title": "Peer comparison, ACME", "where": "computed from stored statements", "text": "margin 30%"}]
    (tmp_path / "ACME.evidence.json").write_text(json.dumps({"items": items, "numbers": ""}), encoding="utf-8")
    verdicts = iter(["supported", "supported", "not_in_source"])
    rows = evals.grade(["ACME"], judge=lambda t, c, s: {"verdict": next(verdicts), "reason": ""})
    s = evals.summarise(rows, ["ACME"])
    assert s["overall"]["supported"] == pytest.approx(2 / 3)
    assert s["by_source"]["our own numbers"]["supported"] == 1.0
    assert s["name_check"] == {"flagged": 1, "flagged_and_judged_unsupported": 1}
    assert s["by_brief"]["ACME"]["cited_share"] == pytest.approx(3 / 4)       # "It is cheap." is too short to count


def test_agreement_with_hand_marked_sentences(monkeypatch, tmp_path):
    monkeypatch.setattr(evals, "DIR", tmp_path)
    (tmp_path / "labels.csv").write_text(
        "id,ticker,claim,sources,your_verdict\na,X,c,s,supported\nb,X,c,s,not_in_source\nc,X,c,s,supported\n"
        "d,X,c,s,\n", encoding="utf-8")
    rows = [{"id": "a", "verdict": "supported"}, {"id": "b", "verdict": "supported"},
            {"id": "c", "verdict": "supported"}, {"id": "d", "verdict": "partly"}]
    got = evals.human_agreement(rows)
    assert got["marked"] == 3 and got["agreement"] == pytest.approx(2 / 3)


def test_names_no_source_mentions_are_caught_in_uncited_sentences():
    items = [{"title": "Annual report", "where": "page 1", "text": "Michael Miebach is chief executive."}]
    report = ("# X\n\nThe chief executive is Ajay Banga. Michael Miebach runs it.\n"
              "Revenue grew [1]. Someone Else said so [1].\n\n## Sources\n\n1. Annual report\n")
    found = evals.unsourced_names(report, items)
    assert [f["names"] for f in found] == [["Ajay Banga"]]


def test_names_from_the_numbers_block_or_in_brackets_count_as_sourced():
    items = [{"title": "Insider trades", "where": "web", "text": "Zhang (Xiulan) Independent Director bought"}]
    report = "# X\n\nZhang Xiulan bought shares in North America. The Magic Formula likes it. It is chaired by Hua Chen.\n"
    found = evals.unsourced_names(report, items, numbers="Magic Formula: earnings yield 7.5%")
    assert [f["names"] for f in found] == [["Hua Chen"]]
