"""Fixed- and random-effects meta-analysis and meta-regression.

This module mirrors the behaviour of ``metafor::rma.uni`` (Viechtbauer, 2010) and is
validated against it in ``tests/test_models.py``. Every formula here is standard; the
references are listed in ``docs/methods.md``.

Notation: ``yi`` are the study effect sizes, ``vi`` their sampling variances, ``X`` the
design matrix (a single column of ones when there are no moderators), ``tau2`` the
between-study variance.
"""
from __future__ import annotations

from dataclasses import dataclass, field, asdict
from typing import Optional, Sequence

import numpy as np
from scipy import optimize, stats

METHODS = ("FE", "DL", "REML", "ML", "PM", "HE")
TESTS = ("z", "knha")


@dataclass
class MetaResult:
    """Everything a fitted model reports. Field names follow metafor where possible."""

    method: str
    test: str
    k: int
    p: int
    beta: np.ndarray
    se: np.ndarray
    vb: np.ndarray
    ci_lb: np.ndarray
    ci_ub: np.ndarray
    zval: np.ndarray
    pval: np.ndarray
    tau2: float
    QE: float
    QEp: float
    I2: float
    H2: float
    dfs: Optional[int]
    level: float
    coef_names: list = field(default_factory=list)
    QM: Optional[float] = None
    QMp: Optional[float] = None
    QMdf: Optional[tuple] = None
    pi_lb: Optional[float] = None
    pi_ub: Optional[float] = None
    converged: bool = True
    yi: np.ndarray = field(default=None, repr=False)
    vi: np.ndarray = field(default=None, repr=False)
    X: np.ndarray = field(default=None, repr=False)

    @property
    def estimate(self) -> float:
        """Pooled estimate (intercept) of a model without moderators."""
        return float(self.beta[0])

    @property
    def weights(self) -> np.ndarray:
        """Percentage weight of each study (inverse-variance, including tau2)."""
        w = 1.0 / (self.vi + (0.0 if self.method == "FE" else self.tau2))
        return 100.0 * w / w.sum()

    def to_dict(self) -> dict:
        d = asdict(self)
        for key in ("yi", "vi", "X", "vb"):
            d.pop(key, None)
        for key, val in list(d.items()):
            if isinstance(val, np.ndarray):
                d[key] = val.tolist()
            elif isinstance(val, (np.floating, np.integer)):
                d[key] = val.item()
        d["weights"] = self.weights.tolist()
        return d


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

def _as_design(X, k: int) -> np.ndarray:
    if X is None:
        return np.ones((k, 1))
    X = np.asarray(X, dtype=float)
    if X.ndim == 1:
        X = X[:, None]
    return X


def _wls(yi, vi, X, tau2):
    """Weighted least squares at a given tau2. Returns beta, vb, weights, P matrix."""
    w = 1.0 / (vi + tau2)
    W = np.diag(w)
    XtWX = X.T @ W @ X
    vb = np.linalg.inv(XtWX)
    beta = vb @ X.T @ W @ yi
    P = W - W @ X @ vb @ X.T @ W
    return beta, vb, w, P


def _q_gen(yi, vi, X, tau2) -> float:
    """Generalised Q statistic at a given tau2 (used by PM and the Q-profile CI)."""
    beta, _, w, _ = _wls(yi, vi, X, tau2)
    r = yi - X @ beta
    return float(np.sum(w * r * r))


def _tau2_dl(yi, vi, X):
    k, p = X.shape
    w = 1.0 / vi
    W = np.diag(w)
    vb = np.linalg.inv(X.T @ W @ X)
    P = W - W @ X @ vb @ X.T @ W
    Q = float(yi @ P @ yi)
    denom = np.trace(P)
    return max(0.0, (Q - (k - p)) / denom)


def _tau2_he(yi, vi, X):
    k, p = X.shape
    stXX = np.linalg.inv(X.T @ X)
    P = np.eye(k) - X @ stXX @ X.T
    rss = float(yi @ P @ yi)
    return max(0.0, (rss - np.trace(P @ np.diag(vi))) / (k - p))


def _tau2_pm(yi, vi, X):
    k, p = X.shape
    if _q_gen(yi, vi, X, 0.0) <= k - p:
        return 0.0
    hi = max(1.0, 10 * np.var(yi))
    while _q_gen(yi, vi, X, hi) > k - p:
        hi *= 10
    return optimize.brentq(lambda t: _q_gen(yi, vi, X, t) - (k - p), 0.0, hi, xtol=1e-12)


