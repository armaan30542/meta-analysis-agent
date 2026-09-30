"""Search execution and dual-reviewer screening: the stages between a search strategy and
the included-studies list.

Workflow (files live in ``<project>/search`` and ``<project>/screening``):

1. ``run_search``: execute the final PubMed strategy (e.g. from the pubmed-search-builder skill),
   fetch every record's title/abstract, and log date, count and strategy hash for PRISMA-S.
2. ``import_ris`` + ``deduplicate``: add records from other databases and remove duplicates
   (PMID, DOI, then normalised title + year).
3. Two reviewers (people or AI screeners) each write ``decisions_<stage>_<reviewer>.jsonl``.
   ``screening_prompt``/``parse_screening_reply`` let an LLM act as a screener.
4. ``reconcile_screening``: agreement and Cohen's kappa, the conflicts to resolve, and the
   liberal-acceptance rule at title/abstract stage (either reviewer's include/maybe goes on).
5. ``prisma_counts`` fills prisma.json; ``write_included`` produces the list `metakit ingest` reads.
"""
from __future__ import annotations

import csv
import hashlib
import json
import re
import unicodedata
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from pathlib import Path

from .retrieve import EFETCH, Fetcher

ESEARCH = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esearch.fcgi"
DECISIONS = ("include", "exclude", "maybe")
STAGES = ("title_abstract", "full_text")


# --- search ------------------------------------------------------------------------------

def _parse_pubmed_xml(raw: bytes) -> list[dict]:
    out = []
    root = ET.fromstring(raw)
    for art in root.findall(".//PubmedArticle"):
        t = lambda p: " ".join("".join(art.find(p).itertext()).split()) if art.find(p) is not None else ""
        pmid = art.findtext(".//MedlineCitation/PMID")
        abstract = "\n".join(((a.get("Label") + ": ") if a.get("Label") else "") + " ".join("".join(a.itertext()).split())
                             for a in art.findall(".//Abstract/AbstractText"))
        authors = [f"{a.findtext('LastName')} {a.findtext('Initials') or ''}".strip()
                   for a in art.findall(".//AuthorList/Author") if a.findtext("LastName")]
        year = art.findtext(".//JournalIssue/PubDate/Year") or (art.findtext(".//JournalIssue/PubDate/MedlineDate") or "")[:4]
        doi = next((e.text for e in art.findall(".//ArticleIdList/ArticleId") if e.get("IdType") == "doi"), None)
        pubtypes = [p.text for p in art.findall(".//PublicationTypeList/PublicationType")]
        out.append({"id": f"PMID:{pmid}", "pmid": pmid, "doi": (doi or "").lower() or None, "title": t(".//ArticleTitle"),
                    "abstract": abstract, "authors": "; ".join(authors), "year": int(year) if year[:4].isdigit() else None,
                    "journal": t(".//Journal/Title"), "publication_types": pubtypes, "source": "PubMed"})
    return out


def run_search(strategy: str, outdir: Path, fetcher: Fetcher | None = None, max_records: int = 10000,
               batch: int = 200, log=print) -> dict:
    """Run a PubMed Boolean strategy and save every record (PRISMA-S item 8/9/13 logging)."""
    fetcher = fetcher or Fetcher()
    outdir = Path(outdir)
    outdir.mkdir(parents=True, exist_ok=True)
    strategy = strategy.strip()
    raw = fetcher.get(ESEARCH, {"db": "pubmed", "term": strategy, "retmax": max_records, "retmode": "json"})
    res = json.loads(raw)["esearchresult"]
    count = int(res["count"])
    ids = res.get("idlist", [])
    if res.get("errorlist") or res.get("warninglist", {}).get("quotedphrasesnotfound"):
        log(f"PubMed warnings: {res.get('errorlist') or res.get('warninglist')}")
    if count > len(ids):
        raise ValueError(f"strategy returns {count} records, more than the {max_records} cap; refine it or raise max_records")
    records = []
    for i in range(0, len(ids), batch):
        chunk = ids[i:i + batch]
        records += _parse_pubmed_xml(fetcher.get(EFETCH, {"db": "pubmed", "id": ",".join(chunk), "retmode": "xml"}))
        log(f"  fetched {len(records)}/{len(ids)}")
    entry = {"database": "PubMed", "interface": "NCBI E-utilities", "date": datetime.now(timezone.utc).isoformat(timespec="seconds"),
             "strategy": strategy, "strategy_sha256": hashlib.sha256(strategy.encode()).hexdigest(),
             "count": count, "records_retrieved": len(records)}
    (outdir / "pubmed_records.json").write_text(json.dumps(records, indent=1))
    log_path = outdir / "search_log.json"
    history = json.loads(log_path.read_text()) if log_path.exists() else []
    history.append(entry)
    log_path.write_text(json.dumps(history, indent=2))
    return entry


