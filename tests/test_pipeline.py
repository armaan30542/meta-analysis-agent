"""End-to-end: validate -> harmonise -> analyse -> report, through the CLI."""
import json
import math
import shutil

import pytest

from conftest import mutate
from metakit import convert
from metakit.cli import main
from metakit.extraction import load_extractions
from metakit.harmonize import harmonize
from metakit.protocol import ProtocolError, load_protocol, normalize_protocol
from metakit.reconcile import compare
from metakit.rob import load_rob, nos_overall, validate_rob


def test_harmonize_applies_every_conversion(project):
    proto = load_protocol(project / "protocol.yaml")
    h = harmonize(load_extractions(project / "extraction"), proto)
    st = {e.study_id: e for e in h["st_elevation"]["effects"]}
    assert len(st) == 6
    # Beta reported millimetres: 2.4 mm -> 0.24 mV, 1.3 mm -> 0.13 mV
    assert st["Beta 2020"].yi == pytest.approx(0.24 - 0.13)
    assert any("mm -> mV" in d for d in st["Beta 2020"].derivations)
    # Gamma reported SEs
    sd_t = convert.sd_from_se(0.012, 80)
    sd_c = convert.sd_from_se(0.009, 75)
    assert st["Gamma 2021"].vi == pytest.approx(sd_t ** 2 / 80 + sd_c ** 2 / 75)
    # Delta reported CIs (n < 60 -> t distribution)
    assert any("t critical value" in d for d in st["Delta 2021"].derivations)
    # Epsilon reported medians/IQRs and is flagged as estimated
    assert st["Epsilon 2022"].estimated_sd
    assert any("q1/median/q3" in d for d in st["Epsilon 2022"].derivations)
    # binary: Gamma has zero events in both arms -> excluded; Beta has one zero cell -> corrected
    ecg = h["abnormal_ecg"]
    assert "Gamma 2021" in [x.study_id for x in ecg["excluded"]]
    beta = next(e for e in ecg["effects"] if e.study_id == "Beta 2020")
    assert any("zero cell" in d for d in beta.derivations)


def test_full_cli_run(project, capsys):
    assert main(["analyze", "-p", str(project)]) == 0
    assert main(["report", "-p", str(project)]) == 0
    res = json.loads((project / "analysis" / "results.json").read_text())
    st = res["outcomes"]["st_elevation"]
    assert st["k"] == 6 and st["main"]["test"] == "knha"
    assert 0 < st["main"]["display"]["estimate"] < 0.2
    assert st["sensitivity"]["excluding_high_risk_of_bias"]["removed"] == ["Gamma 2021"]
    assert st["sensitivity"]["excluding_estimated_means_sds"]["removed"] == ["Epsilon 2022"]
    assert set(st["subgroups"]["sport"]["per_group"]) == {"running", "cycling", "rowing"}
    assert "warning" in st["meta_regression"]["mean_age"]  # k < 10
    assert st["grade"]["rating"] in ("very low", "low", "moderate", "high")
    assert st["grade"]["start"] == "low"  # observational
    assert res["outcomes"]["abnormal_ecg"]["k"] == 5
    assert res["outcomes"]["early_repol"]["k"] == 1
    for fig in ("forest", "funnel", "leave_one_out", "cumulative", "forest_by_sport"):
        assert (project / "analysis" / st["figures"][fig]).exists()
    assert (project / "analysis" / "rob.png").exists()
    assert (project / "analysis" / "prisma.png").exists()
    report = (project / "report" / "report.md").read_text()
    assert "Knapp-Hartung" in report
    assert "Only one study (Alpha 2019)" in report
    assert "estimated with the methods of Luo" in report          # medians were converted
    assert "excluding studies at high risk of bias" in report
    assert "Gamma 2021: zero events in both arms" in report
    assert "GRADE" in report and "Appendix B" in report


