"""Figures: forest, funnel, leave-one-out, cumulative, risk-of-bias and PRISMA flow."""
from __future__ import annotations

import math
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import matplotlib.ticker  # noqa: E402
import numpy as np  # noqa: E402
from matplotlib.patches import FancyBboxPatch, Polygon  # noqa: E402
from scipy import stats  # noqa: E402

INK = "#1f2933"
ACCENT = "#1b4f72"
MUTED = "#7b8794"
plt.rcParams.update({"font.family": "DejaVu Sans", "font.size": 9, "axes.edgecolor": INK,
                     "axes.labelcolor": INK, "xtick.color": INK, "ytick.color": INK})


def _fmt(v, digits=2):
    return f"{v:.{digits}f}"


def forest(labels, yi, vi, res, measure_name, transform=lambda x: x, log_axis=False,
           null=None, favours=None, path=None, title=None, weights=None, groups=None,
           group_results=None, digits=2):
    """Classic forest plot. ``transform`` maps the analysis scale to the display scale."""
    yi, vi = np.asarray(yi, float), np.asarray(vi, float)
    k = len(yi)
    z = stats.norm.ppf(0.975)
    lo, hi = yi - z * np.sqrt(vi), yi + z * np.sqrt(vi)
    weights = res.weights if weights is None else np.asarray(weights)

    # row layout (top to bottom), optionally grouped
    rows = []  # (kind, payload)
    if groups is not None:
        levels = list(dict.fromkeys(groups))
        for lev in sorted(levels, key=str):
            rows.append(("header", str(lev)))
            for i in [i for i in range(k) if groups[i] == lev]:
                rows.append(("study", i))
            if group_results and str(lev) in group_results and group_results[str(lev)]["k"] > 1:
                rows.append(("subtotal", str(lev)))
            rows.append(("gap", None))
    else:
        rows += [("study", i) for i in range(k)]
        rows.append(("gap", None))
    rows.append(("overall", None))
    n = len(rows)
    top_in, bottom_in = (0.85 if title else 0.5), 1.25
    height = top_in + bottom_in + 0.26 * n
    fig = plt.figure(figsize=(10, height))
    ax = fig.add_axes([0.36, bottom_in / height, 0.36, 0.26 * n / height])
    ax.set_ylim(-0.8, n - 0.2)
    ypos = {j: n - 1 - j for j in range(n)}

    tr = np.vectorize(transform)
    all_lo = [tr(v) for v in lo] + [transform(res.ci_lb[0])]
    all_hi = [tr(v) for v in hi] + [transform(res.ci_ub[0])]
    if res.pi_lb is not None:
        all_lo.append(transform(res.pi_lb))
        all_hi.append(transform(res.pi_ub))
    xmin, xmax = min(all_lo), max(all_hi)
    if log_axis:
        ax.set_xscale("log")
        span = math.log(xmax) - math.log(xmin)
        xmin, xmax = math.exp(math.log(xmin) - 0.05 * span), math.exp(math.log(xmax) + 0.05 * span)
        if null is not None:
            xmin, xmax = min(xmin, null * 0.9), max(xmax, null * 1.1)
    else:
        pad = 0.05 * (xmax - xmin or 1)
        xmin, xmax = xmin - pad, xmax + pad
        if null is not None:
            xmin, xmax = min(xmin, null - pad), max(xmax, null + pad)
    ax.set_xlim(xmin, xmax)
    if log_axis:
        _nice_log_ticks(ax, xmin, xmax)

    fig_text_x = {"label": 0.02, "est": 0.74, "w": 0.95}
    to_fig_y = lambda y: ax.transData.transform((xmin, y))

    def put(col, y, text, **kw):
        _, py = to_fig_y(y)
        _, fy = fig.transFigure.inverted().transform((0, py))
        ha = "left" if col == "label" else "right" if col == "w" else "left"
        fig.text(fig_text_x[col], fy, text, va="center", ha=ha, **kw)

    maxw = max(weights) if len(weights) else 1
    for j, (kind, payload) in enumerate(rows):
        y = ypos[j]
        if kind == "header":
            put("label", y, payload, weight="bold", color=INK)
        elif kind == "study":
            i = payload
            e, l, h = transform(yi[i]), transform(lo[i]), transform(hi[i])
            ax.plot([l, h], [y, y], color=INK, lw=1)
            size = 4 + 10 * math.sqrt(weights[i] / maxw)
            ax.plot([e], [y], marker="s", ms=size, color=ACCENT, mec=ACCENT)
            put("label", y, str(labels[i]), color=INK)
            put("est", y, f"{_fmt(e, digits)} [{_fmt(l, digits)}, {_fmt(h, digits)}]", color=INK)
            put("w", y, f"{weights[i]:.1f}%", color=INK)
        elif kind in ("overall", "subtotal"):
            if kind == "overall":
                b, cl, cu = res.beta[0], res.ci_lb[0], res.ci_ub[0]
                label = f"{'Random' if res.method != 'FE' else 'Fixed'}-effects model ({res.method}" + \
                        (", Knapp-Hartung" if res.test == "knha" else "") + ")"
            else:
                gr = group_results[payload]
                b, cl, cu = gr["estimate"], gr["ci_lb"], gr["ci_ub"]
                label = f"Subtotal: {payload}"
            e, l, h = transform(b), transform(cl), transform(cu)
            ax.add_patch(Polygon([[l, y], [e, y + 0.32], [h, y], [e, y - 0.32]], closed=True,
                                 color=INK if kind == "overall" else MUTED))
            put("label", y, label, weight="bold" if kind == "overall" else None, color=INK)
            put("est", y, f"{_fmt(e, digits)} [{_fmt(l, digits)}, {_fmt(h, digits)}]",
                weight="bold" if kind == "overall" else None, color=INK)
            if kind == "overall":
                put("w", y, "100%", weight="bold", color=INK)
                if res.pi_lb is not None and res.method != "FE":
                    ax.plot([transform(res.pi_lb), transform(res.pi_ub)], [y - 0.55, y - 0.55],
                            color=MUTED, lw=2, solid_capstyle="butt")
    if null is not None:
        ax.axvline(null, color=MUTED, lw=0.8, ls="--")
    ax.set_yticks([])
    for side in ("left", "right", "top"):
        ax.spines[side].set_visible(False)
    ax.set_xlabel(measure_name + (" (log scale)" if log_axis else ""), labelpad=22 if favours else 4)
    # column headers, just above the first row
    fy = (bottom_in + 0.26 * n + 0.08) / height
    fig.text(0.02, fy, "Study", weight="bold", va="bottom")
    fig.text(0.74, fy, f"{measure_name} [95% CI]", weight="bold", va="bottom")
    fig.text(0.95, fy, "Weight", weight="bold", va="bottom", ha="right")
    het = (f"Heterogeneity: \u03c4\u00b2 = {res.tau2:.3f}; I\u00b2 = {res.I2:.0f}%; "
           f"Q = {res.QE:.2f}, df = {res.k - res.p}, p = {res.QEp:.3g}")
    if res.pi_lb is not None and res.method != "FE":
        het += (f"   |   95% prediction interval: {_fmt(transform(res.pi_lb), digits)} "
                f"to {_fmt(transform(res.pi_ub), digits)} (grey bar)")
    fig.text(0.02, 0.12 / height, het, color=MUTED, fontsize=8)
    if favours and null is not None:
        fy_f = (bottom_in - 0.42) / height
        xn = 0.36 + 0.36 * _frac(null, xmin, xmax, log_axis)
        fig.text(xn - 0.01, fy_f, f"\u2190 {favours[0]}", ha="right", va="center", fontsize=8, color=MUTED)
        fig.text(xn + 0.01, fy_f, f"{favours[1]} \u2192", ha="left", va="center", fontsize=8, color=MUTED)
    if title:
        fig.text(0.02, 1 - 0.18 / height, title, ha="left", va="top", weight="bold", fontsize=11)
    if path:
        fig.savefig(path, dpi=200, bbox_inches="tight")
        plt.close(fig)
    return fig


