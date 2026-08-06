# Development Progress

This document records when relevant project work was completed and why the
corresponding decisions were made.

## 2026-08-06

### Incremental DDD fragments and projected master starts

The layered DDD builder now caches time cells and compatible transition
targets across refinement rounds. A changed partition invalidates only cached
transitions whose source or target is that physical state; unrelated
state-to-state fragments remain reusable. The anonymous master also receives a
projected partial MIP start: the preceding physical route sequence is replayed
from each fixed start and mapped to the refined child cells. Starts are used
during pure time refinement and deliberately disabled after prefix conflict
rows become active, where labelled-model construction rather than primal
discovery dominates. Both optimizations are independently switchable for
controlled experiments.

The anonymous-flow decomposer was corrected to reserve every labelled cabin
prefix before extending any path through residual anonymous flow. This avoids
an early cabin consuming an arc required by a later solved prefix and is
covered by a dedicated merge-tail regression.

On the 19-cabin Five-Station fixed-start Skip/no-wait probe, cached fragments
reduced 100-round network-build time from 90.04 to 23.38 seconds. Projected
starts changed the refinement trajectory: the first complete temporal lift
was reached in round 52 and generated 71 exact resource-conflict cuts, whereas
the preceding run still had no resource cut after round 100. The resulting
delayed prefix formulation then became the new bottleneck, reaching 228,784
prefix variables and 159.90 seconds of master time; total runtime was 189.19
seconds and no validated incumbent was obtained. The experiment therefore
confirms the intended initial refinement behavior while exposing prefix-cut
scaling as the next optimization target.

### Canonical integer time for DDD

The Phase-0 DDD path now quantizes physical time once to integer microsecond
ticks. Time partitions, half-open cell membership, shifted interval
intersections, exact duration accumulation, resource occurrence times, split
deduplication, deterministic IDs, and fingerprints use integer arithmetic;
seconds remain the external plan and metric unit. This replaced the former
12-significant-digit float normalization and removed refinement slivers that
were accepted as partial arcs but too narrow for a tolerance-safe split.

On the 19-cabin Five-Station fixed-start Skip/no-wait probe, the matched
100-round run contained no stalled/invalid numerical lift rounds, compared
with 66 previously. It processed 964 instead of 802 safe boundaries, reduced
runtime from 325.72 to 102.00 seconds, and reduced final arcs from 13,489 to
13,275. The final integer-storage implementation reproduced exactly the 964
splits, 6,249 nodes, and 13,275 arcs of the preceding hybrid tick-arithmetic
run, while reducing network-build time from 261.53 to 90.04 seconds. It still
produced no validated incumbent or resource cut: genuine time-cell refinement
remains the next bottleneck, so integer time is a correctness, stability, and
substantial build-time improvement rather than the complete scaling solution.

## 2026-07-15

### EAN root-relaxation diagnostics

The Phase-0 bottleneck runner gained an optional typed root-relaxation recorder.
It binds to the canonical movement and passenger models and samples Gurobi
`MIPNODE` relaxation values without parsing solver output. Fractional variable
counts, fractional distance, and linear-objective contribution are aggregated
for movement times, waiting, stop/skip, horizon activation, headway order,
passenger slots, selected passenger times, and unserved demand.

The recorder is attached through an optional diagnostic-observer collection in
`EanSolveConfig` and shares the existing solver callback with progress
recording. Normal solves therefore retain the same formulation and behavior
when diagnostics are disabled. The bottleneck JSON stores samples per case,
and plots compare final root fractionality by family and root-bound progress.
A real Three-Station smoke run reached the root, produced typed samples, and
verified JSON and SVG generation.

The Five-Station MIP did not expose an optimal `MIPNODE` relaxation within its
300-second root processing. The diagnostic therefore gained a separately
labelled raw-LP fallback: it clones the completed integrated model with
`Model.relax()`, solves it by barrier without crossover, records the same typed
family metrics, and disposes the clone before the MIP solve. A Three-Station
comparison verified why the two sources remain separate: the raw LP contained
14,317 fractional headway-order variables, while the later post-cut root sample
contained only seven; passenger slots remained heavily fractional in both.

The final Five-Station diagnostic solved the raw LP in 68.67 seconds with an
objective of 312,738 passenger-seconds. It found 50,609 fractional headway
orders, 16,528 fractional passenger slots, and 739 fractional stop decisions.
The subsequent five-minute MIP raised the bound to 1,604,228 seconds but still
did not expose a post-cut relaxation vector. The family values are therefore
recorded as raw-LP structure rather than attributed directly to the remaining
post-cut gap.

