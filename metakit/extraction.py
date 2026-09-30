"""Data-extraction records and their validation.

One JSON file per study lives in ``<project>/extraction/``. Every number carries the exact
quote it came from and where in the paper that quote is. The validator enforces three
layers of checks, from cheapest to strongest:

1. **Structure**: the right fields exist for the outcome's data type.
2. **Plausibility**: events <= n, SD > 0, the mean inside its CI, quartiles in order ...
3. **Provenance**: the number actually appears in its quote, and the quote actually appears
   in the full text the extractor was given. This is what catches an LLM that "reads" a
   number that is not in the paper.

See ``docs/extraction-guide.md`` for the format with worked examples.
"""
from __future__ import annotations

import difflib
import json
import math
import re
import unicodedata
from dataclasses import dataclass, field
from pathlib import Path

ARM_STATS = ("mean", "sd", "se", "ci_lower", "ci_upper", "median", "q1", "q3", "min", "max")

DATA_TYPES = {
    "binary": {"required": ("events_t", "n_t", "events_c", "n_c"), "optional": ()},
    "continuous": {
        "required": ("n_t", "n_c"),
        "optional": tuple(f"{s}_{a}" for a in ("t", "c") for s in ARM_STATS),
    },
    "single_group": {"required": ("n",), "optional": ARM_STATS},
    "proportion": {"required": ("events", "n"), "optional": ()},
    "correlation": {"required": ("r", "n"), "optional": ()},
    "generic": {"required": ("estimate",), "optional": ("se", "ci_lower", "ci_upper", "n")},
}
INTEGER_FIELDS = {"n", "n_t", "n_c", "events", "events_t", "events_c"}


@dataclass
class Issue:
    level: str  # "error" | "warning"
    study: str
    where: str
    message: str

    def __str__(self):
        return f"[{self.level.upper()}] {self.study} / {self.where}: {self.message}"


@dataclass
class ValidationReport:
    issues: list = field(default_factory=list)
    n_studies: int = 0
    n_values: int = 0
    n_quotes_verified: int = 0
    n_quotes_checked: int = 0

    @property
    def errors(self):
        return [i for i in self.issues if i.level == "error"]

    @property
    def warnings(self):
        return [i for i in self.issues if i.level == "warning"]

    @property
    def ok(self):
        return not self.errors

    def to_markdown(self) -> str:
        lines = ["# Extraction validation report", "",
                 f"- Studies checked: {self.n_studies}",
                 f"- Numeric values checked: {self.n_values}",
                 f"- Quotes verified against full text: {self.n_quotes_verified} of {self.n_quotes_checked} checked",
                 f"- Errors: {len(self.errors)}", f"- Warnings: {len(self.warnings)}", ""]
        if self.ok:
            lines.append("**No errors.** Warnings (if any) still need a human look before analysis.")
        else:
            lines.append("**Fix every error before running the analysis.**")
        for level, items in (("Errors", self.errors), ("Warnings", self.warnings)):
            if items:
                lines += ["", f"## {level}", ""]
                lines += [f"- **{i.study}** / `{i.where}`: {i.message}" for i in items]
        return "\n".join(lines) + "\n"


# ---------------------------------------------------------------------------
# text normalisation and number matching
# ---------------------------------------------------------------------------

_NUM_RE = re.compile(r"(?<![\w.])[-+]?\d{1,3}(?:,\d{3})+(?:\.\d+)?|(?<![\w.])[-+]?\d*\.?\d+")


def normalize_text(s: str) -> str:
    s = unicodedata.normalize("NFKC", s)
    s = s.replace("\u2212", "-").replace("\u2013", "-").replace("\u2014", "-")
    s = s.replace("\u00b7", ".")  # Lancet-style mid-dot decimals
    s = s.replace("\u00a0", " ").replace("\u2009", " ")
    s = re.sub(r"\s+", " ", s)
    return s.strip().lower()


def numbers_in(text: str) -> list[tuple[float, int]]:
    """All numeric tokens in ``text`` as (value, decimals shown)."""
    text = normalize_text(text)
    out = []
    for tok in _NUM_RE.findall(text):
        clean = tok.replace(",", "").lstrip("+")
        try:
            val = float(clean)
        except ValueError:
            continue
        dec = len(clean.split(".")[1]) if "." in clean else 0
        out.append((val, dec))
        if clean.startswith("-"):  # "20-30" style ranges: also accept the bare number
            out.append((abs(val), dec))
    return out


