# Initial Placement Tail Model Size

Date: 2026-07-20

Base commit: `67aa73b` (dirty worktree containing optimized initial placement)

## Configuration

The comparison constructs movement models only. It does not measure solver
runtime or establish a general performance ranking.

- scenario: `three_station_optimized_initial_placement_v0`;
- directed switch cycle: four entry switches;
- passenger cutoff: `T = 1200 s`;
- certification tail: `delta_tail = 300 s`;
- operational horizon: `H = 1500 s`;
- fleet limit: four cabins in both cases;
- horizon formulation: exact-time activation;
- fixed starts: derived visit bounds;
- optimized initial placement: boundary-state-safe visit bounds;
- candidate-horizon pruning, directed-ring ride dominance, and tight Big-M
  bounds disabled in both constructions.

The fixed-start artifact uses the four physical cabin states. The initial
placement artifact uses four homogeneous potential cabins and permits a
station or rope state at time zero.

## Observed Construction Sizes

| Fleet mode | Visits per cabin | Headway pairs | Variables | Constraints | Nonzeros |
| --- | ---: | ---: | ---: | ---: | ---: |
| Fixed starts | 34 | 5,814 | 6,850 | 13,628 | 88,314 |
| Optimized initial placement | 39 | 7,500 | 8,864 | 18,443 | 119,218 |

The values were obtained by building `EanMovementModelBuilder` directly with
the configuration above.

## Interpretation

The larger optimized-initial-placement model is expected for this instance.
It must cover every selectable phase through the same horizon, materializes
initial station and rope choices, and retains boundary headway rows. The
additional visits are a common-list coverage requirement, not modeled
pre-service movement.

These values are structural observations for the specified instance only.
They do not show that either fleet mode solves faster or produces a better
passenger solution. Runtime comparisons require matched passenger instances,
solver budgets, and repeated runs.
