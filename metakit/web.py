"""Glue between the browser app (docs/app) and metakit.

The website runs this exact package in the browser through Pyodide, so the web app and the
command line share one validated code path. Everything here is plain functions on JSON-able
data; the browser passes strings in and gets dicts back.
"""
from __future__ import annotations

import base64
import io
import json
import shutil
import tempfile
import zipfile
from pathlib import Path

import yaml

from . import __version__
from .analysis import run_analysis
from .extraction import DATA_TYPES, ValidationReport, load_extractions, validate_folder, validate_record
from .protocol import normalize_protocol
from .reconcile import compare
from .report import write_report
from .retrieve import jats_to_markdown
from .rob import load_rob


def version() -> str:
    return __version__


def data_types() -> dict:
    return {k: {"required": list(v["required"]), "optional": list(v["optional"])} for k, v in DATA_TYPES.items()}


def _manual_field(name, value, who):
    q = f"{name} = {value} (entered manually by {who})"
    return {"value": value, "quote": q, "location": "manual entry"}


def rows_to_records(rows: list[dict], outcome: dict, who: str = "reviewer") -> list[dict]:
    """Turn spreadsheet-style rows into extraction records.

    Each row: ``{"study_id", "year"?, "design"?, <fields for the data type>, <moderators>}``.
    Values typed by a person have no paper quote, so the quote records who entered them;
    the report's validation appendix shows these as manual entries.
    """
    dt = outcome["data_type"]
    allowed = set(DATA_TYPES[dt]["required"]) | set(DATA_TYPES[dt]["optional"])
    records = []
    for r in rows:
        sid = str(r.get("study_id") or "").strip()
        if not sid:
            continue
        fields, mods = {}, {}
        for k, v in r.items():
            if k in ("study_id", "year", "design") or v in (None, ""):
                continue
            try:
                num = float(v)
                num = int(num) if num.is_integer() and k in ("n", "n_t", "n_c", "events", "events_t", "events_c") else num
            except (TypeError, ValueError):
                num = None
            if k in allowed:
                fields[k] = _manual_field(k, num if num is not None else v, who)
            else:
                mods[k] = _manual_field(k, num if num is not None else str(v), who)
        oc = {"outcome": outcome["id"], "data_type": dt, "fields": fields}
        if dt == "generic":
            oc["scale"] = outcome.get("generic_scale") or "difference"
        rec = {"study_id": sid, "outcomes": [oc], "moderators": mods, "extracted_by": f"manual ({who})"}
        if r.get("year") not in (None, ""):
            try:
                rec["year"] = int(float(r["year"]))
            except ValueError:
                pass
        if r.get("design"):
            rec["design"] = r["design"]
        records.append(rec)
    return records


def _write_project(root: Path, protocol: dict, records: list[dict], sources: dict | None,
                   rob: dict | None, prisma: dict | None):
    for d in ("extraction", "fulltext", "rob"):
        (root / d).mkdir(parents=True, exist_ok=True)
    (root / "protocol.yaml").write_text(yaml.safe_dump(protocol, sort_keys=False))
    for i, rec in enumerate(records):
        key = "".join(c if c.isalnum() else "_" for c in rec.get("study_id", f"study{i}")).strip("_") or f"study{i}"
        (root / "extraction" / f"{key}_{i}.json").write_text(json.dumps(rec))
    for name, text in (sources or {}).items():
        p = root / name
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text)
    for sid, rec in (rob or {}).items():
        key = "".join(c if c.isalnum() else "_" for c in sid).strip("_")
        (root / "rob" / f"{key}.json").write_text(json.dumps({"study_id": sid, **rec}))
    if prisma and any(v not in (None, "") for v in prisma.values()):
        (root / "prisma.json").write_text(json.dumps(prisma))


def validate(protocol_json: str, records_json: str, sources_json: str = "{}") -> dict:
    """Validate extraction records (one list) against the protocol and source texts."""
    protocol = normalize_protocol(json.loads(protocol_json))
    records = json.loads(records_json)
    sources = json.loads(sources_json)
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        _write_project(root, protocol, records, sources, None, None)
        rep = validate_folder(root / "extraction", protocol, root)
    return {"ok": rep.ok, "errors": [i.__dict__ for i in rep.errors],
            "warnings": [i.__dict__ for i in rep.warnings], "n_values": rep.n_values,
            "n_quotes_checked": rep.n_quotes_checked, "n_quotes_verified": rep.n_quotes_verified,
            "markdown": rep.to_markdown()}


def validate_one(protocol_json: str, record_json: str, source_text: str | None) -> dict:
    """Validate a single study (used right after the AI extracts it)."""
    protocol = normalize_protocol(json.loads(protocol_json))
    rec = json.loads(record_json)
    sources = {}
    if source_text is not None:
        rec["source_file"] = "fulltext/source.md"
        sources["fulltext/source.md"] = source_text
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        _write_project(root, protocol, [], sources, None, None)
        rep = ValidationReport(n_studies=1)
        validate_record(rec, protocol, rep, root)
    return {"ok": rep.ok, "errors": [i.__dict__ for i in rep.errors],
            "warnings": [i.__dict__ for i in rep.warnings],
            "n_quotes_checked": rep.n_quotes_checked, "n_quotes_verified": rep.n_quotes_verified}


