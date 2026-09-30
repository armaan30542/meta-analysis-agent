---
name: systematic-review
description: Run a full systematic review and meta-analysis end to end, from a plain-language question through a review-team protocol, a high-sensitivity PubMed search, dual screening, dual extraction, meta-analysis and a GRADE-rated report. Use when the user wants the whole pipeline rather than one stage.
argument-hint: "\"<review question>\""
---

# Systematic review, end to end

## Overview

An orchestrator over five skills, organised as a LabClaw-style library (one skill per stage,
each usable on its own):

| Stage | Skill | Human checkpoint |
|---|---|---|
| 1. Protocol | `review-team` (Virtual Lab meeting) | approve `protocol.yaml` |
| 2. Search | `pubmed-search-builder` (Aaron Tay, vendored) | concept gate; PRESS review |
| 3. Screening | `literature-screening` | full-text conflicts |
| 4. Extraction and analysis | `meta-analysis` | extraction disagreements, risk of bias, GRADE |
| 5. Interpretation | `review-team` | approve the Discussion |

## When to Use

The user asks for a systematic review or meta-analysis "from scratch", or asks to go from a
question to results. If they already have included studies, start at `meta-analysis`.

## Key Capabilities

Everything each stage skill does, with artifacts passed between them in one project folder:
`protocol.yaml` → `final_strategy.md` → `screening/` → `included.csv` → `extraction/` →
`analysis/results.json` → `report/report.md` + `meetings/discussion.draft.md`.

## Usage Examples

1. `metakit init <project>`. Invoke **review-team** with the question and the domain; the
   user approves the protocol.
2. Invoke **pubmed-search-builder** with the same plain-language question; follow its gates
   (it asks for seed PMIDs and a concept decision) and save `final_strategy.md` in the project.
3. Invoke **literature-screening** with the strategy file.
4. Invoke **meta-analysis** with the project (it starts from `metakit ingest included.csv`).
5. Invoke **review-team** `interpret`, then deliver the report, the figures, the search audit,
   the screening report and the meeting transcripts together; these files are the audit trail.

Tell the user at the start which checkpoints need them, and never skip one to save time.