def value_in_quote(value: float, quote: str) -> bool:
    """True if ``value`` appears in ``quote`` exactly (4 matches "4.0"; 0.125 does not match "0.12").

    Extractors must copy numbers as printed. Any rounding or recalculation belongs in a
    ``derived`` field with a written derivation, never silently in ``value``.
    """
    for tok, _ in numbers_in(quote):
        if abs(tok - value) <= 1e-9 * max(1.0, abs(tok)):
            return True
    return False


def _strip_with_map(x: str):
    kept, pos = [], []
    for i, ch in enumerate(x):
        if ch.isalnum() or ch == ".":
            kept.append(ch)
            pos.append(i)
    return "".join(kept), pos


def quote_in_source(quote: str, source: str, threshold: float = 0.9):
    """Locate ``quote`` in ``source``. Exact after normalisation, else fuzzy.

    Fuzzy matching tolerates line breaks, hyphenation and PDF-extraction noise.
    Returns ``(found, similarity, window)`` where ``window`` is the matching stretch of the
    *source* (normalised), so callers can check numbers against the paper itself rather
    than against the extractor's copy of the sentence.
    """
    q = normalize_text(quote)
    s = normalize_text(source)
    if not q:
        return False, 0.0, ""
    i = s.find(q)
    if i >= 0:
        return True, 1.0, s[i:i + len(q)]
    qs, _ = _strip_with_map(q)
    ss, pos = _strip_with_map(s)
    if not qs or not ss:
        return False, 0.0, ""

    def window_for(a, b):
        a = max(0, min(a, len(pos) - 1))
        b = max(a, min(b, len(pos) - 1))
        return s[pos[a]:pos[b] + 1]

    j = ss.find(qs)
    if j >= 0:
        return True, 1.0, window_for(j, j + len(qs) - 1)
    sm = difflib.SequenceMatcher(None, ss, qs, autojunk=False)
    m = sm.find_longest_match(0, len(ss), 0, len(qs))
    if m.size == 0:
        return False, 0.0, ""
    # slide a window of the quote's length around the anchor and keep the best alignment
    base = m.a - m.b
    best, best_start = 0.0, max(0, base)
    for off in range(-20, 21):
        start = max(0, base + off)
        win = ss[start:start + len(qs)]
        r = difflib.SequenceMatcher(None, win, qs, autojunk=False).ratio()
        if r > best:
            best, best_start = r, start
    return best >= threshold, best, window_for(best_start, best_start + len(qs) - 1)


# ---------------------------------------------------------------------------
# loading
# ---------------------------------------------------------------------------

def load_extractions(folder: Path) -> list[dict]:
    folder = Path(folder)
    records = []
    for path in sorted(folder.glob("*.json")):
        with open(path, encoding="utf-8") as fh:
            try:
                rec = json.load(fh)
            except json.JSONDecodeError as exc:
                raise ValueError(f"{path.name}: invalid JSON ({exc})") from exc
        rec["_path"] = str(path)
        records.append(rec)
    return records


def field_value(fields: dict, name: str):
    f = fields.get(name)
    if f is None:
        return None
    if isinstance(f, dict):
        return f.get("value")
    return f


# ---------------------------------------------------------------------------
# validation
# ---------------------------------------------------------------------------

def _num(x):
    return isinstance(x, (int, float)) and not isinstance(x, bool) and math.isfinite(x)


def _arm_complete(fields, suffix):
    g = lambda s: field_value(fields, f"{s}{suffix}")
    if g("mean") is not None and any(g(s) is not None for s in ("sd", "se")):
        return True
    if g("mean") is not None and g("ci_lower") is not None and g("ci_upper") is not None:
        return True
    if g("median") is not None and ((g("q1") is not None and g("q3") is not None)
                                    or (g("min") is not None and g("max") is not None)):
        return True
    return False


