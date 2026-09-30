"""Statistical conversions: validated against metafor::conv.fivenum and hand-derived values."""
import json
import math
from pathlib import Path

import numpy as np
import pytest

from metakit import convert, effects

REF = json.loads((Path(__file__).parent / "fixtures" / "metafor_reference.json").read_text())
FN = REF["fivenum"]


@pytest.mark.parametrize("case", ["range", "iqr", "both"])
def test_median_to_mean_sd_matches_metafor(case):
    inp = FN["input"]
    for i, n in enumerate(inp["n"]):
        kw = {"median": inp["median"][i]}
        if case in ("range", "both"):
            kw.update(minimum=inp["min"][i], maximum=inp["max"][i])
        if case in ("iqr", "both"):
            kw.update(q1=inp["q1"][i], q3=inp["q3"][i])
        r = convert.mean_sd_from_quantiles(n, **kw)
        assert r["mean"] == pytest.approx(FN[case]["mean"][i], rel=1e-10)
        assert r["sd"] == pytest.approx(FN[case]["sd"][i], rel=1e-10)


def test_skew_warning():
    r = convert.mean_sd_from_quantiles(50, median=2, q1=1.8, q3=9)
    assert r["warning"] and "skewed" in r["warning"]
    assert convert.mean_sd_from_quantiles(50, median=5, q1=4, q3=6)["warning"] is None


def test_quantiles_need_spread():
    with pytest.raises(ValueError):
        convert.mean_sd_from_quantiles(50, median=5)


def test_sd_from_se_and_ci():
    assert convert.sd_from_se(0.5, 100) == pytest.approx(5.0)
    # large sample: normal critical value (Cochrane 6.5.2.2 worked example: n=100 -> SD from CI)
    sd = convert.sd_from_ci(10.0, 14.0, 100)
    assert sd == pytest.approx(10 * 4 / (2 * 1.959964), rel=1e-6)
    # small sample uses t with n-1 df, giving a smaller SD than the normal approximation
    t_sd = convert.sd_from_ci(10.0, 14.0, 25)
    assert t_sd == pytest.approx(5 * 4 / (2 * 2.063899), rel=1e-6)


def test_se_from_ratio_ci_is_on_log_scale():
    se = convert.se_from_ci(0.5, 2.0, log_scale=True)
    assert se == pytest.approx((math.log(2) - math.log(0.5)) / (2 * 1.959964), rel=1e-6)
    with pytest.raises(ValueError):
        convert.se_from_ci(-1, 2, log_scale=True)


def test_se_from_exact_p():
    se = convert.se_from_p(0.5, 0.05)
    assert se == pytest.approx(0.5 / 1.959964, rel=1e-6)
    with pytest.raises(ValueError):
        convert.se_from_p(0.5, 0.0)


def test_combine_groups_matches_pooling_raw_data():
    rng = np.random.default_rng(3)
    a, b = rng.normal(10, 2, 40), rng.normal(14, 3, 60)
    r = convert.combine_groups(40, a.mean(), a.std(ddof=1), 60, b.mean(), b.std(ddof=1))
    both = np.concatenate([a, b])
    assert r["n"] == 100
    assert r["mean"] == pytest.approx(both.mean(), rel=1e-12)
    assert r["sd"] == pytest.approx(both.std(ddof=1), rel=1e-12)


def test_change_score_sd():
    assert convert.sd_change(10, 10, 0.5) == pytest.approx(10.0)
    assert convert.sd_change(3, 4, 0.0) == pytest.approx(5.0)
    with pytest.raises(ValueError):
        convert.sd_change(1, 1, 1.5)


def test_or_smd_roundtrip():
    smd, v = convert.log_or_to_smd(1.0, 0.04)
    lo, lv = convert.smd_to_log_or(smd, v)
    assert lo == pytest.approx(1.0) and lv == pytest.approx(0.04)


def test_units_including_ecg_calibration():
    assert convert.convert_units(1.0, "mm", "mV") == pytest.approx(0.1)
    assert convert.convert_units(150, "uV", "mV") == pytest.approx(0.15)
    assert convert.convert_units(0.2, "s", "ms") == pytest.approx(200)
    assert convert.convert_units(5, "mV", "mV") == 5
    with pytest.raises(KeyError):
        convert.convert_units(1, "furlong", "mV")


def test_more_zero_cells_match_metafor():
    Z = REF["zero_more"]
    rd = [effects.binary("RD", 0, 20, 4, 20), effects.binary("RD", 3, 20, 0, 20)]
    assert [e.yi for e in rd] == pytest.approx(Z["rd_yi"], rel=1e-10)
    assert [e.vi for e in rd] == pytest.approx(Z["rd_vi"], rel=1e-10)
    for m, yk, vk in (("PR", "pr_yi", "pr_vi"), ("PLO", "plo_yi", "plo_vi")):
        es = [effects.proportion(m, x, n) for x, n in ((0, 20), (5, 30), (20, 20))]
        assert [e.yi for e in es] == pytest.approx(Z[yk], rel=1e-10)
        assert [e.vi for e in es] == pytest.approx(Z[vk], rel=1e-10)


def test_generic_effect_from_ratio_ci():
    e = effects.generic(0.8, ci_lower=0.64, ci_upper=1.0, ratio=True)
    assert e.yi == pytest.approx(math.log(0.8))
    assert math.sqrt(e.vi) == pytest.approx((math.log(1.0) - math.log(0.64)) / (2 * 1.959964), rel=1e-6)


def test_hedges_j_approximation():
    # exact J is close to the familiar 1 - 3/(4 df - 1)
    for df in (5, 20, 100):
        assert effects.hedges_j(df) == pytest.approx(1 - 3 / (4 * df - 1), rel=2e-3)
