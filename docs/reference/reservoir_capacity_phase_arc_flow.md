# Reservoir capacity: exact phase witnesses and global All-Stop bounds

Implementation: `optimization/ddd/reservoir_capacity/`. Experimental; old
Fixed-K, anonymous reservoir, CP-SAT and journey-bound defaults remain intact.

## What the pilot proves

For identical physical inputs, demand, horizon, fleet maximum and waiting,
`U_SS_validated < LB_AS_global` proves that one feasible Skip-Stop schedule
serves more passengers than every All-Stop schedule. It does not require the
Skip-Stop optimum. A restricted graph bound is never substituted for a global
bound. More partially served demand is different from a larger completely
served prefix; complete-prefix capacity requires nested demand and U=0.

The modern single-use reservoir domain is authoritative: dispatch throughout
its declared window, optional cabins, return at its declared times, empty
return, and the last return node's state-time occupancy. The older Arc-Flow
warmup-only dispatch restriction is not imported. Maximum fleet is not an
equality and 38 is only a reference construction, not a proven reservoir cap.

## Exact phase encoding

Each STOP has entry, platform arrival, exit-ready, holding, and exit/suffix
edges. SKIP is an independent full movement edge. Edges retain integer ticks;
zero-duration phase edges have different phase nodes, so there is no directed
zero-time cycle. Returning without a movement is explicitly excluded.

Resource uses are factored according to their waiting coefficients:

* `(0,0)`: the unchanged resource interval belongs to the arrival/prefix edge.
* `(1,1)`: the interval belongs to the departure/suffix edge, shifted from
  actual platform exit by its exact original offset.
* `(0,1)`: entry must equal exit-ready and clear must be at or after it. Its
  interval is partitioned into consecutive holding edges and one exit tail.

The pieces are half-open and tile the original protected interval. Protection
is applied once, not once per holding edge. End events precede start events
in the resource sweep. A resource entered at the operational horizon remains
present and its protected end is not clipped.

Positive waiting requires an actual single-occupancy `(0,1)` exit resource.
Unsupported coefficient patterns or phase geometry are rejected before graph
construction. They are not silently replaced by a weaker resource rule.

### Maximum total waiting

On one such physical waiting resource, occupied intervals cannot overlap.
Thus the order of exit-ready events and actual exits is FIFO, even though
the physical cabin order elsewhere (including the bypass) remains free.
For ordered events s_i, d_i, the following constraints are equivalent:

```
d_i - s_i <= W                  for each visit
E(s + W) >= A(s)                for each possible exit-ready time s
```

Flow conservation supplies the matching and prevents departures before
readiness. Single occupancy supplies FIFO. Prefix count variables are linked
by short equalities; the matrix does not repeat every earlier event in every
deadline row. These variables may be continuous because their values are
integer sums of the binary movement variables.

Holding edges connect only equal residues modulo the allowed waiting step.
Positive holding cannot begin before the existing waiting-release phase.
These constraints bound a whole visit, not each small edge independently.

### Passenger conservation

Integer group flows board on the origin exit edge only after release, and
alight on the destination arrival edge before its waiting. The direct
support excludes destination SKIP and continuation beyond the first
destination. Capacity is imposed on every occupied phase edge, so alighting
and subsequent boarding do not form a false combined load.

At each exact phase node at most one cabin is present. Consequently group
flows cannot switch cabins at a merged node. Selected flows are decomposed
into complete cabin paths; onboard obligations are tracked back to their
boarding visit and exported through canonical ride IDs. The original
independent validator checks physics, integer demand and journey statistics.

## Declared restriction: seed_events_v1

Seed event times are mandatory. Additional dispatch anchors are the domain
endpoints, seed dispatches and their integer midpoints, and 30-second anchors
that satisfy the dispatch step. All-Stop/All-Skip duration chains create
initial event times. Releases and seed protection ends provide additional
exit anchors. Two deterministic duration-closure rounds add possible events;
then disconnected edges are removed. Resource conflicts are left to Gurobi.

