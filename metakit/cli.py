"""``metakit`` command line.

    metakit init PROJECT                 scaffold a new meta-analysis project
    metakit meeting protocol|interpret   virtual review-team meeting (Virtual Lab protocol)
    metakit search --strategy FILE       run a PubMed strategy, merge other databases, deduplicate
    metakit screen --reviewer A|B        AI title/abstract or full-text screener
    metakit screen-reconcile             kappa, conflicts, PRISMA counts, included.csv
    metakit ingest FILE [-p PROJECT]     read the included-studies list from the systematic review
    metakit retrieve [-p PROJECT]        fetch metadata + open-access full texts
    metakit validate [-p PROJECT]        check extraction files (structure, plausibility, provenance)
    metakit reconcile DIR_A DIR_B        compare two independent extractions
    metakit analyze [-p PROJECT]         validate, harmonise, run all analyses, draw figures
    metakit report [-p PROJECT]          write report/report.md from the analysis
    metakit run [-p PROJECT]             validate + analyze + report
    metakit crosscheck [-p PROJECT]      re-run every outcome in R/metafor and compare
    metakit benchmark [NAME]             reproduce published meta-analyses end to end
    metakit convert ...                  one-off statistical conversions (see --help)
"""
from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

from . import __version__

REPO = Path(__file__).resolve().parent.parent


def _project(args) -> Path:
    return Path(getattr(args, "project", None) or ".").resolve()


def _load(project: Path):
    from .protocol import load_protocol
    return load_protocol(project / "protocol.yaml")


def _rob(project: Path, protocol: dict):
    from .rob import load_rob
    tool = protocol.get("risk_of_bias_tool")
    if not tool or tool == "none":
        return None, None, {}
    records, problems = load_rob(project / "rob", tool)
    return (records or None), tool, problems


# ---------------------------------------------------------------------------

def cmd_init(args):
    from .protocol import TEMPLATE
    p = Path(args.project).resolve()
    for d in ("fulltext", "extraction", "rob", "analysis", "report"):
        (p / d).mkdir(parents=True, exist_ok=True)
    proto = p / "protocol.yaml"
    if proto.exists() and not args.force:
        print(f"{proto} exists; leaving it (use --force to overwrite)")
    else:
        proto.write_text(TEMPLATE)
    prisma = p / "prisma.json"
    if not prisma.exists():
        prisma.write_text(json.dumps({
            "identified": None, "duplicates_removed": None, "screened": None,
            "excluded_screening": None, "fulltext_assessed": None, "fulltext_excluded": None,
            "fulltext_exclusion_reasons": {}}, indent=2))
    gi = p / ".gitignore"
    if not gi.exists():
        gi.write_text("# full texts are copyrighted: keep them out of git\nfulltext/*.pdf\nfulltext/*.md\n.env\n")
    print(f"Project ready at {p}\nNext: edit protocol.yaml, then `metakit ingest <included studies file> -p {args.project}`")
    return 0


def cmd_ingest(args):
    from .ingest import read_included, write_studies
    project = _project(args)
    studies = read_included(Path(args.file))
    write_studies(studies, project / "studies.csv")
    print(f"{len(studies)} studies -> {project / 'studies.csv'}")
    for s in studies:
        ids = ", ".join(f"{k}={s[k]}" for k in ("pmid", "pmcid", "doi") if s.get(k)) or "(title only)"
        print(f"  {s['study_id']:<28} {ids}")
    return 0


def cmd_retrieve(args):
    from .ingest import read_studies, write_studies
    from .retrieve import Fetcher, retrieve_all
    project = _project(args)
    studies = read_studies(project / "studies.csv")
    print(f"Retrieving {len(studies)} studies (open access only)...")
    retrieve_all(studies, project / "fulltext", Fetcher(email=args.email))
    write_studies(studies, project / "studies.csv")
    need = [s for s in studies if s.get("status") == "needs_pdf"]
    ok = sum(1 for s in studies if s.get("status") == "fulltext_oa")
    print(f"\n{ok} open-access full texts saved; {len(need)} need a PDF added by hand:")
    for s in need:
        print(f"  fulltext/{s['key']}.pdf   <- {s['study_id']} (doi: {s.get('doi')})")
    return 0


