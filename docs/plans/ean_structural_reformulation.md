# EAN Structural Reformulation Plan

Status: **future work**

## Goal

Reduce the integrated EAN passenger MILP before adding more solver tuning or
decomposition. Prefer exact projections and removal of redundant variables and
constraints over alternative Big-M constants.

This plan precedes the candidate-bound, MIP-start, and general headway search
work in `ean_formulation_and_search.md`.

## Correctness Baseline

All phases must preserve the intended integer optimum for both passenger
objectives and both currently supported waiting modes:

```text
waiting_time
journey_time

no_waiting
end_of_platform_wait
```

Changes that preserve only the objective value but remove dominated optimal
solutions must be identified explicitly. Changes that alter horizon or
post-horizon semantics are correctness decisions, not benchmark toggles.

## Phase 0: Resolve Horizon and Waiting Semantics

Before benchmarking structural reformulations, align the implementation with
one documented interpretation of three separate boundaries:

```text
T: passenger service cutoff
H: operational safety/certification horizon
B: minimum post-H boundary context needed to close modeled transitions
```

The current implementation derives a global time upper bound from the longest
no-wait visit chains and adds ten seconds. All switch, exit, and wait variables
use that bound. For the cabin defining the maximum chain, cumulative waiting
therefore has only ten seconds of slack unless faster skip choices create
additional time. This can unintentionally couple waiting feasibility to
skipping.

The current builder also creates safety visits after `model_end_seconds`.
Optimizer headway constraints include those visits, while movement validation
ignores headway pairs once either leader-clear time is after the model end.

### Immediate Finite-Horizon Contract

Use the existing configuration fields as:

```text
T = horizon_seconds
H = horizon_seconds + tail_seconds
```

The interval `[0, T]` is passenger service. The interval `(T, H]` is a
passenger-free operational or recovery tail. Stop, skip, wait, and physical
ordering decisions remain free in that tail; do not impose an all-stop,
no-wait, or other fixed recovery policy.

This contract certifies safety only through `H`. It prevents the passenger
cutoff at `T` from also acting as an abrupt physical cutoff, but it does not
claim that the resulting state can continue safely forever.

Classify generated visits by their conservative time windows:

- visits that may use a checkpoint by `H` remain operational;
- no passenger may board or alight after `T`;
- a visit proven to start after `H` is boundary context only;
- boundary context retains only the times needed to close the preceding
  operational transition;
- it receives no independent passenger, stop, skip, wait, or headway decision.

A headway pair may be omitted only when conservative timing proves that both
checkpoint entries are after `H`. A leader-clear time after `H` is not by
itself a reason to omit or skip the pair: a follower can enter before `H` while
the leader still occupies the resource. Optimizer generation and movement
validation must use the same rule.

Replace the global no-wait-chain-plus-ten-seconds bound. The selected
finite-horizon formulation must provide explicit, explainable bounds for:

- station waiting;
- operational switch and exit times;
- boundary closure times;
- headway implications.

An explicit physical maximum wait per waiting station permits valid
visit-specific cumulative time bounds, but it does not by itself decide whether
a visit delayed across `H` is operational. For exact finite-horizon semantics,
activate visit and checkpoint constraints according to whether their modeled
times lie within `H`, and represent resource occupancy that crosses the
boundary without creating a fresh post-`H` service decision.

A simpler first implementation may conservatively keep every visit that could
start by `H` under its earliest timing and require a freely optimized
continuation for that finite suffix. This is not a pure finite-horizon model:
it can constrain some events whose realized times are after `H`. If selected,
document it as a conservative extension requirement and benchmark its effect
separately. Do not silently approximate unbounded waiting with a small global
constant.

### Full-Day Terminal Designs

The finite-horizon contract is not the final full-day boundary model. Keep the
following exact terminal designs available for later implementation.

#### Return to Depot

After passenger service, optimize an unrestricted recovery phase until:

```text
all passengers have alighted
all cabins are in the depot
```

This gives an independent next-day start. It requires explicit depot entry,
exit, capacity, inventory, and conflict semantics.

#### Identity-Free Cyclic Day

Require the physical terminal state after day length `D` to equal the initial
state without requiring the same cabin identifiers at the same positions. For
identical cabins, permit a type-preserving bijection `pi`:

```text
state(c, D) = state(pi(c), 0)
```