The 30 seconds are a search-calendar choice, not a physical time unit. No
travel, wait or resource timestamp is rounded. The graph and its fingerprint
are exported so that the restriction can be inspected and reproduced.
No optimality or infeasibility claim extends beyond that graph. There is no
own LNS, greedy scheduling controller, or adaptive DDD in this implementation.

## Global All-Stop relaxation and arithmetic

The existing solver-free visit/time-region preparation covers all original
All-Stop trajectories. Each cabin maps to dispatch, movement and return mass;
each canonical ride maps to conserved boarding, onboard and alighting mass.
The objective is `D - sum(alighted)`. Travel-time products and moments are
absent. Time cells are an optimistic relaxation, not candidate departure
times. Resource rows use minimum necessary overlap with protected windows.
The fine partition retains the coarse resource windows.

Capacity rows use integer tick coefficients. The numerical dual vector y is
interpreted as an exact dyadic rational and its signs are projected according
to row senses. With finite variable bounds, for r = c - A^T y:

```
LB = objective_constant + b^T y + sum_j min(r_j * lower_j, r_j * upper_j)
```

This is a valid Lagrangian bound even with reduced-cost residuals. Evaluation
uses Python integers with a common power-of-two denominator. The ceiling of
this exact bound is valid for integer unserved demand. Noninteger LP data,
nonfinite values, unavailable duals or a validation deadline yield no new
certificate and retain the trivial bound zero. A primal LP objective is never
promoted to a global lower bound.

This proof certifies arithmetic for the built relaxation; the separate
projection argument and enumeration tests establish that it relaxes the
physical problem. An optimal LP is not declared an optimal physical schedule.

## Running and outputs

```
.venv/bin/python benchmarks/run_reservoir_capacity_arc_flow.py \
  --method phase_arc_flow --reference CHECKPOINT.json \
  --time-limit 300 --threads 12 --output-dir NEW_DIRECTORY
```

Methods are `phase_arc_flow`, `all_stop_bound`, and `cp_sat`; only All-Stop
supports `all_stop_bound`. `--build-only` validates construction without
search. Checkpoint loading is strict; changing the domain must leave every
imported ride and movement valid. `--require-full-service` tests U=0; an
incomplete reference is not reported as a witness of that requirement.

`reference.json` is separate from native events. `best.json` always contains
an independently valid physical plan, including the fallback after timeout.
`result.json` states objective and bound scope; `events.jsonl` records native
solutions and progress; `network.json` freezes phase arcs. The supervisor
records process-tree RSS/CPU and enforces elapsed/civil deadlines and memory.

The campaign freezes sources, versions, inputs, R0 and complementary R2.
Its correctness suite runs before the 60-minute campaign clock. Search jobs
are sequential and checkpoints use the same reference within each comparison.
No unavailable measurement is inferred from a solver status.

## Literature and limits

