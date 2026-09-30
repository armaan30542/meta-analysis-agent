"""A virtual review team: LLM agents that hold meetings about the review.

Adapted from the **Virtual Lab** (Swanson, Wu, Bulaong et al., "The Virtual Lab of AI agents
designs new SARS-CoV-2 nanobodies", *Nature* 2025; https://github.com/zou-group/virtual-lab,
MIT licence). The agent definition, the team-meeting and individual-meeting protocols, and the
Scientific Critic are kept close to the original prompts; the changes are:

* agents run on Claude through the Anthropic Messages API (standard library HTTP only);
* the team is an evidence-synthesis team (information specialist, biostatistician, ...);
* meetings are *advisory*: their outputs are drafts that metakit validates and a human
  approves. A protocol meeting's YAML is checked by ``normalize_protocol``; an interpretation
  meeting's text is checked so that every number it states exists in ``results.json``.

Transcripts are saved as Markdown and JSON next to the project, as in the original.
"""
from __future__ import annotations

import json
import os
import re
import time
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Sequence

DEFAULT_MODEL = os.environ.get("METAKIT_MODEL", "claude-opus-5-5")


@dataclass(frozen=True)
class Agent:
    """An LLM agent (same four-part persona as the Virtual Lab)."""

    title: str
    expertise: str
    goal: str
    role: str
    model: str = DEFAULT_MODEL

    @property
    def prompt(self) -> str:
        return (f"You are a {self.title}. Your expertise is in {self.expertise}. "
                f"Your goal is to {self.goal}. Your role is to {self.role}.")

    def __str__(self) -> str:
        return self.title


# --- the team -----------------------------------------------------------------------------

PRINCIPAL_INVESTIGATOR = Agent(
    title="Principal Investigator",
    expertise="leading systematic reviews and meta-analyses in clinical and exercise science",
    goal="produce an evidence synthesis whose conclusions are correct, useful and defensible under peer review",
    role="lead a team of experts, make key decisions about the review's design and interpretation based on "
         "team member input, and keep the work within what the data can support")

# Verbatim from the Virtual Lab (virtual_lab/prompts.py).
SCIENTIFIC_CRITIC = Agent(
    title="Scientific Critic",
    expertise="providing critical feedback for scientific research",
    goal="ensure that proposed research projects and implementations are rigorous, detailed, feasible, and scientifically sound",
    role="provide critical feedback to identify and correct all errors and demand that scientific answers that are "
         "maximally complete and detailed but simple and not overly complex")

INFORMATION_SPECIALIST = Agent(
    title="Information Specialist",
    expertise="high-sensitivity literature searching, MeSH, PRISMA-S reporting and PRESS peer review",
    goal="make sure no eligible study is missed and the search is reproducible",
    role="advise on databases, concepts, eligibility criteria that can be applied from titles and abstracts, "
         "and search reporting")

BIOSTATISTICIAN = Agent(
    title="Biostatistician",
    expertise="meta-analysis methods: effect measures, random-effects models, heterogeneity, small-study "
              "effects, meta-regression and GRADE",
    goal="make the statistical plan pre-specified, appropriate for the data type and robust",
    role="choose effect measures and models, flag multiplicity and post-hoc analyses, and insist on "
         "sensitivity analyses")


def domain_expert(field: str) -> Agent:
    """A clinical/domain expert for the review's topic, e.g. ``domain_expert("sports cardiology")``."""
    return Agent(
        title=f"{field.title()} Expert", expertise=field,
        goal="make sure the question, outcomes and interpretation are clinically meaningful",
        role="say which outcomes, populations and subgroups matter to clinicians, and which findings would "
             "change practice")


# --- prompts (adapted from virtual_lab/prompts.py) ------------------------------------------------

SYNTHESIS_PROMPT = ("synthesize the points raised by each team member, make decisions regarding the agenda based "
                    "on team member input, and ask follow-up questions to gather more information and feedback "
                    "about how to better address the agenda")
SUMMARY_PROMPT = ("summarize the meeting in detail for future discussions, provide a specific recommendation "
                  "regarding the agenda, and answer the agenda questions (if any) based on the discussion while "
                  "strictly adhering to the agenda rules (if any)")


