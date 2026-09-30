"""Review-team meetings (Virtual Lab protocol) and search/screening, with mocked LLM and HTTP."""
import json
from pathlib import Path

import pytest

from metakit import screening, team
from metakit.cli import main

ROOT = Path(__file__).resolve().parent.parent


class FakeLLM:
    def __init__(self, final=None):
        self.calls, self.final = [], final

    def __call__(self, model, system, messages):
        self.calls.append((system, [dict(m) for m in messages]))
        roles = [m["role"] for m in messages]
        assert roles[0] == "user" and all(a != b for a, b in zip(roles, roles[1:])), "roles must alternate"
        last = messages[-1]["content"]
        if "please summarize the meeting" in last and self.final:
            return self.final
        return f"reply from agent #{len(self.calls)}"


def test_team_meeting_follows_virtual_lab_protocol(tmp_path):
    llm = FakeLLM()
    members = (team.domain_expert("sports cardiology"), team.BIOSTATISTICIAN, team.SCIENTIFIC_CRITIC)
    out = team.run_meeting("team", "Plan the review", llm, tmp_path, "m", team_lead=team.PRINCIPAL_INVESTIGATOR,
                           team_members=members, agenda_questions=("Q1?",), num_rounds=2)
    # rounds: (lead + 3 members) x 2 rounds + final lead summary = 9 calls
    assert len(llm.calls) == 9
    systems = [c[0] for c in llm.calls]
    assert systems[0].startswith("You are a Principal Investigator") and systems[-1] == systems[0]
    assert "Sports Cardiology Expert" in systems[1]
    first = llm.calls[0][1][0]["content"]
    assert "This is the beginning of a team meeting" in first and "Q1?" in first
    assert "### Recommendation" in llm.calls[-1][1][-1]["content"]
    assert (tmp_path / "m.md").exists() and json.loads((tmp_path / "m.json").read_text())["num_rounds"] == 2


def test_individual_meeting_uses_scientific_critic(tmp_path):
    llm = FakeLLM()
    team.run_meeting("individual", "Draft eligibility criteria", llm, None,
                     team_member=team.INFORMATION_SPECIALIST, num_rounds=2)
    systems = [c[0] for c in llm.calls]
    assert len(systems) == 5  # agent, critic, agent, critic, agent
    assert "Scientific Critic" in systems[1] and "Information Specialist" in systems[4]
    assert "critique Information Specialist's most recent answer" in llm.calls[1][1][-1]["content"]


def test_meeting_validation():
    with pytest.raises(ValueError):
        team.run_meeting("team", "x", FakeLLM(), team_lead=team.PRINCIPAL_INVESTIGATOR,
                         team_members=(team.PRINCIPAL_INVESTIGATOR,))
    with pytest.raises(ValueError):
        team.run_meeting("panel", "x", FakeLLM())


PROTO_YAML = """### Recommendation
Pool ST elevation.
```yaml
title: ST elevation in athletes
question: Do athletes show more ST elevation than controls?
study_designs: [cross-sectional]
eligibility: {include: [adult athletes], exclude: [case reports]}
outcomes:
  - {id: st_elevation, label: ST elevation, primary: true, data_type: continuous, measure: MD, unit: mV}
model: {method: REML, test: knha}
subgroups: [sport]
```"""


def test_protocol_meeting_writes_validated_draft(tmp_path):
    res = team.protocol_meeting("ST elevation in athletes?", "sports cardiology", FakeLLM(PROTO_YAML), tmp_path, 1)
    assert res["protocol_error"] is None
    draft = (tmp_path / "protocol.draft.yaml").read_text()
    assert draft.startswith("# DRAFT") and "st_elevation" in draft
    bad = PROTO_YAML.replace("measure: MD", "measure: OR")
    res = team.protocol_meeting("q", "f", FakeLLM(bad), tmp_path / "b", 1)
    assert "does not fit data_type" in res["protocol_error"]


def test_interpretation_meeting_flags_invented_numbers(tmp_path):
    results = {"outcomes": {"tb": {"label": "TB", "k": 13, "main": {"estimate": -0.7145, "I2": 92.22,
               "display": {"estimate": 0.489, "ci_lb": 0.344, "ci_ub": 0.696}}}}}
    good = "RR 0.49 (95% CI 0.34 to 0.70) across 13 trials, I2 92%."
    bad = good + " The number needed to vaccinate is 238."
    r1 = team.interpretation_meeting(results, {"title": "t"}, "infectious disease", FakeLLM(good), tmp_path, 1)
    assert r1["unverified_numbers"] == []
    r2 = team.interpretation_meeting(results, {"title": "t"}, "infectious disease", FakeLLM(bad), tmp_path, 1)
    assert r2["unverified_numbers"] == ["238"]
    assert "WARNING" in (tmp_path / "discussion.draft.md").read_text()


# --- search & screening ------------------------------------------------------------------

EFETCH_XML = """<PubmedArticleSet>{}</PubmedArticleSet>"""
ART = """<PubmedArticle><MedlineCitation><PMID>{p}</PMID><Article><Journal><JournalIssue><PubDate><Year>2020</Year></PubDate>
</JournalIssue><Title>J</Title></Journal><ArticleTitle>{t}</ArticleTitle><Abstract><AbstractText>{a}</AbstractText></Abstract>
<AuthorList><Author><LastName>Lee</LastName><Initials>K</Initials></Author></AuthorList>
<PublicationTypeList><PublicationType>Journal Article</PublicationType></PublicationTypeList></Article></MedlineCitation>
<PubmedData><ArticleIdList><ArticleId IdType="doi">10.1/{p}</ArticleId></ArticleIdList></PubmedData></PubmedArticle>"""


