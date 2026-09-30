"""The validator is the safety net for LLM extraction: every planted error must be caught."""
import json

import pytest

from conftest import mutate
from metakit.extraction import (numbers_in, quote_in_source, validate_folder, value_in_quote)
from metakit.protocol import load_protocol


def run(project):
    return validate_folder(project / "extraction", load_protocol(project / "protocol.yaml"), project)


def msgs(rep, level="error"):
    return [str(i) for i in rep.issues if i.level == level]


def test_clean_project_passes_and_every_quote_is_verified(project):
    rep = run(project)
    assert rep.ok, msgs(rep)
    assert rep.n_quotes_checked == rep.n_quotes_verified > 60


# --- number/quote matching -------------------------------------------------

@pytest.mark.parametrize("value,quote,expected", [
    (4, "Of 123 children, 4 developed TB", True),
    (0.12, "ST depression 0\u00b712 mV", True),           # Lancet mid-dot decimal
    (1234, "n = 1,234", True),                              # thousands separator
    (-0.5, "a change of \u22120.5", True),                  # unicode minus
    (25, "aged 20\u201325 years", True),                    # en-dash range
    (0.13, "0.12 mV", False),
    (0.125, "0.12 mV", False),                              # more precision than shown is not a match
    (12, "0.12 mV", False),
    (7, "7/60 athletes", True),
])
def test_value_in_quote(value, quote, expected):
    assert value_in_quote(value, quote) is expected


def test_numbers_in_handles_formats():
    vals = [v for v, _ in numbers_in("n = 1,234; 0\u00b712 mV; \u22123.5")]
    assert 1234 in vals and 0.12 in vals and -3.5 in vals


def test_quote_matching_tolerates_pdf_noise():
    src = "Results: the mean ST ele-\nvation in V2 was 0.21 mV\n(SD 0.08) in athletes."
    found, sim, _ = quote_in_source("the mean ST elevation in V2 was 0.21 mV (SD 0.08)", src)
    assert found and sim == 1.0


def test_near_identical_quote_with_changed_number_is_located_but_number_rejected():
    src = ("In the athlete group (n = 212) the mean ST elevation in V2 was 0.21 mV (SD 0.08), "
           "compared with 0.12 mV (SD 0.05) in controls.")
    fake = src.replace("0.21", "0.31")
    found, sim, window = quote_in_source(fake, src)
    assert found and sim > 0.95          # fuzzy match alone would accept this
    assert not value_in_quote(0.31, window)  # ...but the paper does not contain 0.31
    assert value_in_quote(0.21, window)


# --- planted errors: each must produce an error ------------------------------

def test_catches_number_not_in_quote(project):
    mutate(project, "Alpha_2019.json",
           lambda r: r["outcomes"][0]["fields"]["mean_t"].update(value=0.25))
    assert any("does not appear in its quote" in m for m in msgs(run(project)))


def test_catches_fabricated_quote(project):
    def f(r):
        r["outcomes"][0]["fields"]["sd_t"]["quote"] = "The SD of ST elevation among athletes was 0.08 mV overall."
    mutate(project, "Alpha_2019.json", f)
    assert any("quote not found" in m for m in msgs(run(project)))


def test_catches_doctored_quote_with_wrong_number(project):
    def f(r):
        fld = r["outcomes"][0]["fields"]["mean_t"]
        fld["quote"] = fld["quote"].replace("0.21", "0.31")
        fld["value"] = 0.31
    mutate(project, "Alpha_2019.json", f)
    assert any("does not contain 0.31" in m for m in msgs(run(project)))


def test_catches_missing_quote_and_required_field(project):
    def f(r):
        r["outcomes"][0]["fields"]["sd_t"]["quote"] = ""
        del r["outcomes"][1]["fields"]["n_c"]
    mutate(project, "Alpha_2019.json", f)
    m = msgs(run(project))
    assert any("missing quote" in x for x in m)
    assert any("'n_c' missing" in x for x in m)


@pytest.mark.parametrize("patch,needle", [
    (lambda r: r["outcomes"][1]["fields"]["events_t"].update(value=70), "exceeds n_t"),
    (lambda r: r["outcomes"][0]["fields"]["n_t"].update(value=60.5), "whole number"),
    (lambda r: r["outcomes"][0]["fields"]["sd_t"].update(value=-0.08), "must be positive"),
    (lambda r: r["outcomes"][0].update(data_type="dichotomous"), "data_type must be one of"),
    (lambda r: r["outcomes"][0].update(outcome="st_depression"), "not defined in protocol.yaml"),
    (lambda r: r["outcomes"][0]["fields"].update(foo={"value": 1, "quote": "1", "location": "x"}), "unexpected field"),
    (lambda r: r.update(source_file="fulltext/nope.md"), "does not exist"),
])
def test_plausibility_and_structure_errors(project, patch, needle):
    mutate(project, "Alpha_2019.json", patch)
    assert any(needle in m for m in msgs(run(project))), msgs(run(project))


def test_mean_outside_ci(project):
    def f(r):
        flds = r["outcomes"][0]["fields"]
        flds["mean_t"]["value"] = 0.20
        flds["ci_upper_t"]["value"] = 0.14
        flds["ci_lower_t"]["value"] = 0.14  # also make the quote check fail-safe irrelevant
    mutate(project, "Delta_2021.json", f)
    assert any("outside its CI" in m for m in msgs(run(project)))


def test_derived_values_need_explanation_and_raise_warning(project):
    def f(r):
        r["outcomes"][1]["fields"]["events_t"].update(value=8, derived=True)
    mutate(project, "Alpha_2019.json", f)
    assert any("no derivation explanation" in m for m in msgs(run(project)))

    def g(r):
        r["outcomes"][1]["fields"]["events_t"]["derivation"] = "13.3% of 60 = 8"
    mutate(project, "Alpha_2019.json", g)
    rep = run(project)
    assert rep.ok
    assert any("derived by the extractor" in m for m in msgs(rep, "warning"))


def test_duplicate_study_ids(project):
    rec = json.loads((project / "extraction" / "Alpha_2019.json").read_text())
    (project / "extraction" / "Alpha_copy.json").write_text(json.dumps(rec))
    assert any("duplicate study_id" in m for m in msgs(run(project)))


def test_se_reported_as_sd_warning(project):
    # make Zeta's control SD look like an SE: 0.06 / sqrt(118) ~ 0.0055 -> quote must also match
    def f(r):
        flds = r["outcomes"][0]["fields"]
        s = flds["sd_c"]["quote"].replace("(SD 0.06)", "(SD 0.0055)")
        for v in flds.values():
            v["quote"] = s
        flds["sd_c"]["value"] = 0.0055
    mutate(project, "Zeta_2023.json", f)
    (project / "fulltext" / "Zeta_2023.md").write_text(
        (project / "fulltext" / "Zeta_2023.md").read_text().replace("(SD 0.06)", "(SD 0.0055)"))
    rep = run(project)
    assert any("standard error reported as an SD" in m for m in msgs(rep, "warning"))
