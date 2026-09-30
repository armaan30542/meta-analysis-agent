# Statistical methods and references

Everything metakit computes, with the formula or the source. Notation: study *i* has effect
*y*ᵢ with sampling variance *v*ᵢ; *k* studies; *p* model coefficients; τ² is the between-study variance.

## Effect sizes (`metakit/effects.py`)

| Measure | *y*ᵢ | *v*ᵢ |
|---|---|---|
| log RR | ln[(a/n₁)/(c/n₂)] | 1/a − 1/n₁ + 1/c − 1/n₂ |
| log OR | ln[ad/(bc)] | 1/a + 1/b + 1/c + 1/d |
| RD | a/n₁ − c/n₂ | p₁(1−p₁)/n₁ + p₂(1−p₂)/n₂ |
| MD | m₁ − m₂ | s₁²/n₁ + s₂²/n₂ |
| SMD (Hedges' g) | J·(m₁ − m₂)/s_p, with exact J = Γ(df/2) / [√(df/2)·Γ((df−1)/2)] | 1/n₁ + 1/n₂ + g²/[2(n₁+n₂)] |
| log ROM | ln(m₁/m₂) | s₁²/(n₁m₁²) + s₂²/(n₂m₂²) |
| MN | m | s²/n |
| PLO | ln[x/(n−x)] | 1/x + 1/(n−x) |
| ZCOR | atanh(r) | 1/(n−3) |

A 2×2 table (or proportion) containing a zero gets 0.5 added to every cell. Studies with no
events in both arms are excluded from ratio measures (Cochrane Handbook §10.4.4.2). This
matches `metafor::escalc` defaults.

## Conversions (`metakit/convert.py`)

- SD = SE·√n; SD from a CI of a mean: SE = (U − L)/(2·t₀.₉₇₅,ₙ₋₁) for n < 60, else with z
  (Cochrane Handbook §6.5.2.2).
- Mean and SD from medians: Luo et al. (2018) for the mean; Wan et al. (2014) for the SD from
  range or IQR; Shi et al. (2020) for the SD from the full five-number summary. Identical to
  `metafor::conv.fivenum(method = "default")`.
- Combining groups: Cochrane Handbook Table 6.5.a.
- Change-score SD: √(s_b² + s_f² − 2r·s_b·s_f) (§6.5.2.8).
- OR ↔ SMD: Chinn (2000), factor √3/π.

## Models (`metakit/models.py`)

Weights *w*ᵢ = 1/(*v*ᵢ + τ²); β̂ = (XᵀWX)⁻¹XᵀWy; Var(β̂) = (XᵀWX)⁻¹.

τ² estimators:
- **DerSimonian-Laird**: τ² = max{0, [Q − (k−p)]/tr(P)} with fixed-effect weights.
- **Hedges (HE)**: from OLS residuals.
- **Paule-Mandel**: solves Q_gen(τ²) = k − p.
- **REML / ML**: Fisher scoring with step halving, started at HE; REML update
  Δ = [yᵀPPy − tr(P)] / tr(PP).

REML is the default (Veroniki et al., 2016; Langan et al., 2019).

**Knapp-Hartung** (default): Var(β̂) is multiplied by s² = Σwᵢ(yᵢ − xᵢβ̂)²/(k − p), and tests use
t (or F) with k − p df (Knapp & Hartung, 2003; IntHout et al., 2014).

**Heterogeneity**: Q = Σ(1/vᵢ)(yᵢ − xᵢβ̂_FE)²; I² = 100·τ²/(τ² + ṽ), with typical within-study
variance ṽ = (k − p)/tr(P) (Higgins & Thompson, 2002); H² = (τ² + ṽ)/ṽ. The CI for τ² uses the
Q-profile method (Viechtbauer, 2007), and I² and H² CIs follow from it.

**Prediction interval**: β̂ ± t·√(Var(β̂) + τ²) (Riley et al., 2011; with z when test = "z", as in metafor).

**Meta-regression / subgroups**: the same model with moderators in X; omnibus test
Q_M = β̂ᵀV⁻¹β̂ (χ², or F under Knapp-Hartung). R² = (τ²₀ − τ²)/τ²₀ (Raudenbush, 2009).
Subgroup differences are tested by a categorical moderator with common τ².

## Small-study effects (`metakit/bias.py`)

- **Egger's test**: default is metafor's version (meta-regression on √vᵢ using the fitted
  model's estimator); `egger_model: lm` gives the classic weighted regression (Egger et al., 1997).
- **Begg's test**: Kendall's τ between standardized deviates and variances (Begg & Mazumdar, 1994).
- **Trim-and-fill**: Duval & Tweedie (2000), L0 estimator by default, side chosen by the sign
  of the Egger slope, as in `metafor::trimfill`.

All are flagged as unreliable below 10 studies (Sterne et al., 2011).

## Sensitivity (`metakit/sensitivity.py`, `analysis.py`)

Leave-one-out; cumulative by year; pre-specified exclusion of high risk-of-bias studies and of
studies with estimated means/SDs; DerSimonian-Laird and fixed-effect comparisons.

## GRADE (`metakit/grade.py`)

Start: high (randomized) or low (observational). Suggested downgrades:
risk of bias (more than 50% of weight from high-risk studies), inconsistency (I² ≥ 50%;
−2 when I² ≥ 90% and the prediction interval crosses no effect), imprecision (CI crosses no
effect; fewer than 300 events or 400 participants, the GRADE optimal-information-size rule of
thumb), publication bias (Egger p < 0.10 with k ≥ 10). Indirectness is set by reviewers.

## Validation

All estimators are tested against metafor 4.4-0 (reference values: `r/make_reference.R`).
metafor's default convergence threshold is 1e-5; at matched thresholds the two agree to
floating-point precision (`metakit crosscheck`).

## References

- Begg CB, Mazumdar M. *Biometrics* 1994;50:1088-101.
- Chinn S. *Stat Med* 2000;19:3127-31.
- Colditz GA, et al. *JAMA* 1994;271:698-702.
- Duval S, Tweedie R. *Biometrics* 2000;56:455-63.
- Egger M, et al. *BMJ* 1997;315:629-34.
- Guyatt GH, et al. GRADE. *BMJ* 2008;336:924-6.
- Higgins JPT, Thompson SG. *Stat Med* 2002;21:1539-58.
- Higgins JPT, et al. (eds). *Cochrane Handbook for Systematic Reviews of Interventions*, version 6.
- IntHout J, Ioannidis JPA, Borm GF. *BMC Med Res Methodol* 2014;14:25.
- Knapp G, Hartung J. *Stat Med* 2003;22:2693-710.
- Langan D, et al. *Res Synth Methods* 2019;10:83-98.
- Luo D, et al. *Stat Methods Med Res* 2018;27:1785-805.
- Normand SLT. *Stat Med* 1999;18:321-59.
- Page MJ, et al. PRISMA 2020. *BMJ* 2021;372:n71.
- Riley RD, Higgins JPT, Deeks JJ. *BMJ* 2011;342:d549.
- Shi J, et al. *Res Synth Methods* 2020;11:641-54.
- Sterne JAC, et al. *BMJ* 2011;343:d4002. (funnel plot asymmetry)
- Sterne JAC, et al. RoB 2. *BMJ* 2019;366:l4898.
- Sterne JAC, et al. ROBINS-I. *BMJ* 2016;355:i4919.
- Veroniki AA, et al. *Res Synth Methods* 2016;7:55-79.
- Viechtbauer W. *Stat Med* 2007;26:37-52.
- Viechtbauer W. metafor. *J Stat Softw* 2010;36(3):1-48.
- Wan X, et al. *BMC Med Res Methodol* 2014;14:135.