def import_ris(path: Path, source: str) -> list[dict]:
    """Records from another database (Embase, CINAHL, Web of Science ...) exported as RIS."""
    from .ingest import _parse_ris
    recs = []
    for i, r in enumerate(_parse_ris(Path(path).read_text(encoding="utf-8-sig"))):
        year = re.search(r"(19|20)\d{2}", str(r.get("year") or ""))
        recs.append({"id": f"{source}:{i + 1}", "pmid": r.get("pmid"), "doi": (r.get("doi") or "").lower() or None,
                     "title": r.get("title") or "", "abstract": r.get("abstract") or "", "authors": r.get("authors") or "",
                     "year": int(year.group(0)) if year else None, "journal": r.get("journal"), "source": source})
    return recs


def _norm_title(t: str) -> str:
    t = unicodedata.normalize("NFKD", t or "").encode("ascii", "ignore").decode().lower()
    return re.sub(r"[^a-z0-9]+", "", t)


def deduplicate(records: list[dict]) -> tuple[list[dict], list[dict]]:
    """Remove duplicates by PMID, then DOI, then normalised title + year. Returns (unique, removed)."""
    seen, unique, removed = {}, [], []
    for r in records:
        keys = [k for k in (f"pmid:{r['pmid']}" if r.get("pmid") else None,
                            f"doi:{r['doi']}" if r.get("doi") else None,
                            f"ty:{_norm_title(r['title'])}:{r.get('year')}" if len(_norm_title(r.get("title", ""))) > 20 else None)
                if k]
        hit = next((seen[k] for k in keys if k in seen), None)
        if hit is not None:
            removed.append({**r, "duplicate_of": hit["id"]})
            for k in keys:
                seen.setdefault(k, hit)
            continue
        for k in keys:
            seen[k] = r
        unique.append(r)
    return unique, removed


def build_screening_set(project: Path, ris_files: dict | None = None) -> dict:
    """Merge PubMed + other sources, deduplicate, and write screening/records.json."""
    project = Path(project)
    recs = json.loads((project / "search" / "pubmed_records.json").read_text()) if (project / "search" / "pubmed_records.json").exists() else []
    for source, path in (ris_files or {}).items():
        recs += import_ris(path, source)
    unique, removed = deduplicate(recs)
    sdir = project / "screening"
    sdir.mkdir(parents=True, exist_ok=True)
    (sdir / "records.json").write_text(json.dumps(unique, indent=1))
    (sdir / "duplicates.json").write_text(json.dumps(removed, indent=1))
    return {"identified": len(recs), "duplicates_removed": len(removed), "to_screen": len(unique)}


# --- screening decisions -----------------------------------------------------------------

def load_decisions(path: Path) -> dict:
    out = {}
    if not Path(path).exists():
        return out
    for line in Path(path).read_text().splitlines():
        if line.strip():
            d = json.loads(line)
            if d.get("decision") not in DECISIONS:
                raise ValueError(f"{path}: decision must be one of {DECISIONS}: {d}")
            out[d["id"]] = d
    return out


def append_decisions(path: Path, decisions: list[dict]):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "a", encoding="utf-8") as fh:
        for d in decisions:
            fh.write(json.dumps(d) + "\n")


