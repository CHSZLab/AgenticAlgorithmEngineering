#!/usr/bin/env python3
"""Build claude-plugin/, the edition of AAE for Anthropic's plugin directory.

The directory accepts only Markdown, text, JSON, YAML and images from plugins of
organizations that are not Verified, no symbolic links, and no commands that
download code. This script derives such an edition from the sources of truth:

  AAE.md                      -> claude-plugin/skills/aae/SKILL.md (adapted, see EDITS)
  templates/report/*          -> claude-plugin/skills/aae/report-template.md
                                 (the LaTeX skeleton plus the generated files of an
                                 example session, produced by build_report.py)
  knowledge-base/*.md         -> claude-plugin/skills/aae/knowledge-base/
  img/icon.png                -> claude-plugin/.claude-plugin/icon.png

Run it after changing any of these and commit the result:

  python3 scripts/build_claude_plugin.py          # rewrite claude-plugin/
  python3 scripts/build_claude_plugin.py --check  # exit 1 if claude-plugin/ is out of date

Every edit asserts that its anchor text exists, so a change in AAE.md that would
silently break the edition makes this script fail instead.
"""
import json
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "claude-plugin"
SKILL = OUT / "skills" / "aae"

PLUGIN_JSON = {
    "name": "aae",
    "displayName": "Agentic Algorithm Engineering",
    "version": "1.12.0",
    "description": "Agentic Algorithm Engineering: autonomous performance tuning through falsifiable "
                   "hypotheses, benchmarks, numbered patches, and a PDF report.",
    "author": {"name": "Christian Schulz"},
    "homepage": "https://chszlab.github.io/AgenticAlgorithmEngineering/",
    "repository": "https://github.com/CHSZLab/AgenticAlgorithmEngineering",
    "license": "MIT",
    "icon": ".claude-plugin/icon.png",
    "keywords": ["performance", "optimization", "algorithm engineering", "benchmarking", "profiling"],
}

REPORT_INTRO = """\
The report is a LaTeX document, `report/report.tex`, that inputs files from `report/generated/`.
You write both yourself: copy the skeleton below once during setup, and rewrite the generated
files from `report/session.json` and `report/experiments/NNN/{meta.json,change.patch}` after
every experiment. Then compile in `report/` with `latexmk -pdf -interaction=nonstopmode report.tex`
(or run `pdflatex` twice). This edition of AAE contains no report generator program; the
example below shows exactly what each generated file looks like for a session with three
experiments, so follow its structure and macros.

Rules for the generated files:

- Escape LaTeX special characters in all text from `meta.json` (`\\ & % $ # _ { } ~ ^`);
  text in backticks becomes `\\texttt{...}`, text in `$...$` is passed through as math.
- `metric` defaults to the geometric mean of `measurements`. Compare every experiment with
  the baseline (experiment 001) and with the best value accepted before it, respecting
  `direction` (`lower` or `higher`).
- `trajectory.tex` plots `generated/traj_*.dat`: one data file per series (best so far as a
  step line, baseline, kept with the patch number as label, discarded); each file has a header
  line and one row per point.
- `experiments.tex` has one page per experiment, kept, discarded and crashed alike. The code
  change is read from `generated/diffs/NNN.diff` (the experiment's `change.patch` without the
  commit header); shorten very long diffs so that the page stays one page.
- `accepted.tex` lists the kept changes in acceptance order with their patch files.
"""


def edit(text, old, new, count=1):
    if text.count(old) != count:
        raise SystemExit(f"build_claude_plugin: anchor found {text.count(old)} times, expected {count}:\n{old[:200]}")
    return text.replace(old, new)


def cut_section(text, heading, next_heading):
    """Remove from `heading` up to (not including) `next_heading`."""
    a = text.find(heading)
    b = text.find(next_heading, a + 1)
    if a < 0 or b < 0:
        raise SystemExit(f"build_claude_plugin: section {heading!r} not found")
    return text[:a] + text[b:]


