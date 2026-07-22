# General EAN Network Builder Migration

## Goal

Replace the ring-specific construction stack with one physical movement-network
index without changing the feasible set, objective, or headway semantics of the
current deterministic line and ring examples. `Scenario` remains the source of
truth. Dynamic turnbacks and rope transfers will extend this index later rather
than introduce a second topology model.

## Implemented parallel stage

The opt-in `network` construction mode now provides:

- `EanMovementNetwork`, movement states, route options, resource usages, and
  deterministic circulation patterns;
- direct extraction by `PhysicalMovementNetworkBuilder` from physical nodes,
  station routes, track segments, and shared `resource_id` values;
- deterministic discovery of closed circulation patterns, canonically rotated
  by stable state ID;
- explicit compatibility resources for current platform-entry, platform-exit,
  and exit-switch checkpoints, without introducing segment headways;
- independent network timing and visit derivation;
- a neutral `EanCompatibilityArtifactAssembler` shared by the legacy and
  network topology front ends; the network builder no longer invokes the ring
  artifact builder;
- `EanResourceConflictIndex`, grouping current candidates by the compatibility
  resource that creates their conflict;
- additive network and pattern provenance in `EanBuildArtifact`;
- `legacy_ring` and `network` selection in export and benchmark CLIs.

The default remains `legacy_ring`. In the parallel stage, the network builder
intentionally runs the established candidate/pair assembly as a compatibility
pipeline and verifies that network timings, starts, visits, and transitions are
identical before returning an artifact. This is temporary migration scaffolding,
not a second mathematical formulation.

## Proven invariants

Tests compare legacy and network construction for current line/ring examples,
fixed starts and optimized initial placement, skip/no-skip, and wait/no-wait.
They require identical timings, starts, visits, transitions, checkpoint IDs,
candidate IDs, pair IDs, pair counts, and headway semantics. A build-only Gurobi
test additionally requires identical variable, constraint, and nonzero counts.

Stage-one extraction rejects multiple service choices, multiple skip choices,
non-reconverging service/skip routes, and multiple or unexpected continuations
with `dynamic routing not yet supported`. Shared physical resource IDs are
preserved in the canonical network but do not yet create new headways.

## Remaining migration sequence

1. Change fixed-start and OIP phase inputs from `switch_cycle` to the selected
   `EanCirculationPattern`.
2. Change capacity preparation and packing bounds to network/pattern queries;
   movement, passenger, validation, replay, and export consumers already use
   the canonical artifact pattern order.
3. Change the remaining physical timing and visit kernels to neutral network
   services.
4. Register all production examples with pattern selections and switch the
   default to `network` after the full regression and performance gate.
5. Reconstruct `switch_cycle` only in a legacy export adapter, then remove it
   from the canonical artifact.
6. Delete `RingEanBuildArtifactBuilder`, `PhysicalRingTopologyBuilder`,
   `PhysicalSkipStopTimingBuilder`, and `RingSwitchVisitBuilder` once no
   production or test caller remains.

Only after this removal does the dynamic-routing stage add indexed visit and
route decisions. Passenger assignment remains outside that first movement-only
extension.

## Commands

```bash
.venv/bin/python -m ropeway_skip_stop_optimization.exports.cli \
  --example three_station_v0 \
  --artifact-set ean_skip_stop_feasibility \
  --ean-artifact-construction network

.venv/bin/python benchmarks/run_ean_build_baselines.py three_station \
  --ean-artifact-construction network --progress
```
