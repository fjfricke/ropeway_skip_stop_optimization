# Thesis experiment calibration — 14 September 2026

## Status and scope

The bounded calibration completed all 19 planned runs in 2,972 seconds
(49.5 minutes). Every subprocess wrote a result, supervisor record and source
identity; no run exceeded the 32 GiB process-tree limit. Raw artifacts are in
`results/thesis_calibration_20260914_v6/`.

This is a calibration of model size, demand resolution and useful run budgets.
It is not the final thesis campaign. No unresolved capacity interval is
reported as an optimum.

## Fleet limits and the historical Max50 cap

The number 50 came from the historical Max50 reservoir experiment. It was a
chosen computational cap, not a value derived from ropeway geometry, headways
or passenger capacity. It is not used as a cap for the new thesis cases.

The new cases distinguish `K_AS`, the largest validated regularly spaced
No-Wait All-Stop fleet, from `K_port^UB`, the necessary throughput upper bound
obtained from the dispatch window and reservoir-port headway. `K_port^UB` does
not claim that every smaller fleet is feasible; station resources and route
interactions still have to be checked.

| Topology | Geometry | All-Stop cycle [s] | AS headway [s] | `K_AS` | `K_port^UB` |
|---|---|---:|---:|---:|---:|
| T5R | G300 | 565.333333 | 11.666667 | 48 | 537 |
| T5R | G800 | 982.000000 | 11.666667 | 84 | 933 |
| T5R | G1200 | 1,315.333333 | 11.666667 | 112 | 1,249 |
| T6R | G300 | 678.400000 | 11.666667 | 58 | 644 |
| T6R | G800 | 1,178.400000 | 11.666667 | 101 | 1,119 |
| T6R | G1200 | 1,578.400000 | 11.666667 | 135 | 1,499 |
| T6R | GUNEQ-v2 | 1,178.400000 | 11.666667 | 101 | 1,119 |

The five later Skip-Stop caps are geometrically spaced between these derived
endpoints. The calibration used the first three G800 values: 84, 154 and 280.
These are computational sampling points, not physical thresholds.

## All-Stop capacity and release-time resolution

The baseline uses 84 regularly spaced All-Stop cabins on T5R/G800 and optimizes
their common phase together with integer passenger assignment. A feasible
endpoint is a validated full-service plan. An infeasible endpoint is a CP-SAT
proof for the same fixed All-Stop family. A missing upper endpoint means it was
not proved inside the 120-second budget.

| Demand | Resolution | Proven feasible | Proven infeasible | Capacity | Peak RSS |
|---|---:|---:|---:|---|---:|
| F2/P0 | 30 s | 2,875 | 2,882 | open | 1.83 GiB |
| F2/P0 | 15 s | 2,500 | 3,000 | open | 3.03 GiB |
| F0/P0 | 30 s | 4,000 | — | open above | 5.99 GiB |
| F0/P0 | 15 s | 2,000 | — | open above | 9.45 GiB |
| F4/P0 | 30 s | 12,000 | — | open above | 3.60 GiB |
| F4/P0 | 15 s | 4,000 | — | open above | 5.13 GiB |

The unequal lower endpoints show that the 15-second models are harder within a
common short budget; they do not show that aggregation changes true capacity.
Because no pair produced two exact capacities, the planned one-percent
acceptance test could not be evaluated. Resolution therefore remains
**unresolved**. The campaign used 15 seconds for the following line runs as the
conservative finer representation.

For F2/30 s, the tightest result is

\[
2{,}875 \leq \kappa_{AS} < 2{,}882.
\]

The same run proved full service at 2,750. That statement applies only to the
30-second aggregation.

## Reservoir line formulation

The line test used F2/P0 with 2,750 people. Phase 1 optimized No-Wait pattern,
fleet and dispatch decisions; phase 2 fixed the route sequence and released
dispatch times and Exit-Waiting in the complete reservoir CP-SAT model.

