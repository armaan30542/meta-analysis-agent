---
name: review-team
description: Convene a virtual review team of AI agents (Principal Investigator, domain expert, Information Specialist, Biostatistician, Scientific Critic) using the Virtual Lab meeting protocol, either to draft a meta-analysis protocol or to interpret finished results. Use when the user wants expert-panel style input on designing or interpreting a systematic review or meta-analysis.
argument-hint: "protocol \"<review question>\" | interpret"
allowed-tools: Bash(${CLAUDE_PLUGIN_ROOT}/bin/metakit *)
---

# Review team

## Overview

A panel of Claude agents holds structured meetings about the review, following the protocol of
the **Virtual Lab** (Swanson et al., *Nature* 2025; github.com/zou-group/virtual-lab, MIT).
In a **team meeting** the Principal Investigator opens, each member speaks in turn, the PI
synthesizes, and after the set number of rounds the PI writes a structured summary
(Agenda, Team Member Input, Recommendation, Answers, Next Steps). In an **individual meeting** one
agent answers and the Scientific Critic critiques, round after round.

Meetings are advisory. Their outputs are drafts that software checks and a human approves.

## When to Use

- **Before extraction**: to draft `protocol.yaml` (question, eligibility, outcomes, effect
  measures, pre-specified subgroups) for the user to review.
- **After analysis**: to draft the Discussion section from `analysis/results.json`.
- Not for extracting data or computing statistics; metakit and the extractor agents do that.

## Key Capabilities

| Command | What it does | Output (in `meetings/`) |
|---|---|---|
| `metakit meeting protocol --question "..." --field "<domain>" -p <project>` | Team: PI, domain expert, Information Specialist, Biostatistician, Scientific Critic | transcript `.md/.json`; `protocol.draft.yaml`, validated by metakit's protocol checker |
| `metakit meeting interpret --field "<domain>" -p <project>` | Team: PI, domain expert, Biostatistician, Scientific Critic | transcript; `discussion.draft.md` with **every number checked against results.json** |

Options: `--rounds N` (default 2). The API key comes from `ANTHROPIC_API_KEY`; the model from
`METAKIT_MODEL` (default `claude-opus-5-5`). The CLI is `${CLAUDE_PLUGIN_ROOT}/bin/metakit`.

## Usage Examples

1. Protocol: run `metakit meeting protocol --question "Do endurance athletes show greater
   ST-segment elevation than sedentary controls?" --field "sports cardiology" -p st-review`.
   Show the user the Recommendation section and the draft YAML, walk through every choice,
   and only after explicit approval copy it to `protocol.yaml`. If the command reports that the
   protocol did not validate, show the error and build `protocol.yaml` with the user by hand.
2. Interpretation: after `metakit run`, run `metakit meeting interpret --field "sports
   cardiology" -p st-review`. If it prints `WARNING: numbers not found in results.json`, those
   numbers were invented by an agent: delete or correct them before the draft is used anywhere.

## Rules

- A meeting never replaces the user's decision on the protocol, risk of bias, or GRADE.
- Never copy a number from a transcript into the report; numbers come from `results.json`.
- Tell the user the agents' views are simulated expertise, not real experts. Quote the
  Scientific Critic's objections even when the PI overrules them.