def _tau2_fisher(yi, vi, X, method, tol=1e-10, maxiter=1000):
    """REML / ML by Fisher scoring with step halving (as in metafor), started at HE."""
    tau2 = _tau2_he(yi, vi, X)
    for _ in range(maxiter):
        _, _, w, P = _wls(yi, vi, X, tau2)
        Py = P @ yi
        if method == "REML":
            adj = (Py @ Py - np.trace(P)) / np.sum(P * P)
        else:  # ML
            adj = (Py @ Py - np.sum(w)) / np.sum(w * w)
        while tau2 + adj < 0:
            adj /= 2
            if abs(adj) < tol:
                break
        tau2 = max(0.0, tau2 + adj)
        if abs(adj) < tol:
            return tau2, True
    return tau2, False


def estimate_tau2(yi, vi, X=None, method="REML"):
    yi = np.asarray(yi, float)
    vi = np.asarray(vi, float)
    X = _as_design(X, len(yi))
    if method == "FE":
        return 0.0, True
    if method == "DL":
        return _tau2_dl(yi, vi, X), True
    if method == "HE":
        return _tau2_he(yi, vi, X), True
    if method == "PM":
        return _tau2_pm(yi, vi, X), True
    if method in ("REML", "ML"):
        return _tau2_fisher(yi, vi, X, method)
    raise ValueError(f"unknown method {method!r}; choose from {METHODS}")


# ---------------------------------------------------------------------------
# main entry point
# ---------------------------------------------------------------------------

def rma(yi: Sequence[float], vi: Sequence[float], X=None, method: str = "REML",
        test: str = "z", level: float = 95.0, coef_names=None, btt=None) -> MetaResult:
    """Fit a fixed- or random-effects (meta-regression) model.

    Parameters
    ----------
    yi, vi : effect sizes and sampling variances.
    X : optional design matrix *including* the intercept column. ``None`` = intercept only.
    method : "FE", "DL", "REML", "ML", "PM" or "HE".
    test : "z" (normal) or "knha" (Knapp-Hartung adjustment, t / F distributions).
    level : confidence level in percent.
    btt : indices of coefficients for the omnibus moderator test (default: all but intercept).
    """
    yi = np.asarray(yi, float)
    vi = np.asarray(vi, float)
    if yi.shape != vi.shape:
        raise ValueError("yi and vi must have the same length")
    if np.any(~np.isfinite(yi)) or np.any(~np.isfinite(vi)):
        raise ValueError("yi and vi must be finite; drop or fix studies with missing data first")
    if np.any(vi <= 0):
        raise ValueError("all sampling variances must be > 0")
    if method not in METHODS:
        raise ValueError(f"unknown method {method!r}; choose from {METHODS}")
    if test not in TESTS:
        raise ValueError(f"unknown test {test!r}; choose from {TESTS}")
    k = len(yi)
    X = _as_design(X, k)
    p = X.shape[1]
    if k <= p:
        raise ValueError(f"need more studies (k={k}) than coefficients (p={p})")
    if coef_names is None:
        coef_names = ["intrcpt"] + [f"x{j}" for j in range(1, p)]

    tau2, converged = estimate_tau2(yi, vi, X, method)
    beta, vb, w, _ = _wls(yi, vi, X, tau2)

    # heterogeneity test (always based on the fixed-effects weights)
    wf = 1.0 / vi
    Wf = np.diag(wf)
    vbf = np.linalg.inv(X.T @ Wf @ X)
    Pf = Wf - Wf @ X @ vbf @ X.T @ Wf
    QE = float(yi @ Pf @ yi)
    QEp = float(stats.chi2.sf(QE, k - p)) if k - p > 0 else float("nan")

    # I2 / H2 relative to the 'typical' within-study variance
    vt = (k - p) / np.trace(Pf)
    if method == "FE":
        # with no tau2 to plug in, metafor (and Higgins & Thompson 2002) derive I2/H2 from Q
        I2 = 100.0 * max(0.0, (QE - (k - p)) / QE) if QE > 0 else 0.0
        H2 = QE / (k - p)
    else:
        I2 = 100.0 * tau2 / (tau2 + vt)
        H2 = (tau2 + vt) / vt

    dfs = None
    if test == "knha":
        r = yi - X @ beta
        s2w = float(np.sum(w * r * r) / (k - p))
        vb = vb * s2w
        dfs = k - p
    se = np.sqrt(np.diag(vb))
    zval = beta / se
    alpha = 1 - level / 100
    if test == "knha":
        crit = stats.t.ppf(1 - alpha / 2, dfs)
        pval = 2 * stats.t.sf(np.abs(zval), dfs)
    else:
        crit = stats.norm.ppf(1 - alpha / 2)
        pval = 2 * stats.norm.sf(np.abs(zval))
    ci_lb = beta - crit * se
    ci_ub = beta + crit * se

    res = MetaResult(method=method, test=test, k=k, p=p, beta=beta, se=se, vb=vb,
                     ci_lb=ci_lb, ci_ub=ci_ub, zval=zval, pval=pval, tau2=float(tau2),
                     QE=QE, QEp=QEp, I2=float(I2), H2=float(H2), dfs=dfs, level=level,
                     coef_names=list(coef_names), converged=converged, yi=yi, vi=vi, X=X)

    if p > 1:
        btt = list(range(1, p)) if btt is None else list(btt)
        b = beta[btt]
        V = vb[np.ix_(btt, btt)]
        m = len(btt)
        QM = float(b @ np.linalg.solve(V, b))
        if test == "knha":
            QM = QM / m
            res.QM, res.QMdf = QM, (m, k - p)
            res.QMp = float(stats.f.sf(QM, m, k - p))
        else:
            res.QM, res.QMdf = QM, (m, None)
            res.QMp = float(stats.chi2.sf(QM, m))
    else:
        tcrit = crit
        sd_pi = np.sqrt(vb[0, 0] + tau2)
        res.pi_lb = float(beta[0] - tcrit * sd_pi)
        res.pi_ub = float(beta[0] + tcrit * sd_pi)
    return res


