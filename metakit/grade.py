"""A transparent first draft of the GRADE certainty rating for each outcome.

GRADE (Guyatt et al., 2008; GRADE Handbook) rates certainty as high / moderate / low /
very low. Evidence from RCTs starts high and from observational studies starts low, then is
downgraded for risk of bias, inconsistency, indirectness, imprecision and publication bias.

GRADE is a *judgement*, not a formula. This module applies explicit, published rules of
thumb so the reviewers start from a documented suggestion, and every downgrade comes with
its reason. The report labels the result "suggested" until a human signs off.
"""
from __future__ import annotations

LEVELS = ["very low", "low", "moderate", "high"]
OBSERVATIONAL = {"cohort", "case-control", "cross-sectional", "observational", "case series",
                 "registry", "non-randomised", "non-randomized"}


def _starting_level(designs: list[str], start: str) -> tuple[int, str]:
    if start in ("high", "low"):
        return LEVELS.index(start), f"start fixed at '{start}' by the protocol"
    obs = [d for d in designs if (d or "").lower() in OBSERVATIONAL]
    if designs and len(obs) == len(designs):
        return LEVELS.index("low"), "all studies observational: start at low"
    if obs:
        return LEVELS.index("high"), ("mix of randomised and observational studies: start at high "
                                      "(consider rating the designs separately)")
    return LEVELS.index("high"), "randomised trials: start at high"


def suggest(outcome_result: dict, designs: list[str], protocol_grade: dict,
            n_total: int | None, events_total: int | None, data_type: str) -> dict:
    """Return {"rating", "start", "domains": {name: {"downgrade", "reason"}}, "confirmed": False}."""
    start_idx, start_reason = _starting_level(designs, protocol_grade.get("start", "auto"))
    main = outcome_result["main"]
    k = main["k"]
    domains = {}

    # 1. risk of bias: share of weight from high-risk studies
    w_high = outcome_result.get("weight_high_rob")
    if w_high is None:
        domains["risk_of_bias"] = {"downgrade": 0, "reason": "no risk-of-bias assessments loaded: RATE MANUALLY"}
    elif w_high > 50:
        domains["risk_of_bias"] = {"downgrade": 1, "reason": f"{w_high:.0f}% of the weight comes from high-risk studies"}
    else:
        domains["risk_of_bias"] = {"downgrade": 0, "reason": f"{w_high:.0f}% of the weight from high-risk studies"}

    # 2. inconsistency
    I2 = main["I2"]
    pi_crosses = None
    null = outcome_result.get("null_value_analysis_scale")
    if main.get("pi_lb") is not None and null is not None:
        pi_crosses = main["pi_lb"] < null < main["pi_ub"]
    if k < 2:
        domains["inconsistency"] = {"downgrade": 0, "reason": "single study: inconsistency not assessable"}
    elif I2 >= 75 and pi_crosses:
        domains["inconsistency"] = {"downgrade": 2 if I2 >= 90 else 1,
                                    "reason": f"I2 = {I2:.0f}% and the prediction interval spans no effect"}
    elif I2 >= 50:
        domains["inconsistency"] = {"downgrade": 1, "reason": f"substantial heterogeneity (I2 = {I2:.0f}%)"}
    else:
        domains["inconsistency"] = {"downgrade": 0, "reason": f"I2 = {I2:.0f}%"}

    # 3. indirectness: cannot be computed
    ind = int(protocol_grade.get("indirectness", 0) or 0)
    domains["indirectness"] = {"downgrade": ind,
                               "reason": "set by reviewers in protocol.yaml (grade.indirectness)"
                                         if ind else "not downgraded; reviewers must confirm PICO match"}

    # 4. imprecision: CI crosses no effect, and optimal information size
    down, reasons = 0, []
    ci_lb, ci_ub = main["ci_lb"], main["ci_ub"]
    if null is not None and ci_lb < null < ci_ub:
        down += 1
        reasons.append("95% CI includes no effect")
    if data_type == "binary" and events_total is not None and events_total < 300:
        down += 1
        reasons.append(f"only {events_total} events (< 300, the GRADE rule-of-thumb information size)")
    elif data_type != "binary" and n_total is not None and n_total < 400:
        down += 1
        reasons.append(f"only {n_total} participants (< 400, the GRADE rule-of-thumb information size)")
    domains["imprecision"] = {"downgrade": min(down, 2), "reason": "; ".join(reasons) or "adequately precise"}

    # 5. publication bias
    eg = outcome_result.get("egger")
    if k < 10 or eg is None:
        domains["publication_bias"] = {"downgrade": 0,
                                       "reason": f"only {k} studies: asymmetry tests unreliable; judge from search completeness"}
    elif eg["pval"] < 0.10:
        domains["publication_bias"] = {"downgrade": 1, "reason": f"Egger test p = {eg['pval']:.3f} (< 0.10)"}
    else:
        domains["publication_bias"] = {"downgrade": 0, "reason": f"Egger test p = {eg['pval']:.2f}"}

    total = sum(d["downgrade"] for d in domains.values())
    final = max(0, start_idx - total)
    return {"rating": LEVELS[final], "start": LEVELS[start_idx], "start_reason": start_reason,
            "domains": domains, "total_downgrade": total, "confirmed": False}
