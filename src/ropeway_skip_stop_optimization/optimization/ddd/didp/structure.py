"""Immutable, solver-independent preparation for the exact Fixed-K DIDP pilot."""

from collections import Counter
from dataclasses import dataclass
import json

from ..cp_sat_certificate import validate_ddd_cp_sat_domain, stable_fingerprint
from ..route_topology import deterministic_route_state_ids, unique_stop_route_option
from ..time_ticks import ddd_seconds_to_tick as tick

I32_MAX = 2**31 - 1
EXACT_FLOAT_LIMIT = 2**53 - 1


@dataclass(frozen=True)
class Operation:
    index: int
    cabin: int  # index in sorted fixed starts
    visit: int
    route: object
    candidates: tuple[int, ...]
    maximum_steps: int
    arrival_bounds: tuple[tuple[int, int], ...]  # alighting slot, latest next switch


@dataclass(frozen=True)
class PreparedDidpStructure:
    manifest_json: str
    fingerprint: str
    starts: tuple
    states: tuple[tuple[str, ...], ...]
    groups: tuple
    rides: tuple
    operations: tuple[Operation, ...]
    resources: tuple
    calendar_sizes: tuple[int, ...]
    boundaries: tuple[tuple[tuple[int, int], ...], ...]
    waiting_step: int
    earliest_wait: int
    service_end: int
    operation_end: int
    sentinel: int
    total_demand: int
    capacity: int

    @property
    def manifest(self):
        # Return a copy so callers cannot mutate the immutable prepared domain.
        return json.loads(self.manifest_json)


