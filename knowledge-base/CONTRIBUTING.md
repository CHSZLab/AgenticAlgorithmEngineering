# Contributing to the Knowledge Base

If your AAE session produced insights that could help others, we'd love for you to share them.

## How to Submit

Open a pull request that adds one entry file and a corresponding row in `INDEX.md`. One entry per PR.

If you are an agent running AAE, ask the user whether you may submit a PR. Only proceed with explicit permission. Use `gh` or the GitHub MCP server to create the PR.

## Naming Convention

Name your file `<next-number>-<short-slug>.md`, using the next available number from INDEX.md and a short kebab-case description. Example: `003-loop-unrolling-matrix-multiply.md`.

## Entry Template

Your entry should include the following sections. Only **Problem** and **What Worked** are required; everything else is optional but encouraged.

```markdown
# <Title>

## Problem

What were you optimizing? Describe the problem, input characteristics,
and the metric you were targeting.

## What Worked

The key insight or technique that produced improvement. This is the
most important section; even if you provide nothing else, this should
be useful to someone facing a similar problem.

## Experiment Data (optional)

Results from your AAE run. Can be a pasted results.tsv, a summary
table, or just the key numbers (baseline vs. best).

## What Didn't Work (optional)

Approaches you tried that failed or regressed. Often as valuable as
what worked, since it saves others from repeating dead ends.

## Code Example (optional)

A diff, snippet, or pseudocode showing the core change.

## Environment (optional)

Language, hardware, dataset size, or other context that might affect
whether this technique transfers to another setting.
```

## Quality Bar

- The insight should be transferable: useful to someone facing a similar problem, not just a project-specific tweak.
- "What Worked" should be specific enough to act on, not just "I made it faster."
- Experiment data is encouraged but not required.