SCREENING_SYSTEM = """You are an independent reviewer screening records for a systematic review. Apply the eligibility criteria exactly as written. At the {stage} stage, when information is missing or unclear, answer "maybe" (the record goes to the next stage) rather than excluding it. Return ONLY a JSON array, one object per record, in the order given: {{"id": "...", "decision": "include" | "exclude" | "maybe", "criterion": "<the exact criterion that decided it, or null>", "reason": "<one sentence>"}}."""


def screening_prompt(protocol: dict, records: list[dict], stage: str = "title_abstract") -> tuple[str, str]:
    """(system, user) prompts for an LLM screener. Batches of ~20 records work well."""
    elig = protocol.get("eligibility") or {}
    crit = ("Inclusion criteria:\n" + "\n".join(f"- {c}" for c in elig.get("include", [])) +
            "\nExclusion criteria:\n" + "\n".join(f"- {c}" for c in elig.get("exclude", [])))
    items = "\n\n".join(f"[{r['id']}]\nTitle: {r.get('title', '')}\nYear: {r.get('year')}\n"
                        f"Publication type: {', '.join(r.get('publication_types') or []) or 'unknown'}\n"
                        f"Abstract: {(r.get('abstract') or '(no abstract)')[:4000]}" for r in records)
    user = (f"Review question: {protocol.get('question', '')}\n\n{crit}\n\nStudy designs eligible: "
            f"{', '.join(protocol.get('study_designs') or []) or 'any'}\n\nRecords:\n\n{items}")
    return SCREENING_SYSTEM.format(stage=stage.replace("_", "/")), user


def parse_screening_reply(text: str, records: list[dict], reviewer: str, stage: str) -> list[dict]:
    s = text[text.find("["): text.rfind("]") + 1]
    arr = json.loads(s)
    by_id = {str(d.get("id")).strip("[]"): d for d in arr}
    out = []
    for r in records:
        d = by_id.get(r["id"])
        if not d or d.get("decision") not in DECISIONS:
            d = {"decision": "maybe", "reason": "screener returned no valid decision for this record", "criterion": None}
        out.append({"id": r["id"], "stage": stage, "reviewer": reviewer, "decision": d["decision"],
                    "criterion": d.get("criterion"), "reason": d.get("reason")})
    return out


def screen_with_llm(llm, model: str, protocol: dict, records: list[dict], reviewer: str, out_path: Path,
                    stage: str = "title_abstract", batch: int = 20, log=print) -> int:
    """Screen every record not yet decided by this reviewer (resumable)."""
    done = load_decisions(out_path)
    todo = [r for r in records if r["id"] not in done]
    for i in range(0, len(todo), batch):
        chunk = todo[i:i + batch]
        system, user = screening_prompt(protocol, chunk, stage)
        reply = llm(model, system, [{"role": "user", "content": user}])
        append_decisions(out_path, parse_screening_reply(reply, chunk, reviewer, stage))
        log(f"  {reviewer}: {min(i + batch, len(todo))}/{len(todo)}")
    return len(todo)


def cohen_kappa(a: list[str], b: list[str]) -> float | None:
    """Cohen's kappa for two raters over the same items (categories: include/maybe merged vs exclude)."""
    if not a:
        return None
    cats = sorted(set(a) | set(b))
    n = len(a)
    po = sum(x == y for x, y in zip(a, b)) / n
    pe = sum((a.count(c) / n) * (b.count(c) / n) for c in cats)
    return 1.0 if pe == 1 else (po - pe) / (1 - pe)