def cmd_validate(args, quiet=False):
    from .extraction import validate_folder
    project = _project(args)
    protocol = _load(project)
    rep = validate_folder(project / (args.extraction if hasattr(args, "extraction") and args.extraction else "extraction"),
                          protocol, project)
    rob_records, tool, problems = _rob(project, protocol)
    from .extraction import Issue
    for sid, prs in problems.items():
        for pr in prs:
            rep.issues.append(Issue("error", sid, f"rob ({tool})", pr))
    md = rep.to_markdown()
    (project / "analysis").mkdir(exist_ok=True)
    (project / "analysis" / "validation.md").write_text(md)
    if not quiet:
        print(md)
    return rep


def cmd_analyze(args):
    from .analysis import run_analysis
    from .extraction import load_extractions
    project = _project(args)
    protocol = _load(project)
    rep = cmd_validate(args, quiet=True)
    print(f"Validation: {len(rep.errors)} errors, {len(rep.warnings)} warnings "
          f"(see analysis/validation.md)")
    if rep.errors and not args.force:
        for e in rep.errors[:15]:
            print(f"  {e}")
        print("Fix the errors above (or pass --force to analyse anyway, not recommended).")
        return 1
    records = load_extractions(project / "extraction")
    rob_records, tool, _ = _rob(project, protocol)
    results = run_analysis(project, protocol, records, rob_records, tool)
    for oid, o in results["outcomes"].items():
        if o.get("main"):
            d = o["main"]["display"]
            print(f"  {o['label']}: {o['measure_name']} {d['estimate']:.3f} "
                  f"[{d['ci_lb']:.3f}, {d['ci_ub']:.3f}], k={o['k']}, I2={o['main']['I2']:.0f}%, "
                  f"GRADE (suggested): {o['grade']['rating']}")
        else:
            print(f"  {o['label']}: k={o.get('k', 0)} ({'; '.join(o.get('warnings', []))})")
    print(f"Results -> {project / 'analysis' / 'results.json'}")
    return 0


def cmd_report(args):
    from .report import write_report
    project = _project(args)
    protocol = _load(project)
    rpath = project / "analysis" / "results.json"
    if not rpath.exists():
        print("run `metakit analyze` first")
        return 1
    results = json.loads(rpath.read_text())
    vpath = project / "analysis" / "validation.md"
    out = write_report(results, protocol, project, vpath.read_text() if vpath.exists() else None)
    print(f"Report -> {out}")
    return 0


def cmd_run(args):
    rc = cmd_analyze(args)
    if rc:
        return rc
    rc = cmd_report(args)
    if not rc and shutil.which("Rscript"):
        return cmd_crosscheck(args)
    return rc


def cmd_reconcile(args):
    from .reconcile import compare, to_markdown
    res = compare(Path(args.a), Path(args.b))
    md = to_markdown(res, Path(args.a).name, Path(args.b).name)
    if args.out:
        Path(args.out).write_text(md)
    print(md)
    return 0 if not res["discrepancies"] else 2


