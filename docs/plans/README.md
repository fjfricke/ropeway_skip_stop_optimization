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

- `ean_formulation_and_search.md`: immediate baseline validation, bottleneck
  diagnosis, and conditional exact formulation or MIP-search improvements.
- `ean_structural_reformulation.md`: exact structural reductions of the
  integrated EAN passenger MILP that are evaluated only for a measured
  bottleneck.
- `ean_decomposition.md`: scaling diagnosis, passenger decomposition,
  progressive search, delayed constraints, and alternative solver paths.
- `ean_fleet_activation_and_depots.md`: optional cabin dispatch, fleet-size
  experiments, physical depots, and future full-day terminal semantics.
- `ean_intermediate_turnbacks.md`: intermediate crossovers, deterministic
  short-turn patterns, dynamic switch-graph operation, and infrastructure
  siting.
- `discrete_time_backlog.md`: low-priority discrete prototype work.
- `software_visualization_and_delivery.md`: replay, tooling, UI, and delivery work.

Git history preserves superseded implementation plans.