* [Boland et al. (2017), partial time-expanded service network design](https://doi.org/10.1287/opre.2017.1624).
* [Marshall et al. (2021), interval-based DDD](https://doi.org/10.1287/trsc.2020.0994).
* [Van Dyk and Könemann, storage constraints in DDD](https://arxiv.org/abs/2303.01419).

These motivate the decomposition into primal witnesses and relaxations.
They do not prove this ropeway phase model or promise faster optimization.
The pilot does not implement a complete convergent DDD refinement algorithm.

## Experimental compact passenger and conflict encodings

The optional `ReservoirPhaseFormulationConfig` preserves the original physical
phase graph and defaults to legacy. `passenger_structure.py` prepares immutable
supports and algebra without solver variables. `passenger_model.py` builds a
shared native block; `passenger_certificate.py` projects checked historical
rides and lifts native boardings onto the selected vertex-disjoint cabin paths.
`resource_structure.py` prepares coefficient-aware reduction witnesses and
bounded optional cross-resource conflict triangles.

### P1: OD flow projection

Groups on the same directed cycle with the same origin and first destination
have the same possible continuations after a boarding event that satisfies the
release of the group. The current demand class contains only ID, OD, release
and quantity. Extended group record types are rejected for aggregation until
their extra semantics have an explicit compatibility proof.

Group-specific integer boardings are retained. Non-boarding flows are summed
by OD and exact physical arc. Every capacity row sees each aggregated variable
once. A valid old solution projects by summation. Conversely, at integral
movement every occupied phase node belongs to at most one selected cabin;
conservation transports all boarded persons on that cabin to the first target.
The first-destination support prevents a new circuit or an intermediate
transfer. The resulting group ledger maps to the original canonical rides.

The integer equivalence argument does not assert identical LP polyhedra:
class aggregation can remove individual upper-bound effects. LP measurements
are kept separate from integer correctness.

### P2: on-ground demand chains

For each OD, released demand enters an on-ground inventory chain. A boarding
at tick t removes persons only after releases at t have been added. All
inventories are nonnegative. Summing the inventory equations yields exactly
the cumulative inequality `boarded_through(t) <= released_through(t)`.

Necessity follows by counting a valid original assignment. Sufficiency for
integer boarding quantities follows by processing boardings in time order
and taking unused released members of that OD. Every step has enough stock by
the cumulative inequality. The onboard model then carries these persons on
their concrete cabin to the required destination. Stock at the end is unserved;
boarded persons cannot return to the ground chain or disappear.

This proof assumes interchangeable OD groups after release, a common service
horizon and unit seat weights. It is only implemented for the capacity
objective. A native P2 certificate may choose a different valid group split
than another certificate with the same aggregate flows. Exact historical
projection uses the old group split as a witness. Journey statistics are
computed on the actual exported split, not copied from another solution.

### Integrality and contraction

With `passenger_integrality=boarding`, each individual boarding remains
integer. On a selected cabin path, no passenger flow can split across physical
successors: every other movement arc has zero capacity. Conservation and
first-target discharge propagate integer quantities. Ground inventory is an
integer supply minus integer boardings. These properties would fail if later
changes removed unique cabin occupancy or allowed transfers, so those physical
constraints remain unmodified.

`passenger_network=contracted` substitutes only non-boundary variables linked
by two-term opposite-sign passenger conservation equalities. It preserves all
capacity occurrences on the original movement arcs, combines upper bounds by
taking their minimum, and records the substitution map. Boarding, alighting
and ground-inventory boundaries are not contracted. This is exact algebraic
projection, unlike merging different physical times.

### Resource rows and optional conflict cuts

`resource_encoding=maximal` removes duplicate rows and coefficient-dominated
neighboring sweep rows, resolving each removal to a retained stronger row.
The name denotes the maximal sweep representation; this is conservative and
does not claim to discover every possible global row redundancy. Duplicate
resource uses preserve coefficients greater than one.

For `conflict_cuts=local_cliques`, every retained triangle has three recorded
pairwise conflict witnesses. Binary variables cannot select more than one
member. A cutoff on optional pair and triangle generation never removes a
baseline resource constraint. The work limit is applied separately to pair
construction and triangle examination; reported work is their sum. The default
caps are 100,000 operations per stage and 5,000 optional triangle cuts.

### Reproduction and tests

Runner flags: `--passenger-encoding legacy|od_flow|od_queue`,
`--passenger-integrality all|boarding`, `--passenger-network legacy|contracted`,
`--resource-encoding legacy|maximal`, `--conflict-cuts none|local_cliques`.
Non-default flags are rejected for other methods. Graph and model fingerprints
are separate. `passenger_structure.json` records classes/supports and changed
substitutions; `resource_structure.json` records reduction and conflict proofs.

The [implementation and test plan](../plans/reservoir_arc_flow_compact_architecture_20260911.md)
separates lightweight solver-free tests from native enumeration/LP checks and
historical fixed-movement replays. No performance benefit follows merely from
these equivalence arguments; native experiments are still required.

Timing fields: `total_build_seconds` includes solver-free resource and passenger
preparation; `model_seconds` excludes these two components. Hint construction is
separate. `search_seconds` includes callback/final validation; the separately
reported validation time is a subset and must not be added again. The measured
process total remains the authoritative end-to-end wall time. A recovered
checkpoint result is labelled explicitly and is not a native final solver
return. Interrupted comparisons are excluded from recommendations.