def cmd_crosscheck(args):
    """Independent re-analysis in R/metafor. Any disagreement is a bug to report."""
    project = _project(args)
    if not shutil.which("Rscript"):
        print("Rscript not found: install R and the metafor + jsonlite packages to cross-check")
        return 1
    results = json.loads((project / "analysis" / "results.json").read_text())
    method, test = results["model"]["method"], results["model"]["test"]
    worst, lines = 0.0, []
    for oid, o in results["outcomes"].items():
        if not o.get("main"):
            continue
        with tempfile.TemporaryDirectory() as td:
            out = Path(td) / "r.json"
            p = subprocess.run(["Rscript", str(REPO / "r" / "crosscheck.R"),
                                str(project / "analysis" / oid / "effects.csv"), method, test, str(out)],
                               capture_output=True, text=True)
            if p.returncode:
                print(f"R failed for {oid}:\n{p.stderr}")
                return 1
            r = json.loads(out.read_text())
        m = o["main"]
        pairs = [("estimate", m["estimate"], r["estimate"]), ("ci_lb", m["ci_lb"], r["ci_lb"]),
                 ("ci_ub", m["ci_ub"], r["ci_ub"]), ("tau2", m["tau2"], r["tau2"]), ("I2", m["I2"], r["I2"])]
        if "egger" in o and "egger_p" in r:
            pairs.append(("egger_p", o["egger"]["pval"], r["egger_p"]))
            pairs.append(("trimfill_k0", o["trim_and_fill"]["k0"], r["trimfill_k0"]))
        for name, a, b in pairs:
            diff = abs(a - b) / max(1.0, abs(b))
            worst = max(worst, diff)
            lines.append(f"  {oid:<20} {name:<12} metakit {a:>12.6f}   metafor {b:>12.6f}   rel.diff {diff:.1e}")
    print(f"Cross-check against metafor {r.get('metafor_version')}:")
    print("\n".join(lines))
    ok = worst < 1e-4
    print(f"\n{'PASS' if ok else 'FAIL'}: largest relative difference {worst:.2e} (tolerance 1e-4)")
    (project / "analysis" / "crosscheck.txt").write_text("\n".join(lines) + f"\nworst {worst:.2e}\n")
    return 0 if ok else 1


def cmd_benchmark(args):
    """Run each benchmark project from scratch and compare to published / metafor values."""
    from .analysis import run_analysis
    from .extraction import load_extractions, validate_folder
    from .protocol import load_protocol
    from .reconcile import compare

    bdir = REPO / "benchmarks"
    names = [args.name] if args.name else sorted(p.name for p in bdir.iterdir() if (p / "expected.json").exists())
    all_ok = True
    summary = {}
    for name in names:
        src = bdir / name
        with tempfile.TemporaryDirectory() as td:
            proj = Path(td) / name
            shutil.copytree(src, proj)
            protocol = load_protocol(proj / "protocol.yaml")
            rep = validate_folder(proj / "extraction", protocol, proj)
            records = load_extractions(proj / "extraction")
            results = run_analysis(proj, protocol, records, None, None)
            if args.keep:
                dest = Path(args.keep) / name
                shutil.rmtree(dest, ignore_errors=True)
                shutil.copytree(proj, dest)
        exp = json.loads((src / "expected.json").read_text())
        print(f"\n=== {name}: {protocol['title']}")
        print(f"validation: {len(rep.errors)} errors, {len(rep.warnings)} warnings; "
              f"{rep.n_quotes_verified}/{rep.n_quotes_checked} quotes verified against source")
        ok = rep.ok
        summary[name] = {}
        if "published" in exp:
            pub = exp["published"]
            o = results["outcomes"][pub["outcome"]]["main"]["display"]
            dec = pub["decimals"]
            got = [round(o["estimate"], dec), round(o["ci_lb"], dec), round(o["ci_ub"], dec)]
            want = [pub["estimate"], pub["ci_lb"], pub["ci_ub"]]
            match = got == want
            ok &= match
            print(f"published  {want}  reproduced {got}  {'MATCH' if match else 'MISMATCH'}")
            print(f"           ({pub['source']})")
            summary[name]["published"] = {"want": want, "got": got, "match": match}
        mf = exp["metafor"]
        o = results["outcomes"][mf["outcome"]]
        checks = {"estimate": o["main"]["estimate"], "ci_lb": o["main"]["ci_lb"], "ci_ub": o["main"]["ci_ub"],
                  "tau2": o["main"]["tau2"], "I2": o["main"]["I2"], "QE": o["main"]["QE"]}
        if "trimfill_k0" in mf:
            checks["trimfill_k0"] = o["trim_and_fill"]["k0"]
            checks["egger_p"] = o["egger"]["pval"]
        if "metareg_slope" in mf:
            checks["metareg_slope"] = o["meta_regression"]["ablat"]["beta"][1]
            checks["subgroup_QM"] = o["subgroups"]["alloc"]["test_of_differences"]["QM"]
        worst = 0.0
        for key, val in checks.items():
            diff = abs(val - mf[key]) / max(1.0, abs(mf[key]))
            worst = max(worst, diff)
            print(f"  {key:<14} metakit {val:>13.6f}   metafor {mf[key]:>13.6f}   rel.diff {diff:.1e}")
        ok &= worst < 1e-3
        summary[name]["metafor_worst_rel_diff"] = worst
        print(f"{'PASS' if ok else 'FAIL'}: {name}")
        all_ok &= ok
    if args.gold and args.candidate:
        res = compare(Path(args.gold), Path(args.candidate))
        print(f"\nExtraction accuracy vs gold: {res['n_agree']}/{res['n_fields']} fields "
              f"({100 * res['agreement']:.1f}%)")
        for d in res["discrepancies"][:30]:
            print(f"  {d['study']} / {d['outcome']} / {d['field']}: gold={d['a']} candidate={d['b']}")
        summary["extraction_accuracy"] = res["agreement"]
    if args.json:
        Path(args.json).write_text(json.dumps(summary, indent=2))
    print(f"\n{'ALL BENCHMARKS PASSED' if all_ok else 'BENCHMARK FAILURE'}")
    return 0 if all_ok else 1


