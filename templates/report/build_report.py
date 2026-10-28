#!/usr/bin/env python3
"""Build the AAE experiment report: one page per tested hypothesis plus trajectory and accepted changes.

Usage: python3 build_report.py [REPORT_DIR]   (default: the directory of this script)

Reads REPORT_DIR/session.json and REPORT_DIR/experiments/NNN/{meta.json,change.patch},
writes REPORT_DIR/generated/*.tex and compiles REPORT_DIR/report.pdf with latexmk.
Standard library only; safe to rerun after every experiment.
"""
import json
import math
import re
import shutil
import subprocess
import sys
from pathlib import Path

PAGE_LINES = 62      # rough number of \small text lines on one page
DIFF_MIN_LINES = 12  # always show at least this many diff lines
DIFF_LINES_PER_TEXT_LINE = 1.25  # \scriptsize listing lines per \small text line
DIFF_WIDTH = 112     # characters per \scriptsize listing line before it wraps
TABLE_MAX_ROWS = 14  # per-input rows shown on a page

# ---------------------------------------------------------------- text helpers
_SPECIAL = {"\\": r"\textbackslash{}", "&": r"\&", "%": r"\%", "$": r"\$", "#": r"\#", "_": r"\_",
            "{": r"\{", "}": r"\}", "~": r"\textasciitilde{}", "^": r"\textasciicircum{}"}


def esc(s):
    return "".join(_SPECIAL.get(c, c) for c in str(s))


def tex(s):
    """Plain text to LaTeX: `code` becomes \\texttt, $math$ is passed through, everything else is escaped."""
    if not s:
        return ""
    out = []
    for part in re.split(r"(`[^`]*`|\$[^$]+\$)", str(s)):
        if part.startswith("`") and part.endswith("`") and len(part) > 1:
            out.append(r"\texttt{" + esc(part[1:-1]) + "}")
        elif part.startswith("$") and part.endswith("$") and len(part) > 1:
            out.append(part)
        else:
            out.append(esc(part).replace("->", r"$\rightarrow$"))
    return "".join(out)


def num(x, digits=4):
    if x is None:
        return "--"
    if isinstance(x, float) and (math.isnan(x) or math.isinf(x)):
        return "--"
    ax = abs(x)
    if ax != 0 and (ax >= 1e6 or ax < 1e-3):
        m, e = f"{x:.3e}".split("e")
        return f"${m}\\cdot 10^{{{int(e)}}}$"
    return f"{x:.{digits}g}" if ax >= 1 else f"{x:.{digits}f}".rstrip("0").rstrip(".")


def geomean(xs):
    xs = [x for x in xs if x is not None and x > 0]
    return math.exp(sum(math.log(x) for x in xs) / len(xs)) if xs else None


def text_lines(s, width=95):
    return sum(max(1, math.ceil(len(p) / width)) for p in str(s or "").split("\n")) if s else 0


# ---------------------------------------------------------------- model
class Session:
    def __init__(self, d):
        self.title = d.get("title", "Agentic Algorithm Engineering Report")
        self.subtitle = d.get("subtitle", "")
        self.target = d.get("target", "")
        self.metric = d.get("metric", "metric")
        self.unit = d.get("unit", "")
        self.lower = d.get("direction", "lower") == "lower"
        self.resource = d.get("resource", "")
        self.machine = d.get("machine", "")
        self.branch = d.get("branch", "")
        self.date = d.get("date", "")
        self.summary = d.get("summary", "")

    def better(self, a, b):
        """True if metric value a is strictly better than b."""
        return a < b if self.lower else a > b

    def gain(self, old, new):
        """Improvement factor (>1 means better), independent of direction."""
        if old is None or new is None or old <= 0 or new <= 0:
            return None
        return old / new if self.lower else new / old


def load(report_dir):
    s = Session(json.loads((report_dir / "session.json").read_text()))
    exps = []
    for d in sorted((report_dir / "experiments").glob("*/")):
        f = d / "meta.json"
        if not f.exists():
            continue
        m = json.loads(f.read_text())
        m.setdefault("exp", int(re.sub(r"\D", "", d.name) or 0))
        m["dir"] = d
        meas = m.get("measurements") or []
        if m.get("metric") is None and meas:
            m["metric"] = geomean([r.get("value") for r in meas])
        exps.append(m)
    exps.sort(key=lambda m: m["exp"])
    return s, exps


