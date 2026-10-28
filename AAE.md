---
name: aae
description: Use when asked to autonomously optimize, tune, or speed up a program (running time, throughput, quality, memory) with the Agentic Algorithm Engineering cycle of falsifiable hypotheses, benchmarks, and keep/discard decisions, or when the user runs /aae.
---

# Autonomous Performance Tuning via the Algorithm Engineering Cycle

This program turns an autonomous agent into a performance engineer that follows the Algorithm Engineering (AE) methodology: a cycle of design, analysis, implementation, and experimental evaluation, driven by falsifiable hypotheses (cf. Sanders, "Algorithm Engineering - An Attempt at a Definition").

```
                    ┌─────────────────┐
                    │  Realistic Model │
                    │  of the system   │
                    └───────┬─────────┘
                            │
                            ▼
         ┌──────────┐   ┌────────┐   ┌─────────────┐
         │ Analysis │◄──│ Design │──►│ Falsifiable  │
         │          │   │        │   │ Hypothesis   │
         └────┬─────┘   └────────┘   └──────┬──────┘
              │        (induction)          │
              │  ◄──────────────────────    │
              ▼                             ▼
     ┌────────────────┐           ┌──────────────┐
     │  Performance   │           │   Implement   │
     │  Guarantees    │           │   the change  │
     │  (deduction)   │           └──────┬───────┘
     └────────────────┘                  │
                                         ▼
              ┌─────────────────────────────────────┐
              │           Experiment                 │
              │  Run, measure, compare to baseline   │
              └──────────────┬──────────────────────┘
                             │
                     ┌───────▼───────┐
                     │   Evaluate    │
                     │  keep/discard │
                     └───────┬───────┘
                             │
                      (loop back to Design)
```

## Session Start

