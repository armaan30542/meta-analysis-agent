"""The statistical engine must reproduce metafor. Reference values: r/make_reference.R."""
import json
from pathlib import Path

import numpy as np
import pytest

from metakit import bias, effects, sensitivity
from metakit.models import design_from_moderators, rma, tau2_ci

REF = json.loads((Path(__file__).parent / "fixtures" / "metafor_reference.json").read_text())
BCG = REF["bcg"]
YI, VI = np.array(BCG["yi"]), np.array(BCG["vi"])
col = lambda name: [r[name] for r in BCG["data"]]

# metafor's default convergence threshold is 1e-5; ours is 1e-10, so iterative
# estimators agree to ~1e-5 relative. Closed-form estimators agree to ~1e-12.
TOL_ITER = 5e-4
TOL_EXACT = 1e-9


def close(a, b, tol):
    a, b = np.atleast_1d(a).astype(float), np.atleast_1d(b).astype(float)
    np.testing.assert_allclose(a, b, rtol=tol, atol=tol)


@pytest.mark.parametrize("method,tol", [("FE", TOL_EXACT), ("DL", TOL_EXACT), ("HE", TOL_EXACT),
                                        ("REML", TOL_ITER), ("ML", TOL_ITER), ("PM", TOL_ITER)])
def test_pooled_models_match_metafor(method, tol):
    ref = BCG["fits"][method]
    res = rma(YI, VI, method=method)
    for key in ("beta", "se", "ci_lb", "ci_ub", "zval", "pval"):
        close(getattr(res, key), ref[key], tol)
    for key in ("tau2", "QE", "QEp", "I2", "H2"):
        close(getattr(res, key), ref[key], tol)
    if method != "FE":
        close(res.pi_lb, ref["pi_lb"], tol)
        close(res.pi_ub, ref["pi_ub"], tol)


def test_knapp_hartung_matches_metafor():
    ref = BCG["fits"]["REML_knha"]
    res = rma(YI, VI, test="knha")
    for key in ("beta", "se", "ci_lb", "ci_ub", "pval"):
        close(getattr(res, key), ref[key], TOL_ITER)
    close(res.pi_lb, ref["pi_lb"], TOL_ITER)
    assert res.dfs == len(YI) - 1


def test_tau2_confidence_interval_q_profile():
    ci = tau2_ci(rma(YI, VI))
    close(ci["tau2"], BCG["tau2_ci"], TOL_ITER)
    close(ci["I2"], BCG["I2_ci"], TOL_ITER)
    ci_dl = tau2_ci(rma(YI, VI, method="DL"))
    close(ci_dl["tau2"], BCG["tau2_ci_DL"], TOL_ITER)


@pytest.mark.parametrize("key,mods,cat,method,test", [
    ("metareg_ablat", "ablat", (), "REML", "z"),
    ("metareg_ablat_knha", "ablat", (), "REML", "knha"),
    ("metareg_alloc", "alloc", ("alloc",), "REML", "z"),
    ("metareg_ablat_DL", "ablat", (), "DL", "z"),
])
def test_meta_regression_matches_metafor(key, mods, cat, method, test):
    ref = BCG[key]
    X, names = design_from_moderators({mods: col(mods)}, categorical=cat)
    res = rma(YI, VI, X=X, method=method, test=test, coef_names=names)
    for k2 in ("beta", "se", "ci_lb", "ci_ub", "pval"):
        close(getattr(res, k2), ref[k2], TOL_ITER)
    for k2 in ("tau2", "QE", "I2", "QM", "QMp"):
        close(getattr(res, k2), ref[k2], TOL_ITER)


def test_egger_and_rank_tests():
    res = rma(YI, VI)
    e = bias.egger(res)
    close(e["stat"], BCG["egger_rma"]["zval"], TOL_ITER)
    close(e["pval"], BCG["egger_rma"]["pval"], TOL_ITER)
    close(e["limit_estimate"], BCG["egger_rma"]["limit"], TOL_ITER)
    e2 = bias.egger(res, "lm")
    close(e2["stat"], BCG["egger_lm"]["zval"], TOL_EXACT)
    close(e2["pval"], BCG["egger_lm"]["pval"], TOL_EXACT)
    assert e2["dfs"] == BCG["egger_lm"]["dfs"]
    r = bias.rank_test(res)
    close(r["tau"], BCG["ranktest"]["tau"], TOL_EXACT)
    close(r["pval"], BCG["ranktest"]["pval"], 1e-6)


@pytest.mark.parametrize("method,key", [("REML", "trimfill"), ("FE", "trimfill_FE")])
def test_trim_and_fill(method, key):
    ref = BCG[key]
    tf = bias.trim_and_fill(rma(YI, VI, method=method))
    assert tf["k0"] == ref["k0"]
    assert tf["side"] == ref["side"]
    close(tf["estimate"], ref["beta"], TOL_ITER)
    close(tf["se"], ref["se"], TOL_ITER)


