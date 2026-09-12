# Reservoir capacity pilot — implementation tracking

Authorized plan: exact restricted anonymous phase search plus a separate
global All-Stop capacity bound; Max50 single-use reservoir; existing physics,
integer passengers and microsecond waiting; no standard change.

## Implemented components

- `reservoir_capacity/network.py`: frozen phase graph, geometry checks,
  seed_events_v1 calendar, reachability and historical replay.
- `reservoir_capacity/model.py`: native binary movement/integer passengers,
  resource sweeps, cumulative waiting deadlines, export and validation.
- `reservoir_capacity/bound.py`: global All-Stop capacity relaxation,
  comparison identity and exact compensated dual certificate.
- Existing arrival-bound builder: optional capacity objective; journey default
  retained. Existing CP-SAT: optional full-service requirement.
- Separate supervised runner and frozen 60-minute comparison campaign.
- Enumeration, FIFO, genuine bypass overtaking, turnover, historical replay,
  LP projection/dual and supervised runner tests.

## Experiment contract

R0 is the unchanged historical Max50/3074 snapshot. R2 changes only demand to
B↔D and C↔E, equally weighted across nine releases 300..1100 seconds.
Preparation reoptimizes integer passengers under fixed movement and supplies
the same checked Skip-Stop reference to both search engines.

Budgets: preparation 300 s; four global LP trials 90 s; two All-Stop CP trials
300 s; two phase trials 300 s; two Skip-Stop CP trials 300 s; R2 repeats in
reverse engine order, 300 s each. Nine minutes remain reserved. All budgets
include build and completion, with a common hard 3600-second deadline.

## Conditional work

The six-station double-ring adapter is authorized only if correctness passes
and a valid SS witness beats the global AS bound, or phase Arc-Flow serves at
least ten extra people against CP-SAT on R2 in both trials. Model shrinkage,
local bounds and imported seeds alone do not pass this gate.

If passed: existing architecture B/20m bypass; two directed rings, shared OD
demand, total maximum 50, free direction allocation, direction fixed during
single use, ports at S0, W=1200, warmup 300/service 3600/recovery 300 seconds,
F2/F0/F4 with P0. Adapter and small tests only; no additional large campaign.

If not passed: document the actual bottleneck and stop the package without
automatically launching longer searches or a new adaptive solver.

Detailed model contract and proof arguments:
[reference](../reference/reservoir_capacity_phase_arc_flow.md).