def annotate(s, exps):
    """Attach baseline / previous-best reference values and best-so-far to every experiment."""
    base, best = None, None
    for m in exps:
        st = m.get("status", "discard")
        m["ref_base"], m["ref_best"] = base, best
        ok = st in ("baseline", "keep") and m.get("metric") is not None
        if st == "baseline" and base is None and ok:
            base = best = m
        elif st == "keep" and ok:
            best = m
        m["best_after"] = best["metric"] if best else None
    return base, best


# ---------------------------------------------------------------- pieces
BADGE = {"keep": r"\keep", "discard": r"\discard", "crash": r"\crash", "baseline": r"\baseline"}
VCOLOR = {"keep": "safe", "discard": "neutral", "crash": "unsafe", "baseline": "accent"}


def label(m):
    return f"E{m['exp']:03d}"


def short_title(m, n=70):
    t = m.get("title") or m.get("hypothesis") or ""
    return t if len(t) <= n else t[: n - 3].rsplit(" ", 1)[0] + "..."


def write_session(s, out):
    out.write_text(
        f"\\newcommand{{\\ReportTitle}}{{{tex(s.title)}}}\n"
        f"\\newcommand{{\\ReportSubtitle}}{{{tex(s.subtitle)}}}\n")


def write_summary(s, exps, base, best, out):
    counts = {k: sum(1 for m in exps if m.get("status") == k) for k in ("keep", "discard", "crash")}
    tested = counts["keep"] + counts["discard"] + counts["crash"]
    g = s.gain(base["metric"], best["metric"]) if base and best else None
    unit = f" {tex(s.unit)}" if s.unit else ""
    arrow = "lower is better" if s.lower else "higher is better"
    L = [r"\section*{Summary}", r"\begin{summarybox}"]
    if base and best:
        L.append(f"\\textbf{{{tex(s.metric)}}} ({arrow}): baseline {num(base['metric'])}{unit} "
                 f"$\\rightarrow$ best {num(best['metric'])}{unit}"
                 + (f", an improvement by a factor of \\textbf{{{g:.3f}}}" if g else "") + ".\\par\\medskip")
    L.append(f"{tested} hypotheses tested: {counts['keep']} kept, {counts['discard']} discarded, "
             f"{counts['crash']} crashed. Accepted changes are stored as {counts['keep']} numbered patches in "
             r"\texttt{patches/} (Section~\ref{sec:accepted}).")
    if s.summary:
        L.append(r"\par\medskip " + tex(s.summary))
    L.append(r"\end{summarybox}")
    info = [("Target", s.target), ("Branch", s.branch), ("Machine", s.machine), ("Date", s.date)]
    info = [(k, v) for k, v in info if v]
    if info:
        L.append(r"{\small\begin{tabularx}{\linewidth}{@{}l X@{}}")
        L += [f"{k}: & {tex(v)}\\\\" for k, v in info]
        L.append(r"\end{tabularx}}")
    L.append(r"\subsection*{Contents (one page per hypothesis)}")
    L.append(r"{\small\begin{tabularx}{\linewidth}{@{}l X l r r@{}}")
    L.append(r"\toprule Exp & Hypothesis & Status & " + tex(s.metric) + r" & Page\\\midrule")
    for m in exps:
        L.append(f"\\hyperref[exp:{m['exp']}]{{{label(m)}}} & {tex(short_title(m))} & "
                 f"{BADGE.get(m.get('status'), '')} & {num(m.get('metric'))} & \\pageref{{exp:{m['exp']}}}\\\\")
    L.append(r"\bottomrule\end{tabularx}}")
    out.write_text("\n".join(L) + "\n")


