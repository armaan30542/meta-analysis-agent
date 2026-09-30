# Risk of bias

Risk of bias asks: could flaws in how a study was run push its result away from the truth?
It is judged per study (for the outcomes analysed), with a quote supporting every domain.
The agent drafts; **the human confirms every judgement**.

## Which tool

| Studies | Tool | Judgements |
|---|---|---|
| Randomised trials | **RoB 2** (Sterne 2019) | low / some concerns / high |
| Non-randomised studies of interventions or exposures | **ROBINS-I** (Sterne 2016) | low / moderate / serious / critical |
| Cohort or case-control studies (common in sports cardiology) | **Newcastle-Ottawa Scale** | stars: selection 0-4, comparability 0-2, outcome 0-3 |
| Prognostic factor studies | **QUIPS** (Hayden 2013) | low / moderate / high |

## RoB 2 domains and the questions that decide them

- **D1 Randomisation**: was the sequence random *and concealed* until assignment? Were
  baseline groups similar?
- **D2 Deviations from intended interventions**: were participants and staff aware of
  assignment, and did that change what happened? Was the analysis appropriate (ITT)?
- **D3 Missing outcome data**: are outcomes available for nearly all participants, and could
  missingness depend on the true outcome?
- **D4 Outcome measurement**: could assessors' knowledge of assignment influence the measured
  outcome? (An ECG read by a blinded cardiologist is low; a self-reported symptom in an open
  trial is not.)
- **D5 Selective reporting**: is there a pre-registered protocol, and does the reported
  analysis match it?

Overall: low only if every domain is low; high if any domain is high (or several have some concerns).

## ROBINS-I domains

D1 confounding, D2 selection of participants, D3 classification of interventions,
D4 deviations from intended interventions, D5 missing data, D6 outcome measurement,
D7 selective reporting. Overall is at least the worst domain. In observational athlete
studies, D1 (confounding: age, sex, ethnicity, body size, training volume) is usually the decider.

## Newcastle-Ottawa

Selection (representativeness, selection of controls, ascertainment of exposure, outcome absent
at start), comparability (controls for the most important factor, plus any additional factor),
outcome (assessment, follow-up long enough, adequacy of follow-up). metakit converts stars to
good/fair/poor using the AHRQ thresholds, and "poor" counts as high risk.

## How metakit uses the judgements

- The traffic-light figure (`analysis/rob.png`).
- The sensitivity analysis excluding high-risk studies (`exclude_high_risk_of_bias`).
- GRADE's risk-of-bias domain: downgraded when more than 50% of the analysis weight comes from
  high-risk studies (a transparent rule of thumb the reviewers can override).