def test_leave_one_out_and_cumulative():
    res = rma(YI, VI)
    l1o = sensitivity.leave_one_out(res)
    close([r["estimate"] for r in l1o], BCG["leave1out"]["estimate"], TOL_ITER)
    close([r["tau2"] for r in l1o], BCG["leave1out"]["tau2"], TOL_ITER)
    cum = sensitivity.cumulative(res, col("year"))
    close([r["estimate"] for r in cum], BCG["cumul_year"], TOL_ITER)


def test_subgroup_differences_equal_categorical_metaregression():
    sg = sensitivity.subgroups(YI, VI, col("alloc"))
    close(sg["test_of_differences"]["QM"], BCG["metareg_alloc"]["QM"], TOL_ITER)
    assert set(sg["per_group"]) == {"alternate", "random", "systematic"}


def _escalc_check(computed, ref_yi, ref_vi):
    close([e.yi for e in computed], ref_yi, 1e-10)
    close([e.vi for e in computed], ref_vi, 1e-10)


@pytest.mark.parametrize("measure,yk,vk", [("RR", "yi", "vi"), ("OR", "or_yi", "or_vi"), ("RD", "rd_yi", "rd_vi")])
def test_binary_effects(measure, yk, vk):
    comp = [effects.binary(measure, r["tpos"], r["tpos"] + r["tneg"], r["cpos"], r["cpos"] + r["cneg"])
            for r in BCG["data"]]
    _escalc_check(comp, BCG[yk], BCG[vk])


def test_zero_cell_continuity_correction():
    z = REF["zero_cell"]
    d = z["data"]
    comp = [effects.binary("OR", a, a + b, c, c + dd) for a, b, c, dd in zip(d["ai"], d["bi"], d["ci"], d["di"])] \
        if isinstance(d, dict) else [effects.binary("OR", r["ai"], r["ai"] + r["bi"], r["ci"], r["ci"] + r["di"]) for r in d]
    _escalc_check(comp, z["or_yi"], z["or_vi"])


def test_double_zero_studies_are_excluded():
    e = effects.binary("RR", 0, 50, 0, 48)
    assert e.exclude and "both arms" in e.note


@pytest.mark.parametrize("measure,yk,vk,fit", [("MD", "md_yi", "md_vi", "md_REML"),
                                               ("SMD", "smd_yi", "smd_vi", "smd_REML")])
def test_continuous_effects_and_pooling(measure, yk, vk, fit):
    N = REF["normand"]
    comp = [effects.continuous(measure, r["m1i"], r["sd1i"], r["n1i"], r["m2i"], r["sd2i"], r["n2i"]) for r in N["data"]]
    _escalc_check(comp, N[yk], N[vk])
    res = rma([e.yi for e in comp], [e.vi for e in comp])
    close(res.beta, N[fit]["beta"], TOL_ITER)
    close(res.tau2, N[fit]["tau2"], TOL_ITER)


def test_correlation_proportion_and_mean_effects():
    M = REF["molloy"]
    comp = [effects.correlation("ZCOR", r["ri"], r["ni"]) for r in M["data"]]
    _escalc_check(comp, M["yi"], M["vi"])
    close(rma([e.yi for e in comp], [e.vi for e in comp]).beta, M["REML"]["beta"], TOL_ITER)
    P = REF["pritz"]
    comp = [effects.proportion("PLO", r["xi"], r["ni"]) for r in P["data"]]
    _escalc_check(comp, P["yi"], P["vi"])
    S = REF["single_mean"]
    d = S["data"]
    rows = d if isinstance(d, list) else [dict(zip(d, t)) for t in zip(*d.values())]
    comp = [effects.single_mean(r["mi"], r["sdi"], r["ni"]) for r in rows]
    _escalc_check(comp, S["yi"], S["vi"])


def test_back_transforms():
    assert effects.back_transform("RR", 0.0) == 1.0
    assert abs(effects.back_transform("ZCOR", np.arctanh(0.3)) - 0.3) < 1e-12
    assert abs(effects.back_transform("PLO", 0.0) - 0.5) < 1e-12
    assert effects.null_value("MN") is None


def test_input_validation():
    with pytest.raises(ValueError):
        rma([0.1, 0.2], [0.01, -0.01])
    with pytest.raises(ValueError):
        rma([0.1], [0.01], X=np.ones((1, 1)))
    with pytest.raises(ValueError):
        effects.binary("RR", 12, 10, 3, 10)
    with pytest.raises(ValueError):
        effects.generic(2.0, ci_lower=2.5, ci_upper=3.0, ratio=True)