On a no-overtaking ring, use a cyclic order shift instead of general assignment
binaries whenever the topology proves that this is sufficient. Match position,
direction, motion phase, cabin type or capacity, and every controller state
needed to repeat the schedule. Add wrap-around headway constraints between the
last events of one day and the first events of the next.

Cabin identifiers may differ across the boundary. The number of active cabins
of each interchangeable type must still match for a one-day cycle.

#### Hybrid Line and Depot Cycle

Allow some cabins to remain on the line and others to be exchanged through the
depot. Require:

```text
line state at D = line state at 0, modulo interchangeable cabin identities
depot inventory by cabin type at D = depot inventory by cabin type at 0
```

This is the most general exact one-day design for continuous operation. It
allows mixed stop, skip, and wait patterns and does not reduce the feasible
fleet to the capacity of a fixed all-stop/no-wait policy.

#### Recovery Before a Terminal Condition

Separate passenger service from the day boundary:

```text
[0, T]: passenger operation
(T, D]: passenger-free optimized recovery
```

Use the recovery phase before either `return_to_depot` or `cyclic_state`.
Recovery decisions remain free so that the terminal condition does not
unnecessarily distort the passenger-service period.

#### Multi-Day Supercycle

If active fleet sizes, depot inventories, maintenance states, or service
patterns genuinely differ between days, require repetition only after `k`
days:

```text
state(k * D) = state(0)
```

A different cabin identifier is compatible with a one-day cycle. A different
physical count at the boundary is not; it requires a multi-day cycle, a
non-periodic planning horizon, or rolling-horizon operation.

#### Rolling Horizon

Optimize one day plus an overlap into the next day, execute only the committed
prefix, then solve again from the realized boundary state. This is suitable for
operational replanning but is not a proof of indefinite extendability.

Do not use a fixed all-stop/no-wait terminal policy as a general
extendability certificate. Skip and wait choices can support more cabins on
the line than that fixed policy, so such a certificate can remove physically
valid solutions.

### Phase 0 Checklist

- [ ] Document `T`, `H`, and boundary-context semantics in `EanConfig`.
- [ ] Choose and expose physical station-wait semantics: an explicit maximum
      wait or a horizon-clamped terminal-occupancy representation.
- [ ] Replace `_time_upper_bound` in both EAN optimizers with derived
      visit-specific bounds.
- [ ] Choose exact time-based visit activation or explicitly adopt and label
      the conservative free-continuation suffix.
- [ ] Classify operational and boundary-context visits consistently in the
      builder.
- [ ] Keep passenger decisions within `T` and unrestricted passenger-free
      recovery decisions through `H`.
- [ ] Align optimizer and validator headway inclusion at the horizon.
- [ ] Add a case where a leader clears after `H` but a follower enters before
      `H`.
- [ ] Add a case that waits for more than ten seconds without requiring a skip.
- [ ] Recompute post-horizon visit and headway-pair counts.
- [ ] Record that finite-horizon solutions are certified only through `H`.

Deferred full-day work:

- [ ] Design explicit depot resources and inventory flow.
- [ ] Add `return_to_depot` as an exact terminal mode.
- [ ] Add identity-free `cyclic_state` with wrap-around headways.
- [ ] Extend cyclic matching to the hybrid line/depot state.
- [ ] Add a multi-day supercycle only when daily fleet counts must differ.

Acceptance evidence for the immediate contract:

- a small instance can wait for more than ten seconds without requiring a skip;
- optimizer and validator agree on horizon-crossing headways;
- waiting and no-waiting variants have documented finite time bounds;
- passenger-free recovery does not force all-stop or no-wait operation;
- exact small-instance objectives remain unchanged under the selected
  finite-horizon semantics.

The minimum boundary context should still follow these implementation rules:

- retain the boundary switch time when it is needed to define the preceding
  visit's exit time;
- do not attach a fresh route decision to context that is proven to begin
  after `H`;
- define finite local bounds without an arbitrary cumulative-wait allowance.

## Phase 1: Affine Stop/Skip Timing

Replace the four Big-M timing implications per visit with the exact affine
relation

```text
exit_time
  = switch_time
  + skip_seconds
  + (service_seconds - skip_seconds) * stop
  + wait_time
```

together with the existing waiting-domain rule:

