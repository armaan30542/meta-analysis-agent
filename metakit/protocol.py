"""The review protocol (``protocol.yaml``): the decisions made *before* seeing results.

Pre-specifying outcomes, effect measures, the model and planned subgroup analyses is what
separates a meta-analysis from data dredging (PRISMA 2020 item 24; Cochrane Handbook ch. 1).
"""
from __future__ import annotations

from pathlib import Path

import yaml

from .effects import MEASURES
from .models import METHODS, TESTS

DATA_TYPE_MEASURES = {
    "binary": {"RR", "OR", "RD"},
    "continuous": {"MD", "SMD", "ROM"},
    "single_group": {"MN"},
    "proportion": {"PR", "PLO"},
    "correlation": {"ZCOR", "COR"},
    "generic": {"GEN"},
}

DEFAULTS = {
    "model": {"method": "REML", "test": "knha", "level": 95},
    "bias": {"egger_model": "rma", "trim_and_fill": True},
    "grade": {"start": "auto", "indirectness": 0},
}

TEMPLATE = """\
# Meta-analysis protocol. Fill this in BEFORE extracting data.
title: "Meta-analysis title"
question: >
  One-sentence research question in PICO form.
registration: null            # e.g. PROSPERO CRD42026xxxxxx, or null
authors: ["Your Name"]

pico:
  population: "..."
  intervention_or_exposure: "..."
  comparator: "..."
  outcomes: "..."

study_designs: ["RCT"]        # RCT, cohort, case-control, cross-sectional ...

outcomes:
  - id: primary_outcome       # short id used in every extraction file
    label: "Readable outcome name"
    primary: true
    data_type: binary         # binary | continuous | single_group | proportion | correlation | generic
    measure: RR               # binary: RR/OR/RD; continuous: MD/SMD/ROM; single_group: MN;
                              # proportion: PR/PLO; correlation: ZCOR/COR; generic: GEN
    unit: null                # for MD / MN: the unit every study is converted to
    favours: ["Favours treatment", "Favours control"]   # labels under the forest plot
    generic_scale: null       # generic only: ratio | difference

model:
  method: REML                # REML (recommended), DL, PM, ML, HE, FE
  test: knha                  # knha (Knapp-Hartung, recommended) or z
  level: 95

subgroups: []                 # moderator names (from extraction files) for subgroup analyses
meta_regression: []           # numeric moderators for meta-regression (needs >= 10 studies)
sensitivity:
  exclude_high_risk_of_bias: true
  exclude_estimated_sds: true # drop studies whose mean/SD came from medians

risk_of_bias_tool: RoB2       # RoB2 | ROBINS-I | NOS | QUIPS | none
"""


class ProtocolError(ValueError):
    pass


def load_protocol(path: Path) -> dict:
    path = Path(path)
    if not path.exists():
        raise ProtocolError(f"{path} not found; run `metakit init` to create one")
    with open(path, encoding="utf-8") as fh:
        proto = yaml.safe_load(fh) or {}
    return normalize_protocol(proto)


def normalize_protocol(proto: dict) -> dict:
    proto = dict(proto)
    for key, val in DEFAULTS.items():
        merged = dict(val)
        merged.update(proto.get(key) or {})
        proto[key] = merged
    proto.setdefault("subgroups", [])
    proto.setdefault("meta_regression", [])
    proto.setdefault("sensitivity", {})
    proto["sensitivity"].setdefault("exclude_high_risk_of_bias", True)
    proto["sensitivity"].setdefault("exclude_estimated_sds", True)
    proto.setdefault("risk_of_bias_tool", "none")

    errors = []
    outcomes = proto.get("outcomes") or []
    if not outcomes:
        errors.append("protocol needs at least one outcome")
    ids = set()
    for i, oc in enumerate(outcomes):
        oid = oc.get("id")
        if not oid:
            errors.append(f"outcome {i} has no id")
            continue
        if oid in ids:
            errors.append(f"duplicate outcome id {oid}")
        ids.add(oid)
        dt, m = oc.get("data_type"), oc.get("measure")
        if dt not in DATA_TYPE_MEASURES:
            errors.append(f"{oid}: data_type must be one of {sorted(DATA_TYPE_MEASURES)}")
        elif m not in DATA_TYPE_MEASURES[dt]:
            errors.append(f"{oid}: measure {m!r} does not fit data_type {dt} "
                          f"(choose from {sorted(DATA_TYPE_MEASURES[dt])})")
        if m and m not in MEASURES:
            errors.append(f"{oid}: unknown measure {m}")
        if dt == "generic" and oc.get("generic_scale") not in ("ratio", "difference"):
            errors.append(f"{oid}: generic outcomes need generic_scale: ratio or difference")
        oc.setdefault("label", oid)
        oc.setdefault("favours", None)
        oc.setdefault("unit", None)
    if sum(1 for o in outcomes if o.get("primary")) > 1:
        errors.append("mark exactly one outcome as primary")
    if outcomes and not any(o.get("primary") for o in outcomes):
        outcomes[0]["primary"] = True
    if proto["model"]["method"] not in METHODS:
        errors.append(f"model.method must be one of {METHODS}")
    if proto["model"]["test"] not in TESTS:
        errors.append(f"model.test must be one of {TESTS}")
    if errors:
        raise ProtocolError("protocol.yaml problems:\n  - " + "\n  - ".join(errors))
    return proto
