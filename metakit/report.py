"""Write ``report/report.md``: methods and results sections ready to edit into a manuscript.

The prose is generated from ``analysis/results.json`` only, so every number in the report can
be traced to the analysis. Wording follows PRISMA 2020 reporting items 13 and 20-22.
"""
from __future__ import annotations

from pathlib import Path

METHOD_NAMES = {
    "REML": "restricted maximum likelihood (REML)", "DL": "DerSimonian-Laird",
    "PM": "Paule-Mandel", "ML": "maximum likelihood", "HE": "Hedges'", "FE": "none (fixed-effect model)",
}


def f(v, d=2):
    if v is None:
        return "NA"
    return f"{v:.{d}f}"


def p(v):
    if v is None:
        return "NA"
    return "< 0.001" if v < 0.001 else f"= {v:.3f}"


def ci(d, digits=2):
    return f"{f(d['estimate'], digits)} (95% CI {f(d['ci_lb'], digits)} to {f(d['ci_ub'], digits)})"


def methods_section(results: dict, protocol: dict) -> str:
    mp = results["model"]
    method = mp["method"]
    test = ("with the Hartung-Knapp-Sidik-Jonkman (Knapp-Hartung) adjustment to the standard errors "
            "and t-distribution-based confidence intervals" if mp["test"] == "knha"
            else "with Wald-type (normal) confidence intervals")
    outs = list(results["outcomes"].values())
    measures = sorted({o["measure_name"] for o in outs})
    ders = " ".join(d for o in outs for st in o.get("studies", []) for d in st.get("derivations", []))
    sens_keys = {k for o in outs for k, v in (o.get("sensitivity") or {}).items()}
    ratio = any(o["measure"] in ("RR", "OR", "ROM") or (o["measure"] == "GEN") for o in outs)
    em = [f"Effect measures were pre-specified per outcome ({', '.join(measures)})."]
    if ratio:
        em.append("Ratio measures were analysed on the log scale and back-transformed for presentation.")
    if any(o["data_type"] == "binary" for o in outs):
        em.append("When a study reported a zero cell, 0.5 was added to every cell of that study's 2x2 "
                  "table; studies with no events in either arm were excluded from ratio analyses.")
    if "SD = SE" in ders or "SD from 95% CI" in ders:
        em.append("Standard deviations missing from reports were derived from standard errors or "
                  "confidence intervals (t distribution for groups of fewer than 60).")
    if "estimated from" in ders:
        em.append("Means and standard deviations reported only as medians with ranges or interquartile "
                  "ranges were estimated with the methods of Luo et al. (2018), Wan et al. (2014) and "
                  "Shi et al. (2020).")
    if "converted" in ders:
        em.append("Values reported in other units were converted to a common unit before pooling.")
    sens = []
    if "excluding_high_risk_of_bias" in sens_keys:
        sens.append("excluding studies at high risk of bias")
    if "excluding_estimated_means_sds" in sens_keys:
        sens.append("excluding studies with estimated means or standard deviations")
    if "dersimonian_laird" in sens_keys:
        sens.append("using the DerSimonian-Laird estimator")
    sens_txt = ("Pre-specified sensitivity analyses repeated the primary analysis " + "; ".join(sens) +
                ", and compared it with a fixed-effect model." if sens else
                "The random-effects result was compared with a fixed-effect model.")
    lines = [
        "## Methods", "",
        "### Effect measures",
        "",
        " ".join(em),
        "",
        "### Synthesis methods",
        "",
        (f"Studies were pooled with a random-effects model; the between-study variance (tau^2) "
         f"was estimated with {METHOD_NAMES[method]}, {test}." if method != "FE" else
         "Studies were pooled with an inverse-variance fixed-effect model."),
        "Statistical heterogeneity was quantified with Cochran's Q, I^2 and tau^2 (with a Q-profile "
        "95% confidence interval), and a 95% prediction interval was calculated to show the range of "
        "effects expected in a new setting.",
        sens_txt + " Leave-one-out analyses assessed the influence of single studies.",
        "Small-study effects were examined with funnel plots, Egger's regression test, Begg's rank "
        "correlation test and Duval and Tweedie's trim-and-fill method, interpreted with caution when "
        "fewer than 10 studies were available.",
    ]
    if protocol.get("subgroups"):
        lines.append("Pre-specified subgroup analyses (" + ", ".join(protocol["subgroups"]) + ") were "
                     "tested with mixed-effects meta-regression using a categorical moderator.")
    if protocol.get("meta_regression"):
        lines.append("Pre-specified meta-regression examined " + ", ".join(protocol["meta_regression"]) + ".")
    lines += [
        "Certainty of evidence was rated with GRADE.",
        "",
        f"Analyses used metakit {results['metakit_version']} (Python), whose estimators are validated "
        "against the R package metafor (Viechtbauer, 2010) in an automated test suite.",
        "",
    ]
    return "\n".join(lines)