def _numbered(items):
    return "\n\n".join(f"{i + 1}. {x}" for i, x in enumerate(items))


def _refs(refs, kind, intro):
    if not refs:
        return ""
    body = "\n\n".join(f"[begin {kind} {i + 1}]\n\n{r}\n\n[end {kind} {i + 1}]" for i, r in enumerate(refs))
    return f"{intro}\n\n{body}\n\n"


def _agenda_block(agenda, questions, rules, intro="Here is the agenda for the meeting:",
                  q_intro="Here are the agenda questions that must be answered:",
                  r_intro="Here are the agenda rules that must be followed:"):
    out = f"{intro}\n\n{agenda}\n\n"
    if questions:
        out += f"{q_intro}\n\n{_numbered(questions)}\n\n"
    if rules:
        out += f"{r_intro}\n\n{_numbered(rules)}\n\n"
    return out


def _summary_structure(has_questions: bool) -> str:
    parts = ["### Agenda", "Restate the agenda in your own words.",
             "### Team Member Input",
             "Summarize all of the important points raised by each team member. This is to ensure that key "
             "details are preserved for future meetings.",
             "### Recommendation",
             "Provide your expert recommendation regarding the agenda. You should consider the input from each "
             "team member, but you must also use your expertise to make a final decision and choose one option "
             "among several that may have been discussed. This decision can conflict with the input of some team "
             "members as long as it is well justified. It is essential that you provide a clear, specific, and "
             "actionable recommendation. Please justify your recommendation as well."]
    if has_questions:
        parts += ["### Answers", "For each agenda question, please provide the following:",
                  "Answer: A specific answer to the question based on your recommendation above.",
                  "Justification: A brief explanation of why you provided that answer."]
    parts += ["### Next Steps", "Outline the next steps that the team should take based on the discussion."]
    return "\n\n".join(parts)


# --- LLM transport ------------------------------------------------------------------------

LLM = Callable[[str, str, list], str]  # (model, system, messages) -> text


def anthropic_llm(api_key: str | None = None, max_tokens: int = 4000, temperature: float = 0.2) -> LLM:
    """Claude via the Messages API, standard library only. Key from ANTHROPIC_API_KEY by default."""
    key = api_key or os.environ.get("ANTHROPIC_API_KEY")
    if not key:
        raise RuntimeError("set ANTHROPIC_API_KEY (or pass api_key) to run team meetings")

    def call(model: str, system: str, messages: list) -> str:
        body = json.dumps({"model": model, "max_tokens": max_tokens, "temperature": temperature,
                           "system": system, "messages": messages}).encode()
        for attempt in range(4):
            req = urllib.request.Request("https://api.anthropic.com/v1/messages", data=body, headers={
                "content-type": "application/json", "x-api-key": key, "anthropic-version": "2023-06-01"})
            try:
                with urllib.request.urlopen(req, timeout=300) as r:
                    data = json.loads(r.read())
                return "".join(b.get("text", "") for b in data["content"] if b.get("type") == "text")
            except urllib.error.HTTPError as e:
                if e.code in (429, 500, 529) and attempt < 3:
                    time.sleep(2 ** (attempt + 1))
                    continue
                raise RuntimeError(f"Anthropic API error {e.code}: {e.read().decode(errors='replace')[:300]}") from e
        raise RuntimeError("Anthropic API: retries exhausted")

    return call


# --- meetings -----------------------------------------------------------------------------

