# Current Software Architecture

Status: **implemented reference**

## Pipeline

The physical `Scenario` is the source of truth:

```text
Scenario
  -> validation
  -> DiscreteScenario or EanBuildArtifact
  -> optimizer or deterministic baseline
  -> movement/passenger plan
  -> validation and physical/discrete replay
  -> metrics and JSON export
  -> frontend manifest and visualization
```

`DiscreteScenario` remains supported for the prototype MILPs and replay views.
New exact optimization work uses the continuous EAN path directly from the
physical scenario.

## EAN Construction and Optimization

The EAN builder derives route timing, cabin starts, switch visits and
transitions, headway checkpoints, headway candidates, and headway pairs before
Gurobi model construction.

EAN construction uses the `network` path, which first derives a canonical
`EanMovementNetwork` with movement states, route
options, shared physical resources, compatibility headway resources, and one
deterministic `EanCirculationPattern`. It then verifies exact compatibility with
the established timings, visits, candidates, and pairs. The canonical artifact
stores `state_ids` and pattern provenance; the former ring-specific builders and
`switch_cycle` artifact field have been removed. Stage one deliberately rejects
dynamic route destinations with a clear `dynamic routing not yet supported`
error.

Fixed-start construction shares that same network instance and selected pattern.
The deterministic physical-start mapper derives its target states from the
pattern, while the all-stop builders derive timing and capacity without
constructing a second topology.

Examples expose `EanCirculationPatternDefinition` objects and pass them through
`network_ean_builder_for_pattern`. Physical connectivity and route
reconvergence are validated once by `PhysicalMovementNetworkBuilder`; examples
do not maintain separate ring-connectivity validators.

`EanOptimizer` is the single public continuous-EAN solver API. It accepts one
of three typed problem objects:

- `EanMovementFeasibilityProblem`;
- `EanPassengerServiceProblem`;
- `EanFixedMovementPassengerProblem`.

Both cases use `EanMovementModelBuilder` as the sole implementation of movement
times, stop/skip decisions, waiting, finite-horizon activation, route chaining,
headway activation, and headway ordering. `EanPassengerModelBuilder` composes
the resulting `EanMovementModel` and adds ride slots, selected passenger times,
capacity, demand balance, and the objective. The movement-feasibility case
instead assigns the shared movement model a zero objective. This composition
prevents the feasibility and passenger cases from drifting into different
timing, Big-M, or headway formulations.

The fixed-movement passenger problem validates an extracted movement plan and
builds no movement or headway variables. It filters the shared structural ride
candidates against the fixed stops, release times, event times, and horizon,
then assigns an integer passenger count to each remaining direct ride. Demand
balance and cabin-interval capacities are sufficient because boarding and
alighting times are constants. The same compact model can use continuous ride
counts as an explicitly labelled LP relaxation; fractional assignments are
reported separately and are never extracted as passenger plans.

Solver policy, progress recording, checkpoints, result metadata, validation,
and movement-plan extraction are coordinated by `EanOptimizer`. Passenger
exports adapt the unified internal result back to the established frontend JSON
metadata contract.

Implemented passenger objectives:

- waiting time;
- journey time;
- unserved demand penalty in both models.

Implemented default optimizations:

- candidate horizon pruning;
- exact dominated full-ring ride pruning;
- slot-time relaxation strengthening.

Tight passenger and stop/skip Big-M bounds are implemented behind the opt-in
`tight_big_m_bounds` selection.

The opt-in `fixed_start_headway_precedence` reduction reuses conservative
per-visit bounds for fixed-start artifacts. At each checkpoint it classifies a
pair as fixed forward, fixed reverse, or still disjunctive. A fixed pair keeps
one activation-aware directed headway row and removes its order binary and the
opposite row. Classification is local to the two checkpoint occurrences and
therefore does not impose a global cabin order or prohibit later overtaking.
OIP artifacts reject the explicit selection until selectable-boundary-state
bounds support the same proof.

Stop/skip timing is a mutually exclusive formulation category:

