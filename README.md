<p align="center">
  <img src="https://raw.githubusercontent.com/CHSZLab/AgenticAlgorithmEngineering/main/banner.svg" alt="Agentic Algorithm Engineering" width="900"/>
</p>

# Agentic Algorithm Engineering 

This repository contains the program definition for **Agentic Algorithm Engineering (AAE)**, a methodology that turns autonomous agents into performance engineers following the Algorithm Engineering cycle: design, analysis, implementation, and experimental evaluation, driven by falsifiable hypotheses.

See [AAE.md](AAE.md) for the full program definition.

## Algorithm Engineering

Algorithm Engineering, as defined by [Sanders (2009)](https://doi.org/10.1007/978-3-642-03456-5_22), is a methodology for algorithmic research built around a cycle of design, analysis, implementation, and experimental evaluation. Unlike traditional algorithmics, which often stops at theoretical analysis, algorithm engineering insists on closing the loop: hypotheses about algorithm performance are tested experimentally on realistic inputs, and the results feed back into improved designs. Central to this process are falsifiable hypotheses, following Popper's scientific method applied to algorithms.

Agentic Algorithm Engineering takes this methodology and hands the cycle to an autonomous AI agent. The agent formulates hypotheses, implements changes, runs experiments, and evaluates results, iterating continuously without human intervention. This allows systematic, high-throughput exploration of the optimization space while maintaining the scientific rigor of the AE methodology.

## Usage

The agent must run in a mode that does not require user input, since the AE cycle is designed to run autonomously and indefinitely. If you are using Claude Code, launch it with `--dangerously-skip-permissions` (byPassPermissions mode). For other agent frameworks, ensure that all tool calls (file edits, shell commands, git operations) are auto-approved so the loop can proceed without interruption.

### Keeping the Loop Alive with Agent Teams

In practice, even with `--dangerously-skip-permissions`, the agent may eventually stop and ask for user input instead of continuing the loop. To solve this, use Claude Code's **Agent Teams** feature to set up a manager/executor pair that keeps the loop running autonomously.

**How it works:** A manager agent monitors an executor agent that runs the AAE program. Whenever the executor pauses and asks for input, the manager tells it to continue.

**Setup:**

1. Enable agent teams by setting the environment variable:
   ```bash
   export CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS=1
   ```
   Or add it to your `settings.json`:
   ```json
   {
     "env": {
       "CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS": "1"
     }
   }
   ```

2. Launch Claude Code with `--dangerously-skip-permissions` and instruct it to create a two-agent team:
   - **Manager**: monitors the executor and, whenever it stops or asks for input, sends it a message to continue the AAE loop.
   - **Executor**: runs the AAE program (`AAE.md`) in the target project directory, performing the full experiment cycle.

   Example prompt for the manager:
   ```
   Create an agent team with one executor teammate. The executor should run
   the AAE program defined in AAE.md on this project. Your job as manager is
   to monitor the executor. Whenever it stops, pauses, or asks for input,
   tell it to continue the experiment loop. Never let it idle.
   ```

3. The manager uses tmux split panes (or in-process mode with `Shift+Down`) to monitor the executor and send follow-up messages when needed.

This orchestration ensures the AE cycle runs truly unattended, even across context window boundaries or when the executor would otherwise break out of the loop.

## Knowledge Base

The project includes a community-contributed [knowledge base](knowledge-base/) of optimization techniques, experiment results, and lessons learned from AAE sessions. Browse `knowledge-base/INDEX.md` for an overview, or contribute your own findings (see `knowledge-base/CONTRIBUTING.md`).

## Author

Christian Schulz, [Algorithm Engineering Group](https://ae.ifi.uni-heidelberg.de/), Heidelberg University

## Contributing

We welcome contributions! Feel free to open a pull request if you have improvements, extensions, or new ideas.