def _llm(args):
    from .team import anthropic_llm
    return anthropic_llm()


def cmd_search(args):
    from .screening import build_screening_set, run_search
    from .retrieve import Fetcher
    project = _project(args)
    strategy = Path(args.strategy).read_text()
    # accept pubmed-search-builder's final_strategy.md: use the last fenced block
    import re as _re
    blocks = _re.findall(r"```(?:text|pubmed)?\s*\n(.*?)```", strategy, _re.S)
    if blocks:
        strategy = blocks[-1]
    entry = run_search(strategy, project / "search", Fetcher(email=args.email))
    ris = dict(x.split("=", 1) for x in (args.ris or []))
    counts = build_screening_set(project, ris)
    print(f"PubMed: {entry['count']} records (strategy sha256 {entry['strategy_sha256'][:12]})")
    print(f"All sources: {counts['identified']} identified, {counts['duplicates_removed']} duplicates removed, "
          f"{counts['to_screen']} to screen -> screening/records.json")
    return 0


def _stage_records(project, stage):
    recs = json.loads((project / "screening" / "records.json").read_text())
    if stage == "full_text":
        ta = json.loads((project / "screening" / "title_abstract_result.json").read_text())
        keep = set(ta["included"])
        recs = [r for r in recs if r["id"] in keep]
    return recs


def cmd_screen(args):
    from .screening import screen_with_llm
    from .team import DEFAULT_MODEL
    project = _project(args)
    protocol = _load(project)
    if not (protocol.get("eligibility") or {}).get("include"):
        print("protocol.yaml needs eligibility.include / eligibility.exclude criteria before screening")
        return 1
    recs = _stage_records(project, args.stage)
    out = project / "screening" / f"decisions_{args.stage}_{args.reviewer}.jsonl"
    n = screen_with_llm(_llm(args), args.model or DEFAULT_MODEL, protocol, recs, f"AI-{args.reviewer}", out, args.stage)
    print(f"{n} records screened by reviewer {args.reviewer} -> {out}")
    return 0