def _check_plausibility(study, where, dt, fields, issues):
    g = lambda n: field_value(fields, n)
    E = lambda msg: issues.append(Issue("error", study, where, msg))
    W = lambda msg: issues.append(Issue("warning", study, where, msg))

    for name in INTEGER_FIELDS:
        v = g(name)
        if v is not None and _num(v):
            if v < 0:
                E(f"{name} is negative")
            elif abs(v - round(v)) > 1e-9:
                E(f"{name}={v} should be a whole number of participants/events")
    if dt == "binary":
        for a in ("t", "c"):
            e, n = g(f"events_{a}"), g(f"n_{a}")
            if _num(e) and _num(n) and e > n:
                E(f"events_{a} ({e}) exceeds n_{a} ({n})")
    if dt == "proportion" and _num(g("events")) and _num(g("n")) and g("events") > g("n"):
        E("events exceed n")
    if dt == "correlation" and _num(g("r")) and not -1 < g("r") < 1:
        E("r must be strictly between -1 and 1")
    suffixes = ("_t", "_c") if dt == "continuous" else ("",) if dt == "single_group" else ()
    for sfx in suffixes:
        v = {s: g(f"{s}{sfx}") for s in ARM_STATS}
        arm = {"_t": "treatment arm", "_c": "control arm", "": "group"}[sfx]
        if not _arm_complete(fields, sfx):
            E(f"{arm}: need mean+SD, mean+SE, mean+CI, or median with IQR and/or range")
        for s in ("sd", "se"):
            if v[s] is not None and _num(v[s]) and v[s] <= 0:
                E(f"{s}{sfx} must be positive")
        if all(v[s] is not None for s in ("mean", "ci_lower", "ci_upper")):
            if not v["ci_lower"] <= v["mean"] <= v["ci_upper"]:
                E(f"{arm}: mean {v['mean']} is outside its CI [{v['ci_lower']}, {v['ci_upper']}]")
        order = [v[s] for s in ("min", "q1", "median", "q3", "max") if v[s] is not None]
        if any(b < a for a, b in zip(order, order[1:])):
            E(f"{arm}: min <= q1 <= median <= q3 <= max is violated")
        if v["sd"] is not None and v["se"] is not None:
            n = g(f"n{sfx}")
            if _num(n) and n > 1 and abs(v["se"] * math.sqrt(n) - v["sd"]) / v["sd"] > 0.15:
                W(f"{arm}: SD ({v['sd']}) and SE ({v['se']}) disagree for n={n}; one may be mislabelled")
        if v["mean"] is not None and v["sd"] is not None and v["mean"] > 0 and v["sd"] > 3 * v["mean"]:
            W(f"{arm}: SD is more than 3x the mean; check for a skewed variable or a mislabelled statistic")
    if dt == "generic":
        est, lo, hi, se = g("estimate"), g("ci_lower"), g("ci_upper"), g("se")
        if se is None and (lo is None or hi is None):
            E("generic effect needs an SE or both CI limits")
        if lo is not None and hi is not None and est is not None and not lo <= est <= hi:
            E(f"estimate {est} is outside its CI [{lo}, {hi}]")


def validate_record(rec: dict, protocol: dict | None, report: ValidationReport,
                    project_dir: Path | None = None, verify_quotes: bool = True):
    study = rec.get("study_id") or Path(rec.get("_path", "?")).stem
    issues = report.issues
    E = lambda where, msg: issues.append(Issue("error", study, where, msg))
    W = lambda where, msg: issues.append(Issue("warning", study, where, msg))

    if not rec.get("study_id"):
        E("study_id", "missing study_id")
    outcomes = rec.get("outcomes")
    if not isinstance(outcomes, list) or not outcomes:
        E("outcomes", "no outcomes extracted (if the study reports none, remove it and log the exclusion)")
        return

    source_text = None
    src = rec.get("source_file")
    if verify_quotes and src and project_dir is not None:
        p = (Path(project_dir) / src)
        if p.exists() and p.suffix.lower() in (".md", ".txt", ".xml", ".html"):
            source_text = p.read_text(encoding="utf-8", errors="replace")
        elif p.exists():
            W("source_file", f"{src} is not a text file, so quotes cannot be auto-verified; "
                             "run `metakit retrieve` or save the PDF's text as .md")
        else:
            E("source_file", f"{src} does not exist")
    elif verify_quotes and not src:
        W("source_file", "no source_file given, so quotes cannot be checked against the paper")

    known = None
    if protocol:
        known = {o["id"] for o in protocol.get("outcomes", [])}

    def check_field(where, name, f, is_numeric=True):
        if not isinstance(f, dict):
            E(where, f"{name} must be an object with value, quote and location")
            return
        val = f.get("value")
        if val is None:
            return
        if is_numeric and not _num(val):
            E(where, f"{name} value {val!r} is not a number")
            return
        report.n_values += 1
        quote = (f.get("quote") or "").strip()
        if not quote:
            E(where, f"{name}: missing quote (every number must cite the text it came from)")
            return
        if not f.get("location"):
            W(where, f"{name}: missing location (table/figure/page)")
        if f.get("derived"):
            if not f.get("derivation"):
                E(where, f"{name} is marked derived but has no derivation explanation")
            else:
                W(where, f"{name} was derived by the extractor ({f['derivation']}); a human should confirm")
        elif is_numeric and not value_in_quote(float(val), quote):
            E(where, f"{name}={val} does not appear in its quote \"{quote[:120]}\"")
        if source_text is not None:
            report.n_quotes_checked += 1
            found, sim, window = quote_in_source(quote, source_text)
            if not found:
                E(where, f"{name}: quote not found in {src} (best similarity {sim:.2f}); "
                         "possible misquote or hallucination")
            elif is_numeric and not f.get("derived") and not value_in_quote(float(val), window):
                E(where, f"{name}={val}: the quote matches the paper only approximately and the paper's "
                         f"version of it does not contain {val} (paper reads: \"{window[:140]}\")")
            else:
                report.n_quotes_verified += 1

    for j, oc in enumerate(outcomes):
        where = f"outcomes[{j}]"
        oid = oc.get("outcome")
        if not oid:
            E(where, "missing outcome id")
        elif known is not None and oid not in known:
            E(where, f"outcome {oid!r} is not defined in protocol.yaml (known: {sorted(known)})")
        where = f"{oid or j}"
        dt = oc.get("data_type")
        if dt not in DATA_TYPES:
            E(where, f"data_type must be one of {sorted(DATA_TYPES)}, got {dt!r}")
            continue
        fields = oc.get("fields") or {}
        allowed = set(DATA_TYPES[dt]["required"]) | set(DATA_TYPES[dt]["optional"])
        for name in fields:
            if name not in allowed:
                E(where, f"unexpected field {name!r} for data_type {dt}")
        for name in DATA_TYPES[dt]["required"]:
            if field_value(fields, name) is None:
                E(where, f"required field {name!r} missing")
        for name, f in fields.items():
            if name in allowed:
                check_field(where, name, f)
        _check_plausibility(study, where, dt, fields, issues)
        if dt == "generic" and oc.get("scale") not in ("ratio", "difference"):
            E(where, "generic outcomes need scale: 'ratio' (OR/RR/HR) or 'difference'")

    for name, f in (rec.get("moderators") or {}).items():
        if isinstance(f, dict):
            check_field(f"moderators.{name}", name, f, is_numeric=_num(f.get("value")))
        else:
            E(f"moderators.{name}", "moderators need value, quote and location")


