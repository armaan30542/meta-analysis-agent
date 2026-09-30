"""Read the list of included studies from whatever the systematic review produced.

Accepts CSV/TSV (any columns; PMID, DOI, PMCID, title, year, authors are detected by name),
RIS (EndNote/Zotero/PubMed export), JSON (a list of objects), or plain text with one PMID,
DOI or PMCID per line. Writes a normalised ``studies.csv``.
"""
from __future__ import annotations

import csv
import json
import re
from pathlib import Path

DOI_RE = re.compile(r"10\.\d{4,9}/\S+", re.I)
PMCID_RE = re.compile(r"PMC\d+", re.I)
PMID_RE = re.compile(r"^\d{1,9}$")

COLUMN_ALIASES = {
    "pmid": ["pmid", "pubmed id", "pubmed_id", "pubmedid", "pm id"],
    "doi": ["doi", "digital object identifier"],
    "pmcid": ["pmcid", "pmc id", "pmc"],
    "title": ["title", "article title", "ti"],
    "year": ["year", "publication year", "py", "pub year", "date"],
    "authors": ["authors", "author", "au", "first author"],
    "study_id": ["study_id", "study", "study id", "id", "label"],
    "journal": ["journal", "source", "journal/book", "jo"],
}


def _clean_doi(s):
    m = DOI_RE.search(s or "")
    return m.group(0).rstrip(".,;)").lower() if m else None


def _norm_row(raw: dict) -> dict:
    low = {str(k).strip().lower(): (v.strip() if isinstance(v, str) else v) for k, v in raw.items()}
    out = {}
    for key, aliases in COLUMN_ALIASES.items():
        for a in aliases:
            if a in low and low[a] not in (None, ""):
                out[key] = low[a]
                break
    if out.get("doi"):
        out["doi"] = _clean_doi(str(out["doi"]))
    if out.get("pmid"):
        digits = re.sub(r"\D", "", str(out["pmid"]))
        out["pmid"] = digits or None
    if out.get("pmcid"):
        m = PMCID_RE.search(str(out["pmcid"]))
        out["pmcid"] = m.group(0).upper() if m else None
    if out.get("year"):
        m = re.search(r"(19|20)\d{2}", str(out["year"]))
        out["year"] = int(m.group(0)) if m else None
    return out


def _parse_ris(text: str) -> list[dict]:
    recs, cur = [], {}
    for line in text.splitlines():
        m = re.match(r"^([A-Z][A-Z0-9])  - ?(.*)$", line)
        if not m:
            continue
        tag, val = m.group(1), m.group(2).strip()
        if tag == "ER":
            recs.append(cur)
            cur = {}
            continue
        if tag in ("TI", "T1"):
            cur["title"] = val
        elif tag in ("PY", "Y1", "DA") and "year" not in cur:
            cur["year"] = val
        elif tag in ("AU", "A1"):
            cur.setdefault("authors", val)
        elif tag == "DO":
            cur["doi"] = val
        elif tag in ("JO", "JF", "T2"):
            cur.setdefault("journal", val)
        elif tag == "AN" and re.fullmatch(r"\d+", val):
            cur["pmid"] = val
        elif tag in ("UR", "L2") and "pubmed" in val:
            m2 = re.search(r"(\d{5,9})", val)
            if m2:
                cur.setdefault("pmid", m2.group(1))
        elif tag == "C2" and PMCID_RE.search(val):
            cur["pmcid"] = PMCID_RE.search(val).group(0)
    if cur:
        recs.append(cur)
    return recs


def _parse_lines(text: str) -> list[dict]:
    recs = []
    for line in text.splitlines():
        s = line.strip()
        if not s or s.startswith("#"):
            continue
        if PMCID_RE.fullmatch(s):
            recs.append({"pmcid": s.upper()})
        elif _clean_doi(s):
            recs.append({"doi": s})
        elif PMID_RE.fullmatch(s):
            recs.append({"pmid": s})
        else:
            recs.append({"title": s})
    return recs


def read_included(path: Path) -> list[dict]:
    path = Path(path)
    text = path.read_text(encoding="utf-8-sig")
    suf = path.suffix.lower()
    if suf in (".csv", ".tsv"):
        dialect = "excel-tab" if suf == ".tsv" else "excel"
        rows = list(csv.DictReader(text.splitlines(), dialect=dialect))
    elif suf == ".ris" or text.lstrip().startswith("TY  -"):
        rows = _parse_ris(text)
    elif suf == ".json":
        data = json.loads(text)
        rows = data if isinstance(data, list) else data.get("studies") or data.get("included") or []
    else:
        rows = _parse_lines(text)
    studies = [_norm_row(r) for r in rows]
    studies = [s for s in studies if any(s.get(k) for k in ("pmid", "doi", "pmcid", "title"))]
    return assign_ids(studies)


def assign_ids(studies: list[dict]) -> list[dict]:
    """Give every study a readable, unique ``study_id`` (e.g. ``Smith 2019``, ``Smith 2019b``)."""
    used = {}
    for s in studies:
        if s.get("study_id"):
            base = str(s["study_id"])
        else:
            au = str(s.get("authors") or "").split(";")[0].split(",")[0].strip()
            au = au.split()[0] if au and " " in au and "," not in str(s.get("authors") or "") else au
            yr = s.get("year") or ""
            base = f"{au} {yr}".strip() or (f"PMID{s['pmid']}" if s.get("pmid") else
                                            s.get("pmcid") or (s.get("doi") or "study").split("/")[-1])
        n = used.get(base, 0)
        used[base] = n + 1
        s["study_id"] = base if n == 0 else f"{base}{chr(ord('a') + n)}"
        s["key"] = re.sub(r"[^A-Za-z0-9]+", "_", s["study_id"]).strip("_")
    # retro-letter the first duplicate so it becomes "Smith 2019a"
    for base, count in used.items():
        if count > 1:
            for s in studies:
                if s["study_id"] == base:
                    s["study_id"] = f"{base}a"
                    s["key"] = re.sub(r"[^A-Za-z0-9]+", "_", s["study_id"]).strip("_")
    return studies


FIELDS = ["study_id", "key", "pmid", "pmcid", "doi", "title", "authors", "year", "journal",
          "status", "fulltext"]


def write_studies(studies: list[dict], path: Path):
    with open(path, "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=FIELDS, extrasaction="ignore")
        w.writeheader()
        for s in studies:
            w.writerow(s)


def read_studies(path: Path) -> list[dict]:
    with open(path, encoding="utf-8") as fh:
        rows = list(csv.DictReader(fh))
    for r in rows:
        for k, v in list(r.items()):
            if v == "":
                r[k] = None
        if r.get("year"):
            r["year"] = int(r["year"])
    return rows
