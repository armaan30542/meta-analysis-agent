"""Run the full pre-specified analysis for every outcome in the protocol.

Output (under ``<project>/analysis/``):
    results.json          every number the report uses
    <outcome>/effects.csv the study-level effects with their derivation notes
    <outcome>/*.png       forest, funnel, leave-one-out, cumulative plots
    rob.png               risk-of-bias traffic-light plot
"""
from __future__ import annotations

import json
import math
from pathlib import Path

import numpy as np

from . import __version__, bias, effects, grade, plots, sensitivity
from .harmonize import harmonize, write_effects_csv
from .models import design_from_moderators, rma, tau2_ci
from .rob import TOOLS, is_high_risk


def _jsonable(o):
    if isinstance(o, dict):
        return {str(k): _jsonable(v) for k, v in o.items() if k != "result"}
    if isinstance(o, (list, tuple)):
        return [_jsonable(v) for v in o]
    if isinstance(o, np.ndarray):
        return [_jsonable(v) for v in o.tolist()]
    if isinstance(o, (np.floating,)):
        o = float(o)
    if isinstance(o, (np.integer,)):
        return int(o)
    if isinstance(o, float) and not math.isfinite(o):
        return None
    return o


def _summ(res):
    d = {"k": res.k, "estimate": float(res.beta[0]), "se": float(res.se[0]),
         "ci_lb": float(res.ci_lb[0]), "ci_ub": float(res.ci_ub[0]), "pval": float(res.pval[0]),
         "tau2": res.tau2, "I2": res.I2, "H2": res.H2, "QE": res.QE, "QEp": res.QEp,
         "pi_lb": res.pi_lb, "pi_ub": res.pi_ub, "method": res.method, "test": res.test,
         "dfs": res.dfs}
    return d