- `stop_skip_timing_big_m` uses the historical four conditional timing rows;
- `stop_skip_timing_affine` uses one exact affine equality per active visit.

For an exact-time horizon, the affine equality is attached to the visit
activation binary as an indicator. Affine timing is the default; Big-M remains
selectable for controlled historical comparisons.

Unary passenger-slot activation is another mutually exclusive formulation
category:

- `slot_activation_per_slot` repeats candidate-level stop, release, and
  passenger-cutoff implications for every interchangeable slot;
- `slot_activation_first_slot` adds those implications only for the first
  unary slot, which dominates every later slot, and removes algebraically
  implied zero-release and optional selected-time strengthening rows.

Both cases represent the same integer model and LP relaxation. The per-slot
case remains selectable as the historical comparator; first-slot activation is
the default.

Selected boarding time is a third mutually exclusive formulation category:

- `board_time_explicit` creates one selected boarding-time variable per slot;
- `board_time_projected_journey_time` removes those variables in the
  journey-time model through the exact Fourier--Motzkin projection of their
  linearization, release, and minimum-trip constraints.

The projected case preserves the integer model and LP relaxation, but is
invalid for waiting time because selected boarding time appears in that
objective. The default is objective-aware: Journey-Time uses projection, while
Waiting-Time uses the explicit selected boarding-time variables. Both explicit
CLI selections remain available for controlled comparisons, subject to the
Waiting-Time validity restriction.

## EAN Finite-Horizon Formulations

`EanConfig.horizon_seconds` is the passenger service cutoff \(T\).
`EanConfig.model_end_seconds`, equal to the horizon plus the configured tail,
is the operational certification horizon \(H\). Passengers may board and
alight only through \(T\); movement and resource safety are modeled according
to the selected horizon formulation through \(H\).

The single EAN selection list combines independent optimizations with one value
from each mutually exclusive formulation category. The implemented horizon
cases are:

- `horizon_legacy`: all generated safety visits receive route and headway
  decisions.
- `horizon_conservative_free_suffix`: all visits whose propagated earliest
  switch entry is at or before \(H\) remain fully constrained. Their realized
  times may form a conservative post-\(H\) suffix.
- `horizon_exact_time_activation`: binary visit activation forms a prefix
  based on optimized switch-entry times. A visit entering by \(H\) keeps its
  route clearance and boundary switch time; later visits have no route
  decision. Headway occurrences are activated by follower-entry time, so a
  leader may clear a resource after \(H\) while still constraining a follower
  that enters by \(H\).

The implemented time-bound cases are:

- `time_bounds_legacy_plus_10`: one historical global bound equal to the
  longest generated no-wait chain plus ten seconds.
- `time_bounds_derived_visit_bounds`: per-visit earliest and latest bounds
  propagated along each cabin sequence. A waiting station uses
  `max_wait_seconds` when configured; otherwise one operational horizon is
  used as a finite terminal waiting cap.

The horizon cases are semantic alternatives, not same-model performance
toggles. The legacy time bound is retained for reproducible comparison because
its ten-second residual slack can constrain cumulative waiting on the longest
cabin chain.

Optimized initial placement fixes exact-time activation together with
`time_bounds_initial_placement_safe`. It supports the same nonnegative
certification tail as fixed starts: the ring-list builder sizes the future
suffix to \(H\), while passenger rides remain bounded by \(T\). The selected
initial phase creates an inactive indexing prefix; it does not shorten the
post-service certification interval.

The detailed formulation and its design rationale are recorded in
`ean_initial_placement_model.md` and
`ean_optimized_initial_placement_design.md`.

## DDD Optimization and Certification Paths

DDD is an experimental solver family for certified fixed-start optimization,
not merely a solver-free reference oracle. Its production-facing research path
combines a network-derived anonymous-flow relaxation, adaptive time
discretization, delayed labelled prefixes, exact lifting and resource
validation, CP-SAT primal support oracles, and optional passenger-aware
trajectory optimization. A separate exact root column-generation path derives
certified passenger-objective lower bounds from exact finite-domain trajectory
pricing. These algorithms share domain models and validation contracts but
remain distinct solver strategies.