def cross_study_checks(records: list[dict], report: ValidationReport):
    """Checks that need all studies at once: duplicates and SE-reported-as-SD outliers."""
    seen = {}
    seen_ids = {}
    for rec in records:
        sid = rec.get("study_id")
        fname = Path(rec.get("_path", "?")).name
        if sid in seen:
            report.issues.append(Issue("error", sid, "study_id", f"duplicate study_id (also in {seen[sid]})"))
        seen[sid] = fname
        for key in ("pmid", "doi"):
            val = str(rec.get(key) or "").strip().lower()
            if val:
                if (key, val) in seen_ids:
                    report.issues.append(Issue(
                        "warning", sid, key,
                        f"same {key} as {seen_ids[(key, val)]}: the same study may be counted twice "
                        "(fine only if these are different outcomes/cohorts entered separately)"))
                seen_ids[(key, val)] = sid
    by_outcome = {}
    for rec in records:
        for oc in rec.get("outcomes") or []:
            if oc.get("data_type") in ("continuous", "single_group"):
                fields = oc.get("fields") or {}
                for sfx in (("_t", "_c") if oc["data_type"] == "continuous" else ("",)):
                    sd = field_value(fields, f"sd{sfx}")
                    n = field_value(fields, f"n{sfx}")
                    if _num(sd) and _num(n) and sd > 0:
                        by_outcome.setdefault(oc.get("outcome"), []).append((rec.get("study_id"), sfx, sd, n))
    for oid, rows in by_outcome.items():
        if len(rows) < 4:
            continue
        sds = sorted(r[2] for r in rows)
        med = sds[len(sds) // 2]
        for sid, sfx, sd, n in rows:
            if sd < med / 3 and abs(sd * math.sqrt(n) - med) < abs(sd - med):
                report.issues.append(Issue(
                    "warning", sid, f"{oid} sd{sfx}",
                    f"SD {sd} is far below the typical SD ({med:.3g}) but SD*sqrt(n) = "
                    f"{sd * math.sqrt(n):.3g} is close to it: this is probably a standard error "
                    "reported as an SD"))


def validate_folder(folder: Path, protocol: dict | None = None, project_dir: Path | None = None,
                    verify_quotes: bool = True) -> ValidationReport:
    report = ValidationReport()
    records = load_extractions(folder)
    report.n_studies = len(records)
    for rec in records:
        validate_record(rec, protocol, report, project_dir, verify_quotes)
    cross_study_checks(records, report)
    return report