def cmd_screen_reconcile(args):
    from .screening import load_decisions, prisma_counts, reconcile_screening, screening_report, write_included
    project = _project(args)
    sdir = project / "screening"
    recs = _stage_records(project, args.stage)
    res_path = sdir / f"resolutions_{args.stage}.json"
    resolutions = json.loads(res_path.read_text()) if res_path.exists() else {}
    r = reconcile_screening(recs, load_decisions(sdir / f"decisions_{args.stage}_A.jsonl"),
                            load_decisions(sdir / f"decisions_{args.stage}_B.jsonl"), args.stage, resolutions)
    (sdir / f"{args.stage}_result.json").write_text(json.dumps(r, indent=1))
    ta = json.loads((sdir / "title_abstract_result.json").read_text())
    ft = r if args.stage == "full_text" else None
    if ft is None and (sdir / "full_text_result.json").exists():
        ft = json.loads((sdir / "full_text_result.json").read_text())
    dups = json.loads((sdir / "duplicates.json").read_text())
    search = {"identified": ta["n"] + len(dups), "duplicates_removed": len(dups)}
    report = screening_report(ta, ft)
    (sdir / "screening_report.md").write_text(report)
    print(report)
    if r["missing"] or r["unresolved"]:
        print(f"Not final: {len(r['missing'])} records unscreened, {len(r['unresolved'])} conflicts to resolve "
              f"(write {{\"<record id>\": \"include\"|\"exclude\"}} to {res_path.name}).")
        return 2
    (project / "prisma.json").write_text(json.dumps(prisma_counts(search, ta, ft), indent=2))
    if args.stage == "full_text":
        write_included(recs, r["included"], project / "included.csv")
        print(f"{len(r['included'])} studies included -> included.csv; next: metakit ingest included.csv -p {args.project}")
    return 0


def cmd_meeting(args):
    from .team import interpretation_meeting, protocol_meeting
    project = _project(args)
    mdir = project / "meetings"
    log = lambda s: print(s, flush=True)
    if args.kind == "protocol":
        if not args.question:
            print("--question is required for a protocol meeting")
            return 1
        res = protocol_meeting(args.question, args.field, _llm(args), mdir, args.rounds, log)
        print(f"Transcript -> {mdir / 'protocol_meeting.md'}")
        if res["protocol_error"]:
            print(f"The meeting's protocol did not validate: {res['protocol_error']}. Edit protocol.yaml by hand from the transcript.")
            return 2
        print(f"Draft protocol -> {mdir / 'protocol.draft.yaml'} (review it, then copy to protocol.yaml)")
        return 0
    protocol = _load(project)
    results = json.loads((project / "analysis" / "results.json").read_text())
    res = interpretation_meeting(results, protocol, args.field, _llm(args), mdir, args.rounds, log)
    print(f"Transcript -> {mdir / 'interpretation_meeting.md'}; draft discussion -> {mdir / 'discussion.draft.md'}")
    if res["unverified_numbers"]:
        print("WARNING: numbers not found in results.json: " + ", ".join(res["unverified_numbers"]))
        return 2
    return 0


def cmd_convert(args):
    from . import convert as C
    if args.kind == "median":
        r = C.mean_sd_from_quantiles(args.n, args.median, args.q1, args.q3, args.min, args.max)
    elif args.kind == "se":
        r = {"sd": C.sd_from_se(args.se, args.n)}
    elif args.kind == "ci":
        r = {"sd": C.sd_from_ci(args.lower, args.upper, args.n)}
    elif args.kind == "combine":
        r = C.combine_groups(args.n1, args.mean1, args.sd1, args.n2, args.mean2, args.sd2)
    else:
        return 1
    print(json.dumps(r, indent=2))
    return 0