def write_trajectory(s, exps, gen):
    pts = {"keep": [], "discard": [], "baseline": []}
    best = []
    patch_no = 0
    for m in exps:
        st = m.get("status")
        if st == "keep":
            patch_no += 1
        if m.get("metric") is not None and st in pts:
            pts[st].append((m["exp"], m["metric"], f"P{patch_no}" if st == "keep" else ""))
        if m.get("best_after") is not None:
            best.append((m["exp"], m["best_after"]))
    for k, rows in pts.items():
        (gen / f"traj_{k}.dat").write_text("x y lab\n" + "".join(f"{x} {y} {l or '-'}\n" for x, y, l in rows))
    (gen / "traj_best.dat").write_text("x y\n" + "".join(f"{x} {y}\n" for x, y in best))
    crashes = sum(1 for m in exps if m.get("status") == "crash")
    ylab = tex(s.metric) + (f" [{tex(s.unit)}]" if s.unit else "")
    L = [r"\begin{center}\begin{tikzpicture}",
         r"\begin{axis}[width=0.95\linewidth,height=8.5cm,axis lines=left,xlabel={experiment},ylabel={" + ylab + "},",
         r"  tick label style={font=\small\color{ink!70}},label style={font=\small\color{ink}},",
         r"  axis line style={ink!50},major tick style={ink!50},ymajorgrids,grid style={ink!10},",
         r"  legend style={draw=none,fill=none,font=\small,at={(0.5,1.02)},anchor=south,legend columns=-1,"
         r"/tikz/every even column/.append style={column sep=10pt}},clip=false,",
         r"  xmin=0.5,enlarge y limits=0.08,xtick distance=" + str(max(1, math.ceil(len(exps) / 20))) + "]"]
    if best:
        L.append(r"\addplot[const plot mark left,accent,line width=1.2pt] table[x=x,y=y] {generated/traj_best.dat};")
        L.append(r"\addlegendentry{best so far}")
    style = {"baseline": r"only marks,mark=square*,mark size=3pt,accent,mark options={draw=white,line width=0.6pt}",
             "keep": r"only marks,mark=*,mark size=3pt,safe,mark options={draw=white,line width=0.6pt},"
                     r"nodes near coords,point meta=explicit symbolic,"
                     r"every node near coord/.append style={font=\scriptsize\bfseries\color{ink},anchor=south,yshift=1pt}",
             "discard": r"only marks,mark=o,mark size=2.6pt,neutral,line width=0.7pt"}
    names = {"baseline": "baseline", "keep": "kept (patch number)", "discard": "discarded"}
    for k in ("baseline", "keep", "discard"):
        if pts[k]:
            meta = ",meta=lab" if k == "keep" else ""
            L.append(f"\\addplot[{style[k]}] table[x=x,y=y{meta}] {{generated/traj_{k}.dat}};")
            L.append(f"\\addlegendentry{{{names[k]}}}")
    L += [r"\end{axis}\end{tikzpicture}\end{center}"]
    note = ("Every tested hypothesis is one point; the step line is the best result accepted so far. "
            "Labels P$i$ give the number of the patch in \\texttt{patches/} that a kept change produced.")
    if crashes:
        note += f" {crashes} crashed experiment{'s are' if crashes > 1 else ' is'} not plotted."
    L.append(r"{\small\color{ink!80}" + note + "}")
    # step table: what the trajectory went through
    L.append(r"\subsection*{Course of the session}")
    L.append(r"{\small\begin{tabularx}{\linewidth}{@{}l l X r r@{}}")
    L.append(r"\toprule Exp & Status & Hypothesis & " + tex(s.metric) + r" & best\\\midrule")
    for m in exps:
        L.append(f"{label(m)} & {BADGE.get(m.get('status'), '')} & {tex(short_title(m, 60))} & "
                 f"{num(m.get('metric'))} & {num(m.get('best_after'))}\\\\")
    L.append(r"\bottomrule\end{tabularx}}")
    (gen / "trajectory.tex").write_text("\n".join(L) + "\n")


def write_accepted(s, exps, base, gen):
    kept = [m for m in exps if m.get("status") == "keep"]
    L = []
    if not kept:
        L.append(r"No change has been accepted yet.")
    else:
        L.append(r"Applying the patches in order to the baseline commit reproduces the best version:"
                 r"\par\smallskip\qquad\texttt{git am patches/*.patch}\par\smallskip")
        L.append(r"{\small\begin{tabularx}{\linewidth}{@{}l l X r r r@{}}")
        L.append(r"\toprule Patch & Exp & Change & " + tex(s.metric) + r" & step & total\\\midrule")
        prev = base
        for i, m in enumerate(kept, 1):
            step = s.gain(prev["metric"], m["metric"]) if prev else None
            tot = s.gain(base["metric"], m["metric"]) if base else None
            pname = Path(m.get("patch") or f"{i:04d}").name
            L.append(f"\\texttt{{{esc(pname[:4])}}} & \\hyperref[exp:{m['exp']}]{{{label(m)}}} & "
                     f"{tex(short_title(m, 60))} & {num(m['metric'])} & "
                     f"{'--' if step is None else f'{step:.3f}$\\times$'} & "
                     f"{'--' if tot is None else f'{tot:.3f}$\\times$'}\\\\")
            prev = m
        L.append(r"\bottomrule\end{tabularx}}")
        L.append(r"\par{\small\color{ink!80}\emph{step}: improvement factor over the previous best; "
                 r"\emph{total}: over the baseline.}")
    (gen / "accepted.tex").write_text("\n".join(L) + "\n")


