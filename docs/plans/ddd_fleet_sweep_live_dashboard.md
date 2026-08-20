# DDD Fleet-Sweep Runner and Live Optimization Dashboard

Status: **implemented for fixed-K campaign orchestration, certified envelope
analysis, round/heartbeat live snapshots, and the Optimization Lab frontend;
fine-grained inner-Gurobi samples and automatic replay export remain follow-up
instrumentation**

## Purpose

Build one reproducible experiment workflow that solves several fixed
`K_available` trajectory problems, preserves certified lower and feasible upper
bounds, transfers only validated neighboring-fleet incumbents, and exposes the
campaign live in the existing React frontend.

The first supported campaign compares All-Stop and Skip-Stop on the
single-interface Five-Station architecture-B ring. No-Wait and finite bounded
Waiting are separate campaign policies. The workflow must remain usable for
later line, double-ring, demand-profile, objective, and fleet-cost studies.

The runner is an orchestration and reporting layer. It does not alter the
trajectory master, pricing problem, Passenger objective, resource semantics,
or certificate definition.

This plan implements the fixed-K campaign and frontend portion of
[`ddd_reservoir_fleet_planning.md`](ddd_reservoir_fleet_planning.md). The
mathematical trajectory formulation remains in
[`ddd_trajectory_column_generation.md`](ddd_trajectory_column_generation.md).

## Existing implementation baseline

Reuse rather than duplicate the following components:

- `benchmarks/run_ddd_trajectory_root_column_generation.py` already constructs
  and solves one fixed-start, OIP, or reservoir root-CG trial.
- `DddTrajectoryExactRootColumnGenerationSolver` already exposes completed-round
  progress and atomic checkpoint callbacks.
- `DddTrajectoryRootCgState` persists the pool, rows, incumbent, Passenger ride
  values, certified bounds, elapsed time, fleet domain, Waiting policy, and
  instance fingerprint.
- `build_ddd_reservoir_neighbor_k_initial_pool()` already validates and
  transfers a neighboring-K incumbent without transferring its numerical
  bounds.
- `DddReservoirFleetPlan` already distinguishes available, dispatched, stored,
  and peak-active cabins.
- `export_ddd_root_cg_checkpoint_to_frontend()` already reconstructs and
  validates fixed-start, OIP, and reservoir incumbents.
- `GurobiMipProgressRecorder` already records incumbent, solver bound, gap,
  nodes, solutions, work, phase times, and memory for integrated EAN solves.
- The frontend already contains `EanProgressView`, SVG progress charts,
  Passenger metrics, physical replay, and the generated-example manifest.
- `benchmarks/run_ddd_fixed_start_k_sweep.py` is only an older anonymous
  fixed-start DDD sweep. It is not the new reservoir trajectory campaign
  runner and will not be extended for this purpose.

The current single-run benchmark script contains too much application logic to
be called safely from another Python runner. The first implementation step is
therefore extraction into a reusable typed service, not subprocess composition
and not a second copy of the script.

## Selected architecture

Use three Python layers and one frontend area:

```text
DddRootCgTrialRunner
  one scenario/policy/objective/K solve
              |
              v
DddFleetSweepRunner
  ordering, resume, neighbor warm starts, persistence
              |
              v
DddFleetSweepAnalyzer
  monotone envelopes, service targets, policy comparisons
              |
              v
Optimization Lab
  overview, live trial, fleet curves, validated replay
```

The CLI remains thin. Mathematical and persistence logic belongs under
`src/ropeway_skip_stop_optimization/benchmarking`, not under `benchmarks/` or
inside React.

### Planned files

```text
src/ropeway_skip_stop_optimization/benchmarking/
  ddd_root_cg.py
  ddd_fleet_sweep.py
  optimization_events.py
  optimization_live_store.py

benchmarks/
  run_ddd_trajectory_root_column_generation.py
  run_ddd_reservoir_fleet_sweep.py

frontend/src/
  pages/ScenarioPage.tsx
  pages/OptimizationPage.tsx
  pages/OptimizationCampaignPage.tsx
  pages/OptimizationTrialPage.tsx
  components/optimization/
  hooks/useOptimizationCampaign.ts
  optimizationTypes.ts
```

The existing single-run CLI is retained for focused debugging but delegates to
`DddRootCgTrialRunner`.

## Campaign and trial contracts

### Trial identity

One trial is identified by the complete tuple

```text
campaign_id
policy_id
example_id
objective
K_available
reservoir boundary and warm-up
dispatch cardinality
Waiting policy and grid
horizon and tail
solver/pricing configuration
```

