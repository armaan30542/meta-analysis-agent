"""Turn validated extraction records into one effect size per study per outcome.

Every conversion applied (SE -> SD, median/IQR -> mean/SD, unit changes, continuity
corrections) is written to the study's ``derivations`` list so the report can say exactly
what was done to which number.
"""
from __future__ import annotations

import csv
import math
from dataclasses import dataclass, field
from pathlib import Path

from . import convert, effects
from .extraction import field_value


@dataclass
class StudyEffect:
    study_id: str
    outcome: str
    yi: float
    vi: float
    n_total: int | None
    events_total: int | None = None
    year: int | None = None
    derivations: list = field(default_factory=list)
    estimated_sd: bool = False
    rob_overall: str | None = None
    moderators: dict = field(default_factory=dict)
    display_est: float | None = None
    display_lo: float | None = None
    display_hi: float | None = None


@dataclass
class Exclusion:
    study_id: str
    outcome: str
    reason: str


def _arm_mean_sd(fields: dict, sfx: str, n: float, notes: list, unit_from=None, unit_to=None):
    """Resolve an arm's mean and SD from whatever was reported. Returns (mean, sd, estimated)."""
    g = lambda s: field_value(fields, f"{s}{sfx}")
    arm = {"_t": "treatment", "_c": "control", "": "group"}[sfx]
    estimated = False
    mean, sd = g("mean"), g("sd")
    if mean is not None and sd is not None:
        pass
    elif mean is not None and g("se") is not None:
        sd = convert.sd_from_se(g("se"), n)
        notes.append(f"{arm}: SD = SE x sqrt(n) = {g('se')} x sqrt({n:g}) = {sd:.4g}")
    elif mean is not None and g("ci_lower") is not None and g("ci_upper") is not None:
        sd = convert.sd_from_ci(g("ci_lower"), g("ci_upper"), int(n))
        dist = "t" if n < 60 else "normal"
        notes.append(f"{arm}: SD from 95% CI [{g('ci_lower')}, {g('ci_upper')}] ({dist} critical value) = {sd:.4g}")
    elif g("median") is not None:
        r = convert.mean_sd_from_quantiles(n, g("median"), g("q1"), g("q3"), g("min"), g("max"))
        mean, sd, estimated = r["mean"], r["sd"], True
        notes.append(f"{arm}: mean {mean:.4g} and SD {sd:.4g} estimated from {r['case']} ({r['method']})")
        if r["warning"]:
            notes.append(f"{arm}: WARNING {r['warning']}")
    else:
        raise ValueError(f"{arm} arm has no usable summary statistics")
    if unit_from and unit_to and unit_from != unit_to:
        mean_c = convert.convert_units(mean, unit_from, unit_to)
        sd_c = convert.convert_units(sd, unit_from, unit_to)
        notes.append(f"{arm}: converted {unit_from} -> {unit_to}")
        mean, sd = mean_c, sd_c
    return mean, sd, estimated


