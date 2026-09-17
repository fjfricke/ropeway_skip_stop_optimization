from __future__ import annotations

from collections import defaultdict
from time import perf_counter

from ...reservoir_boundary import state_protection_tick, state_resource_id
from ...reservoir_cp_sat_certificate import (
    DddReservoirCpPlan,
    DddReservoirCpTrip,
    validate_reservoir_cp_plan,
)
from ...time_ticks import ddd_seconds_to_tick
from ..preparation import PreparedLineProblem
from .model import ConflictWitness, LineGenome, MovementEvaluation


def minimum_dispatch_gap_tick(problem) -> int:
    step = ddd_seconds_to_tick(problem.dispatch_step_seconds)
    physical = (
        problem.boundary_policy.headway_tick
        if problem.boundary_policy is not None
        else step
    )
    return ((physical + step - 1) // step) * step


def _template(prepared: PreparedLineProblem, pattern_id: str, dispatch_tick: int):
    matches = [
        t for t in prepared.templates
        if t.pattern_id == pattern_id
        and t.minimum_dispatch_tick <= dispatch_tick <= t.maximum_dispatch_tick
    ]
    if len(matches) != 1:
        raise ValueError(
            f"pattern {pattern_id!r} at dispatch {dispatch_tick} has "
            f"{len(matches)} lifecycle templates"
        )
    return matches[0]


def _overlaps(intervals):
    active = []
    result = []
    for start, end, cabin in sorted(intervals):
        active = [item for item in active if item[1] > start]
        for other_start, other_end, other_cabin in active:
            if other_cabin != cabin:
                result.append((other_cabin, cabin, min(end, other_end) - start))
        active.append((start, end, cabin))
    return result


def decode_no_wait(problem, prepared: PreparedLineProblem, genome: LineGenome) -> MovementEvaluation:
    started = perf_counter()
    gap = minimum_dispatch_gap_tick(problem)
    genome.validate(
        maximum_cabins=prepared.maximum_cabins,
        minimum_gap_tick=gap,
        window_tick=prepared.dispatch_window_end_tick,
        dispatch_step_tick=prepared.dispatch_step_tick,
    )
    if any(pattern not in {t.pattern_id for t in prepared.templates} for pattern in genome.pattern_ids):
        raise ValueError("evolution genome contains a pattern outside the prepared catalog")
    dispatches = genome.dispatch_ticks(gap)
    trips = []
    intervals = defaultdict(list)
    covered_pairs = set()
    demanded = {
        (g.origin_station_id, g.destination_station_id)
        for g in problem.demand_groups if g.count > 0
    }
    try:
        for cabin, (pattern, dispatch) in enumerate(zip(genome.pattern_ids, dispatches, strict=True)):
            template = _template(prepared, pattern, dispatch)
            visits = tuple(dispatch + v.start_tick for v in template.visits)
            trips.append(DddReservoirCpTrip(
                cabin,
                template.route_option_ids,
                visits,
                (0,) * len(visits),
                dispatch + template.duration_tick,
            ))
            for item in template.resource_intervals:
                intervals[item.resource_id].append(
                    (dispatch + item.start_tick, dispatch + item.end_tick, cabin)
                )
            for state, offset in template.state_event_offsets:
                start = dispatch + offset
                intervals[state_resource_id(problem, state)].append(
                    (start, start + state_protection_tick(problem, state), cabin)
                )
            covered_pairs.update(
                pair for pair in demanded
                if pair[0] in template.stop_station_ids and pair[1] in template.stop_station_ids
            )
    except ValueError as error:
        return MovementEvaluation(
            genome, False, None, (), 0, len(covered_pairs), perf_counter() - started, str(error)
        )
    conflicts = []
    for resource_id, values in intervals.items():
        conflicts.extend(
            ConflictWitness(resource_id, a, b, overlap)
            for a, b, overlap in _overlaps(values)
            if overlap > 0
        )
    plan = DddReservoirCpPlan(tuple(trips), {})
    reason = None
    if not conflicts:
        try:
            validate_reservoir_cp_plan(problem, plan)
        except ValueError as error:
            reason = f"independent movement validation failed: {error}"
    return MovementEvaluation(
        genome,
        not conflicts and reason is None,
        plan if not conflicts and reason is None else None,
        tuple(conflicts),
        sum(item.overlap_ticks for item in conflicts),
        len(covered_pairs),
        perf_counter() - started,
        reason,
        plan if conflicts else None,
    )