# ---------------------------------------------------------------------------
# confidence interval for tau2 (Q-profile method; Viechtbauer 2007)
# ---------------------------------------------------------------------------

def tau2_ci(res: MetaResult, level: float = 95.0):
    """Q-profile confidence interval for tau2, with the implied I2 and H2 intervals.

    Returns a dict with ``tau2``, ``I2`` and ``H2`` entries, each (estimate, lower, upper).
    """
    yi, vi, X = res.yi, res.vi, res.X
    k, p = X.shape
    alpha = 1 - level / 100
    q_lo_target = stats.chi2.ppf(1 - alpha / 2, k - p)  # gives the lower bound
    q_hi_target = stats.chi2.ppf(alpha / 2, k - p)      # gives the upper bound
    f = lambda t, target: _q_gen(yi, vi, X, t) - target

    def solve(target):
        if f(0.0, target) < 0:
            return 0.0
        hi = max(1.0, 10 * float(np.var(yi)))
        while f(hi, target) > 0:
            hi *= 10
            if hi > 1e8:
                return float("inf")
        return optimize.brentq(f, 0.0, hi, args=(target,), xtol=1e-12)

    lb = solve(q_lo_target)
    ub = solve(q_hi_target)
    wf = 1.0 / vi
    Wf = np.diag(wf)
    vbf = np.linalg.inv(X.T @ Wf @ X)
    Pf = Wf - Wf @ X @ vbf @ X.T @ Wf
    vt = (k - p) / np.trace(Pf)
    to_i2 = lambda t: 100 * t / (t + vt)
    to_h2 = lambda t: (t + vt) / vt
    return {
        "tau2": (res.tau2, lb, ub),
        "tau": (np.sqrt(res.tau2), np.sqrt(lb), np.sqrt(ub)),
        "I2": (res.I2, to_i2(lb), to_i2(ub)),
        "H2": (res.H2, to_h2(lb), to_h2(ub)),
    }


def design_from_moderators(moderators: dict, categorical: Sequence[str] = ()):
    """Build a design matrix (with intercept) from a dict of moderator columns.

    Categorical moderators are dummy-coded against their first level (sorted),
    matching R's default treatment contrasts. Returns (X, coef_names).
    """
    cols = []
    names = ["intrcpt"]
    k = None
    for name, values in moderators.items():
        values = list(values)
        k = len(values) if k is None else k
        if len(values) != k:
            raise ValueError("all moderators must have the same length")
        if name in categorical:
            levels = sorted(set(values), key=str)
            for lev in levels[1:]:
                cols.append([1.0 if v == lev else 0.0 for v in values])
                names.append(f"{name}{lev}")
        else:
            cols.append([float(v) for v in values])
            names.append(name)
    if k is None:
        raise ValueError("no moderators given")
    X = np.column_stack([np.ones(k)] + [np.asarray(c) for c in cols])
    return X, names
