from __future__ import annotations

from dataclasses import asdict, dataclass, replace
from enum import StrEnum
from hashlib import sha256
import json
import math
from typing import Iterable

from ..fixed_k import DddFixedKTrajectoryProblem
from ..models import DddFixedStart, DddRouteDecision, DddRouteOption
from ..reference import DddReferenceSolution, validate_ddd_reference_solution
from ..resource_time import DddTickInterval
from ..time_ticks import DddTimeTick, ddd_seconds_to_tick
from ..trajectory_column_generation import DddTrajectoryWaitingDomain
from ..trajectory_problem import DddTrajectoryWaitingPolicy


class CorridorArcFlowMode(StrEnum):
    INNER = "inner"
    OUTER = "outer"


@dataclass(frozen=True, slots=True)
class CorridorArcFlowConfig:
    waiting_cap_multiplier: float | None = 2.0
    explicit_maximum_wait_seconds: float | None = None
    maximum_splits_per_round: int = 16

    def validate(self) -> None:
        if self.waiting_cap_multiplier is not None and (
            not math.isfinite(self.waiting_cap_multiplier) or self.waiting_cap_multiplier <= 0
        ):
            raise ValueError("corridor waiting-cap multiplier must be positive")
        if self.explicit_maximum_wait_seconds is not None and (
            not math.isfinite(self.explicit_maximum_wait_seconds)
            or self.explicit_maximum_wait_seconds <= 0
        ):
            raise ValueError("explicit corridor waiting cap must be positive")
        if (self.waiting_cap_multiplier is None) == (self.explicit_maximum_wait_seconds is None):
            raise ValueError("choose exactly one corridor waiting-cap definition")
        if self.maximum_splits_per_round <= 0:
            raise ValueError("corridor split limit must be positive")


@dataclass(frozen=True, slots=True)
class CorridorPartition:
    key: str
    lower_tick: DddTimeTick
    upper_tick: DddTimeTick
    boundaries: tuple[DddTimeTick, ...]

    def validate(self) -> None:
        if not self.key or self.lower_tick >= self.upper_tick:
            raise ValueError("invalid corridor partition")
        if self.boundaries[0] != self.lower_tick or self.boundaries[-1] != self.upper_tick:
            raise ValueError("corridor partition does not cover its domain")
        if any(
            a >= b
            for a, b in zip(self.boundaries[:-1], self.boundaries[1:], strict=True)
        ):
            raise ValueError("corridor partition boundaries must increase")

    @property
    def cells(self) -> tuple[DddTickInterval, ...]:
        self.validate()
        return tuple(
            DddTickInterval(a, b)
            for a, b in zip(self.boundaries[:-1], self.boundaries[1:], strict=True)
        )


@dataclass(frozen=True, slots=True)
class CorridorResourceWindow:
    resource_id: str
    usage_index: int
    outer: DddTickInterval | None
    mandatory_core: DddTickInterval | None


@dataclass(frozen=True, slots=True)
class CorridorArc:
    id: str
    cabin_id: int
    visit_index: int
    state_id: str
    option_id: str
    source_interval: DddTickInterval
    wait_interval: DddTickInterval
    resources: tuple[CorridorResourceWindow, ...]


@dataclass(frozen=True, slots=True)
class CorridorPreparedProblem:
    problem: DddFixedKTrajectoryProblem
    waiting_policy: DddTrajectoryWaitingPolicy
    time_partitions: tuple[CorridorPartition, ...]
    wait_partitions: tuple[CorridorPartition, ...]
    arcs: tuple[CorridorArc, ...]
    states_by_cabin: tuple[tuple[int, tuple[str, ...]], ...]
    options_by_visit: tuple[tuple[int, int, tuple[str, ...]], ...]
    model_fingerprint: str

    @property
    def time_partition_by_key(self) -> dict[str, CorridorPartition]:
        return {item.key: item for item in self.time_partitions}

    @property
    def wait_partition_by_key(self) -> dict[str, CorridorPartition]:
        return {item.key: item for item in self.wait_partitions}


def _deterministic_visits(problem: DddFixedKTrajectoryProblem, start: DddFixedStart):
    movement = problem.resolved_trajectory_problem.structural_movement_problem
    state = start.state_id
    states = [state]
    options_by_visit = []
    for _ in range(start.max_visit_count):
        options = movement.route_options_by_state_id.get(state, ())
        if not options:
            raise ValueError(f"corridor state {state!r} has no route option")
        targets = {option.to_state_id for option in options}
        if len(targets) != 1:
            raise ValueError("corridor pilot requires reconverging route options")
        options_by_visit.append(options)
        state = next(iter(targets))
        states.append(state)
    return tuple(states), tuple(options_by_visit)