def main(argv=None):
    ap = argparse.ArgumentParser(prog="metakit", description="Auditable meta-analysis toolkit")
    ap.add_argument("--version", action="version", version=f"metakit {__version__}")
    sub = ap.add_subparsers(dest="cmd", required=True)

    def with_project(p):
        p.add_argument("-p", "--project", default=".", help="project directory (default: current)")
        return p

    s = sub.add_parser("init", help="scaffold a project")
    s.add_argument("project")
    s.add_argument("--force", action="store_true")
    s.set_defaults(fn=cmd_init)
    s = with_project(sub.add_parser("ingest", help="read the included-studies list"))
    s.add_argument("file")
    s.set_defaults(fn=cmd_ingest)
    s = with_project(sub.add_parser("retrieve", help="fetch open-access full texts"))
    s.add_argument("--email", help="contact email for NCBI (or set METAKIT_EMAIL)")
    s.set_defaults(fn=cmd_retrieve)
    s = with_project(sub.add_parser("validate", help="validate extraction files"))
    s.add_argument("--extraction", default="extraction", help="extraction folder inside the project")
    s.set_defaults(fn=lambda a: 0 if cmd_validate(a).ok else 1)
    s = sub.add_parser("reconcile", help="compare two extraction folders")
    s.add_argument("a")
    s.add_argument("b")
    s.add_argument("--out")
    s.set_defaults(fn=cmd_reconcile)
    for name, fn in (("analyze", cmd_analyze), ("run", cmd_run)):
        s = with_project(sub.add_parser(name))
        s.add_argument("--force", action="store_true", help="analyse despite validation errors")
        s.add_argument("--extraction", default="extraction")
        s.set_defaults(fn=fn)
    s = with_project(sub.add_parser("report"))
    s.set_defaults(fn=cmd_report)
    s = with_project(sub.add_parser("crosscheck", help="re-run in R/metafor and compare"))
    s.set_defaults(fn=cmd_crosscheck)
    s = sub.add_parser("benchmark", help="reproduce published meta-analyses")
    s.add_argument("name", nargs="?")
    s.add_argument("--gold", help="gold extraction folder (for extraction accuracy)")
    s.add_argument("--candidate", help="agent extraction folder to score against --gold")
    s.add_argument("--keep", help="copy the benchmark outputs (figures, report) here")
    s.add_argument("--json", help="write a JSON summary here")
    s.set_defaults(fn=cmd_benchmark)
    s = with_project(sub.add_parser("search", help="run a PubMed strategy and build the screening set"))
    s.add_argument("--strategy", required=True, help="text file with the Boolean strategy (or pubmed-search-builder's final_strategy.md)")
    s.add_argument("--ris", nargs="*", help="other databases as SOURCE=file.ris, e.g. Embase=embase.ris")
    s.add_argument("--email")
    s.set_defaults(fn=cmd_search)
    s = with_project(sub.add_parser("screen", help="AI screener (needs ANTHROPIC_API_KEY)"))
    s.add_argument("--stage", choices=["title_abstract", "full_text"], default="title_abstract")
    s.add_argument("--reviewer", choices=["A", "B"], required=True)
    s.add_argument("--model")
    s.set_defaults(fn=cmd_screen)
    s = with_project(sub.add_parser("screen-reconcile", help="compare reviewers A and B; kappa, conflicts, PRISMA"))
    s.add_argument("--stage", choices=["title_abstract", "full_text"], default="title_abstract")
    s.set_defaults(fn=cmd_screen_reconcile)
    s = with_project(sub.add_parser("meeting", help="virtual review-team meeting (needs ANTHROPIC_API_KEY)"))
    s.add_argument("kind", choices=["protocol", "interpret"])
    s.add_argument("--question")
    s.add_argument("--field", default="clinical medicine", help="domain expert's field, e.g. 'sports cardiology'")
    s.add_argument("--rounds", type=int, default=2)
    s.set_defaults(fn=cmd_meeting)

    s = sub.add_parser("convert", help="statistical conversions")
    s.add_argument("kind", choices=["median", "se", "ci", "combine"])
    for a in ("n", "n1", "n2"):
        s.add_argument(f"--{a}", type=int)
    for a in ("median", "q1", "q3", "min", "max", "se", "lower", "upper", "mean1", "sd1", "mean2", "sd2"):
        s.add_argument(f"--{a}", type=float)
    s.set_defaults(fn=cmd_convert)

    args = ap.parse_args(argv)
    rc = args.fn(args)
    return rc if isinstance(rc, int) else 0


if __name__ == "__main__":
    sys.exit(main())