### Passenger-optimized all-stop MIP start

The integrated EAN passenger solver now supports three explicit MIP-start
strategies: no start, the historical greedy all-stop assignment, and a
passenger-optimized all-stop start. The optimized strategy fixes the
deterministic all-stop movement plan in the canonical model, solves the
resulting passenger assignment with a bounded auxiliary solve, and transfers
the complete extracted solution into the integrated model. It became the
production default after a matched Five-Station experiment.

With identical Journey-Time formulation, exact solver policy, and 300-second
main-solve limit, the optimized start reduced the incumbent from 3,155,354 to
1,947,463 passenger-seconds and the final gap from 49.16% to 17.62%. The final
lower bound was identical at 1,604,228 passenger-seconds, both runs remained at
the root node, and total Gurobi setup increased from 5.75 to 12.85 seconds.
This confirmed that the change repairs primal quality but does not strengthen
the relaxation or improve dual progress.

### Phase-0 EAN bottleneck diagnostic

The selected production formulation can now be diagnosed through one runner
that executes integrated passenger service, movement-only feasibility, and
fixed-movement passenger optimization under the same per-case solver budget.
At this stage, the fixed case reused the integrated movement plan and fixed it
through the canonical `EanMovementModel`; the independent compact evaluator
documented below superseded this implementation later on 2026-07-15.

The callback recorder now captures presolve timing, observed root-relaxation
boundaries, first-incumbent time, and current-memory peaks without parsing
Gurobi text output. Model setup is split into passenger candidate generation,
movement construction, movement fixing, passenger construction, and MIP-start
application. Diagnostic JSON and five SVG case comparisons are written outside
the frontend export tree. A one-second smoke run verified the complete path,
but its values are not performance findings.

### Unified object-oriented EAN solver architecture

The separate skip/stop-feasibility and passenger-service solver entry points
were replaced by one `EanOptimizer` API with typed movement-feasibility and
passenger-service problem objects. Both now construct movement timing,
stop/skip, waiting, horizon activation, chaining, and headways through one
canonical `EanMovementModelBuilder`. The passenger model composes that object
through `EanPassengerModelBuilder` instead of maintaining a second movement
formulation.

This refactor was necessary because the former feasibility implementation had
retained older Big-M rows and did not consistently apply every current
optimization setting. The unified builder uses the previously verified
passenger movement formulation as the reference, while the external passenger,
movement-plan, replay, benchmark, and frontend JSON contracts remain
unchanged. Solver policy, progress callbacks, checkpoints, validation, and
metadata are now handled once by the optimizer. Exact small models, both
horizon modes, both timing formulations, export smokes, the complete test
suite, and Ruff were used as regression checks.

### Projected selected boarding times

The journey-time passenger model received the opt-in
`board_time_projected_journey_time` formulation. It eliminates one selected
boarding-time variable per passenger slot using an exact Fourier--Motzkin
projection of the selected-time linearization, release, and minimum-trip-time
constraints. The resulting constraints preserve both the integer model and
the LP relaxation in the remaining variables. Waiting time retains explicit
selected boarding times because they occur directly in its objective.

The all-stop MIP-start builder was made independent of selected boarding-time
variables, allowing the same movement and passenger assignment start for the
explicit and projected journey-time models. Exact small instances covered
zero and positive release times, both waiting modes, per-slot and first-slot
activation, and both strengthening settings. The complete test suite, Ruff,
and the frontend build passed.

The combination with first-slot activation was subsequently tightened by
keeping the projected physical boarding-release row only for the first unary
slot. Unary ordering implies the omitted later-slot rows even in the LP
relaxation; the slot-specific selected-alighting and board--alight coupling
rows remain unchanged.

A matched 300-second Three-Station comparison at implementation commit
`5872075` reduced variables by 9.3%, rows by 13.1%, nonzeros by 8.0%, and
pre-optimize Gurobi setup time from 2.005 to 1.847 seconds. The projected run
had a slightly worse incumbent and lower bound, a 6.62% rather than 6.52%
gap, and processed 15.3 times as many nodes. At this stage, the exact model
reduction remained opt-in because the individual time-limited run did not
justify changing the export-oriented default. Unrelated documentation plan
edits were present in the worktree while the benchmark ran; the recorded code
revision was nevertheless commit `5872075`.

### Compact unary-slot activation