def run_meeting(meeting_type: str, agenda: str, llm: LLM, save_dir: Path | None = None,
                save_name: str = "discussion", team_lead: Agent | None = None,
                team_members: Sequence[Agent] = (), team_member: Agent | None = None,
                agenda_questions: Sequence[str] = (), agenda_rules: Sequence[str] = (),
                summaries: Sequence[str] = (), contexts: Sequence[str] = (), num_rounds: int = 1,
                log: Callable[[str], None] = lambda s: None) -> dict:
    """Run a team or individual meeting (the Virtual Lab protocol) and return the transcript.

    Team meeting: the lead opens, each member speaks in turn, the lead synthesizes; repeated for
    ``num_rounds`` rounds; then the lead writes the structured summary.
    Individual meeting: one agent answers; the Scientific Critic critiques; the agent revises;
    repeated ``num_rounds`` times.
    """
    if meeting_type == "team":
        if team_lead is None or not team_members:
            raise ValueError("team meeting needs a team lead and team members")
        if team_lead in team_members or len(set(team_members)) != len(team_members):
            raise ValueError("team members must be unique and exclude the lead")
        team = [team_lead, *team_members]
    elif meeting_type == "individual":
        if team_member is None:
            raise ValueError("individual meeting needs team_member")
        team = [team_member, SCIENTIFIC_CRITIC]
    else:
        raise ValueError("meeting_type must be 'team' or 'individual'")

    messages: list[dict] = []
    discussion: list[dict] = []
    t0 = time.time()
    if meeting_type == "team":
        start = (f"This is the beginning of a team meeting to discuss your research project. "
                 f"This is a meeting with the team lead, {team_lead.title}, and the following team members: "
                 f"{', '.join(m.title for m in team_members)}.\n\n"
                 f"{_refs(contexts, 'context', 'Here is context for this meeting:')}"
                 f"{_refs(summaries, 'summary', 'Here are summaries of the previous meetings:')}"
                 f"{_agenda_block(agenda, agenda_questions, agenda_rules)}"
                 f"{team_lead} will convene the meeting. Then, each team member will provide their thoughts on "
                 f"the discussion one-by-one in the order above. After all team members have given their input, "
                 f"{team_lead} will {SYNTHESIS_PROMPT}. This will continue for {num_rounds} rounds. Once the "
                 f"discussion is complete, {team_lead} will {SUMMARY_PROMPT}.")
        discussion.append({"agent": "User", "message": start})
        pending_user = start + "\n\n"
    else:
        pending_user = ""

    for round_index in range(num_rounds + 1):
        round_num = round_index + 1
        for agent in team:
            if meeting_type == "team":
                if agent == team_lead:
                    if round_index == 0:
                        prompt = (f"{team_lead}, please provide your initial thoughts on the agenda as well as any "
                                  f"questions you have to guide the discussion among the team members.")
                    elif round_index == num_rounds:
                        prompt = (f"{team_lead}, please {SUMMARY_PROMPT}.\n\n"
                                  + _agenda_block(agenda, agenda_questions, agenda_rules,
                                                  "As a reminder, here is the agenda for the meeting:",
                                                  "As a reminder, here are the agenda questions that must be answered:",
                                                  "As a reminder, here are the agenda rules that must be followed:")
                                  + "Your summary should take the following form.\n\n"
                                  + _summary_structure(bool(agenda_questions)))
                    else:
                        prompt = f"This concludes round {round_num - 1} of {num_rounds} of discussion. {team_lead}, please {SYNTHESIS_PROMPT}."
                else:
                    prompt = (f"{agent}, please provide your thoughts on the discussion (round {round_num} of "
                              f"{num_rounds}). If you do not have anything new or relevant to add, you may say "
                              f"\"pass\". Remember that you can and should (politely) disagree with other team "
                              f"members if you have a different perspective.")
            else:
                if agent == SCIENTIFIC_CRITIC:
                    prompt = (f"{SCIENTIFIC_CRITIC.title}, please critique {team_member.title}'s most recent answer. "
                              "In your critique, suggest improvements that directly address the agenda and any agenda "
                              "questions. Prioritize simple solutions over unnecessarily complex ones, but demand more "
                              "detail where detail is lacking. Additionally, validate whether the answer strictly "
                              "adheres to the agenda and any agenda questions and provide corrective feedback if it "
                              "does not. Only provide feedback; do not implement the answer yourself.")
                elif round_index == 0:
                    prompt = (f"This is the beginning of an individual meeting with {team_member} to discuss your "
                              f"research project.\n\n"
                              f"{_refs(contexts, 'context', 'Here is context for this meeting:')}"
                              f"{_refs(summaries, 'summary', 'Here are summaries of the previous meetings:')}"
                              f"{_agenda_block(agenda, agenda_questions, agenda_rules)}"
                              f"{team_member}, please provide your response to the agenda.")
                else:
                    prompt = (f"{team_member.title}, please modify your answer to address {SCIENTIFIC_CRITIC.title}'s "
                              "most recent feedback. Remember that your ultimate goal is to make improvements that "
                              "better address the agenda.")
            full = pending_user + prompt
            pending_user = ""
            messages.append({"role": "user", "content": full})
            discussion.append({"agent": "User", "message": prompt})
            log(f"  {agent.title} (round {min(round_num, num_rounds + 1)})")
            reply = llm(agent.model, agent.prompt, messages)
            messages.append({"role": "assistant", "content": reply})
            discussion.append({"agent": agent.title, "message": reply})
            if round_index == num_rounds:
                break

    summary = discussion[-1]["message"]
    out = {"meeting_type": meeting_type, "agenda": agenda, "agenda_questions": list(agenda_questions),
           "agenda_rules": list(agenda_rules), "team": [a.title for a in team], "num_rounds": num_rounds,
           "discussion": discussion, "summary": summary, "seconds": round(time.time() - t0, 1)}
    if save_dir is not None:
        save_dir = Path(save_dir)
        save_dir.mkdir(parents=True, exist_ok=True)
        (save_dir / f"{save_name}.json").write_text(json.dumps(out, indent=2))
        md = [f"# {save_name}", "", f"*{meeting_type} meeting; team: {', '.join(out['team'])}; "
              f"{num_rounds} round(s). Generated by AI agents; advisory only.*", ""]
        for turn in discussion:
            md += [f"## {turn['agent']}", "", turn["message"], ""]
        (save_dir / f"{save_name}.md").write_text("\n".join(md))
    return out


