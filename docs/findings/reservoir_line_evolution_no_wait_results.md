# Reservoir line evolution: no-wait pilot results

Status: core implementation is present. The broad campaign was interrupted
for operator and telemetry corrections. A frozen six-run R2 seed comparison
is running under `benchmarks/output/reservoir_line_evolution_20260914/coupled_seed_comparison_v1`. Its supervisor writes `summary.json` and `report.md` after each run. The broad campaign is not complete.

## Pre-campaign smoke measurements

The R2 current-port domain produced 14 relevant stop patterns and 30 lifecycle
templates without materializing pairwise template tables.

An intentionally restricted K≤12 smoke test gave the following results. These
runs establish operation and evaluation throughput only; they are not part of
the frozen comparison and cannot be compared with the full-fleet all-stop
reference.

| Method | Search wall time | Distinct evaluations | Physically feasible | Best served |
|---|---:|---:|---:|---:|
| Random | 12.9 s | 10,510 | 1,686 | 520 |
| GA `mixed_global` | 12.9 s | 6,846 | 1,084 | 696 |
| Optuna TPE | 7.9 s | 353 | 102 | 336 |

Every reported incumbent passed the independent physical and integral
passenger validator. The fixed-movement passenger IP proved the recorded
smoke incumbents optimal for their movement. The high decoder throughput
confirms that no timing optimizer is invoked for no-wait movement proposals.

Two defects found by the correctness work were fixed before the campaign:

- sampled phase and gap values now obey arbitrary instance dispatch grids;
- initialization terminates even when a tiny domain has fewer distinct
  genomes than the requested population.

The final campaign table, progress curves, all-stop distances and continuation
decision will be added after the frozen run.


## Coupled-operator regression gate

45 evolution/line tests passed after the operator change. New tests verify donor internal dispatch gaps, preservation of all outside departures, rejection of an incompatible block boundary, purely local variation without hidden crossover, and forwarding of the passenger time limit. A short GA smoke produced population snapshots and exercised local, block, coupled-crossover and global operators.
