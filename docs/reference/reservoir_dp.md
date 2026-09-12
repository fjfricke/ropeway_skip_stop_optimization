# Symbolic reservoir DP

Stand: 12.09.2026.

## Purpose

This backend tests two dynamic-programming decompositions for the existing
single-use reservoir problem. Both preserve the original integer-microsecond
movement contract, STOP/SKIP choices, unrestricted legal exit waiting, integer
passenger assignments, optional fleet use, and independent certificate checks.
The objective is the number of passengers delivered by the service horizon.

- `symbolic_visits` chooses every visit independently.
- `pattern_groups` fixes one whole-trip stop mask for a consecutive group of
  lazily activated cabins. It is an explicit search-space restriction.

RPID 0.4.0 supplies serial CABS and parallel CAHDBS2. The Rust dependency and
lockfile are pinned under `native/ropeway_reservoir_dp/`.

## State and transitions

The DP activates cabins lazily. After one cabin returns, the solver can finish
with the current fleet, add another cabin, or, for `pattern_groups`, close the
current group and select another stop mask. This represents every fleet size
from zero through the configured maximum without creating one copy of the
first-cabin search for every possible final fleet size.

One cabin is constructed through return before the next is activated. This is
only a construction order. Resource intervals of a later cabin can be inserted
at every feasible position among existing intervals, so it adds no physical
FIFO condition and preserves overtaking in `symbolic_visits`.

At a visit the state selects STOP/SKIP and the zero/positive-wait branch,
inserts every protected interval into its resource order, and assigns integer
boarding amounts. Boarding can close early, which is exactly equivalent to
assigning zero to all remaining demand groups. Demand groups remain separate;
release buckets are not merged or treated as a FIFO queue.

Boarding immediately adds a safe minimum-arrival constraint for the required
destination STOP. This rejects commitments that could not reach their target
by the service horizon even with minimum travel times. A passenger is credited
only at that target STOP. Return requires an empty cabin and at least one
completed boarding, so an unused slot is represented by ending fleet activation
rather than by a physically empty trip.

## Symbolic time and resources

Every event time is an `i64` tick in a Simple Temporal Network. Conditions are
stored as `t_j - t_i <= c`; inconsistent branches have an exact negative-cycle
certificate. A newly inserted constraint updates the closed distance matrix in
`O(n^2)` with

```text
d'[i,j] = min(d[i,j], d[i,u] + c + d[v,j]).
```

Differential tests compare this update with a full Floyd-Warshall closure.
STOP waiting stays an interval of integer values and is never sampled or
rounded. Resource endpoints use the original affine waiting coefficients and
separation ticks. A complete witness uses a canonical latest integer schedule
and is then checked by `validate_reservoir_cp_plan` against the original domain.

The adapter currently accepts one-tick dispatch and waiting domains. Other
steps need modular time constraints and are rejected before model construction.

## Search modes and bounds

`primal` uses native blind CABS/CAHDBS2. It is intended for incumbents and does
not report a global bound unless the engine proves one. `dual` uses the native
dual-bound variant. Its safe remaining-service bound counts open obligations
and all unassigned demand optimistically; it is valid but weak on the large
instances.

The primal default uses `keep_all_layers=false`. RPID then clears its duplicate
registry between beam depths. It does not remove transitions or declare two
different states equivalent; it may merely re-expand a state reached at another
depth. `--keep-all-layers` remains available for the proof-oriented diagnostic.

A state-potential term guides the beam toward completed visits and passengers
at their destination state. The term telescopes across every complete path and
is zero in the terminal state. Complete solutions therefore remain ordered
exactly by served passengers.

The result records the domain fingerprint, formulation/search profile, pinned
engine name, native source hash, build/search/wall time, peak process-tree RSS,
node counts, native improvements, and independent validation metrics.

## Runner

```bash
uv run python benchmarks/run_reservoir_dp.py \
  --reference-checkpoint benchmarks/output/reservoir_capacity_campaign_20260911_v1/prepare/R2_ss.json \
  --output benchmarks/output/reservoir_dp_example \
  --variant pattern_groups \
  --search-mode primal \
  --time-limit 30 \
  --workers 1 \
  --initial-beam-width 64 \
  --max-beam-width 512 \
  --no-keep-all-layers
```

The checkpoint currently supplies the frozen problem instance and an external
reference metric. It is not passed off as a native CABS warm start.

## Current limits

The closed STN matrix and all still relevant resource intervals remain in each
state. Memory therefore grows quickly with visits, beam width, and cabin count.
The pilot has no proven zone-inclusion dominance, safe timepoint projection, or
passenger-bucket aggregation. A large primal result is a valid incumbent; a
restricted-beam termination is neither an infeasibility nor an optimality
proof.
