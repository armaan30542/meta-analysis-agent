"""Sensitivity analyses: leave-one-out, cumulative meta-analysis, and subgroup analysis."""
from __future__ import annotations

from typing import Sequence

import numpy as np
from scipy import stats

from .models import MetaResult, design_from_moderators, rma


def leave_one_out(res: MetaResult, labels: Sequence[str] | None = None) -> list[dict]:
    """Refit the model k times, each time omitting one study.

    Each row also flags whether dropping that study changes the conclusion
    (the CI crossing zero) - the most useful single number for a reader.
    """
    k = res.k
    labels = list(labels) if labels is not None else [f"study {i + 1}" for i in range(k)]
    full_sig = not (res.ci_lb[0] <= 0 <= res.ci_ub[0])
    out = []
    for i in range(k):
        keep = np.arange(k) != i
        fit = rma(res.yi[keep], res.vi[keep], method=res.method, test=res.test, level=res.level)
        sig = not (fit.ci_lb[0] <= 0 <= fit.ci_ub[0])
        out.append({
            "omitted": labels[i], "estimate": float(fit.beta[0]), "se": float(fit.se[0]),
            "ci_lb": float(fit.ci_lb[0]), "ci_ub": float(fit.ci_ub[0]), "pval": float(fit.pval[0]),
            "tau2": fit.tau2, "I2": fit.I2, "changes_significance": sig != full_sig,
        })
    return out


def cumulative(res: MetaResult, order: Sequence, labels: Sequence[str] | None = None) -> list[dict]:
    """Cumulative meta-analysis, adding studies in the given order (e.g. publication year)."""
    k = res.k
    labels = list(labels) if labels is not None else [f"study {i + 1}" for i in range(k)]
    idx = np.argsort(np.asarray(order), kind="stable")
    out = []
    for j in range(1, k + 1):
        sel = idx[:j]
        if j == 1:
            est, se = float(res.yi[sel][0]), float(np.sqrt(res.vi[sel][0]))
            z = stats.norm.ppf(1 - (1 - res.level / 100) / 2)
            out.append({"added": labels[sel[-1]], "k": 1, "estimate": est,
                        "ci_lb": est - z * se, "ci_ub": est + z * se, "tau2": 0.0, "I2": 0.0})
            continue
        fit = rma(res.yi[sel], res.vi[sel], method=res.method, test=res.test, level=res.level)
        out.append({"added": labels[sel[-1]], "k": j, "estimate": float(fit.beta[0]),
                    "ci_lb": float(fit.ci_lb[0]), "ci_ub": float(fit.ci_ub[0]),
                    "tau2": fit.tau2, "I2": fit.I2})
    return out


def subgroups(yi, vi, groups: Sequence, method: str = "REML", test: str = "z",
              level: float = 95.0) -> dict:
    """Subgroup analysis.

    Reports (a) a separate random-effects model within each subgroup, and (b) the
    test for subgroup differences from a mixed-effects meta-regression with the
    subgroup as a categorical moderator (common tau2; metafor's approach). Subgroups
    with a single study are reported but cannot have a tau2 estimated.
    """
    yi = np.asarray(yi, float)
    vi = np.asarray(vi, float)
    groups = [str(g) for g in groups]
    levels = sorted(set(groups))
    per_group = {}
    for lev in levels:
        sel = np.array([g == lev for g in groups])
        n = int(sel.sum())
        if n == 1:
            z = stats.norm.ppf(1 - (1 - level / 100) / 2)
            y, s = float(yi[sel][0]), float(np.sqrt(vi[sel][0]))
            per_group[lev] = {"k": 1, "estimate": y, "ci_lb": y - z * s, "ci_ub": y + z * s,
                              "tau2": None, "I2": None}
        else:
            fit = rma(yi[sel], vi[sel], method=method, test=test, level=level)
            per_group[lev] = {"k": n, "estimate": float(fit.beta[0]), "se": float(fit.se[0]),
                              "ci_lb": float(fit.ci_lb[0]), "ci_ub": float(fit.ci_ub[0]),
                              "pval": float(fit.pval[0]), "tau2": fit.tau2, "I2": fit.I2}
    out = {"levels": levels, "per_group": per_group}
    if len(levels) > 1:
        X, names = design_from_moderators({"group": groups}, categorical=("group",))
        mr = rma(yi, vi, X=X, method=method, test=test, level=level, coef_names=names)
        out["test_of_differences"] = {"QM": mr.QM, "df": mr.QMdf[0], "pval": mr.QMp,
                                      "residual_tau2": mr.tau2}
    return out
