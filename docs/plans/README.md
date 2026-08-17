# Plans

This directory contains future work only. Implemented designs belong in the
code, the project README, the current architecture reference, or the thesis.
Empirical observations belong in `docs/findings`.

Each plan must:

- describe work that is not yet implemented;
- distinguish exact changes from heuristics and research concepts;
- state ordering, correctness conditions, and acceptance evidence;
- remove completed items instead of accumulating implementation history.

Current plans:

- `ean_root_bound_improvement.md`: immediate root-relaxation diagnosis and the
  evidence-driven sequence for strengthening the integrated passenger model.
- `ean_formulation_and_search.md`: immediate baseline validation, bottleneck
  diagnosis, and conditional exact formulation or MIP-search improvements.
- `ean_structural_reformulation.md`: exact structural reductions of the
  integrated EAN passenger MILP that are evaluated only for a measured
  bottleneck.
- `ean_eager_headway_build_performance.md`: exact pair pruning, compact
  conflict storage, batched Gurobi construction, and compact export for large
  eager OIP headway models.
- `ean_oip_symmetry_and_exact_k.md`: exact OIP cabin-label canonicalization,
  inactive-variable handling, and fixed-fleet-size passenger decomposition.
- `ean_decomposition.md`: scaling diagnosis, passenger decomposition,
  progressive search, delayed constraints, and alternative solver paths.
- `dynamic_discretization_cabin_passenger.md`: exact partial time-space cabin
  and passenger planning through Dynamic Discretization Discovery, with an
  optimistic lower-bound master, exact continuous-time lifting, refinement,
  and certified upper bounds.
- `ddd_stronger_cp_support_cuts.md`: layer-state passenger lower bounds,
  independent primal bootstrapping, nearest-feasible CP-SAT support search,
  certified distance cuts, and proof-safe threshold/resource strengthening.
- `ddd_adaptive_anytime_master.md`: adaptive inexact-master control, live
  incumbent/bound measurements, interruption-safe checkpoints, exact finishing,
  threshold strengthening, and the first directional-cut implementation tranche.
- `ddd_fixed_k_certified_bounds.md`: general exact-cardinality Fixed-$K$ bound
  engine combining anonymous passenger DDD, resource-window cuts, adaptive
  cohort/prefix disaggregation, and independently validated primal schedules.
- `ddd_trajectory_column_generation.md`: DDD-guided whole-horizon cabin
  trajectory master, joint route-and-load pricing, delayed resource-conflict
  rows, and the exact-pricing gate for a second certified fixed-$K$ lower bound.
- `demand_driven_network_operations.md`: recommended finite-horizon
  passenger-guided planner using continuous-time resource reservations,
  bounded conflict repair, exact fixed-movement passenger evaluation, and
  optional rolling-horizon scaling.
- `ean_merge_relaxation_and_backward_repair.md`: topology-derived relaxation
  of stop/skip merge-conflict families, monotone latest-to-earliest timing
  repair, endogenous OIP start-state reconstruction, and passenger recourse.
- `ean_fixed_k_delayed_merge_headways.md`: exact fixed-fleet hybrid EAN with
  an eager physical core, delayed merge-only headway disjunctions, complete
  separation, and staged fixed-start-to-OIP evaluation.
- `rotation_passenger_flow_hybrid.md`: passenger-guided anonymous cabin flow
  over freely changing one-rotation templates, delayed occurrence conflicts,
  minimal-waiting repair, and exact EAN R&C refinement.
- `zero_wait_passenger_master_timing_cuts.md`: simplified zero-wait
  passenger-service master, complete waiting-enabled timing subproblem,
  logic-based infeasibility-core cuts, repaired passenger evaluation, and
  independent bounds.
- `ean_cp_sat_feasibility_gate.md`: optional complete CP-SAT movement-
  feasibility gate for fixed \(K\), followed by a fixed-movement passenger
  seed and exact Gurobi merge row-and-column optimization.
- `ean_terminal_recovery_feasibility.md`: future sink-recovery continuation
  proof, one-ring feasibility model, and optional logic-based decomposition.
- `ean_oip_capacity_bound.md`: exact scaling and later automatic use of the
  implemented OIP packing and capacity-certificate layer.
- `ean_fleet_activation_and_depots.md`: optional cabin dispatch, fleet-size
  experiments, physical depots, and future full-day terminal semantics.
- `ean_intermediate_turnbacks.md`: intermediate crossovers, deterministic
  short-turn patterns, dynamic switch-graph operation, and infrastructure
  siting.
- `ean_network_builder_migration.md`: remaining consumer migration from the
  parallel canonical network builder and eventual removal of the ring stack.
- `discrete_time_backlog.md`: low-priority discrete prototype work.
- `software_visualization_and_delivery.md`: replay, tooling, UI, and delivery work.
- `frontend_independent_replay_safety.md`: independent continuous frontend
  certification of geometric spacing, A/B/C resource headways, waiting
  occupancy, and OIP boundary safety from raw exported plans and policies.

Git history preserves superseded implementation plans.
