# OIP pattern and fleet screening for the thesis

## Question and operating contract

The experiment tests whether a small, demand-specific library of repeating
stop masks can generate useful high-load schedules with fewer than the maximum
fleet. It uses optimized initial placement rather than reservoir dispatch.

- T5R/G500, architecture B, platform speed 0.3 m/s.
- The STOP-leader protection rule applies at both station entry and exit;
  platform occupancy, merge, rope and bypass resources remain unchanged.
- Demand is released over two All-Stop cycles (1,464 s), followed by 900 s for
  passenger completion and 300 s of mandatory continued operation. The service
  and operation horizons are therefore 2,364 s and 2,664 s.
- All cabins are initially empty. There is no reservoir, dispatch window or
  return requirement. Every begun movement and protection interval is checked
  in full, including intervals extending beyond the operation boundary.
- No-Wait, 1-ms movement grid, deterministic 15-s releases, exact active fleet
  sizes K=40, 50 and 62.
- F4 remains excluded. The active demand families are F0, F2 and F3.

The fixed profile sizes are F2=3,210, F3=7,869 and F0=9,781. F2 and F3 are the
110% profile sizes derived from the regular Reservoir All-Stop references. F0
uses the proved regular-reference lower-bound profile because its exact
reference capacity is open. These values are stress loads imported from the
regular-operation study. They are not called capacities or 110% points of this
short OIP contract.

## Pattern allocations

Each family has six deterministic allocations. Counts are obtained with stable
largest-remainder rounding and always sum to K. Cabin IDs assign masks only;
initial spatial order remains free, and symmetry constraints may order cabins
only within identical masks.

- F2: All-Stop; the two complementary direct masks; four-stop; and the three
  pairwise 50/50 mixtures of direct, four-stop and All-Stop.
- F3: All-Stop; the five rotating distance-two direct masks; the five rotating
  three-stop express masks; direct+express; direct+All-Stop; express+All-Stop.
- F0: All-Stop; rotating four-stop; rotating contiguous three-stop; and the
  three pairwise mixtures of those families.

These are prespecified demand-derived allocations. The campaign does not select
new masks after seeing the outcomes.

## Two-stage algorithm

Stage A is an incumbent generator. For every family, K and allocation, CP-SAT
builds the fixed-pattern OIP movement model and stops at the first feasible
movement. The independent movement validator checks it. A fixed-movement
Gurobi model then minimizes unserved passengers and, secondarily, journey time.
Movement search receives 60 s and passenger evaluation 30 s.

Stage B is joint refinement. For each K, the two Stage-A candidates with the
largest validated service are selected; journey time breaks service ties and a
stable allocation order breaks remaining ties. Their complete validated
certificates become CP-SAT hints. The patterns remain fixed, while initial
placement, every event time and the integer passenger assignment are jointly
optimized. Hints fix no decision. Each refinement receives 180 s and minimizes
unserved lexicographically before journey time.

UNKNOWN, resource termination and INFEASIBLE remain distinct. Bounds from a
fixed pattern allocation apply only to that allocation. A fixed-movement
passenger optimum is not an optimum over other initial placements.

## Execution and runtime

Each family contains 18 screening solves and at most six refinements. The
per-family deadline is 60 minutes, including preparation and publication. A
worst-case family uses about 46.5 minutes of solver budgets; the remaining time
covers model construction and validation. The three families run sequentially,
so the full suite can take up to three hours. Seed 0, 12 CP-SAT workers, one
Gurobi passenger thread and a 32-GiB process-tree limit are used throughout.

`benchmarks/run_oip_pattern_screening.py` runs or resumes one frozen family.
`benchmarks/run_oip_thesis_pattern_campaigns.py` freezes and runs F2, F3 and F0
in that order. Manifests include demand/domain fingerprints, exact pattern
counts, solver versions, source revision, all attempts and refinement
provenance. The frontend shows Stage-A service and journey curves and a separate
Stage-B table with source value, refined value, bound and gap.

## Gates and interpretation

Before execution, tests must establish entry/exit headway construction,
cross-solver movement validation, exact pattern cardinalities, fixed-pattern
integrated CP-SAT, checkpoint import from the independently evaluated movement,
stable refinement selection, timeout semantics and frontend serialization.

The experiment succeeds methodologically when it produces independently valid
comparisons and reveals whether joint refinement improves the first feasible
movement. It does not need to beat the regular All-Stop reference. Results are
reported as finite-window OIP stress tests; no claim of periodic feasibility or
regular-operation capacity follows from them.
