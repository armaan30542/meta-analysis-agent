"""Effect sizes and their sampling variances (the equivalent of ``metafor::escalc``).

Supported measures
------------------
Two-group, binary outcome (2x2 table: events/total in each arm)
    RR  log risk ratio          OR  log odds ratio          RD  risk difference
Two-group, continuous outcome (mean, SD, n in each arm)
    MD  raw mean difference     SMD standardized mean difference (Hedges' g)
    ROM log ratio of means
Single group
    MN  raw mean                PR  raw proportion          PLO logit proportion
Correlation
    ZCOR Fisher's z             COR raw correlation
Pre-computed
    GEN any effect with a reported SE or CI (e.g. an adjusted hazard ratio)

Zero cells: as in metafor, 0.5 is added to every cell of a 2x2 table (or to x and n-x for
proportions) that contains a zero. Studies with zero events in *both* arms carry no
information about a ratio and are flagged for exclusion (Cochrane Handbook 10.4.4.2).
"""
from __future__ import annotations

import math
from dataclasses import dataclass

from scipy import special, stats

MEASURES = {
    "RR": "log risk ratio", "OR": "log odds ratio", "RD": "risk difference",
    "MD": "mean difference", "SMD": "standardized mean difference (Hedges' g)",
    "ROM": "log ratio of means", "MN": "mean", "PR": "proportion",
    "PLO": "logit proportion", "ZCOR": "Fisher z correlation", "COR": "correlation",
    "GEN": "generic (pre-computed) effect",
}
RATIO_MEASURES = {"RR", "OR", "ROM"}


@dataclass
class Effect:
    yi: float
    vi: float
    measure: str
    note: str | None = None
    exclude: bool = False


def _cc(*cells, add=0.5):
    if any(c == 0 for c in cells):
        return [c + add for c in cells], f"added {add} to all cells (zero cell)"
    return list(cells), None


def binary(measure: str, events_t: float, n_t: float, events_c: float, n_c: float) -> Effect:
    """2x2 table effects. ``events_*`` are event counts, ``n_*`` are group sizes."""
    for v, nm in ((events_t, "events_t"), (events_c, "events_c")):
        if v < 0:
            raise ValueError(f"{nm} cannot be negative")
    if events_t > n_t or events_c > n_c:
        raise ValueError("events cannot exceed group size")
    a, b, c, d = events_t, n_t - events_t, events_c, n_c - events_c
    if measure in ("RR", "OR") and events_t == 0 and events_c == 0:
        return Effect(float("nan"), float("nan"), measure,
                      "zero events in both arms: uninformative for a ratio, excluded", True)
    if measure in ("RR", "OR") and b == 0 and d == 0:
        return Effect(float("nan"), float("nan"), measure,
                      "all participants had the event in both arms: excluded", True)
    (a, b, c, d), note = _cc(a, b, c, d)
    n1, n2 = a + b, c + d
    if measure == "RR":
        yi = math.log((a / n1) / (c / n2))
        vi = 1 / a - 1 / n1 + 1 / c - 1 / n2
    elif measure == "OR":
        yi = math.log((a * d) / (b * c))
        vi = 1 / a + 1 / b + 1 / c + 1 / d
    elif measure == "RD":
        p1, p2 = a / n1, c / n2
        yi = p1 - p2
        vi = p1 * (1 - p1) / n1 + p2 * (1 - p2) / n2
    else:
        raise ValueError(f"{measure} is not a binary-outcome measure")
    return Effect(yi, vi, measure, note)


def hedges_j(df: float) -> float:
    """Exact small-sample bias correction factor for Cohen's d (Hedges, 1981)."""
    return math.exp(special.gammaln(df / 2) - 0.5 * math.log(df / 2) - special.gammaln((df - 1) / 2))


def continuous(measure: str, mean_t: float, sd_t: float, n_t: float,
               mean_c: float, sd_c: float, n_c: float) -> Effect:
    """Two-group continuous effects from means, SDs and sample sizes."""
    if sd_t <= 0 or sd_c <= 0:
        raise ValueError("SDs must be positive")
    if n_t < 2 or n_c < 2:
        raise ValueError("each group needs at least 2 participants")
    if measure == "MD":
        return Effect(mean_t - mean_c, sd_t ** 2 / n_t + sd_c ** 2 / n_c, measure)
    if measure == "SMD":
        df = n_t + n_c - 2
        sdp = math.sqrt(((n_t - 1) * sd_t ** 2 + (n_c - 1) * sd_c ** 2) / df)
        g = hedges_j(df) * (mean_t - mean_c) / sdp
        vi = 1 / n_t + 1 / n_c + g ** 2 / (2 * (n_t + n_c))
        return Effect(g, vi, measure)
    if measure == "ROM":
        if mean_t <= 0 or mean_c <= 0:
            raise ValueError("ratio of means needs positive means")
        yi = math.log(mean_t / mean_c)
        vi = sd_t ** 2 / (n_t * mean_t ** 2) + sd_c ** 2 / (n_c * mean_c ** 2)
        return Effect(yi, vi, measure)
    raise ValueError(f"{measure} is not a two-group continuous measure")