def _all_stop_cycle_tick(problem: DddFixedKTrajectoryProblem) -> int:
    movement = problem.resolved_trajectory_problem.structural_movement_problem
    state = movement.starts[0].state_id
    initial = state
    total = 0
    seen = set()
    while state not in seen:
        seen.add(state)
        stops = tuple(
            option for option in movement.route_options_by_state_id.get(state, ())
            if option.decision is DddRouteDecision.STOP
        )
        if len(stops) != 1:
            raise ValueError("all-stop cycle requires one STOP option per state")
        total += stops[0].duration_tick
        state = stops[0].to_state_id
        if state == initial:
            return total
    raise ValueError("fixed-start movement does not contain an all-stop cycle")


def build_cycle_spacing_waiting_policy(
    problem: DddFixedKTrajectoryProblem,
    config: CorridorArcFlowConfig = CorridorArcFlowConfig(),
) -> DddTrajectoryWaitingPolicy:
    config.validate()
    movement = problem.resolved_trajectory_problem.structural_movement_problem
    if config.explicit_maximum_wait_seconds is None:
        cycle_seconds = _all_stop_cycle_tick(problem) / 1_000_000
        maximum = math.ceil(config.waiting_cap_multiplier * cycle_seconds / problem.fleet_cardinality)
    else:
        maximum = config.explicit_maximum_wait_seconds
    station_ids = sorted({
        option.station_id for option in movement.route_options
        if option.decision is DddRouteDecision.STOP
        and option.platform_exit_offset_seconds is not None
    })
    return DddTrajectoryWaitingPolicy(
        domain=DddTrajectoryWaitingDomain.BOUNDED_WAIT,
        step_seconds=0.000001,
        maximum_wait_seconds_by_station_id=tuple((station, maximum) for station in station_ids),
        earliest_wait_time_seconds=(
            problem.resolved_trajectory_problem.waiting_policy.earliest_wait_time_seconds
        ),
    )


def _partition(key: str, lower: int, upper: int, anchors: Iterable[int]) -> CorridorPartition:
    points = {lower, upper}
    for tick in anchors:
        if lower < tick < upper:
            points.add(tick)
        if lower < tick + 1 < upper:
            points.add(tick + 1)
    result = CorridorPartition(key, lower, upper, tuple(sorted(points)))
    result.validate()
    return result


def _resource_window(usage, usage_index, resource, source, wait, operational_end):
    # Presence is conditional on actual entry being at or before H.  Optimize
    # the two affine endpoints over the rectangle by checking its corners and
    # the integer boundary induced by entry <= H.
    s_values = {source.lower_tick, source.last_tick}
    w_values = {wait.lower_tick, wait.last_tick}
    enter_offset = usage.follower_enter_offset_tick
    clear_offset = usage.leader_clear_offset_tick + usage.separation_after_tick(
        resource.minimum_headway_tick
    )
    ec = usage.follower_enter_wait_coefficient
    cc = usage.leader_clear_wait_coefficient
    candidates = set()
    for s in s_values:
        for w in w_values:
            candidates.add((s, w))
    for w in w_values:
        threshold = operational_end - enter_offset - ec * w
        for s in (threshold, threshold + 1):
            if source.contains_tick(s):
                candidates.add((s, w))
    for s in s_values:
        if ec:
            threshold = operational_end - enter_offset - s
            for w in (threshold, threshold + 1):
                if wait.contains_tick(w):
                    candidates.add((s, w))
    present = [
        (s + enter_offset + ec * w, s + clear_offset + cc * w)
        for s, w in candidates
        if s + enter_offset + ec * w <= operational_end
    ]
    if not present:
        return CorridorResourceWindow(usage.resource_id, usage_index, None, None)
    outer = DddTickInterval(min(a for a, _ in present), max(b for _, b in present))
    always_present = max(
        s + enter_offset + ec * w for s in s_values for w in w_values
    ) <= operational_end
    core = None
    if always_present:
        lower = max(a for a, _ in present)
        upper = min(b for _, b in present)
        if lower < upper:
            core = DddTickInterval(lower, upper)
    return CorridorResourceWindow(usage.resource_id, usage_index, outer, core)