class FakeFetcher:
    def get(self, url, params=None, retries=3):
        if "esearch" in url:
            return json.dumps({"esearchresult": {"count": "3", "idlist": ["1", "2", "3"]}}).encode()
        ids = params["id"].split(",")
        return EFETCH_XML.format("".join(ART.format(p=i, t=f"ST elevation in athletes study {i}", a=f"Abstract {i}")
                                         for i in ids)).encode()


def test_search_dedup_screen_reconcile_prisma(tmp_path):
    proj = tmp_path / "p"
    assert main(["init", str(proj)]) == 0
    entry = screening.run_search('"athletes"[tiab] AND "ST"[tiab]', proj / "search", FakeFetcher(), log=lambda *a: None)
    assert entry["count"] == 3 and len(entry["strategy_sha256"]) == 64
    ris = tmp_path / "embase.ris"
    ris.write_text("TY  - JOUR\nTI  - ST elevation in athletes study 1\nPY  - 2020\nDO  - 10.1/1\nAB  - dup\nER  - \n"
                   "TY  - JOUR\nTI  - A different Embase-only paper about athletes\nPY  - 2021\nER  - \n")
    counts = screening.build_screening_set(proj, {"Embase": ris})
    assert counts == {"identified": 5, "duplicates_removed": 1, "to_screen": 4}
    recs = json.loads((proj / "screening" / "records.json").read_text())

    proto = {"question": "q", "eligibility": {"include": ["athletes"], "exclude": ["case reports"]}}
    system, user = screening.screening_prompt(proto, recs[:2])
    assert "maybe" in system and "Inclusion criteria" in user and "[PMID:1]" in user

    def reviewer(decisions):
        return lambda model, system, messages: json.dumps(
            [{"id": r, "decision": d, "criterion": "not athletes" if d == "exclude" else None, "reason": "x"}
             for r, d in decisions.items()])
    ids = [r["id"] for r in recs]
    a = dict(zip(ids, ["include", "exclude", "include", "maybe"]))
    b = dict(zip(ids, ["include", "exclude", "exclude", "include"]))
    sdir = proj / "screening"
    for name, dec in (("A", a), ("B", b)):
        n = screening.screen_with_llm(reviewer(dec), "m", proto, recs, f"AI-{name}",
                                      sdir / f"decisions_title_abstract_{name}.jsonl", log=lambda *x: None)
        assert n == 4
    # resumable: nothing left to do
    assert screening.screen_with_llm(reviewer(a), "m", proto, recs, "AI-A", sdir / "decisions_title_abstract_A.jsonl",
                                     log=lambda *x: None) == 0
    assert main(["screen-reconcile", "-p", str(proj)]) == 0
    ta = json.loads((sdir / "title_abstract_result.json").read_text())
    assert len(ta["included"]) == 3 and len(ta["excluded"]) == 1   # liberal rule advanced the conflict
    assert 0 < ta["agreement"] < 1 and ta["kappa"] is not None

    ft_ids = ta["included"]
    fa = {i: "include" for i in ft_ids}
    fb = dict(fa)
    fb[ft_ids[-1]] = "exclude"
    for name, dec in (("A", fa), ("B", fb)):
        screening.append_decisions(sdir / f"decisions_full_text_{name}.jsonl",
                                   [{"id": i, "decision": d, "criterion": "wrong comparator" if d == "exclude" else None}
                                    for i, d in dec.items()])
    assert main(["screen-reconcile", "-p", str(proj), "--stage", "full_text"]) == 2   # conflict must be resolved
    (sdir / "resolutions_full_text.json").write_text(json.dumps({ft_ids[-1]: "exclude"}))
    assert main(["screen-reconcile", "-p", str(proj), "--stage", "full_text"]) == 0
    prisma = json.loads((proj / "prisma.json").read_text())
    assert prisma["identified"] == 5 and prisma["duplicates_removed"] == 1 and prisma["screened"] == 4
    assert prisma["fulltext_assessed"] == 3 and prisma["included_review"] == 2
    assert (proj / "included.csv").exists()
    assert main(["ingest", str(proj / "included.csv"), "-p", str(proj)]) == 0
    assert "Kappa" in (sdir / "screening_report.md").read_text() or "kappa" in (sdir / "screening_report.md").read_text()


def test_kappa_values():
    assert screening.cohen_kappa(["include", "exclude"] * 5, ["include", "exclude"] * 5) == 1.0
    k = screening.cohen_kappa(["include"] * 5 + ["exclude"] * 5, ["include"] * 4 + ["exclude"] * 6)
    assert k == pytest.approx(0.8)


def test_vendored_search_builder_intact():
    d = ROOT / "skills" / "pubmed-search-builder"
    assert (d / "SKILL.md").read_text().startswith("---\nname: pubmed-search-builder")
    assert "Aaron Tay" in (d / "LICENSE").read_text()
    assert "b217cf4" in (d / "UPSTREAM.md").read_text()