A stable SHA-256 trial fingerprint covers the full tuple and the existing DDD
instance fingerprint. A checkpoint, result, event stream, or frontend snapshot
with another fingerprint is rejected rather than silently resumed.

### Typed single-run configuration

Introduce a frozen `DddRootCgTrialConfig` containing at least:

```text
campaign_id
policy_id
example_id
available_fleet_count
objective
reservoir_boundary
warmup_seconds
dispatch_cardinality
waiting_step_seconds
max_iterations
total_time_limit_seconds
pricing_time_limit_seconds
pricing_threads
master_dual_mode
proof_pricing_mip_focus
extra_pricing_mip_focus
pricing_formulation
conflict_row_mode
primal-pricing and diversity settings
output paths
```

`total_time_limit_seconds` and `max_iterations` retain their current cumulative
resume meaning. Resuming a ten-minute checkpoint with a ten-minute total budget
does not grant ten additional minutes. An explicit future `extend_budget_by`
operation may produce a new larger cumulative limit, but never changes a
checkpoint implicitly.

### Typed trial result

`DddRootCgTrialResult` wraps the mathematical result and adds reproducibility
and reporting data:

```text
trial fingerprint and exact configuration
git revision, dirty flag, platform, Python and Gurobi version
start/end timestamps and total elapsed time
status and termination detail
raw certified LB, feasible UB, absolute and relative gap
root-LP certificate flag
K_available, K_dispatched, K_peak_active
served and unserved Passenger counts
canonical Passenger objective metrics
time to first validated incumbent
first and final model-size metrics
master, pricing, separation, validation, and export time
conflicts by boundary, regular resource, merge, and tail provenance
warm-up deployment makespan and operational-tail coverage
checkpoint and validated incumbent artifacts
```

`OPTIMAL_ROOT_LP` means exact root-column-generation convergence. It does not
mean that the integer Passenger timetable is globally optimal. The dashboard
must continue to show the remaining LP-to-incumbent gap.

### Campaign configuration

`DddFleetSweepConfig` contains:

```text
campaign_id and human-readable label
one or more policy cases
explicit K values and execution order
objective
per-K cumulative budget
optional service targets
optional cabin-cost sensitivities
resume and frontend-live settings
```

Each policy case names a versioned example and its explicit reservoir boundary.
For the first campaign the policies are:

```text
all_stop_no_wait
skip_stop_no_wait
all_stop_bounded_wait
skip_stop_bounded_wait
```

No-Wait and Waiting remain separate result curves. Results with different
demands, objectives, horizons, tails, boundaries, warm-ups, or Waiting domains
must never enter one bound envelope.

A JSON campaign file is the reproducible input. The CLI accepts
`--config <path>` plus only operational overrides such as output location,
console progress, and an explicit larger cumulative time budget. It writes the
fully resolved configuration back into the campaign output.

## Sweep algorithm

Run policies sequentially and trials within a policy in the configured order.
The default order is ascending K because optional reservoir dispatch embeds a
smaller incumbent by adding canonical stored cabins.

For each trial:

1. Build or reuse the policy's scenario, sparse network artifact, movement
   core, Passenger candidates, and validated boundary configuration.
2. If an exact matching checkpoint exists, resume the same K.
3. Otherwise locate the nearest completed compatible K checkpoint with a
   validated incumbent.
4. Build a fresh target-K trajectory problem and call
   `build_ddd_reservoir_neighbor_k_initial_pool()`.
5. Transfer trajectories only. Re-solve the target restricted master and all
   proof pricing; never transfer a numerical LB or UB.
6. Solve until the cumulative round/time limit or root-LP convergence.
7. Validate every candidate global incumbent against the complete physical
   core before updating the campaign UB.
8. Persist the completed-round checkpoint, trial result, live snapshot, and
   aggregate campaign result atomically.
9. Recompute every legal cross-K and cross-policy certificate.

An interrupted solve loses at most the current incomplete CG round. The prior
completed checkpoint, event log, and campaign manifest remain readable.

Parallel policy/K solves are deliberately out of scope for Version 1. They
would compete for Gurobi resources and remove the deterministic neighbor-K
warm-start chain. Parallel pricing internal to one trial remains controlled by
the solver configuration.

## Bound contract and derived certificates

All Passenger objectives are minimization objectives.

### Raw fixed-K interval

For each trial:

$$
LB_K \le J^\star(K) \le UB_K.
$$