def prepare_corridor_problem(
    problem: DddFixedKTrajectoryProblem,
    *,
    config: CorridorArcFlowConfig = CorridorArcFlowConfig(),
    seed: DddReferenceSolution | None = None,
    time_partitions: tuple[CorridorPartition, ...] | None = None,
    wait_partitions: tuple[CorridorPartition, ...] | None = None,
) -> CorridorPreparedProblem:
    problem.validate()
    config.validate()
    waiting = build_cycle_spacing_waiting_policy(problem, config)
    movement = problem.resolved_trajectory_problem.structural_movement_problem
    waiting.validate(movement.core)
    if seed is not None:
        validate_ddd_reference_solution(
            movement,
            seed,
            waiting_policy=waiting,
        )
    seed_visits = {
        (trajectory.cabin_id, visit.visit_index): visit
        for trajectory in (() if seed is None else seed.trajectories)
        for visit in trajectory.visits
    }
    time_parts = []
    wait_parts = []
    states_by_cabin = []
    option_rows = []
    structure = {}
    max_wait_by_station = {
        station: ddd_seconds_to_tick(value)
        for station, value in waiting.maximum_wait_seconds_by_station_id
    }
    for start in sorted(movement.starts, key=lambda item: item.cabin_id):
        states, visits = _deterministic_visits(problem, start)
        states_by_cabin.append((start.cabin_id, states))
        earliest = start.time_tick
        latest = start.time_tick
        for index, options in enumerate(visits):
            option_rows.append((start.cabin_id, index, tuple(o.id for o in options)))
            structure[start.cabin_id, index] = options
            seed_visit = seed_visits.get((start.cabin_id, index))
            anchors = () if seed_visit is None else (ddd_seconds_to_tick(seed_visit.switch_time_seconds),)
            time_parts.append(_partition(f"time::{start.cabin_id}::{index}", earliest, latest + 1, anchors))
            max_wait = max(
                max_wait_by_station.get(option.station_id, 0)
                if option.decision is DddRouteDecision.STOP else 0
                for option in options
            )
            wait_anchor = () if seed_visit is None else (ddd_seconds_to_tick(seed_visit.wait_seconds),)
            wait_parts.append(_partition(f"wait::{start.cabin_id}::{index}", 0, max_wait + 1, (0, *wait_anchor)))
            earliest += min(option.duration_tick for option in options)
            latest += max(
                option.duration_tick + (
                    max_wait_by_station.get(option.station_id, 0)
                    if option.decision is DddRouteDecision.STOP else 0
                )
                for option in options
            )
    if time_partitions is not None:
        time_parts = list(time_partitions)
    if wait_partitions is not None:
        wait_parts = list(wait_partitions)
    time_by_key = {p.key: p for p in time_parts}
    wait_by_key = {p.key: p for p in wait_parts}
    arcs = []
    for (cabin, visit), options in structure.items():
        source_cells = time_by_key[f"time::{cabin}::{visit}"].cells
        wait_cells = wait_by_key[f"wait::{cabin}::{visit}"].cells
        for option in options:
            option_wait_max = (
                max_wait_by_station.get(option.station_id, 0)
                if option.decision is DddRouteDecision.STOP else 0
            )
            for source_index, source in enumerate(source_cells):
                for wait_index, wait in enumerate(wait_cells):
                    if wait.lower_tick > option_wait_max or wait.last_tick > option_wait_max:
                        continue
                    if option.decision is DddRouteDecision.SKIP and wait.lower_tick != 0:
                        continue
                    resources = tuple(
                        _resource_window(
                            usage, usage_index, movement.resources_by_id[usage.resource_id], source, wait,
                            movement.operational_end_tick,
                        )
                        for usage_index, usage in enumerate(option.resource_usages)
                    )
                    arcs.append(CorridorArc(
                        id=f"corridor::{cabin}::{visit}::{option.id}::{source_index}::{wait_index}",
                        cabin_id=cabin, visit_index=visit, state_id=option.from_state_id,
                        option_id=option.id, source_interval=source,
                        wait_interval=wait, resources=resources,
                    ))
    payload = {
        "schema": "ddd_corridor_arc_flow_v1",
        "problem": problem.fingerprint,
        "config": asdict(config),
        "waiting": asdict(waiting),
        "time": [asdict(p) for p in time_parts],
        "wait": [asdict(p) for p in wait_parts],
    }
    return CorridorPreparedProblem(
        problem=problem, waiting_policy=waiting,
        time_partitions=tuple(time_parts), wait_partitions=tuple(wait_parts),
        arcs=tuple(arcs), states_by_cabin=tuple(states_by_cabin),
        options_by_visit=tuple(option_rows),
        model_fingerprint=sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest(),
    )