```text
no_waiting:
  wait_time = 0

end_of_platform_wait:
  0 <= wait_time <= wait_upper_bound * stop
```

This is linear because both route durations are constants. For `stop = 0`,
waiting is zero and the skip duration is selected. For `stop = 1`, the service
duration plus waiting is selected.

Implement the same formulation in the passenger optimizer and the
skip/stop-feasibility optimizer. Avoid maintaining two independent timing
derivations; extract only the small shared expression or helper needed by both
models.

Expected structural reduction:

| Example | Current timing implication rows | Affine rows | Removed rows |
|---|---:|---:|---:|
| `three_station_v0` | 1,724 | 431 | 1,293 |
| `five_station_v0` | 3,956 | 989 | 2,967 |

The important expected benefit is the stronger relaxation, not only the row
count. If adopted, the stop/skip portion of `tight_big_m_bounds` becomes
obsolete. Keep the old formulation only as a temporary benchmark toggle and
remove it after equivalence and performance are established.

## Phase 2: Remove Redundant Unary-Slot Rows

Each candidate's unary passenger slots satisfy:

```text
slot[k] <= slot[k - 1]
```

Therefore `slot[0]` is the strongest activation variable for every
candidate-level condition. Add the following only for `slot[0]`:

- boarding visit must stop;
- alighting visit must stop;
- boarding must respect release time;
- boarding must be inside the passenger horizon;
- alighting must be inside the passenger horizon.

The later-slot versions are implied even in the LP relaxation because every
later slot is at most `slot[0]`.

Apply two additional exact simplifications:

- omit the release implication when the release time is zero;
- remove the alight-earliest strengthening row because it is implied by the
  board-release and minimum-trip-duration rows.

For release time zero, the board-release strengthening row is itself
redundant, leaving only:

```text
slot_alight_time - slot_board_time
  >= minimum_trip_time * slot
```

Keep the boarding-horizon implication during the first benchmark even though
alighting before the horizon makes it integer-redundant. Under the current
Big-M relaxation it may still be a useful valid inequality. Test its removal
separately after Phase 1.

Expected row reduction without removing the boarding-horizon inequality:

| Example | Removed passenger rows |
|---|---:|
| `three_station_v0` | approximately 49,816 |
| `five_station_v0` | approximately 267,072 |

These reductions should primarily improve model construction, memory use, and
presolve. Gurobi may already remove part of the redundancy during presolve, so
do not assume an equal solve-time improvement.

## Phase 3: Project Board-Slot Times Out of Journey-Time Models

The journey-time objective uses selected alighting times. Selected boarding
times are auxiliary variables used only to strengthen the relaxation.

For the journey-time model, project `slot_board_time` out instead of merely
deleting it. Derive the complete linear projection of:

```text
slot_board_time = slot * board_time
slot_alight_time - slot_board_time >= minimum_trip_time * slot
```

including the board-time lower and upper bounds needed by the projection. With
a global upper bound `U`, the projected family includes constraints of the
form:

```text
board_time >= release_time * slot

slot_alight_time
  >= (release_time + minimum_trip_time) * slot

slot_alight_time
  >= board_time
     - U * (1 - slot)
     + minimum_trip_time * slot
```

The final implementation must be derived algebraically rather than copied from
this sketch. Include every projection inequality required to preserve the
existing LP relaxation. Candidate-specific bounds from the general formulation
roadmap can later replace `U`.

Potential effect on `three_station_v0`:

- remove 7,664 continuous board-slot variables;
- remove roughly another 14,000 to 15,000 rows after adding the projected
  inequalities.

The waiting-time model keeps selected boarding-time variables because they
appear directly in its objective.

## Phase 4: Transition-Only Cabin Timing

After the affine formulation is validated, investigate eliminating both
`exit_switch_time` and `wait_time`.

For consecutive visit entry times, define the affine minimum transition:

```text
minimum_transition
  = rope_seconds
  + skip_seconds
  + (service_seconds - skip_seconds) * stop
```

Then:

```text
minimum_transition
  <= next_switch_time - switch_time
  <= minimum_transition + wait_upper_bound * stop
```

For no-waiting visits, this collapses to one equality. Waiting is recovered as
the transition slack. Exit-switch and platform-departure times can be expressed
linearly from the current and next switch times.