def outcome_results(o: dict, fig_prefix: str) -> str:
    lines = [f"### {o['label']}", ""]
    if o.get("k", 0) == 0:
        return "\n".join(lines + ["No study reported usable data for this outcome.", ""])
    if o["k"] == 1:
        s = o["studies"][0]
        return "\n".join(lines + [
            f"Only one study ({s['study_id']}) reported this outcome: {o['measure_name']} "
            f"{f(s['display'][0])} (95% CI {f(s['display'][1])} to {f(s['display'][2])}). No pooling was possible.", ""])
    m = o["main"]
    d = m["display"]
    unit = f" {o['unit']}" if o.get("unit") and o["measure"] in ("MD", "MN") else ""
    who = f"{o['k']} studies"
    if o.get("n_total"):
        who += f" ({o['n_total']:,} participants"
        who += f", {o['events_total']:,} events)" if o.get("events_total") is not None else ")"
    het = o["heterogeneity_ci"]
    lines.append(
        f"{who} contributed to the analysis. The pooled {o['measure_name'].lower()} was "
        f"{f(d['estimate'])}{unit} (95% CI {f(d['ci_lb'])} to {f(d['ci_ub'])}; p {p(m['pval'])}). "
        f"Heterogeneity was {'substantial' if m['I2'] >= 50 else 'moderate' if m['I2'] >= 30 else 'low'} "
        f"(I^2 = {f(m['I2'], 0)}%, 95% CI {f(het['I2'][1], 0)}% to {f(het['I2'][2], 0)}%; "
        f"tau^2 = {f(m['tau2'], 3)}; Q = {f(m['QE'])}, p {p(m['QEp'])})."
        + (f" The 95% prediction interval was {f(d['pi_lb'])} to {f(d['pi_ub'])}."
           if d.get("pi_lb") is not None else "")
    )
    lines += ["", f"![Forest plot]({fig_prefix}{o['figures']['forest']})", ""]
    for key, path in o["figures"].items():
        if key.startswith("forest_by_"):
            lines += [f"![Forest plot by subgroup]({fig_prefix}{path})", ""]

    # sensitivity
    sens = o.get("sensitivity", {})
    sl = []
    labels = {"excluding_high_risk_of_bias": "Excluding high risk-of-bias studies",
              "excluding_estimated_means_sds": "Excluding studies with estimated means/SDs",
              "dersimonian_laird": "DerSimonian-Laird estimator"}
    for key, val in sens.items():
        if "skipped" in val:
            sl.append(f"| {labels[key]} | - | {val['skipped']} |")
        else:
            sl.append(f"| {labels[key]} | {val['k']} | {ci(val['display'])} |")
    if o.get("trim_and_fill"):
        t = o["trim_and_fill"]
        sl.append(f"| Trim-and-fill ({t['k0']} {'study' if t['k0'] == 1 else 'studies'} imputed, {t['side']} side) | {o['k'] + t['k0']} | {ci(t['display'])} |")
    fe = o.get("fixed_effect")
    if fe:
        sl.append(f"| Fixed-effect model | {fe['k']} | {ci(fe['display'])} |")
    if sl:
        lines += ["**Sensitivity analyses**", "", "| Analysis | k | Estimate |", "|---|---|---|",
                  f"| Primary analysis | {o['k']} | {ci(d)} |"] + sl + [""]
    l1o = o.get("leave_one_out") or []
    flips = [r["omitted"] for r in l1o if r["changes_significance"]]
    if l1o:
        rng = [r["display"][0] for r in l1o]
        lines.append(f"Omitting one study at a time gave estimates between {f(min(rng))} and {f(max(rng))}; "
                     + (f"removing {', '.join(flips)} changed statistical significance."
                        if flips else "no single study changed the statistical significance of the result."))
        lines.append("")

    # bias
    if o.get("egger"):
        e, r = o["egger"], o["rank_test"]
        lines.append(f"Egger's test {'did not suggest' if e['pval'] >= 0.10 else 'suggested'} funnel-plot "
                     f"asymmetry (p {p(e['pval'])}); Begg's test p {p(r['pval'])}."
                     + (f" {e['warning']}" if e.get("warning") else ""))
        lines += ["", f"![Funnel plot]({fig_prefix}{o['figures']['funnel']})", ""]

    # subgroups
    for mod, sg in (o.get("subgroups") or {}).items():
        if "skipped" in sg:
            lines += [f"Subgroup analysis by {mod} was not performed: {sg['skipped']}.", ""]
            continue
        lines += [f"**Subgroups by {mod}**", "", "| Subgroup | k | Estimate | I^2 |", "|---|---|---|---|"]
        for lev, g in sg["per_group"].items():
            lines.append(f"| {lev} | {g['k']} | {f(g['display'][0])} ({f(g['display'][1])} to {f(g['display'][2])}) | "
                         f"{f(g['I2'], 0) + '%' if g.get('I2') is not None else '-'} |")
        t = sg.get("test_of_differences")
        if t:
            lines += ["", f"Test for subgroup differences: QM = {f(t['QM'])}, df = {t['df']}, p {p(t['pval'])}."]
        lines.append("")
    for mod, mr in (o.get("meta_regression") or {}).items():
        if "skipped" in mr:
            lines += [f"Meta-regression on {mod} was not performed: {mr['skipped']}.", ""]
            continue
        lines.append(f"Meta-regression on {mod} (k = {mr['k']}): slope {f(mr['beta'][1], 4)} per unit "
                     f"(95% CI {f(mr['ci_lb'][1], 4)} to {f(mr['ci_ub'][1], 4)}; p {p(mr['pval'][1])}); "
                     f"residual I^2 = {f(mr['residual_I2'], 0)}%"
                     + (f"; R^2 = {f(mr['R2'], 0)}%." if mr.get("R2") is not None else ".")
                     + (f" {mr['warning']}" if mr.get("warning") else ""))
        lines.append("")
    for w in o.get("warnings", []):
        lines.append(f"> Note: {w}")
    if o.get("warnings"):
        lines.append("")
    return "\n".join(lines)