def analyze_outcome(spec: dict, study_effects, excluded, protocol: dict, outdir: Path,
                    rob_records: dict | None, designs: dict) -> dict:
    oid = spec["id"]
    m = spec["measure"]
    ratio_gen = spec.get("generic_scale") == "ratio"
    bt = lambda v: effects.back_transform(m, v, ratio_gen)
    null_disp = effects.null_value(m, ratio_gen)
    null_an = None if null_disp is None else (0.0 if null_disp in (0.0, 1.0) else null_disp)
    name = effects.display_name(m, ratio_gen)
    log_axis = m in effects.RATIO_MEASURES or (m == "GEN" and ratio_gen)
    odir = outdir / oid
    odir.mkdir(parents=True, exist_ok=True)
    write_effects_csv(study_effects, odir / "effects.csv")

    out = {"outcome": oid, "label": spec.get("label", oid), "measure": m, "measure_name": name,
           "data_type": spec["data_type"], "unit": spec.get("unit"),
           "excluded": [{"study_id": e.study_id, "reason": e.reason} for e in excluded],
           "null_value_display": null_disp, "null_value_analysis_scale": null_an,
           "studies": [{"study_id": e.study_id, "yi": e.yi, "vi": e.vi, "n": e.n_total,
                        "events": e.events_total, "display": [e.display_est, e.display_lo, e.display_hi],
                        "derivations": e.derivations, "estimated_sd": e.estimated_sd,
                        "rob": e.rob_overall, "moderators": e.moderators} for e in study_effects],
           "figures": {}, "warnings": []}
    k = len(study_effects)
    out["k"] = k
    out["n_total"] = sum(e.n_total or 0 for e in study_effects) or None
    ev = [e.events_total for e in study_effects]
    out["events_total"] = sum(ev) if ev and all(v is not None for v in ev) else None
    if k == 0:
        out["warnings"].append("no usable studies for this outcome")
        return out
    if k == 1:
        e = study_effects[0]
        out["warnings"].append("only one study: no pooling possible; its estimate is reported alone")
        out["single_study"] = {"estimate": e.yi, "se": math.sqrt(e.vi)}
        return out

    yi = np.array([e.yi for e in study_effects])
    vi = np.array([e.vi for e in study_effects])
    labels = [e.study_id for e in study_effects]
    mp = protocol["model"]
    res = rma(yi, vi, method=mp["method"], test=mp["test"], level=mp["level"])
    out["main"] = _summ(res)
    out["main"]["weights"] = res.weights.tolist()
    out["main"]["display"] = {"estimate": bt(res.beta[0]), "ci_lb": bt(res.ci_lb[0]),
                              "ci_ub": bt(res.ci_ub[0]),
                              "pi_lb": bt(res.pi_lb) if res.pi_lb is not None else None,
                              "pi_ub": bt(res.pi_ub) if res.pi_ub is not None else None}
    if k == 2:
        out["warnings"].append("only two studies: tau2 is very poorly estimated; treat the random-effects "
                               "result as illustrative (Cochrane Handbook 10.10.4.1)")
    ci = tau2_ci(res)
    out["heterogeneity_ci"] = {key: list(val) for key, val in ci.items()}
    fe = rma(yi, vi, method="FE", level=mp["level"])
    out["fixed_effect"] = _summ(fe)
    out["fixed_effect"]["display"] = {"estimate": bt(fe.beta[0]), "ci_lb": bt(fe.ci_lb[0]), "ci_ub": bt(fe.ci_ub[0])}
    if not res.converged:
        out["warnings"].append("tau2 estimation did not converge; results use the last iterate")

    # risk of bias share
    if rob_records:
        w = res.weights
        out["weight_high_rob"] = float(sum(wi for wi, e in zip(w, study_effects) if is_high_risk(e.rob_overall)))
        missing = [e.study_id for e in study_effects if e.rob_overall is None]
        if missing:
            out["warnings"].append(f"no risk-of-bias record for: {', '.join(missing)}")

    # small-study effects
    if k >= 3:
        out["egger"] = bias.egger(res, protocol["bias"].get("egger_model", "rma"))
        out["rank_test"] = bias.rank_test(res)
        if protocol["bias"].get("trim_and_fill", True):
            tf = bias.trim_and_fill(res)
            out["trim_and_fill"] = {k2: v for k2, v in tf.items() if k2 != "result"}
            out["trim_and_fill"]["display"] = {"estimate": bt(tf["estimate"]), "ci_lb": bt(tf["ci"][0]),
                                               "ci_ub": bt(tf["ci"][1])}
        out["leave_one_out"] = sensitivity.leave_one_out(res, labels)
        for row in out["leave_one_out"]:
            row["display"] = [bt(row["estimate"]), bt(row["ci_lb"]), bt(row["ci_ub"])]

    years = [e.year for e in study_effects]
    if all(isinstance(y, (int, float)) for y in years) and k >= 3:
        out["cumulative"] = sensitivity.cumulative(res, years, [f"{s} ({y})" for s, y in zip(labels, years)])

    # pre-specified sensitivity analyses
    sens = {}
    sp = protocol.get("sensitivity", {})
    def refit(mask, why):
        mask = np.asarray(mask)
        if mask.sum() == k:
            return {"skipped": f"no studies removed ({why})"}
        if mask.sum() < 2:
            return {"skipped": f"fewer than 2 studies left after removing {why}"}
        r = rma(yi[mask], vi[mask], method=mp["method"], test=mp["test"], level=mp["level"])
        s = _summ(r)
        s["removed"] = [lab for lab, keep in zip(labels, mask) if not keep]
        s["display"] = {"estimate": bt(r.beta[0]), "ci_lb": bt(r.ci_lb[0]), "ci_ub": bt(r.ci_ub[0])}
        return s
    if sp.get("exclude_high_risk_of_bias") and rob_records:
        sens["excluding_high_risk_of_bias"] = refit([not is_high_risk(e.rob_overall) for e in study_effects],
                                                    "high risk-of-bias studies")
    if sp.get("exclude_estimated_sds") and spec["data_type"] in ("continuous", "single_group"):
        sens["excluding_estimated_means_sds"] = refit([not e.estimated_sd for e in study_effects],
                                                      "studies with estimated means/SDs")
    if mp["method"] != "DL":
        r = rma(yi, vi, method="DL", level=mp["level"])
        sens["dersimonian_laird"] = _summ(r)
        sens["dersimonian_laird"]["display"] = {"estimate": bt(r.beta[0]), "ci_lb": bt(r.ci_lb[0]), "ci_ub": bt(r.ci_ub[0])}
    out["sensitivity"] = sens

    # subgroups and meta-regression
    out["subgroups"] = {}
    for mod in protocol.get("subgroups") or []:
        vals = [e.moderators.get(mod) for e in study_effects]
        have = [v is not None for v in vals]
        if sum(have) < 3:
            out["subgroups"][mod] = {"skipped": "fewer than 3 studies report this moderator"}
            continue
        sel = np.array(have)
        sg = sensitivity.subgroups(yi[sel], vi[sel], [v for v in vals if v is not None],
                                   method=mp["method"], test=mp["test"], level=mp["level"])
        for g in sg["per_group"].values():
            g["display"] = [bt(g["estimate"]), bt(g["ci_lb"]), bt(g["ci_ub"])]
        sg["n_missing"] = int(k - sel.sum())
        out["subgroups"][mod] = sg
    out["meta_regression"] = {}
    for mod in protocol.get("meta_regression") or []:
        vals = [e.moderators.get(mod) for e in study_effects]
        sel = np.array([isinstance(v, (int, float)) for v in vals])
        if sel.sum() < 4:
            out["meta_regression"][mod] = {"skipped": "fewer than 4 studies with a numeric value"}
            continue
        X, names = design_from_moderators({mod: [v for v in vals if isinstance(v, (int, float))]})
        r = rma(yi[sel], vi[sel], X=X, method=mp["method"], test=mp["test"], level=mp["level"], coef_names=names)
        entry = {"k": r.k, "coef_names": names, "beta": r.beta.tolist(), "se": r.se.tolist(),
                 "ci_lb": r.ci_lb.tolist(), "ci_ub": r.ci_ub.tolist(), "pval": r.pval.tolist(),
                 "QM": r.QM, "QMp": r.QMp, "residual_tau2": r.tau2, "residual_I2": r.I2,
                 "R2": max(0.0, 100 * (res.tau2 - r.tau2) / res.tau2) if res.tau2 > 0 else None}
        if r.k < 10:
            entry["warning"] = "fewer than 10 studies: meta-regression is exploratory at best (Cochrane 10.11.5.1)"
        out["meta_regression"][mod] = entry

    # GRADE
    ds = [designs.get(e.study_id) for e in study_effects]
    out["grade"] = grade.suggest(out, [d for d in ds if d], protocol.get("grade", {}),
                                 out["n_total"], out["events_total"], spec["data_type"])

    # figures
    fav = spec.get("favours")
    plots.forest(labels, yi, vi, res, name, transform=bt, log_axis=log_axis, null=null_disp,
                 favours=fav, path=odir / "forest.png", title=spec.get("label", oid))
    out["figures"]["forest"] = f"{oid}/forest.png"
    if protocol.get("subgroups"):
        mod = protocol["subgroups"][0]
        sg = out["subgroups"].get(mod, {})
        if "per_group" in sg and sg.get("n_missing", 1) == 0:
            groups = [str(e.moderators.get(mod)) for e in study_effects]
            plots.forest(labels, yi, vi, res, name, transform=bt, log_axis=log_axis, null=null_disp,
                         favours=fav, path=odir / f"forest_by_{mod}.png",
                         title=f"{spec.get('label', oid)}: by {mod}", groups=groups,
                         group_results=sg["per_group"])
            out["figures"][f"forest_by_{mod}"] = f"{oid}/forest_by_{mod}.png"
    if k >= 3:
        tf = out.get("trim_and_fill") or {}
        scale = {"RR": "log risk ratio", "OR": "log odds ratio", "ROM": "log ratio of means",
                 "ZCOR": "Fisher's z", "PLO": "logit proportion"}.get(m, name)
        if m == "GEN" and ratio_gen:
            scale = "log ratio"
        plots.funnel(res, scale, path=odir / "funnel.png", filled_yi=tf.get("filled_yi"),
                     filled_vi=tf.get("filled_vi"), title=f"Funnel plot: {spec.get('label', oid)}")
        out["figures"]["funnel"] = f"{oid}/funnel.png"
        plots.estimate_series(out["leave_one_out"], "omitted", name, bt, null_disp,
                              odir / "leave_one_out.png", "Leave-one-out analysis (study omitted)",
                              log_axis=log_axis, reference=res.beta[0])
        out["figures"]["leave_one_out"] = f"{oid}/leave_one_out.png"
    if out.get("cumulative"):
        plots.estimate_series(out["cumulative"], "added", name, bt, null_disp, odir / "cumulative.png",
                              "Cumulative meta-analysis (by year)", log_axis=log_axis)
        out["figures"]["cumulative"] = f"{oid}/cumulative.png"
    return out