The EAN passenger model received an opt-in
`slot_activation_first_slot` formulation alongside the historical
`slot_activation_per_slot` default. Passenger slots for a candidate are unary
ordered, so every later slot is at most the first. Candidate-level stop,
release, and passenger-cutoff conditions therefore need to be attached only
to the first slot; the later rows are implied even in the LP relaxation.

The compact case also removes the zero-release selected-board lower bound and
when slot-time strengthening is enabled, the selected-alight earliest lower
bound. These rows are algebraically implied by nonnegative time domains, the
selected-board release lower bound, and minimum trip duration. Slot-specific
time linearization, passenger costs, capacity, and unary ordering remain
unchanged.

This was kept as a formulation benchmark case rather than a default change.
The optimizer and benchmark JSON now record model nonzeros and pre-optimize
model-setup time, because this reduction is expected to affect construction
and presolve as much as branch-and-bound search. Exact small instances cover
both objectives, no-waiting and end-of-platform waiting, multiple slots, and
zero and positive release times.

One-second construction smokes verified the expected row reductions on the
real examples: 49,816 rows and 106,338 nonzeros on `three_station_v0`, and
267,072 rows and 570,096 nonzeros on `five_station_v0`. The compact setup
measure was lower in these single runs, but the smoke results are only a model
construction check and not a solver-performance conclusion.

The subsequent comparison used three matched five-minute
`three_station_v0` runs per case without checkpoint resume. First-slot
activation reduced rows by 21.4%, nonzeros by 12.4%, and average Gurobi model
setup time from 1.93 to 1.71 seconds. Its final bound was 3,201
passenger-seconds higher and its gap was 0.11 percentage points smaller, while
its incumbent was 174 passenger-seconds worse. The repeated end values were
effectively deterministic. At this stage, the compact formulation remained
opt-in: it is a useful proof-side and resource reduction, but the individual
benchmark did not justify changing the export-oriented default.

### Combined exact journey-time formulation benchmark

The three exact formulation changes were benchmarked together on
`three_station_v0`: affine stop/skip timing, first-slot activation, and
projected journey-time boarding variables. The combined model was compared
against the unchanged `all` baseline for five and fifteen minutes under the
same solver policy, horizon, time bounds, MIP start, and callback sampling.

At five minutes, the combined formulation had the best incumbent, best bound,
gap, served demand, model size, and setup time of the three tested cases. The
fifteen-minute comparison confirmed the result: its gap was 3.09% rather than
6.50%, it served twelve additional passengers, and it used 28.5% fewer rows.
The detailed measurements are recorded in
`docs/findings/ean_passenger_optimization_benchmarks.md`.

The benchmark was subsequently promoted to an objective-aware production
default: passenger solves use affine timing and first-slot activation; the
Journey-Time objective additionally uses projected boarding time, while
Waiting-Time retains explicit boarding time. Big-M, per-slot activation, and
explicit Journey-Time boarding time remain selectable for controlled
comparisons. The evidence remains limited to the Journey-Time Three-Station
case, so `tight_big_m_bounds`, changed horizon semantics, and derived time
bounds remain opt-in experiments.

## 2026-07-14

### Documentation consolidation

The software plans and findings were consolidated in commit `8c4b248`. The
previous collection of implementation-history plans was replaced by a small
future-work roadmap, findings documents, and a current-architecture reference.
The thesis plans were consolidated separately in commit `0a07ad4`.

The purpose was to make future work, implemented architecture, and empirical
findings distinguishable without using plan files as an implementation archive.
Git history remains the archive for removed plans.

### EAN horizon and terminal-state review

The current EAN implementation was found to use three different effective
boundaries:

- the passenger horizon `horizon_seconds`;
- the configured model end `horizon_seconds + tail_seconds`;
- a solver time bound derived from the longest no-wait chain plus ten seconds.

The last bound can leave only ten seconds of cumulative waiting for the
longest cabin chain and can therefore couple waiting feasibility to skipping.
The visit builder, optimizer, validator, and replay also do not yet use one
fully consistent rule for events crossing the model end.

The structural reformulation plan now distinguishes:

- passenger cutoff `T`;
- operational certification horizon `H`;
- minimum post-`H` boundary context;
- future full-day terminal modes such as depot return and identity-free cyclic
  operation.

A fixed all-stop/no-wait terminal policy was rejected as a general
extendability certificate. Mixed skip and wait operation can support a larger
active fleet than that fixed policy.

### Configurable EAN horizon and time-bound formulations

The EAN formulation configuration was extended with two mutually exclusive
categories while preserving one comma-separated CLI selection:

- horizon semantics: legacy generated suffix, conservative free suffix, or
  exact activation from optimized event times;
