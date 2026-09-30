"""Ingest (CSV / RIS / JSON / plain list) and retrieval (mocked NCBI + Europe PMC)."""
import json
import os

import pytest

from metakit.ingest import read_included
from metakit.retrieve import jats_to_markdown, retrieve_all

JATS = b"""<?xml version="1.0"?>
<article><front><article-meta><title-group><article-title>ST elevation in athletes</article-title></title-group>
<abstract><p>Background text.</p></abstract></article-meta></front>
<body><sec><title>Results</title><p>Mean ST elevation was 0.21 mV (SD 0.08).</p>
<table-wrap id="t1"><label>Table 1</label><caption><p>Characteristics</p></caption>
<table><thead><tr><th>Group</th><th>n</th><th>ST (mV)</th></tr></thead>
<tbody><tr><td>Athletes</td><td>60</td><td>0.21 (0.08)</td></tr>
<tr><td colspan="2">Controls, n=58</td><td>0.12 (0.05)</td></tr></tbody></table>
<table-wrap-foot><p>Values are mean (SD).</p></table-wrap-foot></table-wrap>
<sec><title>Subgroups</title><p>Nested section text.</p></sec></sec></body></article>"""


def test_jats_to_markdown_keeps_tables_and_sections():
    md = jats_to_markdown(JATS)
    assert md.startswith("# ST elevation in athletes")
    assert "## Results" in md and "### Subgroups" in md
    assert "**Table 1** Characteristics" in md
    assert "| Athletes | 60 | 0.21 (0.08) |" in md
    assert "| Controls, n=58 |  | 0.12 (0.05) |" in md
    assert "Values are mean (SD)." in md


class FakeFetcher:
    def __init__(self):
        self.calls = []

    def get(self, url, params=None, retries=3):
        self.calls.append((url, params))
        if "idconv" in url:
            ident = params["ids"]
            if ident == "111":
                return json.dumps({"records": [{"pmid": "111", "pmcid": "PMC999", "doi": "10.1/abc"}]}).encode()
            return json.dumps({"records": [{"pmid": ident, "status": "error"}]}).encode()
        if "efetch" in url:
            pmid = params["id"]
            return f"""<PubmedArticleSet><PubmedArticle><MedlineCitation><Article>
              <Journal><JournalIssue><PubDate><Year>2021</Year></PubDate></JournalIssue><Title>J Test</Title></Journal>
              <ArticleTitle>Paper {pmid}</ArticleTitle><Abstract><AbstractText Label="RESULTS">Abstract {pmid}.</AbstractText></Abstract>
              <AuthorList><Author><LastName>Lee</LastName><Initials>K</Initials></Author></AuthorList>
              </Article></MedlineCitation></PubmedArticle></PubmedArticleSet>""".encode()
        if "PMC999/fullTextXML" in url:
            return JATS
        if "search" in url:
            return json.dumps({"resultList": {"result": []}}).encode()
        return None


def test_retrieve_open_access_and_paywalled(tmp_path):
    studies = [{"study_id": "Lee 2021", "key": "Lee_2021", "pmid": "111"},
               {"study_id": "Kim 2020", "key": "Kim_2020", "pmid": "222"}]
    out = retrieve_all(studies, tmp_path, FakeFetcher(), log=lambda *a: None)
    assert out[0]["status"] == "fulltext_oa" and out[0]["pmcid"] == "PMC999" and out[0]["doi"] == "10.1/abc"
    text = (tmp_path / "Lee_2021.md").read_text()
    assert "study_id: Lee 2021" in text and "| Athletes | 60 |" in text
    assert out[1]["status"] == "needs_pdf"
    assert "RESULTS: Abstract 222." in (tmp_path / "Kim_2020.abstract.md").read_text()
    # a PDF dropped in later is picked up on the next run
    _make_pdf(tmp_path / "Kim_2020.pdf")
    out = retrieve_all([studies[1]], tmp_path, FakeFetcher(), log=lambda *a: None)
    assert out[0]["status"] == "pdf_provided"
    assert out[0]["fulltext"] == "fulltext/Kim_2020.pdf.md"
    assert "0.21 mV (SD 0.08)" in (tmp_path / "Kim_2020.pdf.md").read_text()


def _make_pdf(path):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    fig = plt.figure(figsize=(8.5, 11))
    lines = ["Results", "Mean ST elevation was 0.21 mV (SD 0.08) in 60 athletes."]
    lines += [f"Filler line {i} so the page has a realistic amount of text." for i in range(8)]
    for i, line in enumerate(lines):
        fig.text(0.1, 0.9 - 0.04 * i, line)
    fig.savefig(path)
    plt.close(fig)


def test_scanned_pdf_is_rejected(tmp_path):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from metakit.retrieve import pdf_to_text
    fig = plt.figure()
    fig.savefig(tmp_path / "blank.pdf")
    with pytest.raises(ValueError, match="scanned"):
        pdf_to_text(tmp_path / "blank.pdf")


def test_ingest_csv_with_messy_headers(tmp_path):
    p = tmp_path / "inc.csv"
    p.write_text("PubMed ID,Article Title,Publication Year,Authors,DOI\n"
                 "31415926,Trial A,2019,\"Smith J; Doe A\",https://doi.org/10.1000/ABC.1\n"
                 "27182818,Trial B,2019,\"Smith J; Roe B\",\n")
    s = read_included(p)
    assert [x["study_id"] for x in s] == ["Smith 2019a", "Smith 2019b"]
    assert s[0]["doi"] == "10.1000/abc.1" and s[0]["pmid"] == "31415926" and s[0]["year"] == 2019


def test_ingest_ris(tmp_path):
    p = tmp_path / "inc.ris"
    p.write_text("TY  - JOUR\nAU  - Garcia, Maria\nTI  - Athlete ECG study\nPY  - 2022\n"
                 "DO  - 10.5555/xyz\nAN  - 35555555\nER  - \nTY  - JOUR\nAU  - Chen, Li\n"
                 "TI  - Another\nPY  - 2023\nER  - \n")
    s = read_included(p)
    assert len(s) == 2 and s[0]["study_id"] == "Garcia 2022" and s[0]["pmid"] == "35555555"
    assert s[1]["study_id"] == "Chen 2023"


def test_ingest_json(tmp_path):
    p = tmp_path / "inc.json"
    p.write_text(json.dumps({"included": [{"pmid": "123", "title": "X", "year": "2020", "authors": "Park S"}]}))
    s = read_included(p)
    assert s[0]["study_id"] == "Park 2020"


@pytest.mark.skipif(not os.environ.get("METAKIT_NETWORK_TESTS"), reason="set METAKIT_NETWORK_TESTS=1")
def test_live_europe_pmc(tmp_path):
    """Hits the real services; opt-in so CI stays deterministic."""
    from metakit.retrieve import Fetcher
    s = [{"study_id": "Ferrari 2026", "key": "Ferrari_2026", "pmid": "42623958"}]
    out = retrieve_all(s, tmp_path, Fetcher(), log=lambda *a: None)
    assert out[0]["status"] == "fulltext_oa"
    assert "**Table" in (tmp_path / "Ferrari_2026.md").read_text()
