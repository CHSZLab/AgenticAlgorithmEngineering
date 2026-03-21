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
5. **Verify benchmark works**: Run the benchmark once to confirm it produces output.
6. **Initialize results.tsv**: Create `results.tsv` with just the header row.
7. **Confirm and go**: Confirm setup looks good with the user, then begin.

## Constraints

The user defines these per project. The agent must respect them strictly.

**What the agent CAN do:**
- Modify the designated target file(s). Everything within them is fair game: algorithms, data structures, parameters, control flow, memory layout, parallelism, etc.

**What the agent CANNOT do:**
- Modify the benchmark harness or evaluation code.
- Install new packages or add dependencies beyond what is already available.
- Modify the metric definition or measurement methodology.
- Change the time budget or input data.

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

### 6. Evaluate (Keep or Discard)

Compare the result to the current best:
- **Improvement**: Keep the change. The branch advances.
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

Note: do not commit `results.tsv`; leave it untracked.

## The Experiment Loop

The experiment runs on a dedicated branch (e.g. `aae/mar21`).

**The first run** is always the unmodified baseline.

LOOP FOREVER (DO NOT STOP EVER):

1. **Model**: Review the current state: branch, recent results, what has worked and what hasn't. Update your mental model.
2. **Hypothesize**: Formulate a specific, falsifiable hypothesis for the next change.
3. **Analyze**: Predict the expected outcome and assess whether the experiment is worth running.
4. **Implement**: Modify the target file(s) according to the hypothesis.
5. **Commit**: `git commit` the change.
6. **Experiment**: Run the benchmark: `<run_command> > run.log 2>&1` (redirect everything; do NOT use tee or let output flood your context).
7. **Measure**: Extract results: `grep "^<metric>:" run.log`
8. **Evaluate**:
   - If grep output is empty, the run crashed. Run `tail -n 50 run.log` to read the error. Attempt a fix if trivial; otherwise give up on this hypothesis.
   - If the metric improved: keep the commit, advance the branch.
   - If the metric is equal or worse: `git reset` back to the previous best.
9. **Log**: Record the result in `results.tsv`.
10. **Reflect**: What did this result tell you? Update your model. Did it confirm, refute, or refine your hypothesis? Use induction from accumulated results to generate the next hypothesis.
11. **Go to 1**.

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

**Simplicity criterion**: All else being equal, simpler is better. A small improvement that adds ugly complexity is not worth it. Removing code for equal or better results is a great outcome. Weigh complexity cost against improvement magnitude.

**Resource usage** is a soft constraint. Some increase is acceptable for meaningful metric gains, but it should not blow up dramatically.

## Philosophical Foundation

This methodology mirrors Popper's scientific method as applied to algorithm engineering (Sanders, 2009):

- **Falsifiable hypotheses** drive every experiment. "It might be faster" is not a hypothesis. "Replacing the O(n^2) inner loop with a hash-based lookup will reduce latency by ~40% for inputs >10k elements" is.
- **Induction** from experiments feeds back into new hypotheses. Each result, whether positive or negative, refines understanding.
- **Reproducibility** is ensured by git commits, deterministic benchmarks, and logged results.
- **The cycle never ends**: there is always another hypothesis to test, another angle to explore, another simplification to try. Algorithm engineering is not a linear process but a continuous spiral of refinement.
