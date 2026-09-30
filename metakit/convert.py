"""Conversions for the statistics papers actually report.

Studies rarely report exactly the mean and SD a meta-analysis needs. These functions turn
what *is* reported (standard errors, confidence intervals, medians with ranges or IQRs,
subgroups that need merging) into usable numbers, using the methods recommended in the
Cochrane Handbook (chapter 6) and validated against ``metafor::conv.fivenum``.

Every function is pure and documented with its source, so each derived number in a
meta-analysis can be traced to a published method.
"""
from __future__ import annotations

import math

from scipy import stats


def _crit(n: int | None, level: float) -> float:
    """Critical value: t with n-1 df for small samples (n < 60), else normal.

    Cochrane Handbook 6.5.2.2 recommends the t distribution when groups are small.
    """
    alpha = 1 - level / 100
    if n is not None and n < 60:
        return float(stats.t.ppf(1 - alpha / 2, n - 1))
    return float(stats.norm.ppf(1 - alpha / 2))


def sd_from_se(se: float, n: int) -> float:
    """SD = SE * sqrt(n). (Cochrane Handbook 6.5.2.2)"""
    return se * math.sqrt(n)


def se_from_ci(lower: float, upper: float, n: int | None = None, level: float = 95.0,
               log_scale: bool = False) -> float:
    """SE from a confidence interval.

    For ratio measures (odds ratio, risk ratio, hazard ratio) pass ``log_scale=True``:
    the interval is symmetric on the log scale, so SE = (ln U - ln L) / (2 * crit).
    For a CI of a single-group mean, pass ``n`` to use the t distribution when n < 60.
    For CIs of ratio measures and large-sample estimates, leave ``n`` as None (normal).
    """
    if upper <= lower:
        raise ValueError("upper CI limit must exceed lower limit")
    if log_scale:
        if lower <= 0:
            raise ValueError("ratio-scale CI limits must be positive")
        lower, upper = math.log(lower), math.log(upper)
    return (upper - lower) / (2 * _crit(n, level))


def sd_from_ci(lower: float, upper: float, n: int, level: float = 95.0) -> float:
    """SD of a single group from the CI of its mean. (Cochrane Handbook 6.5.2.2)"""
    return sd_from_se(se_from_ci(lower, upper, n, level), n)


def se_from_p(estimate: float, p: float, log_scale: bool = False) -> float:
    """SE from an estimate and its exact two-sided p-value (Cochrane Handbook 6.3.2).

    Only valid for exact p-values ("p = 0.03"), never for thresholds ("p < 0.05").
    """
    if not 0 < p < 1:
        raise ValueError("p must be strictly between 0 and 1")
    if log_scale:
        estimate = math.log(estimate)
    z = stats.norm.ppf(1 - p / 2)
    return abs(estimate) / z


def _xi(n):
    return 2 * stats.norm.ppf((n - 0.375) / (n + 0.25))


def _eta(n):
    return 2 * stats.norm.ppf((0.75 * n - 0.125) / (n + 0.25))


def mean_sd_from_quantiles(n: int, median: float, q1: float | None = None, q3: float | None = None,
                           minimum: float | None = None, maximum: float | None = None) -> dict:
    """Estimate mean and SD from a median plus range and/or IQR.

    Uses the same methods as ``metafor::conv.fivenum(method="default")``:

    * min, median, max        -> mean: Luo et al. (2018) eq. 7;  SD: Wan et al. (2014) eq. 9
    * q1, median, q3          -> mean: Luo et al. (2018) eq. 11; SD: Wan et al. (2014) eq. 16
    * min, q1, median, q3, max -> mean: Luo et al. (2018) eq. 15; SD: Shi et al. (2020) eq. 10

    These assume roughly normal data. A strongly skewed distribution (median far from the
    middle of the IQR) is flagged in ``warning``; consider excluding it in a sensitivity analysis.
    """
    has_range = minimum is not None and maximum is not None
    has_iqr = q1 is not None and q3 is not None
    n = float(n)
    warning = None
    if has_range and has_iqr:
        w1 = 2.2 / (2.2 + n ** 0.75)
        w2 = 0.7 - 0.72 / n ** 0.55
        mean = w1 * (minimum + maximum) / 2 + w2 * (q1 + q3) / 2 + (1 - w1 - w2) * median
        th1 = (2 + 0.14 * n ** 0.6) * stats.norm.ppf((n - 0.375) / (n + 0.25))
        th2 = (2 + 2 / (0.07 * n ** 0.6)) * stats.norm.ppf((0.75 * n - 0.125) / (n + 0.25))
        sd = (maximum - minimum) / th1 + (q3 - q1) / th2
        case = "min/q1/median/q3/max"
    elif has_iqr:
        w = 0.7 + 0.39 / n
        mean = w * (q1 + q3) / 2 + (1 - w) * median
        sd = (q3 - q1) / _eta(n)
        case = "q1/median/q3"
    elif has_range:
        w = 4 / (4 + n ** 0.75)
        mean = w * (minimum + maximum) / 2 + (1 - w) * median
        sd = (maximum - minimum) / _xi(n)
        case = "min/median/max"
    else:
        raise ValueError("need (q1, q3), (minimum, maximum), or both, alongside the median")
    if has_iqr and q3 > q1:
        skew = abs((q1 + q3) / 2 - median) / (q3 - q1)
        if skew > 0.25:
            warning = ("median sits far from the centre of the IQR; data look skewed, so the "
                       "normal-theory mean/SD estimate may be poor")
    return {"mean": float(mean), "sd": float(sd), "case": case, "warning": warning,
            "method": "Luo 2018 (mean); Wan 2014 / Shi 2020 (SD)"}


