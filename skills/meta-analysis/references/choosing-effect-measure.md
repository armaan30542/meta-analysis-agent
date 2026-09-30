# Choosing the effect measure

Pick the measure in the protocol, before looking at results. The outcome's data type narrows
the choice; the question decides within it.

## Binary outcomes (event / no event)

| Measure | Use when | Read it as |
|---|---|---|
| **RR** risk ratio | Default for trials and cohorts. | "Athletes had 0.6 times the risk." Easy for clinicians to read. |
| **OR** odds ratio | Case-control studies (the only valid measure there), or when studies report adjusted ORs from logistic regression. | Close to the RR only when events are rare (under about 10%). |
| **RD** risk difference | You want the absolute effect ("3 fewer events per 100"). | Usually more heterogeneous across studies than ratios; report alongside a ratio. |

Zero cells get 0.5 added automatically. Studies with zero events in *both* arms are excluded
from RR/OR (they carry no information about a ratio) and listed in the report.

## Continuous outcomes

| Measure | Use when |
|---|---|
| **MD** mean difference | Every study measured the outcome on the same scale, or one convertible to it (mV, mm at standard gain, ms, kg). Keeps real units: "0.07 mV higher". **Prefer this whenever possible.** |
| **SMD** Hedges' g | Studies used different instruments for the same construct (for example, different fatigue questionnaires). Unitless: 0.2 small, 0.5 medium, 0.8 large (Cohen's rough guide). |
| **ROM** ratio of means | Outcomes on a ratio scale where proportional change matters, such as biomarkers that vary a lot in baseline level. |

## Single-group data (no comparator)

**MN** pools means, for example "mean ST elevation in athletes" across studies without controls.
It describes a population rather than an effect, so there is no null line, and heterogeneity
is usually large because populations differ.

**PR / PLO** pool proportions ("prevalence of early repolarisation in athletes"). PLO (logit)
is preferred: it keeps confidence intervals inside 0-100% and behaves better near 0% or 100%.

## Correlations

**ZCOR** (Fisher's z) is the standard; results are back-transformed to r for display.

## Pre-computed effects

**GEN** handles adjusted estimates (for example, a hazard ratio from a Cox model) reported
with a CI or SE. Set `generic_scale: ratio` for HR/OR/RR (analysed on the log scale) or
`difference` for differences. Do not mix adjusted and unadjusted estimates in one analysis
without a sensitivity analysis.

## Worked example (the Montalvo call's example)

"Meta-analysis of ST-segment changes in athletes":

- Studies comparing athletes with controls, reporting ST amplitude in mV or mm:
  `data_type: continuous`, `measure: MD`, `unit: mV`. Papers in mm are converted (10 mm = 1 mV
  at standard calibration); record `"unit": "mm"` in those extractions.
- Studies reporting how many athletes had ST depression vs controls:
  `data_type: binary`, `measure: RR`.
- Athlete-only cohorts reporting prevalence: `data_type: proportion`, `measure: PLO`.

These are three outcomes in one protocol, not one analysis: never pool a prevalence with a
mean difference.
