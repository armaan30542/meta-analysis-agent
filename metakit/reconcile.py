"""Compare two extraction sets.

Used two ways:

* **Reconciliation** (``metakit reconcile extraction_a extraction_b``): two independent
  extractors (two agent runs, or an agent and a human) extract the same studies blind to each
  other, as the Cochrane Handbook (5.5.2) recommends; every disagreement is listed for a human
  to resolve.
* **Accuracy benchmarking** (``metakit benchmark --gold ...``): one side is a verified gold
  standard, and the agreement rate *is* the extraction accuracy.
"""
from __future__ import annotations

from pathlib import Path

from .extraction import field_value, load_extractions


def _index(records):
    idx = {}
    for rec in records:
        sid = rec.get("study_id")
        for oc in rec.get("outcomes") or []:
            key = (sid, oc.get("outcome"))
            fields = oc.get("fields") or {}
            idx[key] = {"data_type": oc.get("data_type"),
                        "values": {n: field_value(fields, n) for n in fields if field_value(fields, n) is not None}}
        for name, f in (rec.get("moderators") or {}).items():
            idx.setdefault((sid, "_moderators"), {"data_type": None, "values": {}})
            val = f.get("value") if isinstance(f, dict) else f
            if val is not None:
                idx[(sid, "_moderators")]["values"][name] = val
    return idx


def _same(a, b, rel_tol=1e-6):
    if isinstance(a, (int, float)) and isinstance(b, (int, float)):
        return abs(a - b) <= rel_tol * max(1.0, abs(a), abs(b))
    return str(a).strip().lower() == str(b).strip().lower()


def compare(folder_a: Path, folder_b: Path) -> dict:
    A, B = _index(load_extractions(folder_a)), _index(load_extractions(folder_b))
    rows, agree, total = [], 0, 0
    studies_a = {k[0] for k in A}
    studies_b = {k[0] for k in B}
    for key in sorted(set(A) | set(B), key=str):
        sid, oc = key
        if key not in A or key not in B:
            rows.append({"study": sid, "outcome": oc, "field": "*",
                         "a": "present" if key in A else "missing",
                         "b": "present" if key in B else "missing", "type": "outcome_missing"})
            n_fields = len((A.get(key) or B.get(key))["values"])
            total += n_fields
            continue
        a, b = A[key], B[key]
        if a["data_type"] != b["data_type"]:
            rows.append({"study": sid, "outcome": oc, "field": "data_type", "a": a["data_type"],
                         "b": b["data_type"], "type": "data_type"})
        for name in sorted(set(a["values"]) | set(b["values"])):
            total += 1
            va, vb = a["values"].get(name), b["values"].get(name)
            if va is not None and vb is not None and _same(va, vb):
                agree += 1
            else:
                rows.append({"study": sid, "outcome": oc, "field": name, "a": va, "b": vb,
                             "type": "value" if va is not None and vb is not None else "field_missing"})
    return {"agreement": agree / total if total else 1.0, "n_fields": total, "n_agree": agree,
            "discrepancies": rows, "studies_only_in_a": sorted(studies_a - studies_b),
            "studies_only_in_b": sorted(studies_b - studies_a)}


def to_markdown(result: dict, name_a="A", name_b="B", title="Dual extraction reconciliation") -> str:
    lines = [f"# {title}", "",
             f"- Fields compared: {result['n_fields']}",
             f"- Agreement: {result['n_agree']} / {result['n_fields']} ({100 * result['agreement']:.1f}%)",
             f"- Discrepancies to resolve: {len(result['discrepancies'])}", ""]
    if result["studies_only_in_a"]:
        lines.append(f"- Studies only in {name_a}: {', '.join(result['studies_only_in_a'])}")
    if result["studies_only_in_b"]:
        lines.append(f"- Studies only in {name_b}: {', '.join(result['studies_only_in_b'])}")
    if result["discrepancies"]:
        lines += ["", f"| Study | Outcome | Field | {name_a} | {name_b} | Resolution |", "|---|---|---|---|---|---|"]
        for d in result["discrepancies"]:
            lines.append(f"| {d['study']} | {d['outcome']} | {d['field']} | {d['a']} | {d['b']} | |")
        lines += ["", "Resolve each row by re-reading the source, fix the extraction files, and re-run."]
    return "\n".join(lines) + "\n"
