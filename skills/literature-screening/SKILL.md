---
name: literature-screening
description: Run a PubMed search strategy, merge and deduplicate records from other databases, and screen titles/abstracts and full texts with two independent reviewers (AI and/or human), reporting agreement, Cohen's kappa, conflicts and PRISMA counts. Use after a search strategy exists and before data extraction in a systematic review.
argument-hint: "[project folder]"
allowed-tools: Bash(${CLAUDE_PLUGIN_ROOT}/bin/metakit *)
---

# Literature screening

## Overview

Connects the search (for example, the **pubmed-search-builder** skill's `final_strategy.md`) to
data extraction. Every record is screened by two reviewers independently, per Cochrane
Handbook §4.6. At title/abstract stage a record advances if either reviewer includes it or
answers "maybe" (the liberal-acceptance rule). At full-text stage every disagreement needs a
decision. Counts flow straight into `prisma.json`.

## When to Use

- The user has a final PubMed strategy (or RIS exports from other databases) and needs the
  included-studies list for a meta-analysis.
- Not for building the strategy (use `pubmed-search-builder`) or extracting data (use `meta-analysis`).

## Key Capabilities

| Step | Command |
|---|---|
| Run the strategy, log it for PRISMA-S, merge other databases, deduplicate | `metakit search --strategy final_strategy.md --ris Embase=embase.ris -p <project> --email <email>` |
| AI screener (resumable, batches of 20) | `metakit screen --reviewer A -p <project>` (stage `--stage full_text` later) |
| Reconcile, kappa, conflicts, PRISMA | `metakit screen-reconcile -p <project> [--stage full_text]` |

Files: `search/search_log.json` (date, count, strategy SHA-256), `screening/records.json`,
`screening/decisions_<stage>_<A|B>.jsonl`, `screening/resolutions_<stage>.json`,
`screening/screening_report.md`, `prisma.json`, and finally `included.csv`.

## Usage Examples

1. Check `protocol.yaml` has `eligibility.include` and `eligibility.exclude`. Criteria must be
   judgeable from a title and abstract; if not, rewrite them with the user.
2. `metakit search --strategy final_strategy.md -p <project> --email <user email>`.
3. Dual screening, two options:
   - **Two AI reviewers**: launch two `screener` subagents in parallel (reviewer A and B, blind to
     each other), or run `metakit screen --reviewer A` and `--reviewer B` with an API key.
   - **AI + human**: AI as A; the user screens as B by writing JSON lines
     `{"id": "PMID:123", "decision": "include|exclude|maybe", "criterion": "...", "reason": "..."}`.
     This is the stronger design for a publishable review.
4. `metakit screen-reconcile -p <project>`. Report agreement and kappa (0.61-0.80 substantial,
   above 0.80 almost perfect). A kappa below 0.6 means the criteria are ambiguous: fix them and re-screen.
5. Get full texts for the advanced records (`metakit ingest` + `metakit retrieve`), then
   screen at `--stage full_text`. **Show the user every full-text conflict** and record each
   decision in `screening/resolutions_full_text.json`, then reconcile again. It writes
   `included.csv` and final PRISMA counts, and the `meta-analysis` skill takes over from `metakit ingest included.csv`.

## Rules

- Screeners never see each other's decisions.
- Full-text exclusions need a stated criterion; they become the PRISMA exclusion reasons.
- Never silently resolve a full-text conflict; a human decides.