def skill_md():
    t = (ROOT / "AAE.md").read_text()

    t = edit(t, "or when the user invokes $aae in Codex or /aae in Claude Code.",
             "or when the user invokes /aae:aae in Claude Code.")
    t = cut_section(t, "## Codex sessions\n", "## Setup\n")

    t = edit(t, "by opening a pull request to the AAE repository and updating it every 10 experiments (see [Contributing Back](#contributing-back))",
             "by writing a knowledge-base entry to `report/kb-entry.md` and updating it every 10 experiments, which the user can submit to the AAE repository (see [Contributing Back](#contributing-back))")

    old = t[t.index("**Template.**"):t.index("**Session data.**")]
    t = t.replace(old, "**Template.** This skill ships the report template in `report-template.md`, next to this file. "
                       "During setup, create `report/experiments/` and copy the LaTeX skeleton from `report-template.md` "
                       "into `report/report.tex`.\n\n")

    old = t[t.index("**Build.** After every experiment"):]
    old = old[:old.index("```\n", old.index("```bash") + 7) + 4]
    t = t.replace(old, "**Build.** After every experiment (after logging), rewrite the files in `report/generated/` "
                       "as described in `report-template.md` and compile the report:\n\n"
                       "```bash\n(cd report && latexmk -pdf -interaction=nonstopmode report.tex > /dev/null 2>&1) || true\n```\n")
    t = edit(t, "This writes `report/report.pdf`.", "This writes `report/report.pdf`. If `latexmk` is not available, run `pdflatex` twice instead, or keep the sources and tell the user that the PDF could not be built.")
    t = edit(t, "then rebuild the report with `python3 report/build_report.py report`.",
             "then rebuild the report (see [Experiment Report](#experiment-report)).")
    t = edit(t, "if `metric` is omitted, the generator uses their geometric mean",
             "if `metric` is omitted, use their geometric mean")
    t = edit(t, "The generator compares every experiment against the baseline",
             "The report compares every experiment against the baseline")

    t = edit(t, "open or update the session's knowledge-base PR (see [Contributing Back](#contributing-back))",
             "write or update `report/kb-entry.md` (see [Contributing Back](#contributing-back))")

    old = t[t.index("This methodology is supported by a community-contributed knowledge base"):t.index("### Contributing Back")]
    t = t.replace(old, """This methodology is supported by a community-contributed knowledge base of optimization techniques, experiment results, and lessons learned from AAE sessions. A copy is bundled with this skill in `knowledge-base/`, next to this file; the latest version is at https://github.com/CHSZLab/AgenticAlgorithmEngineering/tree/main/knowledge-base

Before or during a tuning session, consult the knowledge base for techniques relevant to your problem:

1. Read `knowledge-base/INDEX.md` and scan titles, problem domains, and key techniques.
2. Read the individual entries that seem relevant.
3. Use the insights to inform hypothesis generation in the AE cycle.

""")
    old = t[t.index("### Contributing Back"):t.index("## Philosophical Foundation")]
    t = t.replace(old, """### Contributing Back

Permission is asked once, during [Setup](#setup) (step 8), and stored as `kb_contributions` in `report/session.json`. Never write a contribution unless it is `true`.

If permission was given, contribute every 10 experiments (loop step 12). Each session has **one** entry, which grows over the session:

1. **First contribution** (experiment 010): write `report/kb-entry.md` following the entry template in `knowledge-base/CONTRIBUTING.md`, and record `kb_entry` in `report/session.json`.
2. **Later contributions** (experiments 020, 030, ...): update the same file with what the last 10 experiments taught (new techniques that worked, dead ends worth recording, updated baseline vs. best numbers).
3. **Nothing new**: if the last 10 experiments produced no transferable insight, skip the contribution and note that in the report summary.

At the end of the session, tell the user where the entry is and that they can submit it as a pull request to https://github.com/CHSZLab/AgenticAlgorithmEngineering (new file in `knowledge-base/` plus a row in `INDEX.md`). Only share transferable insights, and never include proprietary code, data, or paths from the user's project beyond what the entry needs.

""")
    for banned in ("curl ", "build_report.py", "gh repo fork", "gh pr create", "$aae"):
        if banned in t:
            raise SystemExit(f"build_claude_plugin: {banned!r} is still in SKILL.md")
    return t


