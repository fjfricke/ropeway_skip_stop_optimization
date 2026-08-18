# Independent Frontend Replay Safety Certification

Status: **implemented (2026-08-17)**

Implementation note: the pure checker lives in `frontend/src/safety/`, runs in
a Web Worker, and is also available through `npm run safety:check`. Live replay,
frame export, and video export consume the same report. Missing or legacy input
fails closed as `indeterminate`. The backend replay export retains one raw
interpolation event on either side of the checked horizon; these events are
kinematic input, not backend-computed safety evidence.

## Objective

The frontend shall independently decide whether a displayed EAN movement plan
is physically collision- and headway-feasible. It must derive this decision
from the exported physical scenario, the complete physical headway policy, the
movement/fleet plan, and the physical replay. It must not consume a backend
validation result or precomputed backend violation list.

The visible warning layer remains frame-based. The final verdict is not based
on a finite video-frame sample: it checks the complete continuous interval
\([0,H]\) and attaches each detected violation to the frames in which it is
relevant. Otherwise a short violation between two rendered frames could be
missed.

The result has three states:

- `safe`: every required check completed and no violation was found;
- `unsafe`: at least one independently reconstructed violation was found;
- `indeterminate`: required input is missing, inconsistent, or uses unsupported
  semantics.

Unknown cases must fail closed as `indeterminate`; they must never be shown as
safe.

## Authoritative Frontend Inputs

Extend the TypeScript schema to represent and runtime-check:

- `Scenario.headway_design`;
- the complete `DerivedHeadwayPolicy`, including rule kinds, resources,
  spatial spacings, quantities, and provenance;
- the `EffectiveHeadwayPolicy` and dominance certificates for explanation only;
- `headway_rule_id` and the pair scope;
- `EanFleetPlan`, including OIP initial state, previous event time, next event
  time, and `previous_service`;
- a safety-schema version and the physical-policy derivation version.

The safety engine uses the **complete** `DerivedHeadwayPolicy`. It does not trust
resource removal or coalescing for its verdict. The effective policy is shown
only to explain which constraints the solver materialized.

The ordinary movement-plan export must include the matching fleet plan for OIP.
For fixed starts, cabin starts and the movement plan are sufficient. Exported
objects need stable IDs but no backend safety result.

Before checking, a small explicit runtime decoder validates discriminated
unions, finite numbers, unique IDs, references, scenario IDs, horizons, and
policy versions. This should remain a local decoder rather than adding a large
schema dependency.

## Frontend Safety Model

The implemented pure module is independent of React and SVG rendering:

```text
frontend/src/safety/
  types.ts
  decodeSafetyInputs.ts
  headways.ts
  geometry.ts
  certifyReplaySafety.ts
  markers.ts
  replaySafety.worker.ts
  useReplaySafetyReport.ts
```

Its main interface is:

```ts
certifyReplaySafety({ scenario, artifact, movementPlan, fleetPlan, replay })
  -> ReplaySafetyReport
```

The report records completeness, checked horizon, violations, minimum observed
slack, counts by resource and category, and diagnostic reasons for an
indeterminate result. Each violation contains cabin and visit IDs, resource and
rule IDs, route behavior, actual and required separation, time interval, and a
physical anchor for rendering.

### Directed rule evaluation

Port the two rule types as a small exhaustive TypeScript function:

\[
h_r(i,j)=
\begin{cases}
h_r, & \text{constant rule},\\
h_r^B, & \text{leader }i\text{ bypasses},\\
h_r^S, & \text{leader }i\text{ serves}.
\end{cases}
\]

An unknown rule kind makes the report indeterminate. The code must not fall
back to `maximum_seconds`, because that would be conservative but no longer an
exact check of the modeled architecture.

### Exact resource-usage reconstruction

For every visit and every full physical policy resource, construct an active
usage

```ts
{ cabinId, visitIndex, behavior, enterTime, clearTime, resourceKey }
```

when its service/bypass activation applies. The time semantics are:

- platform entry: `enter = clear = platform_entry_time`;
- exit switch: `enter = clear = exit_switch_time`;
- service mechanism: service visits only, at `exit_switch_time`;
- platform exit with `END_OF_PLATFORM_WAIT`:
  `enter = platform_exit_time - wait_seconds` and
  `clear = platform_exit_time`;
- platform exit without waiting: point semantics if the resource is active;
- FIFO waiting: indeterminate until the replay contains a complete FIFO
  position/occupancy trace.

Usages are grouped by the actual physical resource identity. Use
`physical_resource_id` when present and otherwise the policy resource ID. If
several requirements refer to one physical resource, their rule compatibility
must be checked explicitly; inconsistent guarantees make the result
indeterminate rather than silently selecting one value.

For every pair of usages \(i,j\) on one resource, accept exactly when

\[
F(j)-L(i)\ge h_r(i,j)
\quad\lor\quad
F(i)-L(j)\ge h_r(j,i),
\]

where \(F\) is the follower-enter time and \(L\) the leader-clear time. The
check includes different rotations of the same cabin. Candidate and eager-pair
exports are not used, so sparse/delayed artifacts receive the same complete
frontend check.

The implementation deterministically sorts resource usages and stops scanning
followers after the first safe follower. This is exact for the supported rule
types because their required separation depends only on the leader and later
followers have nondecreasing entry times. Dense conflict clusters are still
enumerated completely.

### OIP boundary

For every initial rope state, create a synthetic pre-horizon usage at
`previous_event_time_seconds`. Its behavior comes from `previous_service`.
Check:

- consecutive initial rope states;
- initial rope state against the first regular exit usage;
- retained service-mechanism boundary requirements.

