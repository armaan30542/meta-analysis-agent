"""The browser app's Python layer (run in Pyodide) - same code, tested here."""
import base64
import importlib.util
import io
import json
import zipfile
from pathlib import Path

from conftest import PROTOCOL, build_project
from metakit import web
from metakit.extraction import load_extractions

ROOT = Path(__file__).resolve().parent.parent


def _project_payload(tmp_path):
    proj = build_project(tmp_path / "p")
    recs = [{k: v for k, v in r.items() if k != "_path"} for r in load_extractions(proj / "extraction")]
    sources = {f"fulltext/{p.name}": p.read_text() for p in (proj / "fulltext").glob("*.md")}
    rob = {}
    for p in (proj / "rob").glob("*.json"):
        r = json.loads(p.read_text())
        rob[r.pop("study_id")] = r
    return recs, sources, rob, json.loads((proj / "prisma.json").read_text())


def test_analyze_end_to_end(tmp_path):
    recs, sources, rob, prisma = _project_payload(tmp_path)
    proto = dict(PROTOCOL)
    out = web.analyze(json.dumps(proto), json.dumps(recs), json.dumps(sources), json.dumps(rob), json.dumps(prisma))
    assert out["validation"]["ok"], out["validation"]["errors"]
    assert out["validation"]["n_quotes_verified"] == out["validation"]["n_quotes_checked"] > 60
    assert out["results"]["outcomes"]["st_elevation"]["k"] == 6
    assert "st_elevation/forest.png" in out["figures"] and "rob.png" in out["figures"]
    assert base64.b64decode(out["figures"]["prisma.png"])[:4] == b"\x89PNG"
    assert "Knapp-Hartung" in out["report_md"]
    names = zipfile.ZipFile(io.BytesIO(base64.b64decode(out["zip_b64"]))).namelist()
    assert "meta-analysis/report/report.md" in names and "meta-analysis/analysis/results.json" in names


def test_analyze_blocks_on_errors(tmp_path):
    recs, sources, rob, prisma = _project_payload(tmp_path)
    recs[0]["outcomes"][0]["fields"]["mean_t"]["value"] = 0.99
    out = web.analyze(json.dumps(PROTOCOL), json.dumps(recs), json.dumps(sources))
    assert out["results"] is None and not out["validation"]["ok"]
    forced = web.analyze(json.dumps(PROTOCOL), json.dumps(recs), json.dumps(sources), allow_errors=True)
    assert forced["results"] is not None


def test_manual_rows_reproduce_bcg():
    ref = json.loads((ROOT / "tests" / "fixtures" / "metafor_reference.json").read_text())["bcg"]
    outcome = {"id": "tb", "label": "TB", "data_type": "binary", "measure": "RR", "primary": True}
    rows = [{"study_id": f"{r['author']} {r['year']}", "year": r["year"], "events_t": r["tpos"],
             "n_t": r["tpos"] + r["tneg"], "events_c": r["cpos"], "n_c": str(r["cpos"] + r["cneg"]),
             "ablat": r["ablat"], "alloc": r["alloc"]} for r in ref["data"]]
    recs = web.rows_to_records(rows, outcome, who="Armaan")
    assert recs[0]["moderators"]["alloc"]["value"] == "random"
    proto = {"title": "BCG", "outcomes": [outcome], "model": {"method": "REML", "test": "z"},
             "subgroups": ["alloc"], "meta_regression": ["ablat"]}
    out = web.analyze(json.dumps(proto), json.dumps(recs))
    assert out["validation"]["ok"]  # manual entries pass (with a no-source warning)
    d = out["results"]["outcomes"]["tb"]["main"]["display"]
    assert [round(d["estimate"], 2), round(d["ci_lb"], 2), round(d["ci_ub"], 2)] == [0.49, 0.34, 0.70]


def test_validate_one_catches_doctored_quote():
    src = "Mean ST elevation in V2 was 0.21 mV (SD 0.08) in 60 athletes and 0.12 mV (SD 0.05) in 58 controls."
    fake = src.replace("0.21", "0.31")
    f = lambda v, q: {"value": v, "quote": q, "location": "Results"}
    rec = {"study_id": "X 2020", "outcomes": [{"outcome": "st_elevation", "data_type": "continuous", "fields": {
        "n_t": f(60, src), "mean_t": f(0.31, fake), "sd_t": f(0.08, src),
        "n_c": f(58, src), "mean_c": f(0.12, src), "sd_c": f(0.05, src)}}]}
    out = web.validate_one(json.dumps(PROTOCOL), json.dumps(rec), src)
    assert not out["ok"]
    assert any("0.31" in e["message"] for e in out["errors"])


def test_reconcile_and_prompts():
    a = [{"study_id": "S", "outcomes": [{"outcome": "o", "data_type": "proportion",
          "fields": {"events": {"value": 3}, "n": {"value": 20}}}]}]
    b = json.loads(json.dumps(a))
    b[0]["outcomes"][0]["fields"]["events"]["value"] = 4
    r = web.reconcile(json.dumps(a), json.dumps(b))
    assert len(r["discrepancies"]) == 1
    p = web.extraction_user_prompt(json.dumps(PROTOCOL), "Alpha 2019", "TEXT")
    assert "st_elevation" in p and "Alpha 2019" in p and "sport" in p
    assert "validator rejected" in web.fix_prompt([{"where": "x", "message": "bad"}])
    assert "binary" in web.data_types()


def test_jats_passthrough():
    md = web.jats("<article><front><article-meta><title-group><article-title>T</article-title>"
                  "</title-group></article-meta></front><body><p>Hello 0.21</p></body></article>")
    assert md.startswith("# T") and "Hello 0.21" in md


def test_web_bundle_is_current():
    spec = importlib.util.spec_from_file_location("build_web", ROOT / "scripts" / "build_web.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    bundle = ROOT / "docs" / "app" / "metakit.zip"
    assert bundle.exists(), "run: python scripts/build_web.py"
    assert bundle.read_bytes() == mod.build_bytes(), "web bundle is stale: run python scripts/build_web.py"