The complete fixed-$K$ arc-flow runner additionally exposes the gated
`exact_anonymous` formulation. It quotients the complete labeled no-wait DAG
by exact physical state and tick, retains labels only on fixed source slots,
and reconstructs labels by deterministic integer-flow decomposition. Exact
node capacity makes its integer Movement and Passenger solutions equivalent
to the labeled model, but its fractional relaxation permits anonymous
re-pairing. The first $K=20$ gate was materially weaker than the labeled
candidate-flow formulation, so `labeled` remains the production default. See
`ddd_fixed_k_arc_flow.md` for the equations and
`../findings/ddd_exact_anonymous_arc_flow_gate.md` for the measured gate.

`EanArtifactToDddMovementProblemAdapter` projects a sparse, network-backed EAN
artifact into domain types that import neither Gurobi nor EAN model classes. The
currently certified trajectory DDD domain accepts fixed starts, continuous
fixed-$K$ OIP, or a single dispatch-only ideal reservoir on one deterministic
circulation pattern. Fixed starts and reservoir dispatch support exact bounded
end-of-platform Waiting with explicit station maxima and a finite control step;
continuous OIP remains No-Wait. FIFO/continuous Waiting, dynamic movement
effects, removals, redispatch, and inconsistent route or horizon semantics fail
explicitly at the relevant solver boundary.

`DddReferenceSolver` enumerates every exact individual trajectory within the
certified visit bound, prunes same-cabin resource conflicts, and combines one
trajectory per fixed start while checking cross-cabin conflicts incrementally.
Identical fixed starts use a nondecreasing trajectory index to remove cabin-ID
permutations. Resource activation follows exact follower-entry horizon
semantics, including leader clearance after the operational horizon.

A feasible reference solution converts back to the existing `EanMovementPlan`
with exact-time horizon activation. It then uses complete sparse headway
separation and normal movement-plan validation, replay, and export contracts.
The reference oracle does not consume materialized `HeadwayPair` objects. It is
retained as an independent correctness oracle for small instances; its
benchmark entry points are `run_ddd_phase0_census.py` and
`run_ddd_phase0_reference.py`.

The benchmark-only
`three_station_two_cabin_stop_skip_merge_v0` fixture reuses the physical
Three-Station network with fixed middle-station entries at 0 and 19.7 seconds,
no waiting, and an operational horizon of 30 seconds. Its four Stop/Skip
supports contain exactly three feasible cases. Cabin 0 STOP followed by cabin
1 SKIP places their exit-switch events about 0.482 seconds apart, violating the
0.7-second headway by about 0.218 seconds. All three accepted supports pass
complete sparse EAN validation; eager EAN independently agrees that the
instance is feasible.

The first closed Phase-0 refinement loop is implemented by
`DddSupportMaster`, `DddExactSupportLifter`, and
`DddDelayedConflictSolver`. The tiny support master enumerates complete
individual no-wait trajectories but initially omits every cross-cabin
resource conflict. It is solver-independent and represents the exact binary
trajectory-column master semantics intended for a later MILP backend. A
failed lift produces a conflict row over both route-decision prefixes up to
the conflicting visits. Fixed starts, exact route durations, and no waiting
make those prefixes sufficient to reproduce the exact conflicting resource
times, so the row cannot remove a feasible realization of the same prefix.

On the physical two-cabin fixture, a deliberately chosen objective makes the
optimistic first master select Cabin 0 Stop and Cabin 1 Skip. The exact lift
finds the 0.218-second violation and adds precisely
`y[0,0,stop] + y[1,0,skip] <= 1`. The second master solve selects a feasible
support, which passes both independent DDD validation and complete sparse EAN
validation. `run_ddd_phase0_conflict_loop.py` records the two-round trace and
the generated cut. This proves delayed conflict-row plumbing independently of
time discretization.