# --- evidence-synthesis meetings built on the protocol -------------------------------------

PROTOCOL_RULES = (
    "Pre-specify everything: outcomes, effect measures, subgroups and sensitivity analyses are fixed before any data is seen.",
    "Only propose subgroups or meta-regression moderators with a stated clinical or methodological rationale.",
    "Choose effect measures that match what primary studies in this field actually report.",
    "Eligibility criteria must be applicable from a title and abstract wherever possible.",
    "End the summary with a single fenced ```yaml block containing a complete metakit protocol (keys: title, "
    "question, pico, study_designs, eligibility {include: [...], exclude: [...]}, outcomes [{id, label, "
    "primary, data_type, measure, unit}], model {method, test}, subgroups, meta_regression, sensitivity, "
    "risk_of_bias_tool).",
)


def protocol_meeting(question: str, field: str, llm: LLM, save_dir: Path, num_rounds: int = 2,
                     log: Callable[[str], None] = lambda s: None) -> dict:
    """Team meeting that drafts the review protocol. Returns the transcript plus the parsed protocol."""
    from .protocol import TEMPLATE, normalize_protocol
    res = run_meeting(
        "team", f"Design the protocol for a systematic review and meta-analysis answering: {question}", llm,
        save_dir, "protocol_meeting", team_lead=PRINCIPAL_INVESTIGATOR,
        team_members=(domain_expert(field), INFORMATION_SPECIALIST, BIOSTATISTICIAN, SCIENTIFIC_CRITIC),
        agenda_questions=(
            "What is the precise question in PICO/PECO form, and which study designs are eligible?",
            "What are the inclusion and exclusion criteria?",
            "Which outcomes, with which data type, effect measure and common unit?",
            "Which subgroups or moderators are justified in advance, and why?",
            "Which risk-of-bias tool, model and sensitivity analyses?"),
        agenda_rules=PROTOCOL_RULES, contexts=(f"metakit protocol format:\n{TEMPLATE}",),
        num_rounds=num_rounds, log=log)
    m = re.findall(r"```ya?ml\s*\n(.*?)```", res["summary"], re.S)
    res["protocol_yaml"], res["protocol_error"] = None, None
    if m:
        import yaml
        try:
            proto = normalize_protocol(yaml.safe_load(m[-1]))
            res["protocol_yaml"] = yaml.safe_dump(proto, sort_keys=False)
            (Path(save_dir) / "protocol.draft.yaml").write_text(
                "# DRAFT from the review-team meeting. Review every line, then rename to protocol.yaml.\n"
                + res["protocol_yaml"])
        except Exception as exc:  # the meeting produced an invalid protocol: report, don't guess
            res["protocol_error"] = str(exc)
    else:
        res["protocol_error"] = "the meeting summary did not contain a ```yaml protocol block"
    return res


