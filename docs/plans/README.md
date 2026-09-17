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

- [`ean_cp_sat_optimized_initial_placement_20260917.md`](ean_cp_sat_optimized_initial_placement_20260917.md):
  geplantes Ereignis-CP-SAT mit modellbestimmten Anfangspositionen und kompakten
  OD-Passagieren; begrenzter F2-/F3-Pilot, getrennte Nachlaufprüfung und klare
  Verfahrenszuordnung für Journey- und Kapazitätsstudie.

- [`thesis_capacity_final_campaign_20260917.md`](thesis_capacity_final_campaign_20260917.md):
  abschließende Kapazitätsreihe mit ausdrücklich neuen F2-Läufen, kleinem
  Musterkatalog, begrenztem F3-Gate und CP-SAT-Nachoptimierung; keine vorzeitige
  Rückkehr in irgendeinem Verfahren, höchstens 6 h 40 min einschließlich Reserve.

- [`cp_sat_od_inventory_passengers_20260916.md`](cp_sat_od_inventory_passengers_20260916.md):
  implementierte exakte OD-Bestandsformulierung mit Cumulative-Verfügbarkeit statt
  Ankunftsgruppe×Fahrt-Zuordnung; Gleichheitsgates, Zertifikatsrekonstruktion und
  Größenvergleich sind abgeschlossen, der Suchzeitvergleich bleibt offen.

- [`reservoir_line_evolution_no_wait.md`](reservoir_line_evolution_no_wait.md):
  implemented solver-free no-wait line decoding with GA, TPE and random
  controls; the frozen one-hour R0/R2 comparison remains to be executed and
  documented in the linked findings report.

- [`thesis_example_calibration_20260913.md`](thesis_example_calibration_20260913.md):
  quellenbasierte neue Geometrieprofile, verteilte Nachfragefreigaben,
  geprüfte Vorlauf-/Rückkehrverträge, Flottenreferenz und Frontend-Auswahl;
  alte Beispiele bleiben unverändert, Umsetzung mit Korrektheitsgates.
- [`reservoir_line_interval_scaling_20260913.md`](reservoir_line_interval_scaling_20260913.md):
  kontrollierte Fünf-Stationen-Matrix abgeschlossen; offen bleiben die
  quellenkalibrierten Sechs-Stationen-Profile und deren neue Zeitverträge. Siehe
  [Ergebnisbericht](../findings/reservoir_line_length_scaling_results_20260913.md).
- [`../reference/all_stop_no_wait_capacity_baseline.md`](../reference/all_stop_no_wait_capacity_baseline.md):
  verbindlicher Vergleichsvertrag für alle Kapazitätsexperimente; jede
  Nachfrageinstanz benötigt eine phasenoptimierte, vollständig gefüllte
  All-Stop-No-Wait-Referenz mit exakter Passagierzuweisung. Das gemeinsame
  Phasenvariablen-Modell ist noch umzusetzen; Sweeps bleiben kleine Kontrolltests.
- [`reservoir_symbolic_and_pattern_dp_20260912.md`](reservoir_symbolic_and_pattern_dp_20260912.md):
  planned RPID/CABS pilot with symbolic temporal networks and a shared
  whole-trip pattern-group variant; optional reservoir fleet, integral
  passengers, staged correctness gates and a proposed bounded comparison.
- [`reservation_insertion_implementation.md`](reservation_insertion_implementation.md):
  completed bounded profiling, calendar optimization and optional assignment
  refinement; records the decision against further ALNS expansion; see the
  [reference](../reference/ddd_reservation_insertion.md) and
  [K39 finding](../findings/ddd_reservation_insertion_gate.md).
- [`reservation_insertion_kernel.md`](reservation_insertion_kernel.md):
  paper-grounded K39 service insertion, legal exit-wait windows, conflict-driven
  suffix repair, passenger accounting, and a bounded diagnostic pilot under the
  accepted finite horizon; broader design beyond the implemented bounded pilot.
- [`heuristic_and_non_mip_roadmap.md`](heuristic_and_non_mip_roadmap.md):
  gated reservation/Greedy/Regret/ALNS prototype, and a separate research path
  for event-based search, decision diagrams, and continuous CBS; includes
  horizon validation, fair benchmarks, sources, and presentation priorities.
