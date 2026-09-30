"""Small-study effects / publication bias diagnostics.

* ``egger``: regression test for funnel plot asymmetry (Egger et al., 1997).
  ``model="rma"`` fits a meta-regression with the standard error as moderator
  (metafor's default); ``model="lm"`` is the classic weighted linear regression.
* ``rank_test``: Begg & Mazumdar (1994) rank correlation test.
* ``trim_and_fill``: Duval & Tweedie (2000) nonparametric trim-and-fill, L0/R0 estimators.

All three have low power with fewer than ~10 studies (Cochrane Handbook 13.3.5.4);
``min_k_warning`` is included in every result so reports can say so.
"""
from __future__ import annotations

import warnings

import numpy as np
from scipy import stats

from .models import MetaResult, rma

MIN_K = 10


def _warn(k):
    if k < MIN_K:
        return (f"Only {k} studies: funnel-plot asymmetry tests have low power below "
                f"{MIN_K} studies and should be interpreted cautiously (Cochrane Handbook 13.3.5.4).")
    return None


def egger(res: MetaResult, model: str = "rma") -> dict:
    """Egger's regression test using the standard error as predictor."""
    yi, vi = res.yi, res.vi
    sei = np.sqrt(vi)
    k = len(yi)
    if model == "rma":
        X = np.column_stack([np.ones(k), sei])
        fit = rma(yi, vi, X=X, method=res.method, test=res.test)
        return {
            "model": "rma", "stat": float(fit.zval[1]), "pval": float(fit.pval[1]),
            "dfs": fit.dfs, "limit_estimate": float(fit.beta[0]),
            "limit_ci": [float(fit.ci_lb[0]), float(fit.ci_ub[0])],
            "warning": _warn(k),
        }
    if model == "lm":
        # weighted least squares of yi on sei with weights 1/vi; t-test with k-2 df
        w = 1.0 / vi
        X = np.column_stack([np.ones(k), sei])
        W = np.diag(w)
        XtWX = X.T @ W @ X
        beta = np.linalg.solve(XtWX, X.T @ W @ yi)
        r = yi - X @ beta
        s2 = float(np.sum(w * r * r) / (k - 2))
        vb = np.linalg.inv(XtWX) * s2
        se = np.sqrt(np.diag(vb))
        t = beta[1] / se[1]
        return {
            "model": "lm", "stat": float(t), "pval": float(2 * stats.t.sf(abs(t), k - 2)),
            "dfs": k - 2, "limit_estimate": float(beta[0]),
            "limit_ci": [float(beta[0] - stats.t.ppf(.975, k - 2) * se[0]),
                         float(beta[0] + stats.t.ppf(.975, k - 2) * se[0])],
            "warning": _warn(k),
        }
    raise ValueError("model must be 'rma' or 'lm'")


def rank_test(res: MetaResult) -> dict:
    """Begg & Mazumdar rank correlation between standardised effects and variances."""
    yi, vi = res.yi, res.vi
    fe = rma(yi, vi, method="FE")
    b, vb = fe.beta[0], fe.vb[0, 0]
    vi_star = vi - vb
    yi_star = (yi - b) / np.sqrt(vi_star)
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        tau, p = stats.kendalltau(yi_star, vi, method="auto")
    return {"tau": float(tau), "pval": float(p), "warning": _warn(len(yi))}


def trim_and_fill(res: MetaResult, estimator: str = "L0", side: str | None = None,
                  maxiter: int = 100) -> dict:
    """Duval & Tweedie trim-and-fill. Returns k0, side, the filled studies and the refit."""
    if res.p != 1:
        raise ValueError("trim-and-fill is only defined for models without moderators")
    yi0, vi0 = res.yi.copy(), res.vi.copy()
    k = len(yi0)
    if side is None:
        slope_fit = rma(yi0, vi0, X=np.column_stack([np.ones(k), np.sqrt(vi0)]), method=res.method)
        side = "left" if (not np.isfinite(slope_fit.beta[1]) or slope_fit.beta[1] > 0) else "right"
    yi = -yi0 if side == "right" else yi0.copy()
    order = np.argsort(yi, kind="stable")
    yi, vi = yi[order], vi0[order]

    k0, k0_prev, it = 0, -1, 0
    b = 0.0
    while k0 != k0_prev:
        k0_prev = k0
        it += 1
        if it > maxiter:
            raise RuntimeError("trim-and-fill did not converge")
        fit = rma(yi[: k - k0], vi[: k - k0], method=res.method)
        b = fit.beta[0]
        yc = yi - b
        ranks = stats.rankdata(np.abs(yc), method="ordinal")
        signed = np.sign(yc) * ranks
        if estimator == "L0":
            Sr = signed[signed > 0].sum()
            k0 = (4 * Sr - k * (k + 1)) / (2 * k - 1)
        elif estimator == "R0":
            neg = signed[signed < 0]
            k0 = (k - (np.max(-neg) if neg.size else 0)) - 1
        else:
            raise ValueError("estimator must be 'L0' or 'R0'")
        k0 = int(round(max(0.0, float(k0))))
        k0 = min(k0, k - 1)

    filled_yi = np.array([])
    filled_vi = np.array([])
    if k0 > 0:
        yc = yi - b
        filled_yi = -yc[k - k0:] + b
        filled_vi = vi[k - k0:]
        if side == "right":
            filled_yi = -filled_yi
    all_yi = np.concatenate([yi0, filled_yi])
    all_vi = np.concatenate([vi0, filled_vi])
    refit = rma(all_yi, all_vi, method=res.method, test=res.test) if k0 > 0 else res
    return {
        "k0": k0, "side": side, "estimator": estimator,
        "filled_yi": filled_yi.tolist(), "filled_vi": filled_vi.tolist(),
        "estimate": float(refit.beta[0]), "se": float(refit.se[0]),
        "ci": [float(refit.ci_lb[0]), float(refit.ci_ub[0])], "tau2": float(refit.tau2),
        "result": refit,
        "note": ("Trim-and-fill assumes asymmetry is caused by publication bias; it is a "
                 "sensitivity analysis, not a corrected estimate."),
    }