The solver-independent time-partition reference path is implemented by
`DddTimePartition`, `DddPartialTimeMaster`, `DddStrictTimeCellLifter`,
`DddCellFreeSupportRecovery`, and `DddTimeRefinementSolver`. Its
`event_cell_bound_probe_v0` fixture has one cabin, exact Stop/Skip route
durations, and a coarse intermediate cell that permits incompatible incoming
and outgoing existential witnesses. The initial master has a valid
optimistic lower bound of zero. Strict lifting detects the shared-event
inconsistency and derives a split at seven seconds, while cell-free recovery
retains only the physical route support and immediately validates a schedule
with objective one. Rebuilding the local arcs after the split removes the
spliced path, reduces four partial paths to the two exact physical supports,
and raises the bound to one. The second round therefore closes
`LB = UB = 1`; exhaustive exact enumeration independently confirms objectives
one and two. Recovery never contributes to the lower bound, and failed
recovery never implies infeasibility. This remains a tiny acyclic reference
backend; it remains available as an oracle for the network-derived flow path.

`DddLayeredTimeNetworkBuilder` now derives the reachable visit-layer graph
from a network-backed `DddMovementProblem` and state-dependent partitions.
`DddAnonymousFlowMaster` places one integer flow unit per fixed start on source
arcs, aggregates those units on shared internal movement and sink arcs, and
uses ordinary flow conservation. `DddAnonymousFlowDecomposer` deterministically
recovers one path per source cabin; the recovered paths feed a resource-free
per-path cell lift and cell-free recovery. A successful cell lift means only
that exact event times agree with the selected cells. Horizon coverage and all
shared physical resources are subsequently validated on the combined paths;
only that complete validation can certify an incumbent or upper bound.

The layered builder is state-incremental across refinement rounds. It caches
partition cells and compatible targets for each physical state transition. A
split of state `S` invalidates only fragments entering or leaving `S`; all
other compatibility classifications are reused. Before the next pure
time-refinement master solve, `DddAnonymousFlowWarmStartProjector` replays the
previous route options from the fixed integer-tick start, maps every exact
arrival to its refined child cell, and supplies the resulting complete or
partial anonymous flow as a MIP start. Prefix-cut rounds omit this start because
constructing the delayed labelled formulation dominates there. The decomposer
first reserves all solved cabin-specific prefixes and only then extends their
anonymous tails, preventing one cabin from consuming another cabin's required
prefix arc.

All Phase-0 DDD time arithmetic now uses a canonical integer-microsecond
domain. Movement durations, fixed starts, horizons, resource offsets, and
partition boundaries are quantized once on construction. Cell membership,
arc compatibility, shifted interval intersections, exact route propagation,
split deduplication, IDs, and fingerprints operate on integer ticks. Public
plans and metrics continue to expose seconds. This removes sub-tolerance
floating-point sliver arcs without treating a relaxed master path as a
feasible trajectory.

The physical `three_station_time_refinement_v0` fixture uses the actual
Three-Station route durations and resources. Round one builds three reachable
nodes and six arcs, returns lower bound zero, recovers an objective-one Stop
trajectory, and derives a split at 44.0909 seconds at `R_entry_lr`. Round two
has four nodes and six arcs and proves `LB = UB = 1`. The exact exhaustive
oracle independently obtains Stop and Skip objectives one and two, and the
final two-visit plan passes complete sparse EAN validation. This establishes
the network-derived anonymous-flow gate. Multiple-cabin merge conflicts now
feed exact-prefix rows back into the anonymous master through delayed
partial disaggregation. For every cabin appearing beyond visit zero in an
active cut, the master creates binary prefix flow only through the deepest
referenced visit. These variables obey per-cabin prefix conservation, may
terminate through a selected sink, and satisfy `sum_c prefix[c,a] <= flow[a]`.
Thus route literals in a cut are exact without copying every internal arc for
every cabin. The decomposer reserves and consumes the solved prefix arcs before
assigning residual anonymous flow, so the exact lift checks the same
decomposition that satisfied the active master rows.