def reconcile_screening(records: list[dict], dec_a: dict, dec_b: dict, stage: str,
                        resolutions: dict | None = None) -> dict:
    """Compare two reviewers. Title/abstract: liberal rule; full text: disagreements need resolution."""
    resolutions = resolutions or {}
    ids = [r["id"] for r in records]
    missing = [i for i in ids if i not in dec_a or i not in dec_b]
    both = [i for i in ids if i in dec_a and i in dec_b]
    binar = lambda d: "exclude" if d == "exclude" else "include"
    a = [binar(dec_a[i]["decision"]) for i in both]
    b = [binar(dec_b[i]["decision"]) for i in both]
    final, conflicts = {}, []
    for i in both:
        da, db = dec_a[i]["decision"], dec_b[i]["decision"]
        if i in resolutions:
            final[i] = resolutions[i]
        elif binar(da) == binar(db):
            final[i] = "exclude" if binar(da) == "exclude" else "include"
        elif stage == "title_abstract":
            final[i] = "include"  # liberal acceptance: either reviewer's include/maybe goes to full text
            conflicts.append({"id": i, "a": dec_a[i], "b": dec_b[i], "auto": "advanced to full text (liberal rule)"})
        else:
            conflicts.append({"id": i, "a": dec_a[i], "b": dec_b[i], "auto": None})
    unresolved = [c for c in conflicts if c["auto"] is None]
    return {"stage": stage, "n": len(ids), "screened_by_both": len(both), "missing": missing,
            "agreement": (sum(x == y for x, y in zip(a, b)) / len(both)) if both else None,
            "kappa": cohen_kappa(a, b), "conflicts": conflicts, "unresolved": unresolved,
            "included": [i for i in both if final.get(i) == "include"],
            "excluded": [i for i in both if final.get(i) == "exclude"],
            "exclusion_reasons": _reasons([dec_a[i] for i in both if final.get(i) == "exclude"])}


def _reasons(decs):
    out = {}
    for d in decs:
        k = d.get("criterion") or d.get("reason") or "not stated"
        out[k] = out.get(k, 0) + 1
    return dict(sorted(out.items(), key=lambda kv: -kv[1]))


def prisma_counts(search: dict, ta: dict, ft: dict | None) -> dict:
    counts = {"identified": search["identified"], "duplicates_removed": search["duplicates_removed"],
              "screened": ta["n"], "excluded_screening": len(ta["excluded"]),
              "fulltext_assessed": len(ta["included"])}
    if ft:
        counts["fulltext_excluded"] = len(ft["excluded"])
        counts["fulltext_exclusion_reasons"] = ft["exclusion_reasons"]
        counts["included_review"] = len(ft["included"])
    return counts


def write_included(records: list[dict], included_ids: list[str], path: Path):
    by_id = {r["id"]: r for r in records}
    with open(path, "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=["pmid", "doi", "title", "authors", "year", "journal"])
        w.writeheader()
        for i in included_ids:
            r = by_id[i]
            w.writerow({k: r.get(k) for k in ("pmid", "doi", "title", "authors", "year", "journal")})


def screening_report(ta: dict, ft: dict | None) -> str:
    def block(r, name):
        k = "NA" if r["kappa"] is None else f"{r['kappa']:.2f}"
        ag = "NA" if r["agreement"] is None else f"{100 * r['agreement']:.1f}%"
        lines = [f"## {name}", "", f"- Records: {r['n']} (screened by both reviewers: {r['screened_by_both']})",
                 f"- Agreement: {ag}; Cohen's kappa: {k}", f"- Included: {len(r['included'])}; excluded: {len(r['excluded'])}",
                 f"- Conflicts: {len(r['conflicts'])} ({len(r['unresolved'])} need a decision)"]
        if r["missing"]:
            lines.append(f"- NOT YET SCREENED by both reviewers: {len(r['missing'])}")
        if r["unresolved"]:
            lines += ["", "| Record | Reviewer A | Reviewer B |", "|---|---|---|"]
            lines += [f"| {c['id']} | {c['a']['decision']}: {c['a'].get('reason')} | {c['b']['decision']}: {c['b'].get('reason')} |"
                      for c in r["unresolved"]]
        if r["exclusion_reasons"]:
            lines += ["", "Exclusion reasons:", ""] + [f"- {k}: {v}" for k, v in r["exclusion_reasons"].items()]
        return lines
    out = ["# Screening report", ""] + block(ta, "Title and abstract")
    if ft:
        out += [""] + block(ft, "Full text")
    return "\n".join(out) + "\n"