| Formulation | Fleet cap | Variables | Constraints | Build | No-Wait served | With Waiting | Used K | Peak RSS |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| shared_rounds | 84 | 1,594,236 | 4,878,426 | 32.6 s | 120 | 120 | 3 | 15.43 GiB |
| shared_rides | 84 | 218,988 | 2,815,554 | 14.9 s | 320 | 320 | 8 | 15.09 GiB |
| shared_rounds | 154 | 2,922,766 | 8,943,466 | 58.3 s | — | — | — | 14.25 GiB |
| shared_rides | 154 | 401,478 | 5,161,534 | 28.1 s | 195 | 208 | 5 | 14.66 GiB |
| shared_rounds | 280 | 5,314,120 | 16,260,538 | 111.3 s | — | — | — | 12.85 GiB |
| shared_rides | 280 | 729,960 | 9,384,298 | 55.6 s | — | — | — | 14.44 GiB |
| shared_rides, seed 1 | 280 | 729,960 | 9,384,298 | 56.1 s | 448 | **456** | 11 | 14.31 GiB |
| shared_rides, seed 2 | 280 | 729,960 | 9,384,298 | 55.7 s | 448 | 448 | 11 | 15.15 GiB |

`shared_rides` is the structural winner. At K=84 it uses about 86% fewer
variables than `shared_rounds`, finds a better incumbent and is the only
formulation to find a plan at K=154. This supports using `shared_rides` as the
experimental line formulation while keeping historical defaults reproducible.

The long K=280 runs continued to improve. Seed 1 reached 448 served after 611.8
seconds; seed 2 reached the same value after 460.7 seconds. Waiting then improved
seed 1 from 448 to 456, while seed 2 stayed at 448. The second stage can repair
and improve a fixed route sequence, but cannot compensate for a weak pattern
incumbent. The line model is not ready for the final capacity comparison: 456
of 2,750 is far below the relevant All-Stop scale, and the native served upper
bound remained the trivial total demand of 2,750.

The main scaling problem is model construction and constraint count, not the
32 GiB cap. `shared_rides` at K=280 spends about 56 seconds building 9.38 million
constraints. Raising K to the port bound is unjustified with this encoding.

## Labelled Arc-Flow journey-time control

The Journey-Time calibration proved an All-Stop K=1 full-service capacity of 62
people and fixed demand at 31 people (50%). All runs use T5R/G300, F3/P0, full
service and the same balanced starts.

| K | Validated objective [passenger-s] | Status | Binary vars | Integer vars | Constraints | B&B nodes | Wall |
|---:|---:|---|---:|---:|---:|---:|---:|
| 1 | 13,702.905092 | optimal, gap 0 | 958 | 8,803 | 13,840 | 1 | 2.5 s |
| 5 | 5,646.686741 | optimal, gap 0 | 4,790 | 43,991 | 70,240 | 1 | 3.5 s |
| 20 | 4,169.583398 | optimal, gap 0 | 18,575 | 169,830 | 268,767 | 210 | 35.5 s |
| 20, seed 1 | 4,169.583398 | optimal, gap 0 | 18,575 | 169,830 | 268,767 | 251 | 26.8 s |
| 20, seed 2 | 4,169.583398 | optimal, gap 0 | 18,575 | 169,830 | 268,767 | 226 | 28.1 s |

Both additional seeds reproduce the K=20 optimum. Labelled Arc-Flow is ready
for the planned low-demand Journey-Time curves at this scale. Larger K values
should follow the predeclared geometric sequence and stop at the stated
unresolved/size criterion.

## Decision for the full thesis campaign

1. Keep the common-phase All-Stop model as capacity reference and report open
   intervals until adjacent feasible/infeasible demands are proved.
2. Use Labelled Arc-Flow for low-demand Journey Time. K1/K5/K20 are globally
   solved and independently validated.
3. Use `shared_rides` for further line-pattern pilots because its size and
   incumbents dominate `shared_rounds` here.
4. Do not launch the full high-load capacity matrix yet. First reduce the
   `shared_rides` constraint count or supply a much better constructive line
   seed. More RAM is not the observed bottleneck.
5. Keep 30-versus-15-second resolution open. These results do not support a
   one-percent equivalence claim.

Technology values follow Haimerl et al. (2022),
[WSC paper, section 4.1](https://informs-sim.org/wsc22papers/138.pdf), and the
station derivation is documented against the
[GART/STRMTG/Cerema guide (2023), section 7.3](https://www.gart.org/wp-content/uploads/2023/08/Guide-accessibilite-transport-par-cable_Juin-2023.pdf#page=139).
The exact contract and demand references are in
`docs/thesis/experiment_definition_register_20260913.md`.
