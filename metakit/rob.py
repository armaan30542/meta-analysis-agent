"""Risk-of-bias assessments: one JSON file per study in ``<project>/rob/``.

Supported tools and their domains:

* **RoB2** (Sterne et al., 2019) for randomised trials
* **ROBINS-I** (Sterne et al., 2016) for non-randomised studies of interventions
* **NOS** (Newcastle-Ottawa Scale) for cohort / case-control studies (star-based)
* **QUIPS** (Hayden et al., 2013) for prognostic-factor studies

Judgements are made by the reviewers (or proposed by the agent and then confirmed); every
judgement needs a supporting quote, as with extracted numbers.
"""
from __future__ import annotations

import json
from pathlib import Path

TOOLS = {
    "RoB2": {
        "domains": {
            "D1": "Randomisation process",
            "D2": "Deviations from intended interventions",
            "D3": "Missing outcome data",
            "D4": "Measurement of the outcome",
            "D5": "Selection of the reported result",
        },
        "levels": ["low", "some concerns", "high"],
    },
    "ROBINS-I": {
        "domains": {
            "D1": "Confounding", "D2": "Selection of participants",
            "D3": "Classification of interventions", "D4": "Deviations from intended interventions",
            "D5": "Missing data", "D6": "Measurement of outcomes",
            "D7": "Selection of the reported result",
        },
        "levels": ["low", "moderate", "serious", "critical"],
    },
    "QUIPS": {
        "domains": {
            "D1": "Study participation", "D2": "Study attrition",
            "D3": "Prognostic factor measurement", "D4": "Outcome measurement",
            "D5": "Study confounding", "D6": "Statistical analysis and reporting",
        },
        "levels": ["low", "moderate", "high"],
    },
    "NOS": {
        "domains": {"selection": "Selection (max 4 stars)", "comparability": "Comparability (max 2)",
                    "outcome": "Outcome / exposure (max 3)"},
        "levels": None,
    },
}

# which overall judgements count as "high risk" for sensitivity analyses and GRADE
HIGH_RISK = {"high", "serious", "critical", "poor"}
NOS_MAX = {"selection": 4, "comparability": 2, "outcome": 3}


def nos_overall(stars: dict) -> str:
    """AHRQ thresholds for converting NOS stars to good / fair / poor."""
    s, c, o = stars.get("selection", 0), stars.get("comparability", 0), stars.get("outcome", 0)
    if s >= 3 and c >= 1 and o >= 2:
        return "good"
    if s == 2 and c >= 1 and o >= 2:
        return "fair"
    return "poor"


def validate_rob(rec: dict, tool: str) -> list[str]:
    problems = []
    if tool not in TOOLS:
        return [f"unknown risk-of-bias tool {tool}"]
    spec = TOOLS[tool]
    domains = rec.get("domains") or {}
    for d in spec["domains"]:
        if d not in domains:
            problems.append(f"missing domain {d} ({spec['domains'][d]})")
            continue
        entry = domains[d]
        if tool == "NOS":
            stars = entry.get("stars")
            if not isinstance(stars, int) or not 0 <= stars <= NOS_MAX[d]:
                problems.append(f"{d}: stars must be an integer 0-{NOS_MAX[d]}")
        else:
            j = (entry.get("judgement") or "").lower()
            if j not in spec["levels"]:
                problems.append(f"{d}: judgement must be one of {spec['levels']}, got {j!r}")
        if not entry.get("support"):
            problems.append(f"{d}: add a supporting quote or reason")
    if tool != "NOS":
        overall = (rec.get("overall") or "").lower()
        if overall not in spec["levels"]:
            problems.append(f"overall must be one of {spec['levels']}")
        else:
            worst = max((spec["levels"].index((domains.get(d, {}).get("judgement") or "low").lower())
                         for d in spec["domains"] if (domains.get(d, {}).get("judgement") or "").lower() in spec["levels"]),
                        default=0)
            if spec["levels"].index(overall) < worst:
                problems.append(f"overall ({overall}) is better than the worst domain "
                                f"({spec['levels'][worst]}); RoB2/ROBINS-I overall is at least the worst domain")
    return problems


def load_rob(folder: Path, tool: str) -> tuple[dict, dict]:
    """Returns ({study_id: record}, {study_id: [problems]})."""
    folder = Path(folder)
    records, problems = {}, {}
    if not folder.exists():
        return records, problems
    for p in sorted(folder.glob("*.json")):
        rec = json.loads(p.read_text(encoding="utf-8"))
        sid = rec.get("study_id") or p.stem
        if tool == "NOS":
            stars = {d: (rec.get("domains", {}).get(d) or {}).get("stars", 0) for d in NOS_MAX}
            rec["overall"] = nos_overall(stars)
        rec["overall"] = (rec.get("overall") or "").lower() or None
        records[sid] = rec
        pr = validate_rob(rec, tool)
        if pr:
            problems[sid] = pr
    return records, problems


def is_high_risk(overall: str | None) -> bool:
    return (overall or "").lower() in HIGH_RISK
