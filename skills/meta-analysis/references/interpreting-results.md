# Interpreting and explaining the results

Every statistic gets one plain-English clause when you mention it. Worked numbers below are
from the BCG vaccine benchmark (`metakit benchmark bcg`).

## The pooled estimate

"Across 13 trials, vaccinated people had about half the risk of TB: RR 0.49 (95% CI 0.34 to 0.70)."
The CI is the uncertainty about the *average* effect. Translate ratios into absolute terms
when you can: a 51% relative reduction means very different things at 1% vs 10% baseline risk.

## Random effects, not fixed effect

A random-effects model assumes each study estimates a slightly different true effect
(different populations, doses, settings) and estimates the *average* of those. That is
almost always more realistic than assuming one identical effect everywhere. REML estimates
how much true effects vary; Knapp-Hartung widens the CI to reflect that tau² is itself
uncertain, which matters most with few studies.

## Heterogeneity: three different numbers

- **Q test**: is there more variation than chance alone? It has low power with few studies
  and is almost always significant with many; do not lean on its p-value.
- **I²**: the share of observed variation that is real differences rather than chance. BCG:
  92%. It is not an absolute amount; with large studies even small real differences give high I².
- **tau²**: the actual variance of true effects, on the analysis scale. It is the number that
  tells you how much effects differ.
- **Prediction interval**: the most useful one for readers. "In a new setting, the true RR
  would likely lie between 0.15 and 1.55." BCG: the average effect is clearly protective, but
  in some settings the vaccine may do little. A CI that excludes no effect together with a
  prediction interval that includes it is a common and important pattern: say so.

## Sensitivity analyses

The question is always "does the conclusion change?", not "does the number change a bit?"
Report it as, for BCG: "Omitting one trial at a time gave risk ratios between 0.45 and 0.53,
and no single trial changed the conclusion." If a single study's removal flips significance,
the result is fragile: say so plainly.

## Subgroups and meta-regression

- The test for subgroup *differences* is what matters, not whether each subgroup is
  separately significant. "Significant in A but not B" is not evidence of a difference.
- With fewer than about 10 studies per moderator, meta-regression is exploratory.
- These are observational comparisons *across* studies, even when every study is an RCT.
  BCG: latitude explains about 76% of the heterogeneity (a famous finding), but that is an
  association, not proof that latitude causes the difference.

## Small-study effects / publication bias

- Below 10 studies, say: "Too few studies to assess funnel plot asymmetry." Do not report
  Egger's p as evidence either way.
- Asymmetry has causes other than publication bias (smaller studies may differ in quality or
  population). Trim-and-fill is a "what if" sensitivity analysis, not a corrected answer.

## GRADE

Certainty is about how confident we are that the true effect is close to the estimate.
Explain each downgrade in one sentence. BCG is rated *low* despite being RCTs because
inconsistency is serious: I² 92% and a prediction interval that crosses no effect.

## What not to say

- "The effect is statistically significant, so the treatment works": say how big and how certain.
- "No heterogeneity (p > 0.05)": absence of evidence with low power.
- "Proves" or "confirms": meta-analyses estimate.
