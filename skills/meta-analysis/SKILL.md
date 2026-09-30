---
name: meta-analysis
description: Run a complete, auditable meta-analysis from a systematic review's included studies, including protocol, full-text retrieval, dual blind data extraction with quote-level provenance, risk of bias, metafor-validated pooling, heterogeneity, publication bias, sensitivity and subgroup analyses, GRADE, and a manuscript-ready report. Use when the user wants to meta-analyze, pool, or quantitatively synthesize results from multiple studies, or turn a systematic review into a meta-analysis.
argument-hint: "[project folder or research question]"
allowed-tools: Bash(${CLAUDE_PLUGIN_ROOT}/bin/metakit *)
---

# Meta-analysis with metakit

## Overview

Stage 4 of the evidence-synthesis library: from an included-studies list to a validated,
GRADE-rated meta-analysis. Extraction is dual and blind (the `extractor` agent, twice), every
number is provenance-checked against the paper, and all statistics are computed by metakit
(validated against R's metafor).

## When to Use

The user has included studies (from the `literature-screening` skill, Ram's systematic review
agent, a CSV/RIS, or PMIDs) and wants them pooled. For the protocol, use `review-team`; for the
search, `pubmed-search-builder`; for the whole pipeline, `systematic-review`.

## Key Capabilities and Usage Examples

The steps below are the capabilities, in order. The benchmark (`metakit benchmark`) is the
worked example: it reproduces Colditz et al. (*JAMA* 1994) end to end.

You are running a meta-analysis that a professor will scrutinize. The division of labour is
strict and is the whole point of this tool:

- **You** read papers, find numbers, and write them down *with the exact quote they came from*.
- **metakit** (deterministic Python, validated against R's metafor) does every calculation.
- **The human** makes the judgement calls: the protocol, disputed extractions, risk of bias, GRADE.

Never compute an effect size, pooled estimate, CI, or p-value yourself, and never type a
number into the report. If a number is not in the paper, it is not reported; say so.

The CLI is `${CLAUDE_PLUGIN_ROOT}/bin/metakit`. Call it `metakit` below. The first run sets
up a Python environment (about a minute).

## Step 0: Orient

If `$ARGUMENTS` names an existing folder with `protocol.yaml`, resume: run
`metakit validate -p <folder>` and pick up at the first incomplete step. Otherwise start at Step 1.

## Step 1: Protocol (human checkpoint)

1. `metakit init <project>` creates the folder and a commented `protocol.yaml`.
2. Fill the protocol **with the user**: question (PICO), study designs, and for each outcome
   its `data_type`, `measure`, and `unit`. Use `${CLAUDE_SKILL_DIR}/references/choosing-effect-measure.md` to
   recommend a measure and explain why in one or two sentences.
3. Defaults to keep unless the user has a reason: `method: REML`, `test: knha`. Only list
   subgroups and meta-regression moderators the user can justify *in advance*; post-hoc
   subgroup hunting is how meta-analyses mislead.
4. **Stop and get the user's explicit approval of the protocol before any extraction.**
   After approval, changes to outcomes or measures must be recorded as protocol deviations in
   the report.

## Step 2: Studies and full texts

1. Get the included-studies list from the systematic review (Ram's agent output, a CSV, RIS,
   JSON, or a list of PMIDs/DOIs): `metakit ingest <file> -p <project>`.
2. `metakit retrieve -p <project> --email <user's email>` downloads open-access full texts
   (tables included) into `fulltext/`.
3. Tell the user exactly which studies are `needs_pdf`. They save each PDF as
   `fulltext/<key>.pdf` (through their library access, never a piracy site), then re-run
   `metakit retrieve`, which converts PDFs to text deterministically.
4. Fill in `prisma.json` from the systematic review's screening counts; ask the user for
   numbers you do not have. Never guess them.

## Step 3: Dual blind extraction

Cochrane requires two independent extractors, so run two.

1. For each study, launch **two `extractor` subagents in parallel**, one writing to
   `extraction/`, the other to `extraction_b/`. Give each only: the study's `fulltext` path,
   the `protocol.yaml` path, its output folder, and the study_id. Neither sees the other's work.
   Batch several studies per message to run them in parallel.
2. `metakit validate -p <project>` and `metakit validate -p <project> --extraction extraction_b`.
   Send every error back to the responsible extractor to fix *by re-reading the source*.
3. `metakit reconcile <project>/extraction <project>/extraction_b --out <project>/analysis/reconciliation.md`.
4. Resolve each discrepancy by opening the source text yourself and deciding which value
   the paper supports. Fix `extraction/`. If the paper is genuinely ambiguous (for example,
   two tables disagree), **ask the user** and record the decision in that study's `notes`.
5. Report the agreement rate to the user. It is a quality metric worth quoting.

Read `${CLAUDE_SKILL_DIR}/references/extraction-guide.md` before your first reconciliation: it covers the tricky
cases (SE vs SD, which time point, intention-to-treat vs per-protocol, multi-arm trials).

## Step 4: Risk of bias (human checkpoint)

1. Set `risk_of_bias_tool` in the protocol (RoB2 for RCTs, ROBINS-I for non-randomised
   intervention studies, NOS for cohort/case-control, QUIPS for prognostic factors).
2. Have an `extractor` subagent draft `rob/<key>.json` per study following
   `${CLAUDE_SKILL_DIR}/references/risk-of-bias.md`, with a supporting quote for every domain.
3. **Show the user a table of the draft judgements and have them confirm or change each one.**
   Risk of bias is a judgement; the agent drafts, the human decides.

## Step 5: Analyse

1. `metakit run -p <project>`: validates, analyses every outcome, draws all figures, writes
   `report/report.md`, and (if R is installed) re-runs everything in metafor as an
   independent cross-check.
2. If validation fails, fix the extraction; do not use `--force` without the user's consent.
3. Read `analysis/results.json` and every warning. Explain the findings using
   `${CLAUDE_SKILL_DIR}/references/interpreting-results.md`: the pooled effect *in plain units*, what I² and the
   prediction interval mean for a new setting, whether sensitivity analyses change the story,
   and small-study effects (only if k is 10 or more).

## Step 6: GRADE and report (human checkpoint)

1. The report's Summary-of-Findings table is marked "suggested". Walk the user through each
   downgrade and its reason; indirectness always needs their judgement (set
   `grade.indirectness` in the protocol and re-run).
2. Edit prose in `report/report.md` freely. **Never edit numbers by hand**: change the input
   and re-run `metakit analyze` and `metakit report`.
3. Deliver: `report/report.md`, the figures in `analysis/`, `analysis/results.json`, and the
   reconciliation and validation logs (these *are* the audit trail).

## Ground rules

- Every number has a quote, and every quote is from the text file metakit verifies against.
- Something unclear gets asked about, never guessed. Something missing gets reported as missing.
- Keep full texts out of git (`metakit init` writes a `.gitignore` for this): they are copyrighted.
- With fewer than 10 studies, do not interpret funnel plots or Egger's test as evidence
  either way. With fewer than 5, be explicit that the tau² estimate is imprecise.
- Explain every statistic you mention in one plain-English clause. The user must be able to
  defend this analysis to a professor without you in the room.
