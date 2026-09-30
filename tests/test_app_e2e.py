"""End-to-end tests of the web app in a real browser (Playwright + Chromium).

Opt-in because they download Pyodide (~30 MB):  METAKIT_BROWSER_TESTS=1 pytest tests/test_app_e2e.py
The Anthropic API is mocked, so no key is needed and nothing is billed.
"""
import functools
import http.server
import json
import os
import threading
from pathlib import Path

import pytest

pytestmark = pytest.mark.skipif(not os.environ.get("METAKIT_BROWSER_TESTS"), reason="set METAKIT_BROWSER_TESTS=1")
DOCS = Path(__file__).resolve().parent.parent / "docs"

PAPERS = {
    "Alpha 2019": "Methods: We enrolled 60 runners.\n\nResults\n\nMean ST elevation in V2 was 0.21 mV (SD 0.08) in 60 athletes "
                  "and 0.12 mV (SD 0.05) in 58 controls. " + "Additional discussion text. " * 20,
    "Beta 2020": "Methods: cyclists.\n\nResults\n\nST elevation was 0.19 mV (SD 0.07) among 45 cyclists versus 0.13 mV (SD 0.06) "
                 "among 44 controls. " + "Additional discussion text. " * 20,
}


def record(study, doctor=False, alt_n=False):
    text = PAPERS[study]
    sent = text.split("Results\n\n")[1].split(". ")[0] + "."
    import re
    nums = re.findall(r"\d+\.\d+|\d+", sent.replace("V2", "V"))
    mt, sdt, nt, mc, sdc, nc = (float(nums[0]), float(nums[1]), int(nums[2]), float(nums[3]), float(nums[4]), int(nums[5]))
    f = lambda v, q=sent: {"value": v, "quote": q, "location": "Results"}
    fields = {"mean_t": f(mt), "sd_t": f(sdt), "n_t": f(nt), "mean_c": f(mc), "sd_c": f(sdc), "n_c": f(nc)}
    if doctor:
        fields["mean_t"] = f(round(mt + 0.1, 2), sent.replace(str(mt), f"{mt + 0.1:.2f}"))
    if alt_n:
        fields["n_c"] = f(nt)  # plausible misread: the other group's n (still in the quote)
    return {"study_id": study, "year": int(study.split()[-1]), "design": "cross-sectional",
            "outcomes": [{"outcome": "st_elevation", "data_type": "continuous", "unit": "mV", "fields": fields}]}


@pytest.fixture(scope="module")
def server():
    handler = functools.partial(http.server.SimpleHTTPRequestHandler, directory=str(DOCS))
    httpd = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
    t = threading.Thread(target=httpd.serve_forever, daemon=True)
    t.start()
    yield f"http://127.0.0.1:{httpd.server_address[1]}"
    httpd.shutdown()


@pytest.fixture(scope="module")
def browser():
    from playwright.sync_api import sync_playwright
    with sync_playwright() as p:
        b = p.chromium.launch()
        yield b
        b.close()


def open_app(browser, server):
    page = browser.new_page(viewport={"width": 1280, "height": 900})
    page.on("dialog", lambda d: d.accept())
    errors = []
    page.on("pageerror", lambda e: errors.append(str(e)))
    page.goto(f"{server}/app/")
    page.wait_for_selector("#engine.ready", timeout=180_000)
    return page, errors


def test_bcg_example_reproduces_published_result(browser, server):
    page, errors = open_app(browser, server)
    page.click("#loadExample")
    page.click("nav.steps button[data-step=results]")
    page.click("#runAnalysis")
    page.wait_for_selector("#results .summary", timeout=120_000)
    text = page.inner_text("#results")
    assert "0.49" in text and "95% CI 0.34 to 0.70" in text
    assert "13" in text and "92%" in text
    assert page.locator("#results figure img").count() >= 5
    assert "Test for subgroup differences" in text and "Meta-regression on ablat" in text
    page.screenshot(path="/tmp/app_results.png", full_page=False)
    assert not errors, errors


def test_ai_extraction_catches_doctored_number_and_reconciles(browser, server):
    page, errors = open_app(browser, server)
    page.click("#resetAll")
    page.fill("#p-title", "ST elevation test")
    page.fill("#outcomes input[data-f=label]", "ST elevation")
    page.fill("#outcomes input[data-f=id]", "st_elevation")
    page.dispatch_event("#outcomes input[data-f=id]", "change")
    page.select_option("#outcomes select[data-f=data_type]", "continuous")
    page.fill("#outcomes input[data-f=unit]", "mV")
    page.dispatch_event("#outcomes input[data-f=unit]", "change")

    seen = {}
    calls = []

    def handle(route):
        body = json.loads(route.request.post_data)
        assert route.request.headers["anthropic-dangerous-direct-browser-access"] == "true"
        first = body["messages"][0]["content"]
        study = "Alpha 2019" if "Alpha 2019" in first else "Beta 2020"
        n = len(body["messages"])
        calls.append((study, n))
        if n == 1:
            k = seen.get(study, 0)
            seen[study] = k + 1
            rec = record(study, doctor=(k == 0 and study == "Alpha 2019"), alt_n=(k == 1 and study == "Alpha 2019"))
        else:
            assert "validator rejected" in body["messages"][-1]["content"]
            rec = record(study)
        route.fulfill(status=200, content_type="application/json",
                      body=json.dumps({"content": [{"type": "text", "text": json.dumps(rec)}]}))

    page.route("https://api.anthropic.com/v1/messages", handle)
    page.click("[data-go=data]")
    page.click("#tab-ai")
    page.fill("#apiKey", "sk-ant-test")
    for name, text in PAPERS.items():
        page.fill("#pasteName", name)
        page.fill("#pasteText", text)
        page.click("#addPasted")
    page.click("#extractAll")
    page.wait_for_function("document.querySelector('#extractStatus').textContent.startsWith('Done')", timeout=120_000)
    log = page.inner_text("#paperList")
    assert "attempt 1: 1 errors" in log      # the doctored 0.31 was caught...
    assert "attempt 2: 0 errors" in log      # ...sent back, and fixed
    assert ("Alpha 2019", 3) in calls
    assert "to decide on the Review step" in log

    page.click("nav.steps button[data-step=review]")
    page.click("#runValidate")
    page.wait_for_selector("#validation .msg.ok")
    assert "quotes verified in the papers" in page.inner_text("#validation")
    diff = page.inner_text("#disagreements")
    assert "n_c" in diff and "58" in diff and "60" in diff
    page.screenshot(path="/tmp/app_review.png", full_page=True)

    page.click("nav.steps button[data-step=results]")
    page.click("#runAnalysis")
    page.wait_for_selector("#results .summary", timeout=120_000)
    text = page.inner_text("#results")
    assert "Mean difference" in text and "mV" in text
    assert "only two studies" in text
    assert not errors, errors