def _nice_log_ticks(ax, xmin, xmax):
    """Readable ticks (0.2, 0.5, 1, 2 ...) instead of 10^-1 on log axes."""
    nice = [0.001, 0.002, 0.005, 0.01, 0.02, 0.05, 0.1, 0.2, 0.3, 0.5, 0.7, 1, 1.5, 2, 3, 5, 10,
            20, 50, 100, 200, 500, 1000]
    ticks = [t for t in nice if xmin <= t <= xmax]
    if len(ticks) > 8:
        ticks = [t for t in ticks if f"{t:g}".lstrip("0.")[:1] in ("1", "2", "5")] or ticks
    ax.xaxis.set_major_locator(matplotlib.ticker.FixedLocator(ticks))
    ax.xaxis.set_major_formatter(matplotlib.ticker.FuncFormatter(lambda v, _: f"{v:g}"))
    ax.xaxis.set_minor_locator(matplotlib.ticker.NullLocator())


def _frac(v, lo, hi, log):
    if log:
        return (math.log(v) - math.log(lo)) / (math.log(hi) - math.log(lo))
    return (v - lo) / (hi - lo)


def funnel(res, measure_label, path=None, filled_yi=None, filled_vi=None, title=None):
    """Funnel plot with pseudo 95% confidence limits around the pooled estimate."""
    fig, ax = plt.subplots(figsize=(5.5, 4.5))
    se = np.sqrt(res.vi)
    b = res.beta[0]
    smax = max(se.max(), max(np.sqrt(filled_vi)) if filled_vi is not None and len(filled_vi) else 0) * 1.08
    s = np.linspace(0, smax, 50)
    ax.fill_betweenx(s, b - 1.96 * s, b + 1.96 * s, color="#eef2f6", zorder=0)
    ax.plot(b - 1.96 * s, s, color=MUTED, lw=0.8, ls="--")
    ax.plot(b + 1.96 * s, s, color=MUTED, lw=0.8, ls="--")
    ax.axvline(b, color=INK, lw=0.8)
    ax.scatter(res.yi, se, color=ACCENT, s=28, zorder=3, label="Studies")
    if filled_yi is not None and len(filled_yi):
        ax.scatter(filled_yi, np.sqrt(filled_vi), facecolor="white", edgecolor=ACCENT, s=28,
                   zorder=3, label="Imputed by trim-and-fill")
        ax.legend(frameon=False, fontsize=8)
    ax.set_ylim(smax, 0)
    ax.set_xlabel(measure_label)
    ax.set_ylabel("Standard error")
    for side in ("right", "top"):
        ax.spines[side].set_visible(False)
    if title:
        ax.set_title(title, loc="left", weight="bold")
    if path:
        fig.savefig(path, dpi=200, bbox_inches="tight")
        plt.close(fig)
    return fig