def refine_corridor_partition(
    prepared: CorridorPreparedProblem,
    *,
    partition_key: str,
    boundary_tick: int,
    config: CorridorArcFlowConfig = CorridorArcFlowConfig(),
    seed: DddReferenceSolution | None = None,
) -> CorridorPreparedProblem:
    def split(items):
        result = []
        found = False
        for item in items:
            if item.key == partition_key:
                if not item.lower_tick < boundary_tick < item.upper_tick:
                    raise ValueError("corridor refinement lies outside the partition")
                result.append(replace(item, boundaries=tuple(sorted({*item.boundaries, boundary_tick}))))
                found = True
            else:
                result.append(item)
        if not found:
            raise ValueError("unknown corridor partition key")
        return tuple(result)
    is_time = partition_key.startswith("time::")
    return prepare_corridor_problem(
        prepared.problem, config=config, seed=seed,
        time_partitions=split(prepared.time_partitions) if is_time else prepared.time_partitions,
        wait_partitions=prepared.wait_partitions if is_time else split(prepared.wait_partitions),
    )


def refine_corridor_partitions(
    prepared: CorridorPreparedProblem,
    *,
    splits: tuple[tuple[str, int], ...],
    config: CorridorArcFlowConfig = CorridorArcFlowConfig(),
    seed: DddReferenceSolution | None = None,
) -> CorridorPreparedProblem:
    """Apply a batch of lossless local splits with one network rebuild."""
    if len(splits) > config.maximum_splits_per_round:
        raise ValueError("corridor refinement batch exceeds its configured limit")
    split_by_key = dict(splits)
    if len(split_by_key) != len(splits):
        raise ValueError("corridor refinement batch repeats a partition")
    known = {p.key for p in (*prepared.time_partitions, *prepared.wait_partitions)}
    if set(split_by_key) - known:
        raise ValueError("corridor refinement references an unknown partition")

    def update(items):
        result = []
        for item in items:
            boundary = split_by_key.get(item.key)
            if boundary is None:
                result.append(item)
                continue
            if not item.lower_tick < boundary < item.upper_tick:
                raise ValueError("corridor refinement lies outside the partition")
            result.append(replace(item, boundaries=tuple(sorted({*item.boundaries, boundary}))))
        return tuple(result)

    return prepare_corridor_problem(
        prepared.problem,
        config=config,
        seed=seed,
        time_partitions=update(prepared.time_partitions),
        wait_partitions=update(prepared.wait_partitions),
    )


def anchor_corridor_partitions(
    prepared: CorridorPreparedProblem,
    *,
    anchors: tuple[tuple[str, int], ...],
    config: CorridorArcFlowConfig = CorridorArcFlowConfig(),
    seed: DddReferenceSolution | None = None,
) -> CorridorPreparedProblem:
    """Make selected exact integer values singleton cells in one rebuild."""
    if len(anchors) > config.maximum_splits_per_round:
        raise ValueError("corridor anchor batch exceeds its configured limit")
    anchor_by_key = dict(anchors)
    if len(anchor_by_key) != len(anchors):
        raise ValueError("corridor anchor batch repeats a partition")
    known = {p.key for p in (*prepared.time_partitions, *prepared.wait_partitions)}
    if set(anchor_by_key) - known:
        raise ValueError("corridor anchor references an unknown partition")

    def update(items):
        result = []
        for item in items:
            value = anchor_by_key.get(item.key)
            if value is None:
                result.append(item)
                continue
            if not item.lower_tick <= value < item.upper_tick:
                raise ValueError("corridor anchor lies outside the partition")
            boundaries = set(item.boundaries)
            if item.lower_tick < value < item.upper_tick:
                boundaries.add(value)
            if item.lower_tick < value + 1 < item.upper_tick:
                boundaries.add(value + 1)
            result.append(replace(item, boundaries=tuple(sorted(boundaries))))
        return tuple(result)

    return prepare_corridor_problem(
        prepared.problem,
        config=config,
        seed=seed,
        time_partitions=update(prepared.time_partitions),
        wait_partitions=update(prepared.wait_partitions),
    )
