# metakit: auditable, AI-driven meta-analysis

metakit turns the included studies from a systematic review into a finished meta-analysis
(pooled estimates, heterogeneity, sensitivity and subgroup analyses, publication-bias
checks, GRADE, figures, and a manuscript-ready report) with an AI agent doing the reading
and **deterministic, validated code doing every calculation**.

It is built around one idea: **an AI can read papers, but it must not be trusted with
numbers it cannot prove it read.** Every extracted value carries the exact quote it came
from, and metakit verifies that the quote is really in the paper and that the number is
really in the quote. Statistics are computed by a Python engine that reproduces R's
[metafor](https://www.metafor-project.org) (the reference implementation in the field) to
machine precision.

| | |
|---|---|
| Reproduces a published meta-analysis | BCG vaccine (Colditz et al., *JAMA* 1994): published RR **0.49 (0.34 to 0.70)**, metakit **0.49 (0.34 to 0.70)** |
| Agreement with metafor 4.4 | identical to 1e-16 at matched convergence settings (`metakit crosscheck`) |
| Tests | 87 automated tests, including planted extraction errors the validator must catch |
| Extraction | dual blind extraction by two agents, field-by-field reconciliation |

## How it works

```
 systematic review          metakit                                   you
 (included studies)
        │
        ▼
   1. protocol ─────────── outcomes, effect measures, model ────────── approve
   2. ingest + retrieve ── PubMed / Europe PMC full texts, PDFs → text
   3. extract ×2 ────────── two blind AI extractors, every number quoted
   4. validate ─────────── number in quote? quote in paper? plausible?
   5. reconcile ────────── A vs B, field by field ───────────────────── resolve
   6. risk of bias ─────── RoB 2 / ROBINS-I / NOS / QUIPS drafts ─────── confirm
   7. analyze ──────────── REML + Knapp-Hartung, I², τ², prediction
                           interval, subgroups, meta-regression,
                           leave-one-out, Egger, trim-and-fill
   8. report ───────────── methods + results prose, forest/funnel
                           plots, PRISMA, GRADE ────────────────────── sign off
   9. crosscheck ───────── independent re-run in R/metafor
```

The plain-language walkthrough is in [docs/how-it-works.md](docs/how-it-works.md); the
statistics with references are in [docs/methods.md](docs/methods.md).

## Publish this repo (first time only)

```bash
./scripts/set-owner.sh YOUR-GITHUB-USERNAME   # fills in the GitHub owner everywhere
git remote add origin https://github.com/YOUR-GITHUB-USERNAME/meta-analysis-agent.git
git push -u origin main
```

Then on GitHub: **Settings → Pages → Deploy from a branch → `main` / `docs`** publishes the
project site, and the **Actions** tab shows the test suite and the R cross-check running on
every push.

## Install

### As a Claude Code plugin (recommended)

```bash
claude plugin marketplace add YOUR-GITHUB-USERNAME/meta-analysis-agent
claude plugin install metakit@metakit
```

Then in any Claude Code session: `/metakit:meta-analysis` (or just ask Claude to run a
meta-analysis). Replace `YOUR-GITHUB-USERNAME` with the account that hosts this repo.

### With Codex or another agent

Clone the repo and point the agent at [AGENTS.md](AGENTS.md).

### As a plain command-line tool

```bash
git clone https://github.com/YOUR-GITHUB-USERNAME/meta-analysis-agent
cd meta-analysis-agent
./bin/metakit --version        # first run creates a private Python environment
./bin/metakit benchmark        # reproduce the published benchmarks
```

Requirements: Python 3.10+. Optional: R with the `metafor` and `jsonlite` packages for the
independent cross-check.

## Quick start (command line)

```bash
metakit init my-review                     # scaffold; edit my-review/protocol.yaml
metakit ingest included.csv -p my-review   # from the systematic review (CSV, RIS, JSON, PMIDs)
metakit retrieve -p my-review --email you@school.edu
# ... extraction files go in my-review/extraction/ (the agent writes these) ...
metakit run -p my-review                   # validate → analyze → report → crosscheck
```

Output: `analysis/results.json` (every number), `analysis/<outcome>/*.png` (figures),
`report/report.md` (draft methods, results, summary of findings, study-level appendix).

## What is in the box

| Area | Details |
|---|---|
| Effect measures | risk ratio, odds ratio, risk difference, mean difference, Hedges' g, ratio of means, single-group means, proportions (raw/logit), correlations (Fisher z), pre-computed effects from a CI |
| Messy data | SD from SE or CI (t-based for small groups), mean/SD from median + IQR/range (Luo 2018, Wan 2014, Shi 2020), merging subgroups, change-score SDs, unit conversion (including ECG mm → mV) |
| Models | fixed effect; random effects with REML, DerSimonian-Laird, Paule-Mandel, ML, Hedges; Knapp-Hartung; prediction intervals; Q-profile CIs for τ² and I² |
| Heterogeneity | subgroup analysis with a test for differences, meta-regression with R² |
| Robustness | leave-one-out, cumulative meta-analysis, pre-specified exclusions (high risk of bias, estimated SDs), estimator comparison |
| Small-study effects | Egger's test, Begg's test, trim-and-fill, funnel plots, with warnings below 10 studies |
| Quality | RoB 2, ROBINS-I, QUIPS, Newcastle-Ottawa; GRADE suggestions with a reason for every downgrade |
| Provenance | quote-level verification against full text; SE-as-SD detection; duplicate detection; dual-extraction agreement |

## Validation

- `pytest` (87 tests) checks every estimator against reference values generated by
  `r/make_reference.R` from metafor 4.4, across four published datasets (plus synthetic edge cases).
- `metakit benchmark` reproduces two published meta-analyses end to end, from extraction
  files to report.
- `metakit crosscheck` re-runs any project's analysis in R/metafor and fails loudly on any
  disagreement.
- `metakit benchmark --gold G --candidate C` scores an agent's extraction against a gold
  standard; this is the extraction-accuracy metric.

## Limitations

- Extraction quality depends on the full text available; scanned PDFs need OCR first.
- Network meta-analysis, dose-response models, individual-participant data, and multilevel
  models for dependent effect sizes are out of scope (use metafor directly).
- GRADE output is a documented starting point for reviewers, not a rating.

## Authors

Armaan Punjani and Ramcharan Nagisetty, with mentorship from Dr. Sam Montalvo (Stanford).

## License

MIT. Full texts of papers are copyrighted and must never be committed; `metakit init`
writes a `.gitignore` that excludes them.
