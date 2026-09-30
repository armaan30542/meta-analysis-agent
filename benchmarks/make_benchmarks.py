"""Build the benchmark projects from the metafor reference datasets.

Each benchmark is a complete metakit project: protocol, a source-text file standing in for
the papers, gold-standard extraction files whose quotes cite that source, and the expected
results (published values where they exist, metafor values always).

Run from the repo root:  python benchmarks/make_benchmarks.py
"""
import json
import re
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent
REF = json.loads((ROOT.parent / "tests" / "fixtures" / "metafor_reference.json").read_text())


def fname(sid):
    return re.sub(r"[^A-Za-z0-9]+", "_", sid).strip("_") + ".json"


def fld(value, quote, location):
    return {"value": value, "quote": quote, "location": location}


def bcg():
    proj = ROOT / "bcg"
    (proj / "extraction").mkdir(parents=True, exist_ok=True)
    (proj / "fulltext").mkdir(exist_ok=True)
    rows = REF["bcg"]["data"]
    src = ["# BCG vaccine trials (Colditz et al., JAMA 1994; distributed as metafor::dat.bcg)", "",
           "Each line reproduces one trial's 2x2 table as reported in Colditz et al. (1994), Table 1.", ""]
    for r in rows:
        nt, nc = r["tpos"] + r["tneg"], r["cpos"] + r["cneg"]
        line = (f"Trial {r['trial']} ({r['author']} {r['year']}): vaccinated group {r['tpos']} TB cases "
                f"among {nt} participants; unvaccinated group {r['cpos']} TB cases among {nc} participants; "
                f"absolute latitude {r['ablat']} degrees; allocation {r['alloc']}.")
        src.append(line)
        sid = f"{r['author']} {r['year']}"
        loc = "Colditz 1994, Table 1"
        rec = {
            "study_id": sid, "year": r["year"], "design": "RCT" if r["alloc"] == "random" else "non-randomised",
            "citation": f"{r['author']} ({r['year']}), as tabulated by Colditz et al., JAMA 1994;271:698-702",
            "source_file": "fulltext/colditz1994_table1.md", "extracted_by": "gold (metafor::dat.bcg)",
            "outcomes": [{
                "outcome": "tb_cases", "data_type": "binary",
                "group_t": "BCG vaccinated", "group_c": "not vaccinated",
                "fields": {
                    "events_t": fld(r["tpos"], f"vaccinated group {r['tpos']} TB cases among {nt} participants", loc),
                    "n_t": fld(nt, f"vaccinated group {r['tpos']} TB cases among {nt} participants", loc),
                    "events_c": fld(r["cpos"], f"unvaccinated group {r['cpos']} TB cases among {nc} participants", loc),
                    "n_c": fld(nc, f"unvaccinated group {r['cpos']} TB cases among {nc} participants", loc),
                },
            }],
            "moderators": {
                "ablat": fld(r["ablat"], f"absolute latitude {r['ablat']} degrees", loc),
                "alloc": fld(r["alloc"], f"allocation {r['alloc']}", loc),
            },
        }
        (proj / "extraction" / fname(sid)).write_text(json.dumps(rec, indent=2))
    (proj / "fulltext" / "colditz1994_table1.md").write_text("\n".join(src) + "\n")
    protocol = {
        "title": "BCG vaccine for preventing tuberculosis (benchmark: Colditz et al., 1994)",
        "question": "Does BCG vaccination reduce the risk of tuberculosis compared with no vaccination?",
        "study_designs": ["RCT", "non-randomised"],
        "outcomes": [{"id": "tb_cases", "label": "Tuberculosis cases", "primary": True,
                      "data_type": "binary", "measure": "RR",
                      "favours": ["Favours vaccine", "Favours control"]}],
        "model": {"method": "REML", "test": "z", "level": 95},
        "subgroups": ["alloc"], "meta_regression": ["ablat"],
        "sensitivity": {"exclude_high_risk_of_bias": False, "exclude_estimated_sds": False},
        "risk_of_bias_tool": "none",
    }
    (proj / "protocol.yaml").write_text(yaml.safe_dump(protocol, sort_keys=False))
    f = REF["bcg"]["fits"]["REML"]
    expected = {
        "published": {
            "source": "Colditz GA et al. Efficacy of BCG vaccine in the prevention of tuberculosis. "
                      "JAMA 1994;271(9):698-702 (random-effects RR 0.49, 95% CI 0.34-0.70)",
            "outcome": "tb_cases", "estimate": 0.49, "ci_lb": 0.34, "ci_ub": 0.70, "decimals": 2},
        "metafor": {"outcome": "tb_cases", "estimate": f["beta"], "ci_lb": f["ci_lb"], "ci_ub": f["ci_ub"],
                    "tau2": f["tau2"], "I2": f["I2"], "QE": f["QE"],
                    "trimfill_k0": REF["bcg"]["trimfill"]["k0"], "egger_p": REF["bcg"]["egger_rma"]["pval"],
                    "metareg_slope": REF["bcg"]["metareg_ablat"]["beta"][1],
                    "subgroup_QM": REF["bcg"]["metareg_alloc"]["QM"]},
    }
    (proj / "expected.json").write_text(json.dumps(expected, indent=2))
    (proj / "prisma.json").write_text(json.dumps({
        "identified": 13, "duplicates_removed": 0, "screened": 13, "excluded_screening": 0,
        "fulltext_assessed": 13, "fulltext_excluded": 0,
        "note": "benchmark: the 13 trials tabulated by Colditz et al. are taken as given"}, indent=2))


