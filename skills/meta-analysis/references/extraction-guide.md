# Extraction guide

The extraction format is defined in `agents/extractor.md`. This guide covers the judgement
calls, which cause most real disagreements between extractors.

## What the validator checks (so you know what it cannot)

| Check | Catches |
|---|---|
| Number appears exactly in its quote | Typos, rounding, recalculation, invented numbers |
| Quote appears in the full-text file (fuzzy, tolerant of PDF line breaks) | Invented or paraphrased quotes |
| Number appears in the *paper's* version of an approximately matched quote | A real sentence with one digit changed (a 98.9%-similar fake) |
| Plausibility (events <= n, mean inside CI, quartiles ordered, SD > 0) | Swapped fields, misread tables |
| SD and SE consistency; cross-study SD outliers | SE reported as SD (the most common error in published meta-analyses) |
| Duplicate study IDs, PMIDs, DOIs | Double counting of the same participants |

It **cannot** tell you whether you picked the *right* number: the right time point, arm,
analysis population or subgroup. That is what dual extraction and reconciliation are for.

## Tricky cases

**SE vs SD.** Tables often say "mean ± SE" in a footnote. Check the table footnote and the
statistical methods every time. If unlabelled, "±" values that look too small for the spread
of the data (for example, SD 0.4 for ages 20-60) are probably SEs: flag in `notes`.

**Which time point.** Use the one the protocol pre-specifies. If it says "longest follow-up",
take the longest. If a study only reports other time points, extract the closest and flag it.

**Which population.** Prefer intention-to-treat. Group sizes are the numbers analysed for that
outcome. For binary outcomes with missing data, do not impute; flag it.

**Multi-arm trials.** Two exercise arms vs one control? Do not enter the control twice
(double counting). Options, decided by the human: merge the arms (`metakit convert combine`),
pick the arm that best fits the protocol, or split the control group's n between comparisons.
Extract every arm; the decision goes in `notes`.

**Cluster or crossover trials.** Flag for the human; they need design-effect adjustment
before pooling.

**Same cohort in several papers.** Include each cohort once, usually from the largest or most
complete report. The duplicate PMID/DOI check helps; also watch for the same author group,
setting and years.

**Only a figure.** Do not read values off a plot unless the protocol allows it. If it does,
mark `derived` with "read from Figure 2 with WebPlotDigitizer" and flag it for a sensitivity analysis.

**Percentages only.** "13.3% of 60 athletes": derive 8 with `derived: true` and the
arithmetic. If the percentage cannot produce a whole number (13.3% of 61 = 8.1), flag it.

**Medians.** Record median with IQR and/or range as reported. metakit estimates mean/SD
(Luo 2018, Wan 2014, Shi 2020) and flags strong skew; the protocol's
`exclude_estimated_sds` sensitivity analysis checks whether these studies change the answer.

**Change scores vs final values.** Record whichever the paper reports and note which in
`notes`. MD analyses may mix them (Cochrane 10.5.2); SMD analyses must not.

## Resolving a reconciliation discrepancy

1. Open the source at the location both extractors cite.
2. Decide which value the paper supports; if both are defensible (for example, a table and the
   text disagree), prefer the table, record why, and flag it for the user.
3. Fix `extraction/` (the final set), re-run `metakit validate`, and note the resolution in the
   reconciliation table. The resolved table is part of the audit trail.