def report_template_md():
    skeleton = (ROOT / "templates" / "report" / "report.tex").read_text()
    with tempfile.TemporaryDirectory() as d:
        d = Path(d)
        (d / "experiments").mkdir()
        (d / "session.json").write_text(json.dumps(EXAMPLE_SESSION, indent=1))
        for m, diff in EXAMPLE_EXPERIMENTS:
            e = d / "experiments" / f"{m['exp']:03d}"
            e.mkdir()
            (e / "meta.json").write_text(json.dumps(m, indent=1))
            (e / "change.patch").write_text(diff)
        shutil.copy(ROOT / "templates" / "report" / "report.tex", d / "report.tex")
        # run the generator without LaTeX: only the generated sources are needed here
        env_path = "/nonexistent"
        subprocess.run([sys.executable, str(ROOT / "templates" / "report" / "build_report.py"), str(d)],
                       check=False, capture_output=True, env={"PATH": env_path})
        gen = d / "generated"
        parts = ["# AAE report template\n", REPORT_INTRO,
                 "\n## Skeleton: `report/report.tex`\n\n```latex\n" + skeleton.rstrip() + "\n```\n",
                 "\n## Example session data\n\n`report/session.json`:\n\n```json\n" + json.dumps(EXAMPLE_SESSION, indent=1) + "\n```\n"]
        for m, diff in EXAMPLE_EXPERIMENTS:
            parts.append(f"\n`report/experiments/{m['exp']:03d}/meta.json`:\n\n```json\n{json.dumps(m, indent=1)}\n```\n")
            if diff:
                parts.append(f"\n`report/experiments/{m['exp']:03d}/change.patch`:\n\n```diff\n{diff.rstrip()}\n```\n")
        parts.append("\n## Generated files for this example\n")
        for f in ["session.tex", "summary.tex", "trajectory.tex", "traj_best.dat", "traj_baseline.dat",
                  "traj_keep.dat", "traj_discard.dat", "accepted.tex", "experiments.tex"]:
            lang = "latex" if f.endswith(".tex") else "text"
            parts.append(f"\n`report/generated/{f}`:\n\n```{lang}\n{(gen / f).read_text().rstrip()}\n```\n")
        for f in sorted((gen / "diffs").glob("*.diff")):
            parts.append(f"\n`report/generated/diffs/{f.name}`:\n\n```diff\n{f.read_text().rstrip()}\n```\n")
    return "".join(parts)


EXAMPLE_SESSION = {
    "title": "AAE session: example solver",
    "subtitle": "Running time of the solver on 2 inputs, branch aae/example",
    "target": "src/solver.cpp", "metric": "time", "unit": "s", "direction": "lower",
    "resource": "peak memory [GB]", "machine": "8 cores, 32 GB RAM", "branch": "aae/example",
    "date": "2026-11-21",
    "summary": "Two hypotheses tested: the bucket queue was kept, the cache-aligned layout was discarded.",
}
EXAMPLE_EXPERIMENTS = [
    ({"exp": 1, "title": "Baseline", "commit": "a1b2c3d", "hypothesis": "Baseline, unmodified code.",
      "intuition": "Reference point.", "prediction": "-", "status": "baseline", "metric": 2.572, "resource": 1.2,
      "measurements": [{"input": "rgg_n_2_20", "value": 4.1}, {"input": "road_eu", "value": 4.7}],
      "verdict": "Baseline established.", "reflection": "Profile shows 60% of the time in the priority queue."}, ""),
    ({"exp": 2, "title": "Bucket queue in refinement", "commit": "b2c3d4e",
      "hypothesis": "Replacing the binary heap by a bucket queue reduces time by ~15% because keys are small integers.",
      "intuition": "Most time is spent in heap operations with integer gains.",
      "prediction": "-10% to -20%; could regress if gains are spread widely.", "status": "keep", "metric": 2.181,
      "resource": 1.2, "measurements": [{"input": "rgg_n_2_20", "value": 3.483}, {"input": "road_eu", "value": 3.976}],
      "verdict": "Confirmed: -15.2% geometric mean, matching the prediction.",
      "reflection": "The queue is no longer the bottleneck; next look at memory layout.",
      "patch": "patches/0001-bucket-queue-refinement.patch"},
     "diff --git a/src/solver.cpp b/src/solver.cpp\n--- a/src/solver.cpp\n+++ b/src/solver.cpp\n"
     "@@ -10,3 +10,3 @@\n-    BinaryHeap q;\n+    BucketQueue q(max_gain);\n"),
    ({"exp": 3, "title": "Cache-aligned node array", "commit": "c3d4e5f",
      "hypothesis": "Aligning node records to 64 bytes reduces time by ~5%.", "intuition": "Records straddle cache lines.",
      "prediction": "-3% to -7%.", "status": "discard", "metric": 2.203, "resource": 1.4,
      "measurements": [{"input": "rgg_n_2_20", "value": 3.51}, {"input": "road_eu", "value": 4.02}],
      "verdict": "Refuted: +1.0%, more memory.", "reflection": "Padding increases the working set more than it saves."},
     "diff --git a/src/node.h b/src/node.h\n--- a/src/node.h\n+++ b/src/node.h\n"
     "@@ -1,3 +1,3 @@\n-struct Node {\n+struct alignas(64) Node {\n"),
]