The physical `three_station_two_cabin_network_refinement_v0` gate combines both
mechanisms. Two time splits are followed by two exact conflict rows, including
one visit-one prefix. The final model has nine anonymous arcs and only six
prefix variables, closes `LB = UB = 4` in four rounds, and passes complete EAN
validation. This establishes integration correctness, not large-instance
performance.

### Exact trajectory root column generation

`DddTrajectoryExactRootColumnGenerationSolver` is the current certified
passenger-objective root-bound path for fixed starts, continuous fixed-$K$ OIP,
and dispatch-only reservoir starts. Fixed starts use complete time-expanded
pricing for No-Wait or finite bounded Waiting. Reservoir proof pricing keeps
dispatch continuous and models bounded waits as integer choices in the compact
MILP. Continuous OIP remains No-Wait. Its
restricted master contains a finite pool of exact individual cabin
trajectories, passenger rides, incompatibility rows, and optionally separated
resource-window rows. Solving the restricted LP provides dual values for one
exact pricing problem per cabin. The pricing oracle searches the complete
declared trajectory domain and either returns a negative-reduced-cost trajectory
or a certified reduced-cost lower bound.

The sum of the negative certified pricing bounds corrects the restricted-master
LP value into a valid global lower bound. The restricted integer master yields
feasible trajectory selections and therefore upper bounds only after exact
combined-trajectory validation. Root optimality is certified only when resource
row separation is complete and every cabin pricing problem proves that no
negative-reduced-cost column remains. Pricing time limits without such a proof
can still improve the primal pool but produce `UNKNOWN`, never a false lower
bound certificate.

The reservoir domain gives each available cabin either one resource-free
stored column or one continuous dispatch time in `[-W, 0)`. Warm-up visits are
all-stop; after dispatch, cabins remain on the physical network through the
operational tail and cannot be removed or redispatched. Optional dispatch uses
an integer-only cabin-prefix symmetry, while exact-dispatch mode omits stored
columns. A finite absolute time-expanded anchor sweep supplies fast primal
columns only. Its bounds are never mixed into the continuous certificate; the
complete compact continuous pricer alone supplies reservoir reduced-cost lower
bounds. With bounded Waiting the absolute anchor sweep and resource-window rows
are rejected; concrete pair separation remains exact. Checkpoint schema v5
persists the full reservoir boundary, fleet domain, Waiting policy and grid so
resume and frontend reconstruction cannot silently change them.

The root-CG state records its trajectory pool, row pool, incumbent, certified
bounds, iteration history, fingerprints, and elapsed time. Checkpoint resume
therefore continues the same mathematical root process; it does not preserve a
Gurobi branch-and-bound tree. The exhaustive trajectory master remains the
small-instance equivalence oracle. The primary benchmark entry point is
`run_ddd_trajectory_root_column_generation.py`.

OIP fleet capacity is analyzed by a separate certificate layer. A shared
physical ring-topology builder identifies the service, enabled skip, and rope
segments used by timing and capacity construction. The packing builder assigns
each physical segment the half-open capacity
`ceil(length / required_spacing)`, counts shared segments once, and adds one
slot for each end-of-platform waiting resource. `EanPreparedRing` owns this
shared physical preprocessing together with the all-stop and homogeneous
periodic-route lower bounds. The capacity search then performs passenger-free,
exact-cardinality fixed-\(K\) feasibility probes. Eager all-pairs and delayed
violation generation implement the same headway-probe strategy interface.

Analytic and solver evidence remain distinct: `certified_lower_bound` combines
all valid lower-bound certificates, while `solver_incumbent_lower_bound` is set
only when a feasible MILP incumbent was actually extracted. Route-specific
builders emit the shared `EanPrimalSeed` type; a supplied periodic certificate
must validate against the exact artifact before it can seed a probe. This
analysis does not currently change the explicit production
`available_fleet_count`.

## Validation, Replay, and Frontend