def effect_for_outcome(oc: dict, spec: dict) -> tuple[effects.Effect, dict]:
    """Compute one effect. Returns the Effect and bookkeeping (n, events, notes, estimated)."""
    dt = oc["data_type"]
    if dt != spec["data_type"]:
        raise ValueError(f"extracted as {dt} but the protocol defines {spec['id']} as {spec['data_type']}")
    fields = oc.get("fields") or {}
    g = lambda n: field_value(fields, n)
    m = spec["measure"]
    notes, info = [], {"estimated": False, "events": None}
    unit_to = spec.get("unit")
    unit_from = oc.get("unit") or unit_to

    if dt == "binary":
        eff = effects.binary(m, g("events_t"), g("n_t"), g("events_c"), g("n_c"))
        info["n"] = int(g("n_t") + g("n_c"))
        info["events"] = int(g("events_t") + g("events_c"))
    elif dt == "continuous":
        mt, sdt, e1 = _arm_mean_sd(fields, "_t", g("n_t"), notes, unit_from, unit_to)
        mc, sdc, e2 = _arm_mean_sd(fields, "_c", g("n_c"), notes, unit_from, unit_to)
        eff = effects.continuous(m, mt, sdt, g("n_t"), mc, sdc, g("n_c"))
        info["n"] = int(g("n_t") + g("n_c"))
        info["estimated"] = e1 or e2
    elif dt == "single_group":
        mn, sd, est = _arm_mean_sd(fields, "", g("n"), notes, unit_from, unit_to)
        eff = effects.single_mean(mn, sd, g("n"))
        info["n"] = int(g("n"))
        info["estimated"] = est
    elif dt == "proportion":
        eff = effects.proportion(m, g("events"), g("n"))
        info["n"], info["events"] = int(g("n")), int(g("events"))
    elif dt == "correlation":
        eff = effects.correlation(m, g("r"), g("n"))
        info["n"] = int(g("n"))
    elif dt == "generic":
        ratio = spec.get("generic_scale") == "ratio"
        eff = effects.generic(g("estimate"), se=g("se"), ci_lower=g("ci_lower"),
                              ci_upper=g("ci_upper"), ratio=ratio)
        info["n"] = int(g("n")) if g("n") is not None else None
        if g("se") is None:
            notes.append("SE derived from the reported 95% CI" + (" on the log scale" if ratio else ""))
    else:
        raise ValueError(f"unknown data_type {dt}")
    if eff.note:
        notes.append(eff.note)
    info["notes"] = notes
    return eff, info


def harmonize(records: list[dict], protocol: dict, rob: dict | None = None):
    """Compute effects for every outcome in the protocol.

    Returns ``{outcome_id: {"effects": [StudyEffect], "excluded": [Exclusion]}}``.
    When a study reports the same outcome more than once (several time points, for
    example) only the first entry is used and the duplicate is logged; pre-specify the
    time point in the protocol and extract only that one.
    """
    rob = rob or {}
    out = {o["id"]: {"effects": [], "excluded": []} for o in protocol["outcomes"]}
    specs = {o["id"]: o for o in protocol["outcomes"]}
    for rec in records:
        sid = rec["study_id"]
        used = set()
        mods = {k: (v.get("value") if isinstance(v, dict) else v)
                for k, v in (rec.get("moderators") or {}).items()}
        for oc in rec.get("outcomes") or []:
            oid = oc.get("outcome")
            if oid not in specs:
                continue
            if oid in used:
                out[oid]["excluded"].append(Exclusion(sid, oid, "duplicate entry for this outcome; first one used"))
                continue
            used.add(oid)
            spec = specs[oid]
            try:
                eff, info = effect_for_outcome(oc, spec)
            except (ValueError, KeyError, TypeError) as exc:
                out[oid]["excluded"].append(Exclusion(sid, oid, f"could not compute effect: {exc}"))
                continue
            if eff.exclude or not (math.isfinite(eff.yi) and math.isfinite(eff.vi)) or eff.vi <= 0:
                out[oid]["excluded"].append(Exclusion(sid, oid, eff.note or "non-finite effect or variance"))
                continue
            ratio_gen = spec.get("generic_scale") == "ratio"
            se = math.sqrt(eff.vi)
            bt = lambda v: effects.back_transform(spec["measure"], v, ratio_gen)
            out[oid]["effects"].append(StudyEffect(
                study_id=sid, outcome=oid, yi=eff.yi, vi=eff.vi, n_total=info.get("n"),
                events_total=info.get("events"), year=rec.get("year"), derivations=info["notes"],
                estimated_sd=info["estimated"], rob_overall=(rob.get(sid) or {}).get("overall"),
                moderators=mods, display_est=bt(eff.yi), display_lo=bt(eff.yi - 1.959964 * se),
                display_hi=bt(eff.yi + 1.959964 * se)))
    return out


def write_effects_csv(effects_list: list[StudyEffect], path: Path):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    mod_names = sorted({k for e in effects_list for k in e.moderators})
    with open(path, "w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(["study_id", "year", "yi", "vi", "n_total", "events_total", "rob_overall",
                    "estimated_sd", "derivations"] + mod_names)
        for e in effects_list:
            w.writerow([e.study_id, e.year, repr(e.yi), repr(e.vi), e.n_total, e.events_total,
                        e.rob_overall, e.estimated_sd, " | ".join(e.derivations)]
                       + [e.moderators.get(m) for m in mod_names])