Missing `previous_service` for a behavior-dependent rule, or a missing fleet
plan for OIP, makes the report indeterminate.

### Continuous geometric collision check

Replace sampled marker-distance certification with a swept continuous check.
Build piecewise motion intervals from replay events and physical segments.
Intervals retain exact segment, direction, speed profile, resource ID, and
position as a function of time.

Use the complete policy's spatial spacings:

- rope and bypass movement: `DerivedSpatialRole.ROPE`;
- service path and platform movement: `DerivedSpatialRole.SERVICE`.

For every overlap interval of two cabins on the same one-dimensional path, or
on adjacent path pieces meeting at a common node, minimize their physical
separation over the entire interval. With constant profiles the relative
position is linear. With the current linear-speed profiles it is quadratic, so
the minimum lies at an interval endpoint or at a root of the derivative. Test
all such candidates exactly within a numeric tolerance.

Normalize coordinates for opposite segment directions. A segment whose route
role or speed profile cannot be resolved makes the relevant interval
indeterminate. Screen coordinates are used only to place the warning symbol,
never to calculate physical distance.

This continuous sweep is the final spatial collision check. The existing
`eanReplayCollisionMarkers()` may remain temporarily as a live UI preview, but
it must not produce the green safety verdict.

## Frame Integration

Run `certifyReplaySafety` once whenever its source artifacts change, preferably
in a Web Worker. Index violations by time interval and cabin ID. Each rendered
frame then queries this index and displays:

- geometric spacing violations at their interpolated closest point;
- point-resource violations at the resource node;
- occupancy violations across the affected platform interval;
- actual versus required distance/headway and the A/B/C rule explanation.

The persistent replay-safety panel shows `safe`, `unsafe`, or `indeterminate`,
the checked interval, minimum slacks, and checked-pair counts. The old marker is
retained only as an explicitly labelled live preview while certification is
still running or unavailable; it never produces the verdict or an export.

Video and SVG exports use the same precomputed frontend report and time index;
they must not run a separate simplified collision function.

## Implementation Order

1. Add complete TypeScript policy/fleet types and strict runtime input checks.
2. Implement rule evaluation and complete resource-usage reconstruction.
3. Implement exhaustive resource-pair and OIP-boundary checks.
4. Integrate the report into the replay status panel and frame markers.
5. Implement continuous swept spacing for constant profiles, then linear-speed
   profiles and adjacent path pieces.
6. Move certification to a worker and add the indexed sliding-window
   optimization without changing results.
7. Use the same report in live replay, SVG export, and video export; remove the
   old function as a source of any final verdict.

Steps 1--4 already provide an independent exact A/B/C temporal-headway check.
The UI must remain `indeterminate` for final spatial safety until Step 5 is
complete.

## Tests and Acceptance

Add Vitest for pure TypeScript safety modules and keep rendering tests separate.

Required unit cases:

- constant A rule just below, at, and above its threshold;
- all four B behavior combinations and both temporal directions;
- C main-rope and service-recovery resources;
- no-wait platform point headways;
- positive, unequal `END_OF_PLATFORM_WAIT` occupancy;
- same-cabin conflicts between rotations;
- shared `physical_resource_id` across different states;
- OIP rope/rope, rope/regular, prior-service, and missing-boundary data;
- constant- and linear-speed continuous minima, opposite directions, adjacent
  segments, and a violation strictly between ordinary video frames;
- sparse versus complete pair artifacts producing the same report;
- reduced versus unreduced effective policies producing the same verdict when
  the complete physical policy is identical;
- unsupported rules, FIFO traces, malformed references, and truncated replays
  producing `indeterminate`.

Use generated small fixtures for differential testing against the Python
validator, but only as a test oracle. Also mutate otherwise valid JSON plans to
introduce one violation of every category and require the frontend to find it.

Acceptance gates:

- A/B/C and waiting fixtures agree with the Python validator;
- the verdict is invariant under 1, 10, 30, and 60 fps rendering;
- the Five-Station-B case uses the derived rope spacing (currently about
  \(6.315\,\mathrm m\)), not the legacy \(3.5\,\mathrm m\);
- no backend validation result or violation annotation is loaded by the
  frontend safety engine;
- frontend build and Vitest suite are green;
- large replay certification runs off the UI thread and completes within an
  explicit performance budget;
- `safe` is impossible unless temporal resources, initial boundary, continuous
  geometry, and full-horizon coverage are all complete.

## Acceptance Evidence

The Five-Station full-cabin, skip/no-wait, architecture-B all-stop export was
checked from the exported JSON with the independent TypeScript CLI:

```text
status                         safe
violations                     0
minimum headway slack          +0.1291866 s
minimum spatial slack          +0.0645933 m
full physical resource usages  5,476
ordered resource comparisons   5,456
swept motion intervals         5,090
swept geometric comparisons    15,201
```

The policy used a rope spacing of `6.3146311 m`, rather than the legacy
`cabin_length_m + min_clearance_m = 3.5 m`. The artifact contained 20 complete
physical resources and 15 effective solver resources with five dominance
certificates; the frontend verdict deliberately checked the 20-resource
physical policy.

The frontend build, 14 focused TypeScript tests, 28 export/projection tests,
and the full 710-test Python suite pass. Production dependency audit reports no
known vulnerabilities.

## Correctness Boundary

This certifies the exported deterministic movement replay under the modeled
headway policy. It does not certify the physical assumptions used to derive
that policy, stochastic failures, unmodeled cabin swing dynamics, or a replay
projection that lacks the required physical trace. Those cases must be stated
separately from collision freedom under the model.