def reconcile(records_a_json: str, records_b_json: str) -> dict:
    with tempfile.TemporaryDirectory() as td:
        a, b = Path(td) / "a", Path(td) / "b"
        a.mkdir()
        b.mkdir()
        for folder, recs in ((a, json.loads(records_a_json)), (b, json.loads(records_b_json))):
            for i, rec in enumerate(recs):
                (folder / f"{i}.json").write_text(json.dumps(rec))
        return compare(a, b)


def analyze(protocol_json: str, records_json: str, sources_json: str = "{}", rob_json: str = "{}",
            prisma_json: str = "{}", allow_errors: bool = False) -> dict:
    """Validate, analyse and report. Returns results, figures (base64 PNG), report and a zip."""
    protocol = normalize_protocol(json.loads(protocol_json))
    records = json.loads(records_json)
    rob = json.loads(rob_json) or None
    prisma = json.loads(prisma_json) or None
    td = tempfile.mkdtemp()
    try:
        root = Path(td) / "meta-analysis"
        root.mkdir()
        _write_project(root, protocol, records, json.loads(sources_json), rob, prisma)
        rep = validate_folder(root / "extraction", protocol, root)
        tool = protocol.get("risk_of_bias_tool")
        rob_records, problems = (load_rob(root / "rob", tool) if rob and tool and tool != "none" else ({}, {}))
        out = {"validation": {"ok": rep.ok, "errors": [i.__dict__ for i in rep.errors],
                              "warnings": [i.__dict__ for i in rep.warnings],
                              "n_quotes_checked": rep.n_quotes_checked,
                              "n_quotes_verified": rep.n_quotes_verified},
               "rob_problems": problems}
        if not rep.ok and not allow_errors:
            out["results"] = None
            return out
        (root / "analysis").mkdir(exist_ok=True)
        (root / "analysis" / "validation.md").write_text(rep.to_markdown())
        results = run_analysis(root, protocol, load_extractions(root / "extraction"), rob_records or None,
                               tool if rob_records else None)
        write_report(results, protocol, root, rep.to_markdown())
        figs = {}
        for png in sorted((root / "analysis").rglob("*.png")):
            figs[str(png.relative_to(root / "analysis"))] = base64.b64encode(png.read_bytes()).decode()
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
            for f in sorted(root.rglob("*")):
                if f.is_file():
                    z.write(f, f.relative_to(root.parent))
        out.update({"results": results, "figures": figs,
                    "report_md": (root / "report" / "report.md").read_text(),
                    "zip_b64": base64.b64encode(buf.getvalue()).decode()})
        return out
    finally:
        shutil.rmtree(td, ignore_errors=True)


def jats(xml_text: str) -> str:
    return jats_to_markdown(xml_text.encode("utf-8"))


EXTRACTION_SYSTEM_PROMPT = """You are a meticulous data extractor for a meta-analysis. You read ONE study and return ONLY a JSON object, no prose, no markdown fences.

Rules (a validator will check every one, and errors are sent back to you):
- For every number, copy "value" exactly as printed (never round, convert or recalculate) and copy "quote" CHARACTER-FOR-CHARACTER from the full text: the shortest sentence or table row containing the number. "location" names the table/figure/section.
- Record SE as se_*, confidence limits as ci_lower_*/ci_upper_*, medians as median_* with q1_*/q3_* or min_*/max_*. The software converts them.
- Group sizes are the numbers analysed for that outcome.
- If the paper reports a unit different from the protocol's, put it in the outcome's "unit".
- Only if unavoidable (percentage + denominator but no count), add "derived": true and "derivation": "13.3% of 60 = 8".
- Omit outcomes the paper does not report and list them in "notes". Never guess.
- Suffix _t = intervention/exposed group, _c = comparator.

Fields by data_type:
binary: events_t, n_t, events_c, n_c
continuous: n_t, n_c, plus per arm mean+sd | mean+se | mean+ci_lower+ci_upper | median+q1+q3 and/or min+max (with _t/_c)
single_group: n plus the same per-arm options without suffix
proportion: events, n
correlation: r, n
generic: estimate plus se or ci_lower+ci_upper, and outcome-level "scale": "ratio" or "difference"

Output shape:
{"study_id": "...", "year": 2019, "design": "RCT|cohort|cross-sectional|case-control|...",
 "outcomes": [{"outcome": "<protocol outcome id>", "data_type": "...", "unit": "...",
   "fields": {"n_t": {"value": 60, "quote": "...", "location": "Table 2"}}}],
 "moderators": {"<moderator name>": {"value": ..., "quote": "...", "location": "..."}},
 "notes": "..."}"""


def extraction_user_prompt(protocol_json: str, study_id: str, source_text: str) -> str:
    protocol = normalize_protocol(json.loads(protocol_json))
    outs = [{k: o.get(k) for k in ("id", "label", "data_type", "measure", "unit")} for o in protocol["outcomes"]]
    mods = sorted(set(protocol.get("subgroups") or []) | set(protocol.get("meta_regression") or []))
    return (f"Protocol outcomes: {json.dumps(outs)}\n"
            f"Moderators to extract (if reported): {json.dumps(mods)}\n"
            f"Use study_id exactly: {json.dumps(study_id)}\n\n"
            f"FULL TEXT:\n<<<\n{source_text}\n>>>")


def fix_prompt(errors: list[dict]) -> str:
    lines = "\n".join(f"- {e['where']}: {e['message']}" for e in errors)
    return ("The validator rejected your extraction:\n" + lines +
            "\nRe-read the full text and return the corrected complete JSON object only. "
            "If a number cannot be found verbatim, remove that field and explain in notes.")