def test_analyze_refuses_invalid_extraction(project):
    mutate(project, "Alpha_2019.json", lambda r: r["outcomes"][0]["fields"]["mean_t"].update(value=0.99))
    assert main(["analyze", "-p", str(project)]) == 1
    assert not (project / "analysis" / "results.json").exists()
    assert main(["analyze", "-p", str(project), "--force"]) == 0


@pytest.mark.skipif(shutil.which("Rscript") is None, reason="R not installed")
def test_crosscheck_against_metafor(project):
    assert main(["analyze", "-p", str(project)]) == 0
    assert main(["crosscheck", "-p", str(project)]) == 0


def test_benchmarks_reproduce_published_results():
    assert main(["benchmark"]) == 0


def test_init_and_ingest(tmp_path):
    proj = tmp_path / "new"
    assert main(["init", str(proj)]) == 0
    assert (proj / "protocol.yaml").exists() and (proj / "extraction").is_dir()
    assert "fulltext/*.pdf" in (proj / ".gitignore").read_text()
    lst = tmp_path / "included.txt"
    lst.write_text("# from the SR agent\n31415926\n10.1000/xyz123\nPMC1234567\n")
    assert main(["ingest", str(lst), "-p", str(proj)]) == 0
    rows = (proj / "studies.csv").read_text()
    assert "31415926" in rows and "10.1000/xyz123" in rows and "PMC1234567" in rows


def test_protocol_validation():
    with pytest.raises(ProtocolError, match="does not fit data_type"):
        normalize_protocol({"outcomes": [{"id": "x", "data_type": "binary", "measure": "MD"}]})
    with pytest.raises(ProtocolError, match="generic_scale"):
        normalize_protocol({"outcomes": [{"id": "x", "data_type": "generic", "measure": "GEN"}]})
    p = normalize_protocol({"outcomes": [{"id": "x", "data_type": "binary", "measure": "RR"}]})
    assert p["outcomes"][0]["primary"] and p["model"]["method"] == "REML"


def test_rob_rules(project):
    recs, problems = load_rob(project / "rob", "ROBINS-I")
    assert len(recs) == 6 and not problems
    bad = json.loads((project / "rob" / "Alpha_2019.json").read_text())
    bad["overall"] = "low"  # better than its worst domain (moderate)
    assert any("worst domain" in p for p in validate_rob(bad, "ROBINS-I"))
    assert nos_overall({"selection": 4, "comparability": 1, "outcome": 2}) == "good"
    assert nos_overall({"selection": 2, "comparability": 1, "outcome": 3}) == "fair"
    assert nos_overall({"selection": 1, "comparability": 2, "outcome": 3}) == "poor"


def test_reconcile_finds_disagreements(project, tmp_path):
    b = tmp_path / "extraction_b"
    shutil.copytree(project / "extraction", b)
    rec = json.loads((b / "Delta_2021.json").read_text())
    rec["outcomes"][1]["fields"]["events_c"]["value"] = 5
    (b / "Delta_2021.json").write_text(json.dumps(rec))
    res = compare(project / "extraction", b)
    assert len(res["discrepancies"]) == 1
    d = res["discrepancies"][0]
    assert (d["study"], d["field"], d["a"], d["b"]) == ("Delta 2021", "events_c", 4, 5)
    assert 0.98 < res["agreement"] < 1
    assert main(["reconcile", str(project / "extraction"), str(b)]) == 2


def test_two_study_outcome_warns(project):
    for f in ("Gamma_2021.json", "Delta_2021.json", "Epsilon_2022.json", "Zeta_2023.json"):
        (project / "extraction" / f).unlink()
    assert main(["analyze", "-p", str(project)]) == 0
    res = json.loads((project / "analysis" / "results.json").read_text())
    assert any("only two studies" in w for w in res["outcomes"]["st_elevation"]["warnings"])
    assert math.isfinite(res["outcomes"]["st_elevation"]["main"]["estimate"])
