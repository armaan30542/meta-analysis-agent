# metakit: an evidence-synthesis skill library for AI agents

From a research question to a GRADE-rated meta-analysis, with AI agents doing the reading and
**deterministic, validated code doing every calculation**. Organised like
[LabClaw](https://github.com/wu-yc/LabClaw): a library of standalone `SKILL.md` skills, one per
stage of a systematic review, that you can install together or cherry-pick.

The rule the whole library is built on: **an AI can read papers, but it must not be trusted
with numbers it cannot prove it read.** Every extracted value carries its exact source quote,
and metakit verifies the quote is in the paper and the number is in the quote. Statistics are
computed by a Python engine that reproduces R's [metafor](https://www.metafor-project.org) to
machine precision.

## Skill library

| Stage | Skill | What it does | Built on |
|---|---|---|---|
| 0 | [`systematic-review`](skills/systematic-review/SKILL.md) | Orchestrates stages 1-5 in one project | |
| 1, 5 | [`review-team`](skills/review-team/SKILL.md) | A virtual panel (PI, domain expert, information specialist, biostatistician, Scientific Critic) drafts the protocol and the Discussion | [Virtual Lab](https://github.com/zou-group/virtual-lab) (Zou lab, *Nature* 2025) |
| 2 | [`pubmed-search-builder`](skills/pubmed-search-builder/SKILL.md) | High-sensitivity PubMed strategies: MeSH, seed-PMID validation, PRESS, PRISMA-S audit | [pubmed-search-builder](https://github.com/aarontaycheehsien/pubmed-search-builder) by Aaron Tay (vendored unmodified) |
| 3 | [`literature-screening`](skills/literature-screening/SKILL.md) | Runs the strategy, deduplicates across databases, dual screening with kappa and PRISMA counts | |
| 4 | [`meta-analysis`](skills/meta-analysis/SKILL.md) | Full-text retrieval, dual blind extraction with provenance checks, risk of bias, metafor-validated statistics, GRADE, report | |

Agents: [`extractor`](agents/extractor.md) and [`screener`](agents/screener.md), each run twice,
blind, for dual independent review.

| | |
|---|---|
| Reproduces a published meta-analysis | BCG vaccine (Colditz et al., *JAMA* 1994): published RR **0.49 (0.34 to 0.70)**, metakit **0.49 (0.34 to 0.70)** |
| Agreement with metafor 4.4 | identical to 1e-16 at matched convergence settings (`metakit crosscheck`) |
| Tests | 104 automated tests, including planted extraction errors, invented numbers in agent-written text, and full browser runs of the web app |

## Pipeline

```
question ─► review-team: protocol meeting ──────────────► protocol.yaml          (you approve)
         ─► pubmed-search-builder ──────────────────────► final_strategy.md      (concept gate, PRESS)
         ─► metakit search (+ other databases as RIS) ──► records, deduplicated  (PRISMA-S log)
         ─► screener ×2 → metakit screen-reconcile ─────► included.csv, PRISMA   (you resolve conflicts)
         ─► extractor ×2 → validate → reconcile ────────► extraction/            (you resolve conflicts)
         ─► risk of bias ───────────────────────────────► rob/                   (you confirm)
         ─► metakit run ────────────────────────────────► results, figures, report, R cross-check
         ─► review-team: interpretation meeting ────────► discussion draft       (numbers checked)
```

## How the meta-analysis stage works

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
./scripts/set-owner.sh armaan30542   # fills in the GitHub owner everywhere
git remote add origin https://github.com/armaan30542/meta-analysis-agent.git
git push -u origin main
```

Then on GitHub: **Settings → Pages → Deploy from a branch → `main` / `docs`** publishes the
project site, and the **Actions** tab shows the test suite and the R cross-check running on
every push.

## Web app

**https://armaan30542.github.io/meta-analysis-agent/app/**, no installation.

- **Enter numbers** from papers in a spreadsheet-style table (paste straight from Excel), or
- **extract with AI**: add papers by PubMed/PMC ID (open access, fetched from Europe PMC),
  PDF (text read by pdf.js, not the AI) or pasted text, then Claude extracts every number
  with its source sentence. Each read is validated instantly; failures go back to Claude with
  the validator's errors, and dual extraction lists every A/B disagreement for you to decide.
- Risk of bias (RoB 2, ROBINS-I, QUIPS), then the full analysis, figures and report, with a
  one-click zip of everything.

The statistics run **in your browser** via [Pyodide](https://pyodide.org): the exact metakit
Python package, not a rewrite, so the web app and the command line give identical answers.
AI extraction uses your own Anthropic API key, sent only to Anthropic from your browser.
Projects save in the browser and can be downloaded as a file to share. After changing
anything in `metakit/`, run `python scripts/build_web.py` (CI checks the bundle is current).

## Install

### As a Claude Code plugin (recommended)

```bash
claude plugin marketplace add armaan30542/meta-analysis-agent
claude plugin install metakit@metakit
```

Then in any Claude Code session: `/metakit:meta-analysis` (or just ask Claude to run a
meta-analysis). Replace `armaan30542` with the account that hosts this repo.

### With Codex or another agent

Clone the repo and point the agent at [AGENTS.md](AGENTS.md).

### As a plain command-line tool

```bash
git clone https://github.com/armaan30542/meta-analysis-agent
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

- `pytest` (104 tests; browser tests opt-in with `METAKIT_BROWSER_TESTS=1`) checks every estimator against reference values generated by
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

## Credits

This library builds directly on three open-source projects, all MIT-licensed:

- **LabClaw** (Wu, Jian, Zhao; Le Cong Lab, Stanford and Mengdi Wang Lab, Princeton),
  https://github.com/wu-yc/LabClaw: the modular skill-library structure and the
  Overview / When to Use / Key Capabilities / Usage Examples skill format.
- **Virtual Lab** (Swanson, Wu, Bulaong et al., *Nature* 2025, doi:10.1038/s41586-025-09442-9),
  https://github.com/zou-group/virtual-lab: the agent persona, the team and individual meeting
  protocols and the Scientific Critic, ported to Claude in `metakit/team.py` with prompts kept close
  to the originals.
- **pubmed-search-builder** (Aaron Tay), https://github.com/aarontaycheehsien/pubmed-search-builder:
  included unmodified as the search stage (`skills/pubmed-search-builder`, upstream commit in `UPSTREAM.md`).

If you use the review team, please also cite the Virtual Lab paper.

## Authors

Armaan Punjani and Ramcharan Nagisetty, with mentorship from Dr. Sam Montalvo (Stanford).

## License

MIT. Full texts of papers are copyrighted and must never be committed; `metakit init`
writes a `.gitignore` that excludes them.