def numbers_in_results(results: dict) -> set:
    vals = set()

    def walk(o):
        if isinstance(o, dict):
            for v in o.values():
                walk(v)
        elif isinstance(o, list):
            for v in o:
                walk(v)
        elif isinstance(o, (int, float)) and not isinstance(o, bool):
            vals.add(float(o))
    walk(results)
    return vals


def unverified_numbers(text: str, results: dict) -> list[str]:
    """Numbers in ``text`` that match nothing in ``results`` at the precision written.

    Integers up to 10 and years are ignored (counts of rounds, "95% CI", "2019").
    """
    known = numbers_in_results(results)
    from .extraction import numbers_in
    bad = []
    for val, dec in numbers_in(text):
        if dec == 0 and (abs(val) <= 10 or 1900 <= val <= 2100 or val in (95, 100)):
            continue
        tol = 0.5 * 10 ** (-dec) + 1e-12
        # accept percentages of proportions too (e.g. I2 already in %, weights in %)
        if not any(abs(val - k) <= tol for k in known):
            bad.append(f"{val:.{dec}f}")
    return sorted(set(bad))


INTERPRETATION_RULES = (
    "Use only numbers that appear in the analysis results provided; never compute or estimate new numbers.",
    "State the certainty of evidence (GRADE) alongside every conclusion, and never claim causation from meta-regression or subgroup findings.",
    "With fewer than 10 studies, do not interpret funnel plots or Egger's test as evidence for or against publication bias.",
    "Distinguish the confidence interval (the average effect) from the prediction interval (a new setting).",
)


def interpretation_meeting(results: dict, protocol: dict, field: str, llm: LLM, save_dir: Path,
                           num_rounds: int = 2, log: Callable[[str], None] = lambda s: None) -> dict:
    """Team meeting that drafts the Discussion; every number in its output is checked against results."""
    brief = {oid: {k: o.get(k) for k in ("label", "k", "n_total", "measure_name", "main", "heterogeneity_ci",
                                          "sensitivity", "egger", "trim_and_fill", "subgroups", "meta_regression",
                                          "grade", "warnings")}
             for oid, o in results["outcomes"].items()}
    res = run_meeting(
        "team", "Interpret the meta-analysis results and draft the Discussion section: main findings, "
                "strength of evidence, limitations, and implications for practice and research.", llm,
        save_dir, "interpretation_meeting", team_lead=PRINCIPAL_INVESTIGATOR,
        team_members=(domain_expert(field), BIOSTATISTICIAN, SCIENTIFIC_CRITIC),
        agenda_questions=("What is the main finding, stated with its uncertainty and GRADE certainty?",
                          "How consistent are the studies, and what explains the heterogeneity (if anything)?",
                          "Which limitations most threaten the conclusions?",
                          "What should clinicians and researchers do with this evidence?"),
        agenda_rules=INTERPRETATION_RULES,
        contexts=(f"Protocol:\n{json.dumps({k: protocol.get(k) for k in ('title', 'question', 'outcomes')}, indent=1)}",
                  f"Analysis results (computed by metakit, validated against metafor):\n{json.dumps(brief, indent=1, default=str)}"),
        num_rounds=num_rounds, log=log)
    res["unverified_numbers"] = unverified_numbers(res["summary"], results)
    if save_dir is not None:
        flag = ("All numbers in the summary match the analysis results." if not res["unverified_numbers"] else
                "WARNING: these numbers in the summary do not appear in results.json and must be checked or "
                "removed: " + ", ".join(res["unverified_numbers"]))
        (Path(save_dir) / "discussion.draft.md").write_text(
            "<!-- DRAFT from the review-team meeting. " + flag + " -->\n\n" + res["summary"])
    return res
