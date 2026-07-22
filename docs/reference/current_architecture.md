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
the established timings, visits, candidates, and pairs. Network artifacts retain
`switch_cycle` only as a migration field; new topology work should target the
network and selected pattern instead. Stage one deliberately rejects dynamic
route destinations with a clear `dynamic routing not yet supported` error.

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