`LB_K` enters the campaign only from the existing certified DDD/root-CG bound
contract. `UB_K` enters only after complete physical and Passenger validation.
Local Gurobi pricing bounds are diagnostics and never become global bounds by
themselves.

### Optional-dispatch monotonic envelope

With identical data and optional dispatch, the new cabin may remain stored:

$$
J^\star(K+1)\le J^\star(K).
$$

Therefore the analyzer may tighten:

$$
\widehat{LB}(K)=\max_{j\ge K} LB_j,
$$

$$
\widehat{UB}(K)=\min_{j\le K} UB_j.
$$

Every tightened bound records its source K. The UB source also identifies the
constructive incumbent. These envelopes are disabled for exact-dispatch
campaigns unless a separate inclusion proof is implemented.

### Service-target certificate

For a declared minimization target `J_target`:

```text
tightened UB <= target  -> certified sufficient
tightened LB > target   -> certified insufficient
otherwise               -> unresolved
```

The runner reports the smallest certified-sufficient K, largest
certified-insufficient K, and the unresolved fleet interval.

### Cabin-cost certificate

For a declared ownership cost `c`, define

$$
F_K=J^\star(K)+cK.
$$

K is certified optimal for that sensitivity when

$$
UB_K+cK < LB_j+cj
\qquad\forall j\ne K.
$$

Otherwise report the set of fleets whose intervals still overlap. Do not add
an arbitrary cabin cost to the core Passenger optimization.

### All-Stop versus Skip-Stop

For matched physical and Passenger data, define the benefit

$$
\Delta_K=J^\star_{AS}(K)-J^\star_{SS}(K).
$$

Its certified interval is

$$
LB_\Delta=LB_{AS}-UB_{SS},
$$

$$
UB_\Delta=UB_{AS}-LB_{SS}.
$$

`LB_delta > 0` proves a Skip-Stop improvement. Policy dominance may also reuse
an All-Stop incumbent as a Skip-Stop UB only after reconstructing and validating
that incumbent in the Skip-enabled target problem. The analyzer does not infer
this from labels alone.

Finite Waiting similarly enlarges the No-Wait solution domain when every other
input is identical. Keep the curves visually separate. Any cross-domain bound
reuse requires an explicit checked dominance record and source provenance; it
is never performed implicitly.

## Live progress event model

Introduce a solver-independent `OptimizationProgressEvent` with a monotone
sequence number. Event kinds include:

```text
campaign_started / campaign_completed
trial_queued / trial_started / trial_completed / trial_failed
stage_started / stage_completed
solver_sample
cg_round_completed
incumbent_validated
checkpoint_written
heartbeat
```

Stages include:

```text
scenario_build
artifact_build
seed_build
master_build
master_lp
master_mip
proof_pricing
primal_pricing
resource_separation
incumbent_validation
frontend_export
```

Each event carries only applicable fields:

```text
campaign, policy, K and trial fingerprint
timestamp and campaign/trial/stage elapsed time
CG round and current/total cabin-pricing index
global certified LB, validated UB and gap
local solver incumbent, bound and gap
pricing status and exactness
nodes, solutions, work and memory
column, pair, resource-window and model-size counts
checkpoint and incumbent provenance
message and structured error detail
```

Global and local values are distinct fields and receive distinct frontend
labels. In particular, a pricing-MILP bound must never appear on the global
Passenger-bound curve.

### Non-blocking callback contract

Gurobi callbacks enqueue small immutable events only. They do not serialize
JSON, touch React files, perform network requests, validate plans, or block on
I/O. A background writer coalesces interval events and persists them.

The queue may replace an older periodic sample for the same active solve when
under pressure. It must never drop stage changes, new global incumbents,
completed rounds, certificates, errors, or checkpoint events.

Sample Gurobi progress at a configurable default interval of one second.
Round-level root-CG progress is emitted unthrottled. A heartbeat keeps the UI
alive during long model construction where no Gurobi callback exists.

## Persistence and local live transport

Version 1 uses files and browser polling rather than a new backend server.

Canonical campaign output:

```text
benchmarks/output/ddd_fleet_sweeps/<campaign>/
  resolved_config.json
  campaign.json
  summary.csv
  events.jsonl
  policies/<policy>/k<K>/
    checkpoint.json
    result.json
    incumbent/
```

Derived live frontend output:

```text
frontend/public/generated/optimization/
  index.json
  <campaign>/snapshot.json
  <campaign>/trials/<policy>__k<K>.json
  <campaign>/incumbent/...
```