The final safety visit of each cabin should preferably act as the boundary
switch time for the previous operational visit. It should not receive its own
route decision if Phase 0 proves that it is outside the modeled movement
horizon.

This phase is more invasive because extraction, MIP starts, headway expressions,
and checkpoint files currently reference explicit exit and wait variables.
Benchmark it only after Phases 0 to 3 are stable.

## Phase 5: Headway Structure

### Horizon Pruning

Use conservative earliest occurrence times to omit headway candidates and
pairs that are guaranteed to lie after the selected movement horizon. On the
current examples, the initial analysis found:

| Example | Pairs touching guaranteed post-horizon events |
|---|---:|
| `three_station_v0` | 5,040 |
| `five_station_v0` | 12,803 |

These numbers are planning estimates and must be recomputed after Phase 0
changes visit and horizon semantics.

### Shared Physical Precedence

The same pair of physical cabin visits currently receives separate order
binaries at platform entry, platform exit, and exit switch. Investigate sharing
one precedence binary across those checkpoints when the physical route proves
that both serving cabins cannot overtake.

This remains valid even when a skipping cabin can overtake a serving cabin:
platform constraints are inactive unless both visits serve. The proof must
still cover the actual route topology and end-of-platform waiting semantics.

Current upper-bound estimates for removable order binaries are:

| Example | Potential duplicate order binaries |
|---|---:|
| `three_station_v0` | 34,670 |
| `five_station_v0` | 106,044 |

This work refines, but does not replace, the broader conservative headway
classification work in `ean_formulation_and_search.md`.

## Lower-Priority Experiments

### Eliminate Unserved Variables

Substitute:

```text
unserved[group] = demand[group] - sum(selected slots)
```

into the objective and retain only:

```text
sum(selected slots) <= demand[group]
```

This is exact but removes only one integer variable per demand group. Gurobi
presolve may already perform the same substitution.

### Passenger Count Encoding

Compare the current unary threshold encoding with an exact binary expansion of
the passenger count per ride candidate. Binary expansion can reduce variables
from `Q` to approximately `ceil(log2(Q + 1))`, but weighted capacity and demand
rows are likely to give a weaker relaxation. Treat it as an isolated research
benchmark, not a default optimization.

### Slot-Time Ordering Cuts

For unary slots using a common candidate time, investigate:

```text
slot_time[k] <= slot_time[k - 1]
```

and the analogous alighting inequality. These are valid at integer solutions
and may strengthen fractional slot assignments, but they add rows and should be
tested only after redundant rows have been removed.

### Compact Headway Materialization

Separate solver performance from Python and artifact overhead:

- avoid repeated long pair identifiers in internal structures;
- consider generating pair rows from compact indexed data;
- avoid serializing identical full EAN artifacts for every benchmark run when
  the artifact is unchanged.

This targets build time, memory, and checkpoint size rather than the
branch-and-bound tree.

## Explicit Non-Priority

Do not prioritize capacity-row subset elimination. The current analysis found
only three dominated rows for `three_station_v0` and twelve for
`five_station_v0`, so the implementation complexity is not justified.

## Implementation and Benchmark Order

1. Resolve horizon and waiting semantics.
2. Add and validate affine stop/skip timing.
3. Remove redundant unary-slot rows.
4. Project board-slot variables out of journey-time models.
5. Evaluate transition-only timing.
6. Add guaranteed post-horizon headway pruning.
7. Prove and benchmark shared physical precedence.
8. Consider the lower-priority experiments independently.

Do not combine unvalidated phases in the first benchmark. Each phase needs a
separate optimization toggle until objective equivalence and performance are
established.

## Verification Protocol

For each phase:

- add unit tests for the algebraic reduction or implication;
- compare feasible solutions and objectives on exact tiny instances;
- test waiting-time and journey-time objectives;
- test no-waiting and end-of-platform waiting;
- validate extracted movement and passenger plans;
- record model construction time, presolve time, variables, rows, and nonzeros;
- record root bound, first incumbent, best incumbent, best bound, gap, nodes,
  and runtime;
- run repeated five-minute `three_station_v0` benchmarks against the unchanged
  default;
- run `five_station_v0` model construction and bounded benchmarks after the
  Three-Station checks pass.

Promote an exact reformulation only when objective equivalence is established.
Promote it into the default when it also improves either proof progress,
incumbent quality, or resource use without a material regression in the other
metrics.