def single_mean(mean: float, sd: float, n: float) -> Effect:
    if sd <= 0 or n < 2:
        raise ValueError("need sd > 0 and n >= 2")
    return Effect(mean, sd ** 2 / n, "MN")


def proportion(measure: str, events: float, n: float) -> Effect:
    if not 0 <= events <= n:
        raise ValueError("events must be between 0 and n")
    x, nonx = events, n - events
    note = None
    if measure == "PR":
        p = x / n
        if p in (0.0, 1.0):
            (x, nonx), note = _cc(x, nonx)
            p = x / (x + nonx)
            return Effect(p, p * (1 - p) / (x + nonx), measure, note)
        return Effect(p, p * (1 - p) / n, measure)
    if measure == "PLO":
        (x, nonx), note = _cc(x, nonx)
        return Effect(math.log(x / nonx), 1 / x + 1 / nonx, measure, note)
    raise ValueError(f"{measure} is not a proportion measure")


def correlation(measure: str, r: float, n: float) -> Effect:
    if not -1 < r < 1:
        raise ValueError("r must be strictly between -1 and 1")
    if n < 4:
        raise ValueError("need n >= 4 for a correlation")
    if measure == "ZCOR":
        return Effect(math.atanh(r), 1 / (n - 3), measure)
    if measure == "COR":
        return Effect(r, (1 - r ** 2) ** 2 / (n - 1), measure)
    raise ValueError(f"{measure} is not a correlation measure")


def generic(estimate: float, se: float | None = None, ci_lower: float | None = None,
            ci_upper: float | None = None, ratio: bool = False, level: float = 95.0) -> Effect:
    """A pre-computed effect (e.g. adjusted OR/HR with a CI). Ratios go on the log scale."""
    if ratio:
        if estimate <= 0:
            raise ValueError("ratio estimates must be positive")
        yi = math.log(estimate)
    else:
        yi = estimate
    if se is None:
        if ci_lower is None or ci_upper is None:
            raise ValueError("need se or both CI limits")
        lo, hi = (math.log(ci_lower), math.log(ci_upper)) if ratio else (ci_lower, ci_upper)
        if not lo <= yi <= hi:
            raise ValueError("point estimate lies outside its confidence interval; check extraction")
        se = (hi - lo) / (2 * stats.norm.ppf(1 - (1 - level / 100) / 2))
    # for ratio measures a supplied ``se`` must already be on the log scale
    if se <= 0:
        raise ValueError("se must be positive")
    return Effect(yi, se ** 2, "GEN")


def back_transform(measure: str, value: float, ratio_generic: bool = False) -> float:
    """Map a pooled value back to the scale readers understand."""
    if measure in RATIO_MEASURES or (measure == "GEN" and ratio_generic):
        return math.exp(value)
    if measure == "ZCOR":
        return math.tanh(value)
    if measure == "PLO":
        return 1 / (1 + math.exp(-value))
    return value


def display_name(measure: str, ratio_generic: bool = False) -> str:
    names = {"RR": "Risk ratio", "OR": "Odds ratio", "RD": "Risk difference",
             "MD": "Mean difference", "SMD": "Hedges' g", "ROM": "Ratio of means",
             "MN": "Mean", "PR": "Proportion", "PLO": "Proportion", "ZCOR": "Correlation (r)",
             "COR": "Correlation (r)", "GEN": "Ratio" if ratio_generic else "Effect"}
    return names[measure]


def null_value(measure: str, ratio_generic: bool = False) -> float | None:
    """The 'no effect' line on the displayed (back-transformed) scale."""
    if measure in RATIO_MEASURES or (measure == "GEN" and ratio_generic):
        return 1.0
    if measure in ("RD", "MD", "SMD", "ZCOR", "COR", "GEN"):
        return 0.0
    return None  # single-group measures have no null