def normand():
    proj = ROOT / "normand"
    (proj / "extraction").mkdir(parents=True, exist_ok=True)
    (proj / "fulltext").mkdir(exist_ok=True)
    rows = REF["normand"]["data"]
    src = ["# Specialist stroke care vs routine care: length of hospital stay (days)",
           "(Normand, Stat Med 1999; distributed as metafor::dat.normand1999)", ""]
    for r in rows:
        line = (f"{r['source']}: specialist care mean length of stay {r['m1i']} days (SD {r['sd1i']}, "
                f"n = {r['n1i']}); routine care mean {r['m2i']} days (SD {r['sd2i']}, n = {r['n2i']}).")
        src.append(line)
        sid = r["source"]
        loc = "Normand 1999, Table I"
        q_t = f"specialist care mean length of stay {r['m1i']} days (SD {r['sd1i']}, n = {r['n1i']})"
        q_c = f"routine care mean {r['m2i']} days (SD {r['sd2i']}, n = {r['n2i']})"
        rec = {
            "study_id": sid, "design": "RCT", "source_file": "fulltext/normand1999_table.md",
            "extracted_by": "gold (metafor::dat.normand1999)",
            "outcomes": [{"outcome": "length_of_stay", "data_type": "continuous", "unit": "days",
                          "fields": {"mean_t": fld(r["m1i"], q_t, loc), "sd_t": fld(r["sd1i"], q_t, loc),
                                     "n_t": fld(r["n1i"], q_t, loc), "mean_c": fld(r["m2i"], q_c, loc),
                                     "sd_c": fld(r["sd2i"], q_c, loc), "n_c": fld(r["n2i"], q_c, loc)}}],
        }
        (proj / "extraction" / fname(sid)).write_text(json.dumps(rec, indent=2))
    (proj / "fulltext" / "normand1999_table.md").write_text("\n".join(src) + "\n")
    protocol = {
        "title": "Specialist stroke care and length of hospital stay (benchmark: Normand, 1999)",
        "question": "Does specialist stroke-unit care change length of hospital stay compared with routine care?",
        "study_designs": ["RCT"],
        "outcomes": [{"id": "length_of_stay", "label": "Length of hospital stay", "primary": True,
                      "data_type": "continuous", "measure": "MD", "unit": "days",
                      "favours": ["Shorter with specialist care", "Longer with specialist care"]}],
        "model": {"method": "REML", "test": "z", "level": 95},
        "sensitivity": {"exclude_high_risk_of_bias": False, "exclude_estimated_sds": True},
        "risk_of_bias_tool": "none",
    }
    (proj / "protocol.yaml").write_text(yaml.safe_dump(protocol, sort_keys=False))
    f = REF["normand"]["md_REML"]
    (proj / "expected.json").write_text(json.dumps({"metafor": {
        "outcome": "length_of_stay", "estimate": f["beta"], "ci_lb": f["ci_lb"], "ci_ub": f["ci_ub"],
        "tau2": f["tau2"], "I2": f["I2"], "QE": f["QE"]}}, indent=2))


if __name__ == "__main__":
    bcg()
    normand()
    print("benchmarks written")