- `artificial_case_capacity_experiments.md`: versioned artificial line and
  double-ring cases, nested demand generation, certified exact-$K$ and
  available-fleet capacity frontiers, valid flow ceilings, and adaptive
  $K$--$N$ experiments.
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
- `ddd_arc_flow_passenger_benders.md`: research-backed classical, logic-based,
  and Branch-and-Benders passenger decomposition of the complete fixed-K DDD
  movement arc-flow, with shared OO components and diagnostic gates.
- `ddd_partial_passenger_branch_benders.md`: gated continuation after the
  standard-cut failure, retaining a compact Passenger core and testing
  Pareto/core-point and coupling-aware multi-cuts before any persistent
  Branch-and-Benders callback is built. Its root gate was rejected; see
  [`../findings/ddd_partial_passenger_benders_root_gate.md`](../findings/ddd_partial_passenger_benders_root_gate.md).
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
- `ddd_dive_branch_price_cut.md`: gated extension of certified trajectory
  Root-CG into Dive-and-Cut-and-Price for validated Skip-Stop incumbents and,
  only when the measured root integrality gap warrants it, exact
  Branch-Price-and-Cut with pricing-compatible branching and conflict cuts.
- [`../reference/ddd_merge_time_corridor_primal.md`](../reference/ddd_merge_time_corridor_primal.md):
  implemented primal-only physical merge/time fix-and-optimize neighborhoods
  on top of certified trajectory Root-CG.
- `ddd_reservoir_fleet_planning.md`: an ideal warm-up entry reservoir,
  optional one-way cabin dispatch, continuous compact proof pricing,
  fixed-available-fleet bound curves, and exact finite bounded Waiting.
- `ddd_fleet_sweep_live_dashboard.md`: typed fixed-K trajectory campaign
  runner, checkpoint-safe neighboring-fleet warm starts, certified cross-K
  analysis, and a live Optimization Lab inside the existing frontend.
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

The implemented V0--V3 reservoir-line compaction and its 12-run comparison are
recorded in
[`../findings/reservoir_line_compaction_results_20260913.md`](../findings/reservoir_line_compaction_results_20260913.md).
The original gated design remains in
[`reservoir_line_compaction_tests_20260913.md`](reservoir_line_compaction_tests_20260913.md)
as the experiment protocol rather than future work.

The controlled length and doubled-operation-horizon experiments are recorded
in
[`../findings/reservoir_line_length_scaling_results_20260913.md`](../findings/reservoir_line_length_scaling_results_20260913.md)
and
[`../findings/reservoir_line_operation_horizon_results_20260913.md`](../findings/reservoir_line_operation_horizon_results_20260913.md).
The consolidated category-by-category freeze register for the final thesis
campaign is
[`../thesis/experiment_definition_register_20260913.md`](../thesis/experiment_definition_register_20260913.md).

Implemented certified Fixed-$K$ trajectory Root-CG behavior and the campaign
command are maintained in
[`../reference/ddd_fixed_k_root_cg.md`](../reference/ddd_fixed_k_root_cg.md),
not duplicated as future work here.

Implemented pricing-compatible trajectory branch domains, bounded primal
dives, and their first K=20 gate are maintained in
[`../reference/ddd_trajectory_branching_and_diving.md`](../reference/ddd_trajectory_branching_and_diving.md).

The implemented merge-aware Root-CG gate, its conditional tree design, and its
negative K=20/K=39 decision are recorded in
[`ddd_merge_aware_branch_price_cut.md`](ddd_merge_aware_branch_price_cut.md) and
[`../findings/ddd_merge_aware_root_gate.md`](../findings/ddd_merge_aware_root_gate.md).
# Active pattern-only pilot

- [Kurzer OIP-Kapazitätsvergleich und Musterstarts: aktueller Gesprächsentwurf](oip_short_horizon_pattern_starts_20260917.md)

- [Evolutionäre Musterwahl mit gemeinsamer No-Wait-Dispatchoptimierung](reservoir_pattern_only_evolution.md)