The benchmark directory is the source of truth. The frontend live tree is a
small derived mirror and may be rebuilt from campaign output. JSON snapshots
and indices are written through temporary files followed by atomic replacement.
`events.jsonl` is append-only and stays outside `frontend/public`.

React polls the current snapshot every one second with `cache: "no-store"` and
a sequence-number query token. Polling stops after a terminal campaign state
unless the user requests refresh. A stale timestamp produces a visible
"no update" warning rather than falsely reporting failure.

This design works with the current local Vite server and survives a closed
browser. A later HTTP/SSE service can implement the same event contract without
changing the runner or components. Starting, pausing, or terminating solvers
from the browser is not part of Version 1.

An optional future `MlflowProgressSink` may log parameters, scalar histories,
and artifacts for generic run comparison. MLflow is not a core dependency and
does not replace the domain-specific dashboard or certificate store.

## Frontend integration

Add a top-level navigation with separate pages:

```text
/                                  Scenario Viewer
/optimization                     Optimization Lab
/optimization/:campaignId         Campaign
/optimization/:campaignId/:policyId/:k
                                   Trial detail
```

Move the current `App.tsx` scenario-loading body into `ScenarioPage.tsx`.
Use a small conventional router and configure the production host to rewrite
deep links to `index.html`. The scenario artifact manifest and optimization
campaign index remain independent schemas.

### Optimization overview

Show all known campaigns with:

```text
status and freshness
scenario/demand family
policies, objective and K range
completed/active/queued/failed trial counts
best current service-target and policy conclusions
elapsed time
```

### Campaign page

Show a Policy-by-K matrix. Every cell reports:

```text
queued/running/complete/failed/interrupted
raw and tightened LB/UB/gap
root-LP certificate
K_dispatched / K_available
elapsed/budget
last update
```

Also show:

- raw and monotone fleet-bound intervals;
- All-Stop and Skip-Stop curves;
- service-target lines and fleet classification;
- Skip-Stop benefit intervals;
- cabin-cost sensitivity results;
- a chronological campaign event list.

### Active trial page

Show:

```text
policy, K, objective, Waiting domain and boundary
current stage, CG round and cabin-pricing position
elapsed time versus cumulative budget
global certified LB, validated UB and gap
root-LP status and last validation result
```

Charts and diagnostics:

- global LB/UB/gap timeline;
- local active Gurobi incumbent/bound/gap chart, visually separated;
- master/build/pricing/separation time by round;
- columns, conflicts, windows, model variables/rows/nonzeros;
- exact/inexact pricing counts and reduced-cost diagnostics;
- nodes, solutions, work and memory;
- recent semantic events and errors.

Do not display a fake CG completion percentage. Valid progress indicators are:

- completed campaign trials divided by configured trials;
- elapsed trial time divided by its budget;
- completed cabin pricing calls within the current round;
- certified global gap.

### Validated incumbent replay

On a strictly improved global UB:

1. validate movement, resources, Passenger assignment, fleet, boundary, and
   horizon;
2. persist the checkpoint and selected trajectories;
3. asynchronously produce the existing compact frontend replay artifacts;
4. atomically switch the trial snapshot to the new validated replay.

The UI keeps displaying the prior validated replay while a new one is being
prepared. It never animates an unvalidated Gurobi or restricted-master
incumbent.

Refactor the reusable plotting portion of `EanProgressView` into a generic
`BoundProgressChart`; keep EAN and DDD wrappers responsible for their own units
and semantic labels.

## Implementation order

### Tranche 0: Contracts and single-run extraction

- Add typed trial config/result and stable fingerprint.
- Extract artifact/problem construction, solve invocation, checkpoint handling,
  and result serialization from the existing CLI.
- Keep current single-run commands and JSON semantics working through the new
  service.
- Record exact time to first validated global incumbent and missing model-size
  metrics.

Acceptance: existing root-CG unit tests and one stored checkpoint reproduce the
same mathematical result, pool, LB, UB, and validation outcome.

### Tranche 1: Fleet-sweep core

- Add campaign config/result schemas and JSON configuration input.
- Implement deterministic trial ordering, exact resume, compatible neighbor-K
  discovery, and trajectory-only warm starts.
- Write per-trial and aggregate artifacts atomically.
- Implement optional-dispatch envelopes, service targets, cabin-cost intervals,
  and matched-policy benefit intervals with source provenance.

Acceptance: a Tiny two-K campaign can be interrupted and resumed without
changing either independent fixed-K result or any certificate.

### Tranche 2: Event store and round-level live snapshots

