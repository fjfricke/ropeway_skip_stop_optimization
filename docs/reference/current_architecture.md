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

`EanOptimizer` is the single public continuous-EAN solver API. It accepts one
of two typed problem objects:

- `EanMovementFeasibilityProblem`;
- `EanPassengerServiceProblem`.

Both cases use `EanMovementModelBuilder` as the sole implementation of movement
times, stop/skip decisions, waiting, finite-horizon activation, route chaining,
headway activation, and headway ordering. `EanPassengerModelBuilder` composes
the resulting `EanMovementModel` and adds ride slots, selected passenger times,
capacity, demand balance, and the objective. The movement-feasibility case
instead assigns the shared movement model a zero objective. This composition
prevents the feasibility and passenger cases from drifting into different
timing, Big-M, or headway formulations.

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

Checkpoint files store incumbent solutions and are loaded as MIP starts. They
do not persist or resume the previous branch-and-bound tree.

The bottleneck diagnostic uses the same optimizer and model builders for three
cases: integrated passenger service, zero-objective movement feasibility, and
passenger service with an extracted movement plan fixed through
`EanMovementModel`. Callback observability additionally records presolve,
root-relaxation boundaries when exposed, first-incumbent time, and the peak
current Gurobi memory observed during each case. No solver log parsing is used.
Movement-only bounds are not compared with passenger-objective bounds.

## Benchmark and Delivery

Benchmark scripts write machine-specific JSON, SVG plots, and checkpoints under
the ignored `benchmarks/output/` directory. Frontend artifacts are not produced
by benchmarks unless explicitly requested.

The release deployment workflow packages generated frontend data as a GitHub
release asset, splits oversized JSON into chunks, rebuilds the frontend in
GitHub Actions, deploys through Vercel, and protects requests with Basic Auth.
