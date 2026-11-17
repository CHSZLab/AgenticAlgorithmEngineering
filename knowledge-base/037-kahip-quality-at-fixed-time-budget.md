# Improving the cut quality of a mature multilevel graph partitioner at a fixed time budget

File name for the knowledge base: `037-kahip-quality-at-fixed-time-budget.md`

## Problem

Improving the solution quality (edge cut) of [KaHIP](https://github.com/KaHIP/KaHIP), a mature multilevel graph partitioner, by adding a new preconfiguration `ultra` on top of the `strong` configuration. A previous AAE speed campaign had made KaHIP v3.26 about 2x faster than v3.25; the goal was to spend that saved time on better cuts. Constraints: imbalance 3% as in strong, every existing preconfiguration bit-identical to v3.26, and kaffpaE / KaBaPE (the memetic algorithms that call kaffpa as their operator) should gain too.

- **Metric Q** = geometric mean over jobs of (mean cut of the candidate over the seeds + 1) / (mean cut of v3.26 strong over the same seeds + 1). Lower is better. For kaffpaE the same ratio at a fixed `--time_limit` is called QE.
- **Benchmark:** 73 graph x k jobs (k from 2 to 256) on 19 graphs (meshes, road networks, social and web graphs, 10k to 2.2M nodes). Tuning set: 53 jobs on 15 graphs, seeds 1-5. Held out until the end: 4 graphs (20 jobs) and seeds 7-9 on all jobs. A/A noise of Q measured with strong seeds 11-15 against 1-5.
- **Quality gate:** a change is kept only if Q improves against the current ultra base, measured in the same batch, with a consistent sign across seed batches or k, and no more partitions above the balance bound than strong.
- **Time gate:** per job, ultra must stay within the v3.25 strong time: median wall time <= 1.05 b + 0.05 s for every job (b = v3.25 strong time), and geometric mean and total ratio <= 1.
- **Identity gate:** every kept change passes a bit-identity check of all old configurations (2907 runs over all preconfigurations, k and eps) and of 28 CLI paths against v3.26.

## What Worked

The final ultra reaches **Q 0.9777 (2.2% smaller cuts than v3.26 strong)** on the tuning set and the same 0.9777 on held-out graphs, at 2.0x the time of v3.26 strong and below the time of v3.25 strong on every job. Below are the techniques, in order of impact, with enough detail to reproduce.

### 1. Jet negative-gain label propagation before FM (~1.4%, 6.5% on social graphs)

Jet (Gilbert et al., SIAM J. Sci. Comput. 2024) is a refinement built for GPUs, but it transfers to a sequential multilevel partitioner as a step on every uncoarsening level, run before the existing k-way FM. Per iteration:

1. **Candidate moves:** every unlocked boundary node picks its best adjacent block, and is a candidate if the gain is non-negative or the loss is small: -gain < c * (connection to its own block), with c = 0.25 on unit node weights (finest level) and 0.75 on weighted (coarse) levels. Negative-gain moves are allowed; this is what lets it leave the local minima that FM converges to.
2. **Afterburner:** recompute each candidate's gain assuming that the neighbors with a higher priority (better gain, ties by node id) have already moved, and keep only candidates whose recomputed gain is non-negative. This filters out conflicting moves without sequential dependencies. All kept moves are applied at once, and moved nodes are locked for the next iteration.
3. **Rebalancing:** when a block is over the bound, the iteration rebalances instead of moving: it moves the nodes with the smallest loss per weight out of every overloaded block.
4. Keep the best balanced partition seen; stop after 12 iterations without improvement by more than a factor phi = 0.999.

Then FM and the pairwise flow refinement run as before, on a better starting point.

The decisive detail: **the rebalancer must consider interior nodes, not only boundary nodes.** A version with a boundary-only rebalancer (to save time) lost nearly the whole gain (Q 0.9977 instead of 0.9852), because when the boundary nodes run out, the overloaded block cannot shed weight and Jet's negative-gain moves are rolled back. The final version keeps the incremental cut and boundary bookkeeping and replays the best partition onto KaHIP's boundary structure node by node.

Jet is weakest on 2D meshes and web graphs (worst jobs 1% worse), as the paper reports, and strongest on social graphs.

### 2. The unlocked flow model F_H in pairwise flow refinement (~0.3%)

KaHIP's flow refinement builds a region around the cut of two blocks and computes a min cut. In the classic model, the nodes on the region boundary are fixed to their blocks. The unlocked model of Heuer, Sanders, Schlag (ACM JEA 2019) instead connects each border node to the source or the sink with the weight of its edges that leave the region. The min cut then finds the same cut or a better one, and it may move border nodes too. The change is small (one network construction) and helps most at large k (Q 0.9939 at k = 64). It costs 8% time and gave Q 0.9974 over 10 seeds, with the same sign in both seed batches.

### 3. Spend saved time on global work, not local work (~0.7%)

Before building new components, single parameter levers on v3.26 strong showed where time pays:

- **Global work pays:** 4 V-cycles Q 0.9967; 8 V-cycles 0.9938 (but 10 jobs over budget); 256 initial partitioning repetitions 0.9958.
- **Local work does not pay:** 30 FM multitry rounds Q 0.9999; FM adaptive stopping limit x30: 1.0004; flow regions 16x larger: 1.0001.

The kept setting is 3 V-cycles for k = 2 (4 went over budget on one job) and **best of 2 independent runs for k > 2**. Later, more V-cycles of one run were tested instead of best of 2 at the same time: 0.5% worse for k > 2. So two independent runs beat a longer single run here. The likely reason is that the multilevel hierarchies differ, which gives diversity that more refinement on one hierarchy does not.

### 4. Memetic algorithm (kaffpaE): rank overloaded individuals behind balanced ones, and keep the input individual

These are two small changes in the evolutionary layer. Both are needed once a stronger operator is plugged in:

- **Imbalance penalty:** kaffpaE's fitness was the cut alone. Combine operators partition at a relaxed imbalance (up to 25%) and then refine at the real bound without enforcing it, so an overloaded individual with a small cut could win selection and the final choice. The fix sets the fitness of an overloaded individual to total edge weight + 1 + overload, so every balanced individual ranks before it. The final partition is rebalanced with the existing negative-cycle model if it is still overloaded. On the 8 eps 1 instances with invalid runs, the share of runs over the bound fell from 16 of 24 (v3.26) to 1 of 24, with equal cuts.
- **Keep the input:** when kaffpaE starts from an input partition, the input only seeded the individuals built from it, which are re-partitioned. So at eps 0 the result was worse than the input in 9 to 12 of 124 runs. Inserting the input unchanged as one more individual makes the result never worse than the input (0 of 20 reruns of the worse cases).
- **One partition per operator:** best of 2 is switched off inside kaffpaE (repetitions = 1), since the population already provides diversity and every second counts at a fixed time limit.

With ultra inside, kaffpaE gains 0.5% to 1.6% over v3.26 strong at the same time limits, while the v3.26 speed alone gave kaffpaE 1.9x to 2.6x the rounds and almost no cut gain.

### 5. Guard-field pattern plus identity audits (process, enabled everything above)

Every new behavior is a field in the configuration struct with a default that reproduces the old code path. Only the new preconfiguration function sets it, and the new code lives in its own files. Each kept change then passed two audits:

- **idcheck:** 2907 runs of all old preconfigurations, compared by partition hash against stored v3.26 hashes.
- **xpath:** 28 CLI paths (all programs and modes), 3469 runs, comparing output, return code, metric and balance.

The audits found what review missed. They separated the paths that are nondeterministic in v3.26 itself (global multisection, wall-time limits) from real regressions. They also exposed a pre-existing flow refinement bug (an empty "no change" result read as "move everything", which kept a stale cut value). The bug was fixed in ultra, and later in strong and eco as a separate, measured change.

**Pitfall:** configurations compose. Most modes call `strong()` before the chosen preconfiguration, so a field set in `strong()` must be reset explicitly in configurations that are built on top of it but must not inherit it.

### 6. Held-out graphs and seeds

All tuning used 53 jobs and seeds 1-5. Four graphs (one per class plus a random geometric graph) and seeds 7-9 were only run once, at the end. The held-out graphs gave the same Q (0.9777) and the new seeds a slightly better one (0.9729), so the candidates did not overfit the tuning set. Measuring every candidate against the current base **in the same batch** mattered as much: machine noise between batches was of the same size as most component effects (0.1% to 0.3%).

## Experiment Data

| Step | Q vs v3.26 strong (tuning set) | Time (geomean of the v3.25 strong budget) | Verdict |
|---|---|---|---|
| v3.26 strong | 1.0000 | 0.32 | baseline |
| + 4 V-cycles (k = 2), best of 2 (k > 2) | 0.9932 | 0.59 | kept |
| + unlocked flow model F_H | 0.9912 (0.9974 vs previous, 10 seeds) | 0.64 | kept |
| k = 2 back to 3 V-cycles (budget) | 0.9914 | 0.61 | kept |
| + Jet refinement | 0.9777 | 0.65 | kept |
| kaffpaE imbalance penalty, keep input | (kaffpaE only) | | kept |

Final ultra:

- **Quality:** Q 0.9777 on the tuning set (social 0.930, mesh 0.986, road 0.989; k = 2 0.954); 0.9777 on held-out graphs; 0.9729 on held-out seeds 7-9 (all 73 jobs).
- **Time:** 2.0x v3.26 strong (total 2.09x, max 2.9x). Against v3.25 strong: geomean 0.64, max 0.95, 0 jobs over budget.
- **Balance:** invalid runs ultra vs strong: 0 / 265 vs 3 / 265 (tuning), 1 / 100 vs 2 / 100 (held-out graphs), 1 / 219 vs 4 / 219 (new seeds).
- **Contributions:** best of 2 / V-cycles 0.7%, F_H 0.3%, Jet 1.4% (6.5% on social graphs).
- **kaffpaE / KaBaPE** at fixed time limits (1x, 3x and 10x the strong kaffpa time; 10 instances, seeds 1-5), QE of ultra vs v3.26 strong inside the same binary:

| Mode, limit | QE ultra vs v3.26 strong | QE ultra vs v3.25 | Evolutionary rounds vs v3.26 strong |
|---|---|---|---|
| kaffpaE 1x | 0.9907 | 0.9932 | 0.96 |
| kaffpaE 3x | 0.9912 | 0.9845 | 0.87 |
| kaffpaE 10x | 0.9946 | 0.9896 | 0.79 |
| KaBaPE (eps 0) 3x | 0.9870 | 0.9890 | 1.02 |
| KaBaPE (eps 0) 10x | 0.9838 | 0.9876 | 1.05 |

- **Experiments:** 45 measured candidates, 6 kept (the commits in the table), 39 discarded; one more (a combine operator) was dropped before it was built. The campaign used a written log instead of results.tsv, so the count comes from that log.

## What Didn't Work

- **Relaxed-balance k-way FM** (move a balance-blocked node to its best block with room, or overload temporarily and accept only balanced best states): v1 Q 1.028 to 1.061 (worse, up to 3.8x time); v2 with positive gains only: 1.0001, because the pairwise flows with most-balanced minimum cuts already move those nodes.
- **Randomized top-l move selection in FM** (diversity): l = 2 / 4 / 8 gave Q 1.0004 / 1.0036 / 1.0070, adaptive 1.0014; neutral to worse in kaffpaE; about 0.5% better only in KaBaPE at eps 0.
- **Larger flow regions:** 16x gave 0.13% at +40% time (11 jobs over budget), 32x the same 0.13% at +160% time (43 jobs over budget).
- **More F-cycle arms** (an arm on every level instead of every second): 0.26% for +34% time; 6 jobs over budget.
- **Jet parameter changes:** c = 0.5 Q 1.0006, patience 24 0.9995, phi 0.9999 1.0000, a second Jet pass after FM and flows 1.0000. The paper's settings were already the optimum; FM and flows absorb small extra Jet gains.
- **Weighted sparse tabu search** on the coarsest level (MITS-like, edge-work bounded): 0.6% to 1.1% better coarsest cuts at k = 256, but over 10 seeds Q 0.99966, inside the noise. Uncoarsening absorbs coarse-level gains.
- **KaBaPE relax-and-rebalance rounds** (local search at a relaxed bound, then negative-cycle rebalancing): mean cut 0.10% to 0.13% worse on 194 eps 0 instances; they cost 40% of the evolutionary rounds.
- **Two runs plus a combine** instead of best of 2: dropped before it was built, since recombination is the memetic algorithm's job and the single run should get better local search.
- **ILP region improvement** after the evolutionary search (Gurobi, KaHIP ilp_improve): regions up to 0.65M nonzeros are solved to optimality in 57 s; 1M hits the 600 s limit at a 0.075% gap; 2.5M to 5M leave 0.33% to 1.2% gaps. The region size has to be capped at about 1M nonzeros, and on near-optimal partitions 1 h per instance improved the cut by at most 1 edge.

## Code Example

The guard-field pattern that kept 2907 of 2907 old-configuration runs bit-identical while new code was added:

```cpp
// partition_config.h: the defaults reproduce the old behavior
bool flow_unlocked_model      = false;
bool jet_refinement           = false;
bool mh_penalty_for_imbalance = false;
bool mh_keep_input            = false;

// app/configuration.h: only the new preconfiguration turns them on
inline void configuration::ultra( PartitionConfig & partition_config ) {
        strong(partition_config);
        partition_config.flow_unlocked_model      = true;
        partition_config.jet_refinement           = true;
        partition_config.mh_penalty_for_imbalance = true;
        partition_config.mh_keep_input            = true;
        // k = 2 has the least time headroom: one more V-cycle; otherwise best of two full runs
        if( partition_config.k == 2 ) {
                partition_config.global_cycle_iterations = 3;
        } else {
                partition_config.repetitions = 2;
        }
}

// call site (simplified): the new code lives in its own files and is entered only behind its field
if(config.jet_refinement) {
        jet_refinement jet;
        jet.perform_refinement(config, G, boundary);
}
// ... the unchanged k-way FM and flow refinement follow
```

## Environment

C++ (KaHIP v3.26), GCC 13.3 (CMake Release build, -O3), Ubuntu 24.04, Intel Xeon w5-3435X (16 cores). Runs were single-threaded, 16 at a time on fixed cores, with nice. kaffpaE and KaBaPE used MPI with 1 process per run. The graphs have 10k to 2.2M nodes and up to 2.7M edges; k ranges from 2 to 256 with 3% imbalance, and eps 0 for KaBaPE.

## Links

- KaHIP PR #175 (flow refinement fix): https://github.com/KaHIP/KaHIP/pull/175
- KaHIP PR #177 (ultra preconfiguration, merged into master; review history in #176): https://github.com/KaHIP/KaHIP/pull/177
- ultra manual: https://github.com/KaHIP/KaHIP/blob/master/manual/ultra.pdf
- Jet: M. S. Gilbert, K. Madduri, E. G. Boman, S. Rajamanickam, SIAM J. Sci. Comput. 46(5), 2024, https://doi.org/10.1137/23M1559129
- F_H: T. Heuer, P. Sanders, S. Schlag, ACM JEA 24(1), 2019, https://doi.org/10.1145/3329872