def combine_groups(n1: int, mean1: float, sd1: float, n2: int, mean2: float, sd2: float) -> dict:
    """Merge two subgroups into one group (Cochrane Handbook Table 6.5.a).

    Use when a paper reports, e.g., men and women separately but your comparison needs
    all participants. Apply repeatedly to merge more than two groups.
    """
    n = n1 + n2
    mean = (n1 * mean1 + n2 * mean2) / n
    var = ((n1 - 1) * sd1 ** 2 + (n2 - 1) * sd2 ** 2 + n1 * n2 / n * (mean1 - mean2) ** 2) / (n - 1)
    return {"n": n, "mean": mean, "sd": math.sqrt(var)}


def sd_change(sd_baseline: float, sd_final: float, corr: float) -> float:
    """SD of change scores from baseline and final SDs and an assumed correlation.

    (Cochrane Handbook 6.5.2.8.) The correlation is usually imputed from another study;
    record where it came from and vary it in a sensitivity analysis.
    """
    if not -1 <= corr <= 1:
        raise ValueError("correlation must be in [-1, 1]")
    return math.sqrt(sd_baseline ** 2 + sd_final ** 2 - 2 * corr * sd_baseline * sd_final)


def log_or_to_smd(log_or: float, var_log_or: float) -> tuple[float, float]:
    """Convert a log odds ratio to a standardized mean difference (Chinn, 2000)."""
    k = math.sqrt(3) / math.pi
    return log_or * k, var_log_or * 3 / math.pi ** 2


def smd_to_log_or(smd: float, var_smd: float) -> tuple[float, float]:
    """Convert a standardized mean difference to a log odds ratio (Chinn, 2000)."""
    k = math.pi / math.sqrt(3)
    return smd * k, var_smd * math.pi ** 2 / 3


UNIT_FACTORS = {
    # to the first unit in each pair
    ("mV", "uV"): 1e-3, ("uV", "mV"): 1e3,
    ("mV", "mm"): 0.1,   # standard ECG calibration: 10 mm = 1 mV
    ("mm", "mV"): 10.0,
    ("ms", "s"): 1e3, ("s", "ms"): 1e-3,
    ("kg", "lb"): 0.45359237, ("lb", "kg"): 1 / 0.45359237,
    ("cm", "m"): 100.0, ("m", "cm"): 0.01,
    ("mmol/L", "mg/dL glucose"): 1 / 18.0,
    ("mmol/L", "mg/dL cholesterol"): 1 / 38.67,
}


def convert_units(value: float, from_unit: str, to_unit: str) -> float:
    """Convert between common units. Raises if the pair is unknown rather than guessing.

    Note the ECG calibration entry: many papers report ST deviation in millimetres at
    standard gain (10 mm/mV); 1 mm corresponds to 0.1 mV.
    """
    if from_unit == to_unit:
        return value
    key = (to_unit, from_unit)
    if key not in UNIT_FACTORS:
        raise KeyError(f"no conversion registered from {from_unit!r} to {to_unit!r}; "
                       f"add it to UNIT_FACTORS with a source")
    return value * UNIT_FACTORS[key]