def estimate_series(rows, label_key, measure_name, transform, null, path, title, log_axis=False,
                    reference=None):
    """Leave-one-out or cumulative plot: one estimate + CI per row."""
    n = len(rows)
    fig, ax = plt.subplots(figsize=(7, 0.8 + 0.28 * n))
    for j, r in enumerate(rows):
        y = n - 1 - j
        e, l, h = transform(r["estimate"]), transform(r["ci_lb"]), transform(r["ci_ub"])
        ax.plot([l, h], [y, y], color=INK, lw=1)
        ax.plot([e], [y], "o", color=ACCENT, ms=5)
    ax.set_yticks(range(n))
    ax.set_yticklabels([str(r[label_key]) for r in rows][::-1])
    if log_axis:
        ax.set_xscale("log")
    if null is not None:
        ax.axvline(null, color=MUTED, lw=0.8, ls="--")
    if reference is not None:
        ax.axvline(transform(reference), color=ACCENT, lw=0.8, alpha=0.5)
    if log_axis:
        lo, hi = ax.get_xlim()
        _nice_log_ticks(ax, lo, hi)
    ax.set_xlabel(measure_name)
    for side in ("right", "top"):
        ax.spines[side].set_visible(False)
    ax.set_title(title, loc="left", weight="bold")
    fig.savefig(path, dpi=200, bbox_inches="tight")
    plt.close(fig)


ROB_COLORS = {"low": "#2e7d32", "some concerns": "#f9a825", "moderate": "#f9a825",
              "high": "#c62828", "serious": "#c62828", "critical": "#6a1b9a",
              "good": "#2e7d32", "fair": "#f9a825", "poor": "#c62828"}