def clean_diff(text):
    """Drop the commit header of `git show`, keep only the diff, and make it pdflatex-safe."""
    i = text.find("diff --git")
    text = text[i:] if i >= 0 else text
    return "".join(c if (32 <= ord(c) < 127 or c in "\n\t") else "?" for c in text)


def diffstat(diff):
    files, add, rem = set(), 0, 0
    for ln in diff.splitlines():
        if ln.startswith("diff --git"):
            files.add(ln.split(" b/")[-1])
        elif ln.startswith("+") and not ln.startswith("+++"):
            add += 1
        elif ln.startswith("-") and not ln.startswith("---"):
            rem += 1
    return files, add, rem


def measurement_table(s, m):
    rows = m.get("measurements") or []
    base = {r["input"]: r.get("value") for r in (m["ref_base"] or {}).get("measurements") or []}
    best = {r["input"]: r.get("value") for r in (m["ref_best"] or {}).get("measurements") or []}
    L = [r"{\small\begin{tabularx}{\linewidth}{@{}X r r r r@{}}",
         r"\toprule Input & baseline & previous best & this & vs.\ best\\\midrule"]

    def row(name, b, p, v, bold=False):
        g = s.gain(p, v)
        if g is None:
            d = "--"
        else:  # relative change of the metric itself, coloured by whether it is an improvement
            col = "safe" if g > 1 else ("unsafe" if g < 1 else "ink")
            d = f"\\textcolor{{{col}}}{{{(v - p) / p * 100:+.1f}\\,\\%}}"
        f = (lambda x: r"\textbf{" + x + "}") if bold else (lambda x: x)
        return f"{f(name)} & {f(num(b))} & {f(num(p))} & {f(num(v))} & {d}\\\\"

    shown = rows[:TABLE_MAX_ROWS]
    for r in shown:
        L.append(row(tex(r["input"]), base.get(r["input"]), best.get(r["input"]), r.get("value")))
    if len(rows) > len(shown):
        L.append(f"\\multicolumn{{5}}{{@{{}}l}}{{\\emph{{\\dots\\ {len(rows) - len(shown)} more inputs in "
                 f"\\texttt{{measurements}} of \\texttt{{meta.json}}}}}}\\\\")
    if rows:
        L.append(r"\midrule")
    L.append(row("geometric mean" if rows else tex(s.metric),
                 (m["ref_base"] or {}).get("metric"), (m["ref_best"] or {}).get("metric"), m.get("metric"), True))
    L.append(r"\bottomrule\end{tabularx}}")
    if m.get("resource") is not None and s.resource:
        L.append(f"\\par{{\\small Peak {tex(s.resource)}: {num(m['resource'])}}}")
    return "\n".join(L), len(shown) + 4