README = """# AAE for the Claude plugin directory

This folder is the edition of [Agentic Algorithm Engineering](https://github.com/CHSZLab/AgenticAlgorithmEngineering)
for Anthropic's plugin directory. It is generated by `scripts/build_claude_plugin.py` from `AAE.md`,
the knowledge base and the report template; do not edit it by hand.

Compared with the plugin at the repository root, this edition ships no programs: the agent writes
the LaTeX report itself from the template in `skills/aae/report-template.md`, and knowledge-base
contributions are prepared as a file for the user to submit instead of being opened as pull requests.

Homepage: https://chszlab.github.io/AgenticAlgorithmEngineering/
"""


def build(dest):
    if dest.exists():
        shutil.rmtree(dest)
    skill = dest / "skills" / "aae"
    (dest / ".claude-plugin").mkdir(parents=True)
    (skill / "knowledge-base").mkdir(parents=True)
    (dest / ".claude-plugin" / "plugin.json").write_text(json.dumps(PLUGIN_JSON, indent=2, ensure_ascii=False) + "\n")
    shutil.copy(ROOT / "img" / "icon.png", dest / ".claude-plugin" / "icon.png")
    (dest / "README.md").write_text(README)
    shutil.copy(ROOT / "LICENSE", dest / "LICENSE")
    (skill / "SKILL.md").write_text(skill_md())
    (skill / "report-template.md").write_text(report_template_md())
    for f in sorted((ROOT / "knowledge-base").glob("*.md")):
        shutil.copy(f, skill / "knowledge-base" / f.name)
    # the directory holds or refuses plugins whose text downloads or installs code
    banned = re.compile(r"curl |wget |pip3? install|apt(-get)? install|brew install|npm (i|install) |npx |"
                        r"git clone|gh (repo|pr|auth|api) |conda install|cargo install|go install|^#!", re.M)
    for f in dest.rglob("*.md"):
        hit = banned.search(f.read_text())
        if hit:
            raise SystemExit(f"build_claude_plugin: {f.relative_to(dest)} contains {hit.group(0)!r}; "
                             "point to the tool's own install instructions instead")


def main():
    if "--check" in sys.argv:
        with tempfile.TemporaryDirectory() as d:
            tmp = Path(d) / "claude-plugin"
            build(tmp)
            diff = subprocess.run(["diff", "-r", str(tmp), str(OUT)], capture_output=True, text=True)
            if diff.returncode != 0:
                print("claude-plugin/ is out of date; run python3 scripts/build_claude_plugin.py\n" + diff.stdout[:3000])
                sys.exit(1)
            print("claude-plugin/ is up to date")
        return
    build(OUT)
    print(f"wrote {OUT}")


if __name__ == "__main__":
    main()