When a session starts (for example when this program is invoked as a skill), first show the user the Algorithm Engineering cycle with AAE at its center, exactly as below and inside a code block, followed by one line naming the target program and metric if they are already known. Then continue with [Setup](#setup).

```
                    ╭──────────────────╮
          ┌────────►│      DESIGN      │─────────┐
          │         │   falsifiable    │         │
          │         │    hypothesis    │         ▼
 ╭────────┴─────────╮╰──────────────────╯╭──────────────────╮
 │     EVALUATE     │                    │     ANALYSIS     │
 │  keep / discard  │     ┏━━━━━━━━┓     │ predict outcome  │
 │  patch + report  │     ┃  AAE   ┃     │ before measuring │
 ╰──────────────────╯     ┗━━━━━━━━┛     ╰────────┬─────────╯
          ▲                                       │
          │  ╭──────────────────╮  ╭──────────────▼───╮
          └──┤    EXPERIMENT    │◄─┤  IMPLEMENTATION  │
             │  run · measure   │  │   minimal diff   │
             │  geometric mean  │  │   + git commit   │
             ╰──────────────────╯  ╰──────────────────╯
```

## Overview

The agent receives:
- A **target program** to optimize (the code under test).
- A **metric** to improve (e.g. latency, throughput, val_bpb, memory usage).
- A **benchmark harness** that produces reproducible measurements.
- A **time budget** per experiment.

The agent then runs an autonomous loop, applying the AE cycle to systematically improve performance. Each iteration produces a falsifiable hypothesis ("changing X will improve metric Y by roughly Z"), implements it, runs the experiment, and either keeps or discards the change based on the result.

## Setup

To set up a new tuning session, work with the user to:

1. **Agree on a run tag**: propose a tag based on today's date (e.g. `mar21`). The branch `aae/<tag>` must not already exist.
2. **Create the branch**: `git checkout -b aae/<tag>` from current main/master.
3. **Read the in-scope files**: Understand the full context:
   - The **target file(s)** the agent may modify.
   - The **benchmark harness** (read-only) that defines the metric and evaluation procedure.
   - Any **configuration or constants** that are fixed.
4. **Identify constraints**: Understand what the agent can and cannot change (see below).
5. **Formulate assertions**: After reading the code, derive correctness invariants and present them to the user for confirmation (see below).
6. **Verify benchmark works**: Run the benchmark once to confirm it produces output.
7. **Initialize results.tsv, patches, and report**: Create `results.tsv` with just the header row, an empty `patches/` folder (see [Patches](#patches)), and a `report/` folder with the report template, an `experiments/` subfolder, and `session.json` (see [Experiment Report](#experiment-report)). Add `results.tsv`, `patches/`, and `report/` to `.git/info/exclude`.
8. **Confirm and go**: Confirm setup looks good with the user, then begin.

## Constraints

The user defines these per project. The agent must respect them strictly.

**What the agent CAN do:**
- Modify the designated target file(s). Everything within them is fair game: algorithms, data structures, parameters, control flow, memory layout, parallelism, etc.
- Replace entire subcomponents (e.g. swap one algorithm for a fundamentally different one, replace a data structure with an alternative, rewrite a module from scratch) if the agent has reason to believe this will improve the target metric. Optimizations are not limited to incremental tuning; architectural changes and algorithmic replacements are encouraged when the analysis supports them.

**What the agent CANNOT do:**
- Modify the benchmark harness or evaluation code.
- Install new packages or add dependencies beyond what is already available.
- Modify the metric definition or measurement methodology.
- Change the time budget or input data.

## Assertions

After reading the target code and benchmark during setup, the agent must formulate correctness assertions: invariants that must hold after every change. These act as a safety net, ensuring that optimizations do not silently break the program's correctness.

The agent derives these from its understanding of the code. Examples:
- "The output must be a valid partition (every node assigned to exactly one block, no block empty)."
- "The sorted output must be a permutation of the input."
- "The loss must be finite and non-negative after every training step."

Present the assertions to the user for confirmation during setup. The user may add, modify, or remove assertions. Once agreed upon, verify them after every implementation, before running the full benchmark. If an assertion fails, the change is incorrect; discard it immediately (no need to benchmark) and log it as a crash.

Assertions are distinct from the benchmark metric. The metric measures performance; assertions guard correctness. A change that improves the metric but violates an assertion is always discarded.

## The AE Cycle in Practice

Each iteration of the loop implements one full AE cycle:

### 1. Realistic Model (Understand the System)

Before proposing changes, the agent must have an accurate mental model of:
- The target program's architecture and hot paths.
- The hardware/runtime environment (CPU, GPU, memory hierarchy, I/O).
- Where time and resources are actually spent (profiling data, prior experiments).
- Which assumptions from previous iterations still hold.

The model should be updated after every experiment. When experiments contradict expectations, the model is wrong and must be revised, not the experiment.

### 2. Design (Formulate a Hypothesis)

Propose a specific, falsifiable hypothesis. Good hypotheses are:
- **Specific**: "Increasing batch size from 32 to 64 will improve throughput by ~15% because the GPU is underutilized" (not "make it faster").
- **Falsifiable**: There must be a conceivable experimental outcome that would disprove it.
- **Grounded**: Based on the current model, prior experimental results, or established algorithmic knowledge.
- **Minimal**: Change one thing at a time when possible, to isolate effects.

Hypotheses can come from:
- **Induction**: Patterns observed in prior experiments (e.g. "larger batches consistently helped, so an even larger batch might help further").
- **Creative insight**: Novel algorithmic ideas, known techniques from the literature, or architectural redesigns.
- **Analysis**: Deductive reasoning about algorithmic complexity, cache behavior, parallelism, etc.

### 3. Analysis (Predict Before Measuring)

Before implementing, reason about the expected outcome:
- What is the expected direction and magnitude of improvement?
- What could go wrong (OOM, numerical instability, regression on other metrics)?
- Is the complexity cost worth the expected gain? (Simplicity criterion: all else equal, simpler is better.)

This step prevents wasted experiments and builds understanding even when hypotheses fail.

### 4. Implementation (Make the Change)

Implement the change in the target file(s). Principles:
- **Minimal diff**: Change only what the hypothesis requires.
- **Correctness first**: The program must still produce correct results.
- **Commit before running**: Every experiment has a corresponding git commit, so changes are traceable and revertable.

### 5. Experiment (Run and Measure)

Run the benchmark and collect results:
- Redirect all output to a log file to avoid flooding the agent's context.
- Extract the key metric(s) from the log.
- If the run crashes, diagnose from the log tail.

**Parallel runs**: Whenever the benchmark involves multiple inputs, seeds, or configurations, prefer GNU `parallel` to run them concurrently. This dramatically reduces wall-clock time per iteration and should be the default approach unless runs compete for shared resources (e.g. a single GPU). Example:
```bash
parallel --jobs 4 --results run_results/ './bench.sh --input {} > logs/run_{}.log 2>&1' ::: input1 input2 input3 input4
```
Only parallelize when runs are independent and the system has sufficient resources (CPU cores, memory, GPU slots) to avoid contention that would distort measurements.

**Aggregation**: When an experiment produces multiple measurements (e.g. across inputs or seeds), use the **geometric mean** as the default summary statistic. The geometric mean is appropriate for ratios and multiplicative quantities like speedups or normalized scores, and is less sensitive to outliers than the arithmetic mean. Compute it as:
```
geometric_mean = (x1 * x2 * ... * xn) ^ (1/n)
```
Use the arithmetic mean only when the metric is inherently additive (e.g. total time summed across phases) and the user explicitly requests it.

### 6. Evaluate (Keep or Discard)

Compare the result to the current best:
- **Improvement**: Keep the change. The branch advances, and the change is exported as the next numbered patch (see [Patches](#patches)).
- **No improvement or regression**: Discard. Git reset to the previous best.
- **Crash**: Attempt a quick fix if it's trivial (typo, missing import). Otherwise log as crash and move on.

Apply the **simplicity criterion** when evaluating:
- A tiny improvement that adds significant complexity is not worth keeping.
- An equal result with simpler code is a win; keep it.
- Removing code while maintaining performance is a great outcome.

## Output Format

The benchmark should print a summary with at least the primary metric. The agent extracts key values via grep. Example:

```
grep "^primary_metric:" run.log
```

## Logging Results

Every experiment is logged to `results.tsv` (tab-separated). The TSV has a header row and columns:

```
commit	metric_value	resource_usage	status	hypothesis
```

1. **commit**: git commit hash (short, 7 chars)
2. **metric_value**: the primary metric achieved (use 0.000000 for crashes)
3. **resource_usage**: peak resource consumption, e.g. memory in GB (use 0.0 for crashes)
4. **status**: `keep`, `discard`, or `crash`
5. **hypothesis**: the falsifiable hypothesis that motivated this experiment

Example:

```
commit	metric_value	resource_usage	status	hypothesis
a1b2c3d	0.997900	44.0	keep	baseline
b2c3d4e	0.993200	44.2	keep	doubling LR will reduce val_bpb because current LR undershoots the loss basin
c3d4e5f	1.005000	44.0	discard	GeLU activation will improve gradient flow in early layers
d4e5f6g	0.000000	0.0	crash	doubling model width will improve capacity (OOM)
```

Note: do not commit `results.tsv`, `patches/`, or `report/`; leave them untracked. Add all three to `.git/info/exclude` during setup, so that `git reset --hard` to the previous best never touches them.

## Patches

Every accepted change is kept as a numbered patch in `patches/`, created during setup. Patches are numbered in order of acceptance (`0001`, `0002`, ...), not by experiment number; the baseline gets no patch. Right after a change is kept:

```bash
git format-patch -1 HEAD --stdout > patches/$(printf '%04d' $N)-<short-slug>.patch
```

where `N` is the number of accepted changes so far and `<short-slug>` names the change in a few words (e.g. `0003-bucket-queue-refinement.patch`). The commit message of a kept commit states the hypothesis, so each patch is self-describing. Applying all patches in order to the baseline commit reproduces the current best version:

```bash
git checkout <baseline-commit> && git am patches/*.patch
```

Never renumber or rewrite existing patches. If a later experiment undoes an earlier change, that undoing is itself a new patch.

## Experiment Report

As a side artifact, the agent maintains a PDF report of the whole session: a title page with summary and contents, the trajectory of the metric over all experiments, the list of accepted patches, and **one page per tested hypothesis** (kept, discarded, and crashed alike) with the hypothesis, intuition, prediction, measurements, verdict, reflection, and the code change.

**Template.** The template lives in this repository under `templates/report/` (`report.tex` and `build_report.py`, Python standard library plus a LaTeX installation with `latexmk`). If AAE is installed as a skill, copy them from the skill directory; otherwise fetch them:

```bash
mkdir -p report/experiments
for f in report.tex build_report.py; do
  curl -sL https://raw.githubusercontent.com/CHSZLab/AgenticAlgorithmEngineering/main/templates/report/$f -o report/$f
done
```

**Session data.** During setup, write `report/session.json`:

```json
{"title": "AAE session: <project>", "subtitle": "<one line: what is optimized, on which branch>",
 "target": "<target files>", "metric": "<metric name>", "unit": "s", "direction": "lower",
 "resource": "peak memory [GB]", "machine": "<CPU, cores, RAM>", "branch": "aae/<tag>",
 "date": "<YYYY-MM-DD>", "summary": "<short narrative of the trajectory; update it from time to time>"}
```

`direction` is `lower` or `higher` (which way the metric improves).

**Per experiment.** Experiments are numbered `001`, `002`, ... in the order they are run; the baseline is `001`. Each experiment gets a folder `report/experiments/NNN/` with two files:

- `change.patch`: the code change, saved right after committing and **before** the benchmark runs, because a discarded change disappears with the reset: `git show HEAD > report/experiments/NNN/change.patch`.
- `meta.json`: written in two steps. At commit time, record what was predicted; after evaluation, add what happened:

```json
{"exp": 7, "title": "Bucket queue in refinement", "commit": "b2c3d4e",
 "hypothesis": "Replacing the binary heap ... reduces time by ~15% because ...",
 "intuition": "Why this should work, from the current model of the system (profiles, prior results).",
 "prediction": "Expected direction and magnitude, and what could go wrong.",
 "status": "keep", "metric": 2.181, "resource": 1.2,
 "measurements": [{"input": "rgg_n_2_20", "value": 3.483}, {"input": "road_eu", "value": 3.976}],
 "verdict": "Confirmed: -15.2% geometric mean, matching the prediction.",
 "reflection": "What the result says about the model and what to try next.",
 "patch": "patches/0003-bucket-queue-refinement.patch"}
```

`status` is `baseline`, `keep`, `discard`, or `crash`; `patch` is set only for kept changes. `measurements` holds the per-input values of the primary metric (one entry per input or seed); if `metric` is omitted, the generator uses their geometric mean. Text fields are plain text; `` `code` `` is set in typewriter and `$...$` is passed through as math. The generator compares every experiment against the baseline and the best result accepted before it, so only this experiment's values need to be recorded.

**Build.** After every experiment (after logging), rebuild the report:

```bash
python3 report/build_report.py report > /dev/null 2>&1 || true
```

This writes `report/report.pdf`. Rebuilding is cheap and idempotent, so the report is always current when the user interrupts the loop. A failing build must never stop the loop; note it and fix the offending `meta.json` text later. Before handing the report to the user, check `report/report.log` for overfull boxes and look at the PDF.

## The Experiment Loop

The experiment runs on a dedicated branch (e.g. `aae/mar21`).

**The first run** is always the unmodified baseline.

LOOP FOREVER (DO NOT STOP EVER):

1. **Model**: Review the current state: branch, recent results, what has worked and what hasn't. Update your mental model.
2. **Hypothesize**: Formulate a specific, falsifiable hypothesis for the next change.
3. **Analyze**: Predict the expected outcome and assess whether the experiment is worth running.
4. **Implement**: Modify the target file(s) according to the hypothesis.
5. **Commit**: `git commit` the change, with the hypothesis in the commit message. Save the change and the prediction for the report: `git show HEAD > report/experiments/NNN/change.patch` and the first half of `meta.json` (see [Experiment Report](#experiment-report)).
6. **Experiment**: Run the benchmark: `<run_command> > run.log 2>&1` (redirect everything; do NOT use tee or let output flood your context).
7. **Measure**: Extract results: `grep "^<metric>:" run.log`
8. **Evaluate**:
   - If grep output is empty, the run crashed. Run `tail -n 50 run.log` to read the error. Attempt a fix if trivial; otherwise give up on this hypothesis.
   - If the metric improved: keep the commit, advance the branch, and export it as the next numbered patch in `patches/` (see [Patches](#patches)).
   - If the metric is equal or worse: `git reset` back to the previous best.
9. **Log**: Record the result in `results.tsv`.
10. **Reflect**: What did this result tell you? Update your model. Did it confirm, refute, or refine your hypothesis? Use induction from accumulated results to generate the next hypothesis.
11. **Report** (mandatory, every experiment): Complete `report/experiments/NNN/meta.json` with status, measurements, verdict, and reflection, then rebuild the report with `python3 report/build_report.py report`.
12. **Go to 1**.

## Operational Rules

**Timeout**: Each experiment should complete within the configured time budget (plus startup overhead). If a run exceeds 2x the budget, kill it and treat it as a failure.

**Crashes**: Use judgment. Fix trivial bugs (typo, missing import) and re-run. If the idea is fundamentally broken, skip it, log "crash", and move on.

**NEVER STOP**: Once the loop begins, do NOT pause to ask the user if you should continue. The user may be away and expects autonomous operation. If you run out of ideas, think harder:
- Re-read the target code and benchmark for new angles.
- Combine near-misses from previous experiments.
- Try more radical architectural changes.
- Revisit discarded ideas with modifications.
- Look at algorithmic alternatives for the core computation.

The loop runs until the user manually interrupts.

**Report after every experiment**: The report is updated after each experiment, without exception: kept, discarded, and crashed experiments all get their `meta.json` completed and the report rebuilt before the next hypothesis is formulated. Kept experiments additionally get their numbered patch in `patches/` at the same point. Never batch report updates for later; the report must reflect every experiment run so far whenever the user looks at it or interrupts the loop.

**Simplicity criterion**: All else being equal, simpler is better. A small improvement that adds ugly complexity is not worth it. Removing code for equal or better results is a great outcome. Weigh complexity cost against improvement magnitude.

**Resource usage** is a soft constraint. Some increase is acceptable for meaningful metric gains, but it should not blow up dramatically.

## Knowledge Base

This methodology is supported by a community-contributed knowledge base of optimization techniques, experiment results, and lessons learned from AAE sessions. The knowledge base lives in the AAE repository at:

https://github.com/CHSZLab/AgenticAlgorithmEngineering/tree/main/knowledge-base

Before or during a tuning session, consult the knowledge base for techniques relevant to your problem:

1. Fetch the index: `curl -sL https://raw.githubusercontent.com/CHSZLab/AgenticAlgorithmEngineering/main/knowledge-base/INDEX.md` and scan titles, problem domains, and key techniques.
2. Fetch individual entries that seem relevant (same base URL, replace `INDEX.md` with the entry filename from the index).
3. Use the insights to inform hypothesis generation in the AE cycle.

If you have web search or web fetch tools available, use those instead of curl. If the knowledge base is available locally (e.g. as a git submodule or in the same repository), read the files directly.

### Contributing Back

If your AAE run produces insights that could help others, ask the user whether you may submit a PR to the knowledge base. If the user agrees, fork the AAE repository (if needed), create a new entry following the template in `knowledge-base/CONTRIBUTING.md`, update `INDEX.md`, and open a pull request via `gh` or the GitHub MCP server.

Never create the PR without explicit user permission.

## Philosophical Foundation

This methodology mirrors Popper's scientific method as applied to algorithm engineering (Sanders, 2009):

- **Falsifiable hypotheses** drive every experiment. "It might be faster" is not a hypothesis. "Replacing the O(n^2) inner loop with a hash-based lookup will reduce latency by ~40% for inputs >10k elements" is.
- **Induction** from experiments feeds back into new hypotheses. Each result, whether positive or negative, refines understanding.
- **Reproducibility** is ensured by git commits, deterministic benchmarks, and logged results.
- **The cycle never ends**: there is always another hypothesis to test, another angle to explore, another simplification to try. Algorithm engineering is not a linear process but a continuous spiral of refinement.