def run_analysis(project: Path, protocol: dict, records: list[dict], rob_records: dict | None,
                 rob_tool: str | None) -> dict:
    project = Path(project)
    outdir = project / "analysis"
    outdir.mkdir(parents=True, exist_ok=True)
    harm = harmonize(records, protocol, rob_records)
    designs = {r["study_id"]: r.get("design") for r in records}
    results = {"metakit_version": __version__, "protocol_title": protocol.get("title"),
               "model": protocol["model"], "n_studies_extracted": len(records), "outcomes": {}}
    for spec in protocol["outcomes"]:
        h = harm[spec["id"]]
        results["outcomes"][spec["id"]] = analyze_outcome(spec, h["effects"], h["excluded"], protocol,
                                                          outdir, rob_records, designs)
    if rob_records and rob_tool in TOOLS:
        plots.rob_traffic_light(rob_records, TOOLS[rob_tool]["domains"], outdir / "rob.png",
                                title=f"Risk of bias ({rob_tool})")
        results["rob_figure"] = "rob.png"
        results["rob_tool"] = rob_tool
    prisma = project / "prisma.json"
    if prisma.exists():
        counts = json.loads(prisma.read_text())
        counts.setdefault("included_review", len(records))
        prim = next(o for o in protocol["outcomes"] if o.get("primary"))
        counts.setdefault("included_meta", results["outcomes"][prim["id"]].get("k"))
        plots.prisma_flow(counts, outdir / "prisma.png")
        results["prisma"] = counts
        results["prisma_figure"] = "prisma.png"
    results = _jsonable(results)
    (outdir / "results.json").write_text(json.dumps(results, indent=2))
    return results