def rob_traffic_light(rob_records: dict, tool_domains: dict, path, title="Risk of bias"):
    studies = sorted(rob_records)
    doms = list(tool_domains)
    has_overall = True
    cols = doms + (["Overall"] if has_overall else [])
    fig, ax = plt.subplots(figsize=(1.2 + 0.7 * len(cols), 0.8 + 0.34 * len(studies)))
    for i, sid in enumerate(studies):
        rec = rob_records[sid]
        for j, d in enumerate(cols):
            if d == "Overall":
                j_val = rec.get("overall")
            else:
                entry = (rec.get("domains") or {}).get(d) or {}
                j_val = (entry.get("judgement") or "").lower() or (
                    f"{entry.get('stars')}\u2605" if entry.get("stars") is not None else None)
            color = ROB_COLORS.get(j_val, "#b0bec5") if j_val and "\u2605" not in str(j_val) else "#90a4ae"
            ax.scatter(j, len(studies) - 1 - i, s=260, color=color, edgecolor="white")
            if j_val and "\u2605" in str(j_val):
                ax.text(j, len(studies) - 1 - i, j_val.replace("\u2605", ""), ha="center", va="center",
                        color="white", fontsize=8, weight="bold")
    ax.set_xticks(range(len(cols)))
    ax.set_xticklabels(cols)
    ax.set_yticks(range(len(studies)))
    ax.set_yticklabels(studies[::-1])
    ax.set_xlim(-0.6, len(cols) - 0.4)
    ax.set_ylim(-0.6, len(studies) - 0.4)
    for side in ("right", "top", "left", "bottom"):
        ax.spines[side].set_visible(False)
    ax.tick_params(length=0)
    ax.xaxis.tick_top()
    legend_items = sorted({(rec.get("overall") or "") for rec in rob_records.values()} - {""})
    for lev in legend_items:
        ax.scatter([], [], color=ROB_COLORS.get(lev, "#b0bec5"), label=lev, s=80)
    ax.legend(frameon=False, loc="upper left", bbox_to_anchor=(1.0, 1.0), fontsize=8)
    ax.set_title(title, loc="left", weight="bold", pad=24)
    fig.savefig(path, dpi=200, bbox_inches="tight")
    plt.close(fig)


def prisma_flow(counts: dict, path):
    """PRISMA 2020 flow diagram (databases and registers)."""
    c = lambda k: counts.get(k, "?")
    boxes = [
        ((0.05, 0.80), f"Records identified\n(n = {c('identified')})"),
        ((0.55, 0.80), f"Duplicates removed\n(n = {c('duplicates_removed')})"),
        ((0.05, 0.60), f"Records screened\n(n = {c('screened')})"),
        ((0.55, 0.60), f"Records excluded\n(n = {c('excluded_screening')})"),
        ((0.05, 0.40), f"Full-text reports assessed\n(n = {c('fulltext_assessed')})"),
        ((0.55, 0.40), "Full-text reports excluded\n(n = {})".format(c('fulltext_excluded'))
         + "".join(f"\n  {r}: {n}" for r, n in (counts.get("fulltext_exclusion_reasons") or {}).items())),
        ((0.05, 0.14), f"Studies included in review\n(n = {c('included_review')})\n"
                       f"Included in meta-analysis\n(n = {c('included_meta')})"),
    ]
    fig, ax = plt.subplots(figsize=(7.5, 7.5))
    ax.axis("off")
    for (x, y), text in boxes:
        h = 0.1 + 0.03 * text.count("\n")
        ax.add_patch(FancyBboxPatch((x, y - (h - 0.13)), 0.4, h, boxstyle="round,pad=0.01",
                                    fc="white", ec=INK, lw=1))
        ax.text(x + 0.2, y - (h - 0.13) + h / 2, text, ha="center", va="center", fontsize=9)
    for y0, y1 in ((0.80, 0.73), (0.60, 0.53), (0.40, 0.30)):
        ax.annotate("", xy=(0.25, y1), xytext=(0.25, y0 - 0.0), arrowprops=dict(arrowstyle="->", color=INK))
    for y in (0.865, 0.665, 0.465):
        ax.annotate("", xy=(0.55, y), xytext=(0.45, y), arrowprops=dict(arrowstyle="->", color=INK))
    ax.set_xlim(0, 1)
    ax.set_ylim(0, 1)
    ax.set_title("PRISMA 2020 flow diagram", loc="left", weight="bold")
    fig.savefig(path, dpi=200, bbox_inches="tight")
    plt.close(fig)