- Add progress events, bounded queue, JSONL store, snapshot reducer, live index,
  heartbeat, and stale-run detection.
- Wire campaign, trial, stage, round, checkpoint, validation, and terminal
  events.
- Mirror derived snapshots into the frontend live tree.

Acceptance: every completed checkpoint is represented by an ordered event and
the latest snapshot can be rebuilt byte-stably from the event stream.

### Tranche 3: Optimization Lab frontend

- Split the scenario page from the top-level application and add routing.
- Add navigation, campaign overview, campaign matrix, active-trial header,
  bound curves, diagnostics, polling, stale/error/empty states, and responsive
  layouts.
- Refactor the existing progress chart without changing its EAN behavior.

Acceptance: Vitest with fake timers observes live snapshot updates without a
page reload; `npm run test` and `npm run build` pass.

### Tranche 4: Inner Gurobi telemetry

- Generalize the existing progress recorder for trajectory master LP/MIP,
  proof pricing, and primal pricing.
- Emit one-second samples and phase/memory metrics through the non-blocking
  event sink.
- Label every sample with solve role, cabin, start class, and CG round.

Acceptance: enabling telemetry changes no solver status, objective, bound, or
selected trajectory on deterministic fixtures. Matched runs show negligible
overhead; the target is less than two percent median wall-clock overhead.

### Tranche 5: Live validated replay and experiment gate

- Export a new replay only after a strictly better validated global UB.
- Run the first Five-Station architecture-B campaign for K = 18, 19, 20, 21:
  All-Stop versus Skip-Stop, initially No-Wait.
- Add bounded-Waiting policies only after the No-Wait campaign proves the
  complete workflow.
- Preserve all raw and tightened intervals for thesis tables and figures.

Acceptance: the dashboard remains live through interruption/resume, every
displayed UB has a replayable validation certificate, and every displayed LB
links to its trial and certificate provenance.

## Tests

### Python unit tests

- configuration validation and stable fingerprints;
- incompatible resume and neighbor checkpoints rejected;
- deterministic nearest-neighbor and execution ordering;
- K+1 stored-cabin and K-1 trajectory transfer;
- no numerical bound transfer between K values;
- optional-dispatch monotone LB/UB envelopes and source K;
- exact-dispatch envelope disabled;
- service-target and cabin-cost classifications;
- All-Stop/Skip-Stop benefit intervals;
- Waiting/domain mismatch prevents aggregation;
- ordered event reduction, coalescing, and non-droppable events;
- atomic snapshot/index writes and event-stream reconstruction;
- stale, failed, interrupted, and resumed states.

### Solver integration tests

- Tiny fixed-start single-run equivalence before/after extraction;
- Tiny reservoir K and K+1 independent solve versus neighbor warm start;
- checkpoint interruption and continuation;
- validated UB and certified LB preservation;
- optional all-stored and exact-dispatch cases;
- No-Wait and finite bounded-Wait campaigns remain separate;
- frontend replay validates the exact selected incumbent.

### Frontend tests

- route and top-level navigation;
- campaign index loading and polling cleanup;
- sequence-number updates and out-of-order snapshot rejection;
- campaign matrix state rendering;
- raw versus tightened bounds and provenance;
- global versus local bound labeling;
- service-target and benefit-interval presentation;
- stale, disconnected, empty, interrupted, failed, and complete states;
- responsive trial view and accessible chart summaries;
- current EAN progress and scenario viewer regressions.

## Non-goals of Version 1

- browser control of solver processes;
- distributed workers or concurrent K solves;
- a permanent remote tracking service;
- replacing mathematical checkpoints with frontend state;
- using local pricing bounds as global Passenger bounds;
- comparing mismatched demand, objective, horizon, boundary, warm-up, Waiting,
  or cardinality domains;
- arbitrary multi-interface reservoir dispatch;
- continuous unrestricted Waiting;
- automatic Optuna fleet search before explicit K curves are trustworthy;
- requiring TensorBoard, MLflow, Prometheus, Grafana, or a cloud account.

## First experiment command target

The completed runner should support a command of the form:

```bash
.venv/bin/python benchmarks/run_ddd_reservoir_fleet_sweep.py \
  --config benchmarks/configs/five_station_b_no_wait_fleet_sweep.json \
  --progress \
  --frontend-live
```

The frontend remains independently started with:

```bash
cd frontend
npm run dev
```

Opening `/optimization` then shows the configured campaign before the first
trial starts, updates within approximately one second, retains the last valid
state after interruption, and transitions from live monitoring to archived
result exploration without changing pages or schemas.