def write_experiments(s, exps, gen):
    ddir = gen / "diffs"
    ddir.mkdir(exist_ok=True)
    L = []
    patch_no = 0
    for i, m in enumerate(exps):
        st = m.get("status", "discard")
        if st == "keep":
            patch_no += 1
        L.append(r"\clearpage")
        if i == 0:
            L.append(r"\section{Experiments}\label{sec:experiments}")
        head = [f"commit \\texttt{{{esc(m.get('commit', '--'))}}}"]
        if st == "keep":
            head.append(f"patch \\texttt{{{esc(Path(m.get('patch') or f'{patch_no:04d}').name)}}}")
        L.append(f"\\subsection*{{{label(m)}\\ \\ {tex(m.get('title') or short_title(m))}}}\\label{{exp:{m['exp']}}}")
        L.append(f"\\addcontentsline{{toc}}{{subsection}}{{{label(m)}}}")
        L.append(f"{BADGE.get(st, '')}\\hfill{{\\small\\color{{ink!70}}{' \\textperiodcentered\\ '.join(head)}}}\\par")
        used = 4
        L.append(r"\begin{hypbox}\small\textbf{Hypothesis.} " + tex(m.get("hypothesis")) + r"\end{hypbox}")
        used += text_lines(m.get("hypothesis")) + 2
        for key, name in (("intuition", "Intuition"), ("prediction", "Prediction")):
            if m.get(key):
                L.append(f"{{\\small\\textbf{{{name}.}} {tex(m[key])}}}\\par")
                used += text_lines(m[key])
        if st != "crash" or m.get("measurements"):
            L.append(r"\par\smallskip{\bfseries\color{ink}Measurements}\par")
            tab, n = measurement_table(s, m)
            L.append(tab)
            used += n + 1
        verdict = m.get("verdict", "")
        refl = m.get("reflection", "")
        if verdict or refl:
            L.append(f"\\begin{{verdictbox}}{{{VCOLOR.get(st, 'neutral')}}}\\small")
            if verdict:
                L.append(r"\textbf{Verdict.} " + tex(verdict))
            if refl:
                L.append((r"\par\smallskip" if verdict else "") + r"\textbf{Reflection.} " + tex(refl))
            L.append(r"\end{verdictbox}")
            used += text_lines(verdict) + text_lines(refl) + 4
        patch = m["dir"] / "change.patch"
        if patch.exists() and st != "baseline":
            diff = clean_diff(patch.read_text(errors="replace"))
            files, add, rem = diffstat(diff)
            lines = diff.rstrip("\n").split("\n")
            # the diff comes last and is the only part that is truncated, so the page never overflows
            budget = max(DIFF_MIN_LINES, int((PAGE_LINES - used - 4) * DIFF_LINES_PER_TEXT_LINE))
            shown, cost = [], 0
            for ln in lines:
                cost += max(1, math.ceil(len(ln.expandtabs(4)) / DIFF_WIDTH))
                if cost > budget - 1:
                    break
                shown.append(ln)
            if len(shown) < len(lines):
                shown.append(f"... {len(lines) - len(shown)} more lines, see experiments/{m['dir'].name}/change.patch")
            fn = ddir / f"{m['exp']:03d}.diff"
            fn.write_text("\n".join(shown) + "\n")
            L.append(r"\par\smallskip{\bfseries\color{ink}Code changes}\hfill"
                     f"{{\\small\\color{{ink!70}}{len(files)} file{'s' if len(files) != 1 else ''}, "
                     f"\\textcolor{{safe}}{{+{add}}} \\textcolor{{unsafe}}{{-{rem}}}}}\\par")
            L.append(f"\\lstinputlisting{{generated/diffs/{fn.name}}}")
    (gen / "experiments.tex").write_text("\n".join(L) + "\n")


# ---------------------------------------------------------------- main
def main():
    report_dir = Path(sys.argv[1] if len(sys.argv) > 1 else Path(__file__).parent).resolve()
    tmpl = Path(__file__).resolve().parent / "report.tex"
    if not (report_dir / "report.tex").exists() and tmpl.exists():
        shutil.copy(tmpl, report_dir / "report.tex")
    gen = report_dir / "generated"
    gen.mkdir(exist_ok=True)
    s, exps = load(report_dir)
    base, best = annotate(s, exps)
    write_session(s, gen / "session.tex")
    write_summary(s, exps, base, best, gen / "summary.tex")
    write_trajectory(s, exps, gen)
    write_accepted(s, exps, base, gen)
    write_experiments(s, exps, gen)
    if shutil.which("latexmk"):
        r = subprocess.run(["latexmk", "-pdf", "-interaction=nonstopmode", "-halt-on-error", "report.tex"],
                           cwd=report_dir, capture_output=True, text=True)
        log = (report_dir / "report.log")
        warn = log.read_text(errors="replace").count("Overfull \\hbox") if log.exists() else 0
        print(f"report: {report_dir / 'report.pdf'} ({'ok' if r.returncode == 0 else 'LaTeX FAILED, see report.log'}, "
              f"{len(exps)} experiments, {warn} overfull hboxes)")
        sys.exit(r.returncode)
    print(f"report sources written to {gen}; latexmk not found, compile report.tex manually")


if __name__ == "__main__":
    main()