def prepare_didp_structure(problem):
    manifest = validate_ddd_cp_sat_domain(problem)
    movement = problem.resolved_trajectory_problem.fixed_movement_problem
    policy = problem.resolved_trajectory_problem.waiting_policy
    starts = tuple(sorted(movement.starts, key=lambda s: s.cabin_id))
    groups = tuple(sorted(problem.passenger_build.demand_groups, key=lambda g: g.id))
    rides = tuple(sorted(problem.passenger_build.ride_candidates, key=lambda r: r.id))
    resources = tuple(sorted(movement.resources, key=lambda r: r.id))
    states = tuple(
        deterministic_route_state_ids(
            movement,
            start_state_id=s.state_id,
            max_visit_count=s.max_visit_count,
            error_context="DIDP",
        )
        for s in starts
    )
    step = tick(policy.step_seconds) if policy.step_seconds else 1
    total = sum(g.count for g in groups)
    capacity = problem.artifact.config.cabin_capacity
    if (
        max(total, 2 * capacity, len(rides), sum(s.max_visit_count for s in starts))
        > I32_MAX
    ):
        raise ValueError("DIDP count/index exceeds signed 32-bit range")
    options = movement.route_options_by_state_id
    max_duration = max(o.duration_tick for o in movement.route_options)
    max_wait = max(
        (
            tick(policy.maximum_wait_seconds(o.station_id))
            for o in movement.route_options
        ),
        default=0,
    )
    max_headway = max((r.maximum_headway_tick for r in resources), default=0)
    boundaries = []
    for resource in resources:
        intervals = []
        for occurrence in problem.boundary_context.resource_occurrences:
            if occurrence.resource_id == resource.id:
                entry = max(0, tick(occurrence.follower_enter_time_seconds))
                end = tick(
                    occurrence.leader_clear_time_seconds
                ) + occurrence.separation_after_tick(resource)
                if end > entry:
                    intervals.append((entry, end))
        intervals.sort()
        if any(a[1] > b[0] for a, b in zip(intervals, intervals[1:])):
            raise ValueError("Conflicting fixed boundary intervals")
        boundaries.append(tuple(intervals))
    max_boundary = max((e for items in boundaries for _, e in items), default=0)
    max_release = max((abs(tick(g.release_time_seconds)) for g in groups), default=0)
    # This envelope also covers intermediate sums in lower-bound arithmetic.
    envelope = (
        movement.operational_end_tick
        + max_duration
        + max_wait
        + max_headway
        + max_boundary
        + max_release
        + sum(
            max(o.duration_tick for o in options[s]) for seq in states for s in seq[:-1]
        )
        + 10
    )
    if min(step, movement.operational_end_tick) < 0 or 8 * envelope > EXACT_FLOAT_LIMIT:
        raise ValueError("DIDP time arithmetic exceeds exact Float64 integer envelope")
    sentinel = envelope
    index_by_board = {}
    for n, ride in enumerate(rides):
        index_by_board.setdefault((ride.cabin_id, ride.board_visit_index), []).append(n)
    operations = []
    for k, (start, seq) in enumerate(zip(starts, states)):
        for i, state in enumerate(seq[:-1]):
            arrival_bounds = []
            for j in range(i + 1, len(seq) - 1):
                minimum = sum(
                    min(o.duration_tick for o in options[seq[position]])
                    for position in range(i + 1, j)
                )
                stop = unique_stop_route_option(movement, seq[j], error_context="DIDP")
                minimum += tick(stop.platform_entry_offset_seconds)
                arrival_bounds.append(
                    (j, movement.passenger_service_end_tick - minimum)
                )
            for route in sorted(options[state], key=lambda o: o.id):
                is_stop = route.platform_exit_offset_seconds is not None
                maximum = (
                    tick(policy.maximum_wait_seconds(route.station_id)) // step
                    if is_stop
                    else 0
                )
                if maximum > I32_MAX:
                    raise ValueError(
                        "DIDP waiting-step count exceeds signed 32-bit range"
                    )
                for u in route.resource_usages:
                    base = (
                        u.leader_clear_offset_tick
                        - u.follower_enter_offset_tick
                        + u.separation_after_tick(
                            movement.resources_by_id[u.resource_id].minimum_headway_tick
                        )
                    )
                    coefficient = (
                        u.leader_clear_wait_coefficient
                        - u.follower_enter_wait_coefficient
                    )
                    if min(base, base + coefficient * maximum * step) <= 0:
                        raise ValueError(
                            "Nonpositive protected interval in DIDP domain"
                        )
                operations.append(
                    Operation(
                        len(operations),
                        k,
                        i,
                        route,
                        tuple(index_by_board.get((start.cabin_id, i), ()))
                        if is_stop
                        else (),
                        maximum,
                        tuple(arrival_bounds),
                    )
                )
    # At most one unfinished movement per cabin, plus completed movements whose
    # end is within h of now. Each movement lasts at least d_min; waiting cannot
    # increase the count. Boundary intervals are stored separately.
    d_min = min(o.duration_tick for o in movement.route_options)
    sizes = []
    for r in resources:
        per_route = max(
            Counter(u.resource_id for u in o.resource_usages)[r.id]
            for o in movement.route_options
        )
        all_occurrences = sum(
            max(
                Counter(u.resource_id for u in o.resource_usages)[r.id]
                for o in options[state]
            )
            for seq in states
            for state in seq[:-1]
        )
        bound = (
            len(starts)
            * per_route
            * (2 + ((r.maximum_headway_tick + d_min - 1) // d_min))
        )
        sizes.append(min(all_occurrences, bound))
    if max(len(operations), max(sizes, default=0)) > I32_MAX:
        raise ValueError("DIDP operation/calendar index exceeds signed 32-bit range")
    return PreparedDidpStructure(
        json.dumps(manifest, sort_keys=True),
        stable_fingerprint(manifest),
        starts,
        states,
        groups,
        rides,
        tuple(operations),
        resources,
        tuple(sizes),
        tuple(boundaries),
        step,
        tick(policy.earliest_wait_time_seconds),
        movement.passenger_service_end_tick,
        movement.operational_end_tick,
        sentinel,
        total,
        capacity,
    )
