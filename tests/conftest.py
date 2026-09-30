"""A synthetic, clearly fake meta-analysis project that exercises every messy real-world case.

SYNTHETIC DATA: numbers are invented for testing and describe no real study.
"""
import copy
import json
from pathlib import Path

import pytest
import yaml

PROTOCOL = {
    "title": "SYNTHETIC TEST: ST-segment elevation in athletes vs controls",
    "question": "Do endurance athletes show greater ST elevation in V2 than sedentary controls?",
    "study_designs": ["cross-sectional"],
    "outcomes": [
        {"id": "st_elevation", "label": "ST elevation in V2", "primary": True, "data_type": "continuous",
         "measure": "MD", "unit": "mV", "favours": ["Lower in athletes", "Higher in athletes"]},
        {"id": "abnormal_ecg", "label": "Abnormal ECG", "data_type": "binary", "measure": "OR"},
        {"id": "early_repol", "label": "Early repolarisation prevalence", "data_type": "proportion",
         "measure": "PLO"},
    ],
    "model": {"method": "REML", "test": "knha", "level": 95},
    "subgroups": ["sport"],
    "meta_regression": ["mean_age"],
    "sensitivity": {"exclude_high_risk_of_bias": True, "exclude_estimated_sds": True},
    "risk_of_bias_tool": "ROBINS-I",
}

# (study, sport, age, ST sentence(s), st fields, ecg sentence, ecg fields)
STUDIES = [
    ("Alpha 2019", "running", 24,
     "Mean ST elevation in V2 was 0.21 mV (SD 0.08) in 60 athletes and 0.12 mV (SD 0.05) in 58 controls.",
     {"mean_t": 0.21, "sd_t": 0.08, "n_t": 60, "mean_c": 0.12, "sd_c": 0.05, "n_c": 58}, None,
     "An abnormal ECG was found in 7 of 60 athletes and 3 of 58 controls.",
     {"events_t": 7, "n_t": 60, "events_c": 3, "n_c": 58}),
    ("Beta 2020", "cycling", 29,
     "ST elevation (mm, standard gain) was 2.4 (SD 0.9) among 45 cyclists versus 1.3 (SD 0.6) among 44 controls.",
     {"mean_t": 2.4, "sd_t": 0.9, "n_t": 45, "mean_c": 1.3, "sd_c": 0.6, "n_c": 44}, "mm",
     "Abnormal ECG: 0 of 45 cyclists and 4 of 44 controls.",
     {"events_t": 0, "n_t": 45, "events_c": 4, "n_c": 44}),
    ("Gamma 2021", "running", 31,
     "ST elevation was 0.19 mV (SE 0.012; n = 80) in runners and 0.11 mV (SE 0.009; n = 75) in controls.",
     {"mean_t": 0.19, "se_t": 0.012, "n_t": 80, "mean_c": 0.11, "se_c": 0.009, "n_c": 75}, None,
     "No participant in either group (0 of 80 and 0 of 75) had an abnormal ECG.",
     {"events_t": 0, "n_t": 80, "events_c": 0, "n_c": 75}),
    ("Delta 2021", "cycling", 35,
     "Athletes (n = 40): ST elevation 0.17 mV (95% CI 0.14 to 0.20). Controls (n = 42): 0.13 mV (95% CI 0.11 to 0.15).",
     {"mean_t": 0.17, "ci_lower_t": 0.14, "ci_upper_t": 0.20, "n_t": 40,
      "mean_c": 0.13, "ci_lower_c": 0.11, "ci_upper_c": 0.15, "n_c": 42}, None,
     "Abnormal ECGs occurred in 5 of 40 athletes and 4 of 42 controls.",
     {"events_t": 5, "n_t": 40, "events_c": 4, "n_c": 42}),
    ("Epsilon 2022", "rowing", 27,
     "Median ST elevation was 0.18 mV (IQR 0.13 to 0.24) in 52 rowers and 0.10 mV (IQR 0.07 to 0.14) in 50 controls.",
     {"median_t": 0.18, "q1_t": 0.13, "q3_t": 0.24, "n_t": 52,
      "median_c": 0.10, "q1_c": 0.07, "q3_c": 0.14, "n_c": 50}, None,
     "An abnormal ECG was recorded in 6 of 52 rowers and 2 of 50 controls.",
     {"events_t": 6, "n_t": 52, "events_c": 2, "n_c": 50}),
    ("Zeta 2023", "rowing", 40,
     "In 120 athletes ST elevation averaged 0.16 mV (SD 0.07) compared with 0.13 mV (SD 0.06) in 118 controls.",
     {"mean_t": 0.16, "sd_t": 0.07, "n_t": 120, "mean_c": 0.13, "sd_c": 0.06, "n_c": 118}, None,
     "Abnormal ECG findings: 9 of 120 athletes, 6 of 118 controls.",
     {"events_t": 9, "n_t": 120, "events_c": 6, "n_c": 118}),
]
ROB = {"Alpha 2019": "moderate", "Beta 2020": "moderate", "Gamma 2021": "serious",
       "Delta 2021": "low", "Epsilon 2022": "moderate", "Zeta 2023": "low"}