def sof_table(results: dict) -> str:
    rows = ["## Summary of findings (GRADE; suggested, requires reviewer confirmation)", "",
            "| Outcome | Studies (participants) | Effect (95% CI) | Certainty | Reasons for downgrading |",
            "|---|---|---|---|---|"]
    for o in results["outcomes"].values():
        if o.get("k", 0) < 2:
            continue
        g = o["grade"]
        reasons = "; ".join(f"{k.replace('_', ' ')} (-{v['downgrade']}): {v['reason']}"
                            for k, v in g["domains"].items() if v["downgrade"]) or "none"
        n = f"{o['n_total']:,}" if o.get("n_total") else "?"
        rows.append(f"| {o['label']} | {o['k']} ({n}) | {o['measure_name']} "
                    f"{ci(o['main']['display'])} | **{g['rating'].upper()}** | {reasons} |")
    return "\n".join(rows) + "\n"


def appendix(results: dict) -> str:
    lines = ["## Appendix A. Study-level data and derivations", ""]
    for o in results["outcomes"].values():
        lines += [f"### {o['label']}", "", f"| Study | n | {o['measure_name']} (95% CI) | Derivations |",
                  "|---|---|---|---|"]
        for s in o["studies"]:
            der = "; ".join(s["derivations"]) or "as reported"
            lines.append(f"| {s['study_id']} | {s['n'] or '?'} | {f(s['display'][0])} "
                         f"({f(s['display'][1])} to {f(s['display'][2])}) | {der} |")
        if o["excluded"]:
            lines += ["", "Excluded from this outcome:", ""]
            lines += [f"- {e['study_id']}: {e['reason']}" for e in o["excluded"]]
        lines.append("")
    return "\n".join(lines)


def write_report(results: dict, protocol: dict, project: Path, validation_md: str | None = None) -> Path:
    project = Path(project)
    rdir = project / "report"
    rdir.mkdir(parents=True, exist_ok=True)
    pre = "../analysis/"
    parts = [f"# {protocol.get('title', 'Meta-analysis')}", ""]
    if protocol.get("question"):
        parts += [f"**Question.** {protocol['question'].strip()}", ""]
    parts += ["> Draft generated by metakit from `analysis/results.json`. Every number below is "
              "computed, not written by a language model; edit the prose freely but re-run "
              "`metakit analyze` rather than editing numbers by hand.", ""]
    parts.append(methods_section(results, protocol))
    parts += ["## Results", ""]
    if results.get("prisma"):
        c = results["prisma"]
        parts += [f"The search identified {c.get('identified', '?')} records; after removing "
                  f"{c.get('duplicates_removed', '?')} duplicates, {c.get('screened', '?')} were screened and "
                  f"{c.get('fulltext_assessed', '?')} full texts assessed. {c.get('included_review')} studies "
                  f"were included in the review.", "", f"![PRISMA flow diagram]({pre}{results['prisma_figure']})", ""]
    if results.get("rob_figure"):
        parts += ["### Risk of bias", "", f"![Risk of bias]({pre}{results['rob_figure']})", ""]
    for o in results["outcomes"].values():
        parts.append(outcome_results(o, pre))
    parts.append(sof_table(results))
    parts.append(appendix(results))
    if validation_md:
        parts += ["## Appendix B. Extraction validation", "", validation_md.replace("# Extraction validation report", "").strip(), ""]
    out = rdir / "report.md"
    out.write_text("\n".join(parts), encoding="utf-8")
    return out
