# How metakit works, in plain language

This is the version to read before explaining the tool to a professor. Each stage says what
it does, why it exists, and the question you should be ready to answer about it.

## The big picture

A **literature review** summarizes studies in words. A **systematic review** does that with
a pre-defined, reproducible search and screening process, so anyone repeating it would find
the same studies. A **meta-analysis** goes one step further: it takes the *numbers* from those
studies and combines them statistically into one overall estimate, with a measure of how
certain and how consistent that estimate is.

Example: ten studies each measure ST-segment elevation in athletes and in controls. Each gives
a slightly different difference. A meta-analysis weights each study by how precise it is
(bigger, less noisy studies count more) and produces one pooled difference with a confidence
interval, plus a measure of whether the studies really agree.

Ram's agent does the systematic review (finding and screening studies). metakit does the
meta-analysis (extracting numbers and combining them).

## Why an AI can't just "do the meta-analysis"

Language models are good at reading and bad at being exact. The classic failures are
reading 0.21 as 0.31, taking a standard error for a standard deviation, grabbing the wrong
row of a table, and inventing a plausible-looking number when the real one is hard to find.
In a meta-analysis, one wrong number from one big study can move the whole result.

So metakit splits the work:

| Who | Does what |
|---|---|
| AI agent | Reads papers, finds the numbers, copies the exact sentence each came from |
| metakit (normal code) | Checks every number against its sentence and the paper, does all the math |
| Humans | Approve the plan, settle disagreements, make judgement calls |

## The stages

**1. Protocol.** Before touching any data, we write down the question, which outcomes we'll
analyse, how we'll measure the effect (for example, mean difference in mV), and which
subgroups we'll test. *Why:* if you decide these after seeing results, you can make almost any
conclusion appear. *Be ready for:* "Were your subgroups pre-specified?" Yes, it's in
`protocol.yaml`, written before extraction.

**2. Retrieval.** metakit downloads the full text of open-access papers from PubMed Central
and Europe PMC, keeping their tables. Paywalled papers are added as PDFs and turned into text
by ordinary software, not by the AI, so the AI can't verify its own transcription.

**3. Dual extraction.** Two AI agents extract the numbers from each paper *independently*,
without seeing each other's work. This mirrors the Cochrane standard of two human extractors.
*Why:* errors are rarely made twice in the same way, so comparing two independent extractions
catches most of them.

**4. Validation, the anti-hallucination layer.** For every single number, metakit checks:
- the number appears in the quoted sentence exactly;
- the quoted sentence really appears in the paper (tolerating PDF line breaks);
- when a quote only *approximately* matches the paper, the paper's own version contains the number.

That last check matters: in testing, a sentence copied from a paper with one digit changed
was 98.9% similar to the original, which is enough to fool a simple text match. metakit
still catches it, because the changed number isn't in the paper. It also flags implausible data
(more events than participants, a mean outside its own confidence interval) and the most
common error in published meta-analyses, standard errors reported as standard deviations.

**5. Reconciliation.** metakit lines up the two extractions field by field and lists every
disagreement. A human (or the lead agent, re-reading the paper) decides each one. The
agreement rate is a quality metric worth reporting.

**6. Risk of bias.** Each study is rated on how its design could distort its results (was
randomization done properly, were outcome assessors blinded, is data missing?) using the
standard tools (RoB 2 for trials, ROBINS-I or Newcastle-Ottawa for observational studies).
The agent drafts; a human confirms.

**7. Harmonization.** Papers report things differently: some give a standard deviation,
some a standard error, some a confidence interval, some a median and range, some millimetres
instead of millivolts. metakit converts everything to a common form using published methods,
and logs every conversion so the report shows exactly what was done to which number.

**8. Analysis.** The core calculation is a **random-effects model**: it assumes each study
measures a slightly different true effect (different athletes, sports, ECG protocols) and
estimates the average. Around it:
- **Heterogeneity** (I², τ², prediction interval): do the studies agree? The prediction
  interval answers the practical question "what effect should I expect in a new setting?"
- **Sensitivity analyses**: does the answer change if we drop low-quality studies, studies
  with estimated numbers, or any single study?
- **Subgroups and meta-regression**: does the effect differ by sport, age or sex?
- **Publication bias** (funnel plot, Egger's test, trim-and-fill): are small studies with
  unexciting results missing? These tests only mean something with 10 or more studies.

**9. GRADE.** The final certainty rating (high, moderate, low, very low), downgraded for bias,
inconsistency, indirectness, imprecision and publication bias. metakit proposes a rating
with a written reason for every downgrade; humans sign off.

**10. Report and cross-check.** metakit writes the methods and results sections, the figures,
and a summary-of-findings table, using only computed numbers. It then re-runs the whole
analysis in R's metafor package, the tool most published meta-analyses use, and confirms the
answers are identical.

## How we know the tool is right

1. **Unit tests against metafor.** Every estimator is checked against metafor on four
   published datasets; they agree to many decimal places.
2. **Reproducing a published meta-analysis.** The 1994 BCG vaccine meta-analysis in *JAMA*
   reported a risk ratio of 0.49 (95% CI 0.34 to 0.70). metakit, starting from the trial data,
   reproduces 0.49 (0.34 to 0.70).
3. **Planted errors.** The test suite deliberately inserts invented numbers, fake quotes,
   doctored quotes and impossible values, and checks that each is caught.
4. **Extraction accuracy benchmark.** Run the agents on studies with a known-correct
   extraction and score field-level accuracy (`metakit benchmark --gold ... --candidate ...`).
   This is the concrete evaluation metric for the agent itself.

## Questions to be ready for

- *Why random effects?* Studies differ in populations and methods; assuming one identical
  true effect is rarely credible.
- *Why Knapp-Hartung?* With few studies, the standard method gives confidence intervals that
  are too narrow; Knapp-Hartung corrects that (IntHout et al., 2014).
- *Why REML rather than DerSimonian-Laird?* DL tends to underestimate between-study variance;
  REML is the current recommendation (Veroniki et al., 2016). We report DL as a sensitivity analysis.
- *What does I² = 92% mean?* 92% of the variation between studies reflects real differences,
  not chance. It does not say how *big* those differences are; τ² and the prediction interval do.
- *How do you stop the AI making things up?* It can't put a number into the analysis without a
  quote that software verifies against the paper, and two independent extractions must agree.