- time bounds: historical no-wait chain plus ten seconds, or propagated
  visit-specific bounds.

This was implemented as selectable cases because the horizon alternatives
define different finite feasible sets and must be benchmarked as semantic
variants rather than presented as same-model speedups. Independent exact
optimizations remain freely combinable with one value from each formulation
category.

The derived bounds use a configured station maximum wait when available and
otherwise one operational horizon as a finite terminal waiting cap. Exact
activation retains route clearance and resource occupancy for events entering
by \(H\), even if the leader clears after \(H\). Later visits receive no new
route decision. Cabins with an earliest start may have an empty active visit
prefix when their first optimized switch entry is after \(H\).

The optimizer, movement-plan extraction, validator, export configuration,
benchmark metadata, README, architecture reference, and thesis methodology
were updated together. Small passenger instances and both conservative and
exact Three-Station skip/stop solves were used to verify valid extracted
prefixes. The exact extraction also normalizes adjacent boundary times from the
same optimized switch variable to avoid false monotonicity failures at roughly
\(10^{-12}\) seconds.

### Horizon and time-bound benchmark matrix

All six combinations of the three horizon cases and two time-bound cases were
run for five minutes on `three_station_v0` with the journey-time objective.
The purpose was to separate semantic viability from solver performance before
changing any default.

The legacy and conservative free-suffix horizons produced nearly identical
five-minute results with the historical time domain. Derived visit bounds
worsened both of those runs, but were essential for making exact time
activation computationally usable. Exact activation with the historical
all-visits domain remained near its initial MIP start with a 59.80% gap;
combining it with propagated visit bounds produced a normal incumbent and a
7.91% gap.

The legacy horizon and legacy time bounds remain the default. The new cases
remain explicit formulation experiments because the horizon choices have
different finite-horizon semantics and the derived bounds have not shown a
general performance benefit.

### Affine stop/skip timing formulation

The historical four Big-M timing implications per visit were retained as one
formulation case and an exact affine alternative was added:

```text
exit = switch + skip_duration
       + (service_duration - skip_duration) * stop
       + wait
```

The affine relation is one ordinary linear equality for an unconditionally
active visit. Under exact time activation, an indicator enables the equality
only for an active visit. Passenger and skip/stop-feasibility optimizers use
the same helper so their timing algebra cannot drift independently.

Exact small instances preserved waiting-time and journey-time objectives.
The full suite passed with 242 tests; Ruff lint, the frontend build, and the
thesis PDF build also succeeded.

A five-minute Three-Station comparison reduced rows by 1,293 and improved the
MIP gap from 6.52% to 4.83%. The affine incumbent was slightly worse and served
four fewer passengers. At this stage, Big-M remained the default until
repeated runs showed whether the proof improvement was stable without an
unacceptable primal-side regression.

## 2026-07-15: Fixed-movement passenger LP integrality

The direct-ride passenger assignment with fixed movement was analyzed
mathematically before implementing a separate decomposition evaluator.
Aggregating unary slots yields demand-balance rows and consecutive interval
capacity rows. Although each individual ride has interval structure, ride
alternatives across cabins can combine demand conflicts and capacity conflicts
into an odd cycle.

A valid three-station, two-cabin, no-transfer construction with seven ride
candidates produces an odd-cycle matrix with determinant \(2\). Setting all
seven ride variables to one half is a fractional vertex, and the standard
waiting-time objective gives a strict LP/IP gap on the same construction.
Therefore the fixed-movement passenger LP is not integral in general even
without transfers. The decomposition plan was updated to measure practical
LP gaps and exact integer solve time rather than attempting to infer general
integrality from benchmark observations.

## 2026-07-15: Independent fixed-movement passenger optimizer

The fixed-movement diagnostic and optimized all-stop start no longer rebuild
the integrated movement model and fix all of its variables. A third typed
`EanOptimizer` problem now validates the supplied movement plan and builds only
the direct passenger assignment.

The compact model uses one integer passenger-count variable per feasible ride,
demand upper bounds, and cabin-interval capacities. Waiting and journey costs
are constants from the fixed movement, and unserved demand is represented
implicitly in the objective. The same builder can create a labelled continuous
LP relaxation. LP results expose fractional ride counts but cannot be
extracted as integer passenger plans.

The bottleneck diagnostic retains its exact fixed-movement case and adds a
matched LP case, LP/IP gap metadata, and objective/fractionality plots. A valid
three-station odd-cycle regression test reproduces the formal strict LP/IP gap.
