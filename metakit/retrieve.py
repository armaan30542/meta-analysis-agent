"""Fetch metadata and open-access full texts for the included studies.

Sources (all free, no API key required):

* NCBI ID Converter: PMID <-> PMCID <-> DOI
* PubMed E-utilities (efetch): title, authors, journal, year, abstract
* Europe PMC REST ``fullTextXML``: the full article (JATS XML) for open-access papers,
  converted to Markdown with tables preserved, because results tables are where most
  meta-analysis numbers live.

Papers that are not open access are marked ``needs_pdf``: put the PDF (or its text) in
``fulltext/<key>.pdf`` and the agent reads it directly. Nothing here bypasses paywalls.
"""
from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from pathlib import Path

TOOL = "metakit"
UA = "metakit/1.0 (meta-analysis research tool; https://github.com/)"
IDCONV = "https://www.ncbi.nlm.nih.gov/pmc/utils/idconv/v1.0/"
EFETCH = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/efetch.fcgi"
EPMC_SEARCH = "https://www.ebi.ac.uk/europepmc/webservices/rest/search"
EPMC_FULLTEXT = "https://www.ebi.ac.uk/europepmc/webservices/rest/{pmcid}/fullTextXML"


class Fetcher:
    """Tiny HTTP client with polite rate limiting and retries. Swappable in tests."""

    def __init__(self, email: str | None = None, api_key: str | None = None, delay: float | None = None):
        self.email = email or os.environ.get("METAKIT_EMAIL") or os.environ.get("NCBI_EMAIL")
        self.api_key = api_key or os.environ.get("NCBI_API_KEY")
        self.delay = delay if delay is not None else (0.11 if self.api_key else 0.35)
        self._last = 0.0

    def get(self, url: str, params: dict | None = None, retries: int = 3) -> bytes | None:
        params = dict(params or {})
        if "ncbi.nlm.nih.gov" in url:
            params.setdefault("tool", TOOL)
            if self.email:
                params.setdefault("email", self.email)
            if self.api_key and "eutils" in url:
                params.setdefault("api_key", self.api_key)
        full = url + ("?" + urllib.parse.urlencode(params) if params else "")
        for attempt in range(retries):
            wait = self.delay - (time.time() - self._last)
            if wait > 0:
                time.sleep(wait)
            self._last = time.time()
            try:
                req = urllib.request.Request(full, headers={"User-Agent": UA})
                with urllib.request.urlopen(req, timeout=30) as r:
                    return r.read()
            except urllib.error.HTTPError as e:
                if e.code == 404:
                    return None
                if e.code in (429, 500, 502, 503, 504) and attempt < retries - 1:
                    time.sleep(2 ** attempt)
                    continue
                raise
            except urllib.error.URLError:
                if attempt < retries - 1:
                    time.sleep(2 ** attempt)
                    continue
                raise
        return None


def resolve_ids(fetcher: Fetcher, study: dict) -> dict:
    """Fill in whichever of pmid / pmcid / doi are missing."""
    ident = study.get("pmid") or study.get("pmcid") or study.get("doi")
    if ident and not (study.get("pmid") and study.get("pmcid") and study.get("doi")):
        raw = fetcher.get(IDCONV, {"ids": ident, "format": "json"})
        if raw:
            try:
                recs = json.loads(raw).get("records", [])
            except json.JSONDecodeError:
                recs = []
            if recs and not recs[0].get("status") == "error":
                r = recs[0]
                study["pmid"] = study.get("pmid") or r.get("pmid")
                study["pmcid"] = study.get("pmcid") or r.get("pmcid")
                study["doi"] = study.get("doi") or (r.get("doi") or "").lower() or None
    if not study.get("pmid") and not study.get("pmcid") and (study.get("doi") or study.get("title")):
        q = f'DOI:"{study["doi"]}"' if study.get("doi") else f'TITLE:"{study["title"]}"'
        raw = fetcher.get(EPMC_SEARCH, {"query": q, "format": "json", "resultType": "lite", "pageSize": 1})
        if raw:
            hits = json.loads(raw).get("resultList", {}).get("result", [])
            if hits:
                h = hits[0]
                study["pmid"] = study.get("pmid") or h.get("pmid")
                study["pmcid"] = study.get("pmcid") or h.get("pmcid")
                study["doi"] = study.get("doi") or (h.get("doi") or "").lower() or None
    return study


def fetch_pubmed(fetcher: Fetcher, pmid: str) -> dict:
    raw = fetcher.get(EFETCH, {"db": "pubmed", "id": pmid, "retmode": "xml"})
    if not raw:
        return {}
    root = ET.fromstring(raw)
    art = root.find(".//PubmedArticle")
    if art is None:
        return {}
    t = lambda path: "".join(art.find(path).itertext()).strip() if art.find(path) is not None else None
    abstract = "\n\n".join(
        ((a.get("Label") + ": ") if a.get("Label") else "") + "".join(a.itertext()).strip()
        for a in art.findall(".//Abstract/AbstractText"))
    authors = []
    for au in art.findall(".//AuthorList/Author"):
        ln, ini = au.findtext("LastName"), au.findtext("Initials")
        if ln:
            authors.append(f"{ln} {ini or ''}".strip())
    year = art.findtext(".//JournalIssue/PubDate/Year") or (art.findtext(".//JournalIssue/PubDate/MedlineDate") or "")[:4]
    return {"title": t(".//ArticleTitle"), "journal": t(".//Journal/Title"),
            "year": int(year) if year and year.isdigit() else None,
            "authors": "; ".join(authors), "abstract": abstract}


# ---------------------------------------------------------------------------
# JATS XML -> Markdown
# ---------------------------------------------------------------------------

def _text(el) -> str:
    return " ".join("".join(el.itertext()).split()) if el is not None else ""