EAN output is converted to typed movement and passenger plans, validated
against the build artifact, and projected to physical events. Positive
`STATION_FIFO_BUFFER` waits are intentionally unsupported until position traces
exist. The frontend consumes only paths declared in the generated manifest and
provides scenario, graph, metrics, optimization, and replay views.

## Solver Observability and Checkpoints

Solver policies configure Gurobi without changing the model definition.
Optimizers expose status, objective, bound, gap, runtime, node count, solution
count, variable and row counts, nonzeros, and pre-optimize model-setup time.
Normal EAN passenger exports automatically receive
per-objective progress recorders; benchmark tooling reuses the same callback
metrics and adds result files and plots.

The setup timer covers Gurobi model materialization, objective and MIP-start or
checkpoint assignment through the final `model.update()`. Candidate generation
and EAN preprocessing happen before the timer; presolve and solver search happen
after it.

EAN construction additionally emits structured phase metrics for physical
timing, visit generation, headway candidates, eager pair materialization,
movement variables and base rows, headway order variables and rows, passenger
candidates and rows, MIP-start application, final synchronization, and JSON
serialization. Progress events include checkpoint and pair progress, current
model dimensions, elapsed time, and process peak RSS where supported.

The export CLI's `--ean-build-only` mode writes an
`ean_model_build_profile.json` diagnostic artifact and returns before any main
model optimization. Its `auto` MIP-start policy resolves to `none`; a greedy
all-stop start may be measured explicitly, while `optimized_all_stop` is
rejected because that strategy contains an auxiliary optimization. The
baseline runner covers one-station regression, three-station, five-station OIP
with 38 cabins, and five-station OIP with 76 cabins.

Integrated passenger solves support `none`, `greedy_all_stop`, and
`optimized_all_stop` MIP-start strategies. The production default first fixes
the deterministic all-stop movement plan as input to the compact
fixed-movement passenger optimizer, solves its passenger assignment with a
bounded auxiliary optimization, and transfers the
extracted movement and passenger plans as a partial start into the integrated
model. Candidate generation and passenger semantics are shared; movement and
headway auxiliaries are absent from the auxiliary model and left for Gurobi to
complete in the integrated solve.

Checkpoint files store incumbent solutions and are loaded as MIP starts. They
do not persist or resume the previous branch-and-bound tree.

The bottleneck diagnostic uses the same optimizer for four cases: integrated
passenger service, zero-objective movement feasibility, exact fixed-movement
passenger assignment, and its continuous LP relaxation. The two fixed cases
use the same extracted movement and candidate configuration, allowing the
LP/IP objective gap and ride-count fractionality to be measured directly.
Callback observability additionally records presolve,
root-relaxation boundaries when exposed, first-incumbent time, and the peak
current Gurobi memory observed during each case. No solver log parsing is used.
Movement-only bounds are not compared with passenger-objective bounds.

An optional root-relaxation recorder binds directly to the typed movement and
passenger variable collections after canonical model construction. At optimal
root-node callbacks it obtains `cbGetNodeRel()` values and aggregates integer
fractionality and linear-objective contributions by variable family. Diagnostic
recorders share the existing Gurobi callback with progress recording and are
absent from normal exports unless explicitly supplied. Presolve-only solves can
finish without producing a root sample.

For the integrated bottleneck case, the recorder also clones the completed
model with `Model.relax()` and solves that raw continuous relaxation through
barrier without crossover. The clone is disposed before the normal MIP solve.
Its objective and variable-family metrics are stored separately from
`MIPNODE` samples because presolve and MIP cuts can make the actual root
substantially stronger than the raw LP.

## Benchmark and Delivery

Benchmark scripts write machine-specific JSON, SVG plots, and checkpoints under
the ignored `benchmarks/output/` directory. Frontend artifacts are not produced
by benchmarks unless explicitly requested.

The release deployment workflow packages generated frontend data as a GitHub
release asset, splits oversized JSON into chunks, rebuilds the frontend in
GitHub Actions, deploys through Vercel, and protects requests with Basic Auth.