def _quote_for(sentence, name, value):
    return sentence  # the whole sentence is the quote; it contains the number


def build_project(root: Path) -> Path:
    root = Path(root)
    for d in ("fulltext", "extraction", "rob"):
        (root / d).mkdir(parents=True, exist_ok=True)
    (root / "protocol.yaml").write_text(yaml.safe_dump(PROTOCOL, sort_keys=False))
    for sid, sport, age, st_sent, st, unit, ecg_sent, ecg in STUDIES:
        key = sid.replace(" ", "_")
        methods = f"Methods: We enrolled {sport} athletes with a mean age of {age} years."
        text = f"# {sid} (SYNTHETIC)\n\n{methods}\n\n## Results\n\n{st_sent}\n\n{ecg_sent}\n"
        if sid == "Alpha 2019":
            text += "\nEarly repolarisation was present in 14 of 60 athletes.\n"
        (root / "fulltext" / f"{key}.md").write_text(text)
        loc = "Results"
        outcomes = [
            {"outcome": "st_elevation", "data_type": "continuous", **({"unit": unit} if unit else {}),
             "fields": {k: {"value": v, "quote": st_sent, "location": loc} for k, v in st.items()}},
            {"outcome": "abnormal_ecg", "data_type": "binary",
             "fields": {k: {"value": v, "quote": ecg_sent, "location": loc} for k, v in ecg.items()}},
        ]
        if sid == "Alpha 2019":
            q = "Early repolarisation was present in 14 of 60 athletes."
            outcomes.append({"outcome": "early_repol", "data_type": "proportion",
                             "fields": {"events": {"value": 14, "quote": q, "location": loc},
                                        "n": {"value": 60, "quote": q, "location": loc}}})
        rec = {"study_id": sid, "year": int(sid.split()[-1]), "design": "cross-sectional",
               "source_file": f"fulltext/{key}.md", "outcomes": outcomes,
               "moderators": {"sport": {"value": sport, "quote": methods, "location": "Methods"},
                              "mean_age": {"value": age, "quote": methods, "location": "Methods"}}}
        (root / "extraction" / f"{key}.json").write_text(json.dumps(rec, indent=2))
        worst = ROB[sid]
        doms = {f"D{i}": {"judgement": "low", "support": "Described adequately."} for i in range(1, 8)}
        doms["D1"] = {"judgement": worst, "support": "Confounding by age not fully addressed."}
        (root / "rob" / f"{key}.json").write_text(json.dumps(
            {"study_id": sid, "tool": "ROBINS-I", "domains": doms, "overall": worst}, indent=2))
    (root / "prisma.json").write_text(json.dumps({
        "identified": 212, "duplicates_removed": 40, "screened": 172, "excluded_screening": 150,
        "fulltext_assessed": 22, "fulltext_excluded": 16,
        "fulltext_exclusion_reasons": {"no control group": 9, "wrong outcome": 7}}))
    return root


@pytest.fixture
def project(tmp_path):
    return build_project(tmp_path / "synthetic")


@pytest.fixture
def record(project):
    return json.loads((project / "extraction" / "Alpha_2019.json").read_text())


def mutate(project, fname, fn):
    p = project / "extraction" / fname
    rec = json.loads(p.read_text())
    fn(rec)
    p.write_text(json.dumps(rec, indent=2))
    return copy.deepcopy(rec)