def _table_md(tw) -> str:
    out = []
    label, caption = _text(tw.find("label")), _text(tw.find("caption"))
    out.append(f"**{label}** {caption}".strip())
    for table in tw.iter("table"):
        rows = []
        for tr in table.iter("tr"):
            cells = []
            for c in tr:
                if c.tag in ("td", "th"):
                    txt = _text(c).replace("|", "/")
                    span = int(c.get("colspan", "1") or 1)
                    cells += [txt] + [""] * (span - 1)
            if cells:
                rows.append(cells)
        if not rows:
            continue
        width = max(len(r) for r in rows)
        rows = [r + [""] * (width - len(r)) for r in rows]
        out.append("")
        out.append("| " + " | ".join(rows[0]) + " |")
        out.append("|" + "---|" * width)
        for r in rows[1:]:
            out.append("| " + " | ".join(r) + " |")
    foot = tw.find("table-wrap-foot")
    if foot is not None:
        out.append("")
        out.append("_Table notes:_ " + _text(foot))
    return "\n".join(out)


def jats_to_markdown(xml_bytes: bytes) -> str:
    root = ET.fromstring(xml_bytes)
    lines = []
    title = root.find(".//article-meta//article-title")
    if title is not None:
        lines += [f"# {_text(title)}", ""]
    abstract = root.find(".//article-meta/abstract")
    if abstract is not None:
        lines += ["## Abstract", ""]
        for p in abstract.iter("p"):
            lines += [_text(p), ""]

    def walk(sec, depth):
        t = sec.find("title")
        if t is not None and _text(t):
            lines.extend(["#" * min(depth, 6) + " " + _text(t), ""])
        for child in sec:
            if child.tag == "p":
                # keep inline text but pull nested tables out as their own blocks
                nested = list(child.iter("table-wrap"))
                for tw in nested:
                    lines.extend([_table_md(tw), ""])
                lines.extend([_text(child), ""])
            elif child.tag == "sec":
                walk(child, depth + 1)
            elif child.tag == "table-wrap":
                lines.extend([_table_md(child), ""])
            elif child.tag == "fig":
                lines.extend([f"_Figure {_text(child.find('label'))}: {_text(child.find('caption'))}_", ""])
            elif child.tag == "list":
                for li in child.iter("list-item"):
                    lines.append("- " + _text(li))
                lines.append("")

    body = root.find(".//body")
    if body is not None:
        for sec in body:
            if sec.tag == "sec":
                walk(sec, 2)
            elif sec.tag == "p":
                lines += [_text(sec), ""]
            elif sec.tag == "table-wrap":
                lines += [_table_md(sec), ""]
    # tables sometimes live in <floats-group> at the end
    floats = root.find(".//floats-group")
    if floats is not None:
        tws = list(floats.iter("table-wrap"))
        if tws:
            lines += ["## Tables", ""]
            for tw in tws:
                lines += [_table_md(tw), ""]
    return "\n".join(lines).strip() + "\n"


def pdf_to_text(pdf_path: Path) -> str:
    """Deterministic text extraction from a PDF (pypdf), page by page.

    The text file this produces is what extraction quotes are verified against, so it must
    come from software, never from an LLM transcription of the PDF.
    """
    from pypdf import PdfReader  # imported lazily: only needed for paywalled papers

    reader = PdfReader(str(pdf_path))
    parts = []
    for i, page in enumerate(reader.pages, 1):
        txt = page.extract_text() or ""
        parts.append(f"<!-- page {i} -->\n{txt.strip()}\n")
    text = "\n".join(parts)
    if len(text.strip()) < 200:
        raise ValueError(f"{pdf_path.name}: almost no extractable text (scanned PDF?); run OCR first")
    return text


def retrieve_all(studies: list[dict], outdir: Path, fetcher: Fetcher | None = None, log=print) -> list[dict]:
    fetcher = fetcher or Fetcher()
    outdir = Path(outdir)
    outdir.mkdir(parents=True, exist_ok=True)
    for s in studies:
        key = s["key"]
        try:
            resolve_ids(fetcher, s)
            meta = fetch_pubmed(fetcher, s["pmid"]) if s.get("pmid") else {}
            for k2 in ("title", "journal", "year", "authors"):
                if meta.get(k2) and not s.get(k2):
                    s[k2] = meta[k2]
            text = None
            if s.get("pmcid"):
                raw = fetcher.get(EPMC_FULLTEXT.format(pmcid=s["pmcid"]))
                if raw:
                    text = jats_to_markdown(raw)
            header = (f"<!-- study_id: {s['study_id']} | PMID: {s.get('pmid')} | PMCID: {s.get('pmcid')} | "
                      f"DOI: {s.get('doi')} -->\n\n")
            if text:
                (outdir / f"{key}.md").write_text(header + text, encoding="utf-8")
                s["status"], s["fulltext"] = "fulltext_oa", f"fulltext/{key}.md"
            else:
                if meta.get("abstract"):
                    (outdir / f"{key}.abstract.md").write_text(
                        header + f"# {meta.get('title', '')}\n\n## Abstract\n\n{meta['abstract']}\n", encoding="utf-8")
                pdf = outdir / f"{key}.pdf"
                if pdf.exists():
                    (outdir / f"{key}.pdf.md").write_text(header + pdf_to_text(pdf), encoding="utf-8")
                    s["status"], s["fulltext"] = "pdf_provided", f"fulltext/{key}.pdf.md"
                else:
                    s["status"], s["fulltext"] = "needs_pdf", None
            log(f"  {s['study_id']:<28} {s['status']}")
        except Exception as exc:  # network errors should not kill a 50-study run
            s["status"] = f"error: {exc}"
            log(f"  {s['study_id']:<28} ERROR {exc}")
    return studies
