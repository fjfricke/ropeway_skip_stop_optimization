# EAN Stop/Skip Big-M Bounds Plan

Status: **implemented**

## Goal

Implement Phase 2 of `tight_big_m_bounds`: replace the global Big-M in EAN
stop/skip timing implications with conservative visit-specific bounds.

Current constraints in:

```text
src/ropeway_skip_stop_optimization/optimization/ean/optimizers/passenger_service.py
```

are:

```text
service_exit_ub: exit_time - switch_time - service_time - wait_time <= M * (1 - stop)
service_exit_lb: exit_time - switch_time - service_time - wait_time >= -M * (1 - stop)
skip_exit_ub:    exit_time - switch_time - skip_time <= M * stop
skip_exit_lb:    exit_time - switch_time - skip_time >= -M * stop
```

With `stop = 1`, service timing is active:

```text
exit_time = switch_time + service_time + wait_time
```

With `stop = 0`, skip timing is active:

```text
exit_time = switch_time + skip_time
wait_time = 0
```

The current global Big-M is safe but weak:

```text
global_big_m = time_upper_bound + max_headway + 1
```

The goal is to keep the exact integer feasible set but reduce relaxation slack
in the timing logic.

## Key Safety Argument

Do not derive these M values only from independent variable domains. That would
miss the fact that one timing equation is active exactly when the other timing
equation is inactive.

Instead, derive each M from the opposite active branch:

```text
service constraints inactive -> stop = 0 -> skip timing active and wait_time = 0
skip constraints inactive    -> stop = 1 -> service timing active
```

This is valid for preserving the integer feasible set. It may intentionally cut
some fractional LP solutions, which is the point of the strengthening.

## Bound Formulas

For each visit:

```text
service_time = entry_to_platform_entry
             + min_platform_entry_to_platform_exit
             + platform_exit_to_exit_switch

skip_time = skip_entry_to_exit_switch
```

Define:

```text
wait_upper_bound =
  0                if station waiting mode is no_waiting
  time_upper_bound if station waiting mode is end_of_platform_wait
```

Then use:

```text
service_exit_ub_m = max(0, skip_time - service_time)
service_exit_lb_m = max(0, service_time - skip_time)
skip_exit_ub_m    = max(0, min(
                      service_time + wait_upper_bound - skip_time,
                      time_upper_bound - skip_time,
                    ))
skip_exit_lb_m    = max(0, skip_time - service_time)
```

Rationale:

```text
service_exit_ub inactive at stop = 0:
  exit - switch - service - wait
  = skip - service

service_exit_lb inactive at stop = 0:
  switch + service + wait - exit
  = service - skip

skip_exit_ub inactive at stop = 1:
  exit - switch - skip
  = service + wait - skip
  <= time_upper_bound - skip

skip_exit_lb inactive at stop = 1:
  switch + skip - exit
  = skip - service - wait
  <= skip - service
```

The second `skip_exit_ub_m` upper bound uses existing variable domains:

```text
exit_time <= time_upper_bound
switch_time >= 0
```

So:

```text
exit_time - switch_time - skip_time <= time_upper_bound - skip_time
```

For `NO_WAITING`, the first term usually dominates and gives:

```text
max(0, service_time - skip_time)
```

For `END_OF_PLATFORM_WAIT`, this avoids the overly loose
`service_time + time_upper_bound - skip_time` bound while remaining fully
conservative.

## Toggle Behavior

Use the existing opt-in toggle:

```text
tight_big_m_bounds
```

Do not add a second CLI flag. When the toggle is off, preserve the current
global Big-M behavior exactly. When the toggle is on, apply both:

```text
Phase 1: passenger slot release-time Big-M
Phase 2: stop/skip timing Big-M
```

Keep `tight_big_m_bounds` outside `--ean-optimizations all` until benchmarked.

## Implementation Shape

Implementation status:

```text
implemented behind opt-in toggle tight_big_m_bounds
not included in --ean-optimizations all yet
```

Add a small dataclass near the timing helpers:

```python
@dataclass(frozen=True)
class StopSkipBigMBounds:
    service_exit_ub: float
    service_exit_lb: float
    skip_exit_ub: float
    skip_exit_lb: float
```

Add a helper:

```python
def _stop_skip_big_m_bounds(
    timing: SkipStopTiming,
    station_config: StationEanConfig,
    time_upper_bound: float,
    global_big_m: float,
    enable_tight_big_m_bounds: bool,
) -> StopSkipBigMBounds:
    ...
```

Rules:

```text
if tight bounds disabled:
  return all fields = global_big_m

if waiting mode is no_waiting:
  wait_upper_bound = 0

if waiting mode is end_of_platform_wait:
  wait_upper_bound = time_upper_bound

otherwise:
  keep existing NotImplementedError behavior
```

Use the helper inside `_add_timing_constraints` and replace the four global
`big_m` occurrences with the corresponding bound fields.

## Things To Watch

### Forced Stops

Some timings have `skip_allowed = False`, and the model adds:

```text
stop = 1
```

The skip constraints are still present but inactive. The proposed
`skip_exit_*` bounds must therefore remain valid when service timing is active.
The formulas above handle that.

### Waiting Stations

For `END_OF_PLATFORM_WAIT`, `skip_exit_ub_m` may still be comparatively large
because wait can be large. The current safe cap is `time_upper_bound -
skip_time`. Do not invent a tighter wait upper bound unless it is proven
separately.

### Fractional Stops

These bounds are derived from binary branch validity. They can make the LP
relaxation stricter for fractional `stop` values. That is acceptable as long as
all integer feasible solutions remain feasible.

### Numerical Degeneracy

Some M values can become zero when service and skip timings imply one side of
an inactive inequality is already always satisfied. This is valid, but tests
should cover it explicitly.

## Tests

Add unit tests for `_stop_skip_big_m_bounds`:

```text
disabled toggle returns global M for all fields
no_waiting uses wait_upper_bound = 0
end_of_platform_wait uses wait_upper_bound = time_upper_bound
zero-valued bounds are allowed when max(...) is zero
unsupported waiting mode keeps existing error behavior in _add_timing_constraints
```

Add solver regression tests on the small EAN passenger example:

```text
tight_big_m_bounds off/on both solve optimal
objective values match
served/unserved counts match
movement plan validates
passenger plan validates
```

Keep long Gurobi benchmarks out of pytest.

## Benchmark

Run the same 5-minute comparison as Phase 1:

```bash
uv run python benchmarks/run_ean_passenger_benchmark.py \
  --example three_station_v0 \
  --artifact-set ean_passenger_journey_time \
  --ean-solver-policy exact_optimality \
  --time-limit 300 \
  --sample-interval 5 \
  --ean-optimizations all \
  --label opt_all_5min
```

```bash
uv run python benchmarks/run_ean_passenger_benchmark.py \
  --example three_station_v0 \
  --artifact-set ean_passenger_journey_time \
  --ean-solver-policy exact_optimality \
  --time-limit 300 \
  --sample-interval 5 \
  --ean-optimizations candidate_horizon_pruning,single_ring_dominated_ride_pruning,slot_time_relaxation_strengthening,tight_big_m_bounds \
  --label tight_big_m_phase2_5min
```

Compare:

```text
final mip_gap
best_bound
objective
node_count
time to 10%, 8%, 7%, 6.5% gap
```

Do not compare against stale old runs unless their git commit, dirty state, and
optimization config match the current benchmark exactly.

## Acceptance Criteria

Phase 2 is successful if:

```text
all focused tests pass
solver regression objective and feasibility match with toggle on/off
benchmark improves final gap or time-to-gap without materially worsening objective
no material model-build slowdown is observed
```

If benchmark results are mixed, keep `tight_big_m_bounds` opt-in and document
the result before considering Phase 3 headway bounds.

## Non-Goals

Do not:

```text
tighten horizon constraints in this phase
tighten headway disjunctions in this phase
derive candidate-specific latest board/alight times
change stop/skip semantics
change waiting semantics
add long benchmark runs to pytest
include tight_big_m_bounds in all before benchmark validation
```
