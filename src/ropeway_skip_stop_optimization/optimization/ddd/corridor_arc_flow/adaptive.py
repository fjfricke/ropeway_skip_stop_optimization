from __future__ import annotations

from dataclasses import dataclass
from collections import defaultdict
from time import perf_counter
from typing import Callable

from .domain import (
    CorridorArcFlowConfig,
    CorridorPreparedProblem,
    anchor_corridor_partitions,
)
from .solver import (
    CorridorArcFlowMode,
    CorridorArcFlowOptimizer,
    CorridorArcFlowResult,
    CorridorArcFlowSolveConfig,
)
from ..reference import DddReferenceSolution
from ..time_ticks import ddd_seconds_to_tick


@dataclass(frozen=True, slots=True)
class CorridorAdaptiveConfig:
    total_time_limit_seconds: float = 300.0
    threads: int | None = None
    seed: int = 0
    inner_share: float = 0.7
    outer_share: float = 0.2
    maximum_rounds: int = 8
    inner_slice_seconds: float = 30.0
    outer_slice_seconds: float = 20.0
    memory_limit_gib: float | None = None

    def validate(self) -> None:
        if self.total_time_limit_seconds <= 0 or self.maximum_rounds <= 0:
            raise ValueError("invalid adaptive corridor budget")
        if self.threads is not None and self.threads <= 0:
            raise ValueError("adaptive corridor threads must be positive")
        if self.memory_limit_gib is not None and self.memory_limit_gib <= 0:
            raise ValueError("adaptive corridor memory limit must be positive")
        if self.seed < 0 or not 0 < self.inner_share < 1 or not 0 < self.outer_share < 1:
            raise ValueError("invalid adaptive corridor shares")
        if self.inner_share + self.outer_share >= 1:
            raise ValueError("adaptive corridor shares must leave orchestration reserve")


@dataclass(frozen=True, slots=True)
class CorridorAdaptiveRound:
    index: int
    inner: CorridorArcFlowResult | None
    outer: CorridorArcFlowResult | None
    split_keys: tuple[str, ...]
    split_boundaries: tuple[tuple[str, int], ...]
    conflicting_corridor_count: int


@dataclass(frozen=True, slots=True)
class CorridorAdaptiveResult:
    rounds: tuple[CorridorAdaptiveRound, ...]
    best_inner: CorridorArcFlowResult | None
    best_global_lower_bound: int | None
    final_prepared: CorridorPreparedProblem
    total_seconds: float


def _selected_arcs(
    prepared: CorridorPreparedProblem,
    result: CorridorArcFlowResult | None,
):
    """Map a candidate back to the current partition after any rebuild."""
    if result is None or result.relaxed_candidate is None:
        return ()
    by_visit = defaultdict(list)
    for arc in prepared.arcs:
        by_visit[arc.cabin_id, arc.visit_index, arc.option_id].append(arc)
    selected = []
    for trajectory in result.relaxed_candidate.trajectories:
        for visit in trajectory.visits:
            source = ddd_seconds_to_tick(visit.switch_time_seconds)
            wait = ddd_seconds_to_tick(visit.wait_seconds)
            matches = [
                arc
                for arc in by_visit[
                    trajectory.cabin_id, visit.visit_index, visit.route_option_id
                ]
                if arc.source_interval.contains_tick(source)
                and arc.wait_interval.contains_tick(wait)
            ]
            if len(matches) == 1:
                selected.append(matches[0])
    return tuple(selected)


def _selected_resource_conflicts(
    prepared: CorridorPreparedProblem,
    result: CorridorArcFlowResult | None,
) -> set[str]:
    """Return selected corridor arcs involved in exact resource overlaps."""
    if result is None or result.relaxed_candidate is None:
        return set()
    arcs = {arc.id: arc for arc in _selected_arcs(prepared, result)}
    movement = prepared.problem.resolved_trajectory_problem.structural_movement_problem
    visits = {
        (trajectory.cabin_id, visit.visit_index): visit
        for trajectory in result.relaxed_candidate.trajectories
        for visit in trajectory.visits
    }
    uses = defaultdict(list)
    for arc in arcs.values():
        visit = visits.get((arc.cabin_id, arc.visit_index))
        if visit is None:
            continue
        option = next(item for item in movement.route_options if item.id == arc.option_id)
        source = ddd_seconds_to_tick(visit.switch_time_seconds)
        wait = ddd_seconds_to_tick(visit.wait_seconds)
        for usage in option.resource_usages:
            entry = source + usage.follower_enter_offset_tick + usage.follower_enter_wait_coefficient * wait
            if entry > movement.operational_end_tick:
                continue
            resource = movement.resources_by_id[usage.resource_id]
            clear = (
                source + usage.leader_clear_offset_tick
                + usage.leader_clear_wait_coefficient * wait
                + usage.separation_after_tick(resource.minimum_headway_tick)
            )
            uses[usage.resource_id].append((entry, clear, arc.id))
    for occurrence in prepared.problem.boundary_context.resource_occurrences:
        resource = movement.resources_by_id[occurrence.resource_id]
        entry = max(0, ddd_seconds_to_tick(occurrence.follower_enter_time_seconds))
        clear = (
            ddd_seconds_to_tick(occurrence.leader_clear_time_seconds)
            + occurrence.separation_after_tick(resource)
        )
        if entry < clear:
            uses[occurrence.resource_id].append((entry, clear, None))
    conflicts = set()
    for entries in uses.values():
        entries.sort()
        active = []
        for entry, clear, arc_id in entries:
            active = [item for item in active if item[0] > entry]
            if active:
                if arc_id is not None:
                    conflicts.add(arc_id)
                conflicts.update(item[1] for item in active if item[1] is not None)
            active.append((clear, arc_id))
    return conflicts


def _partition_split(partition, value: int) -> tuple[int, int] | None:
    cell = next((item for item in partition.cells if item.contains_tick(value)), None)
    if cell is None or cell.width_ticks <= 1:
        return None
    return cell.width_ticks, value


def _split_candidates(
    prepared: CorridorPreparedProblem,
    limit: int,
    *,
    outer: CorridorArcFlowResult | None,
    inner: CorridorArcFlowResult | None,
):
    conflict_ids = _selected_resource_conflicts(prepared, outer)
    diagnostic = outer if outer is not None and outer.relaxed_candidate is not None else inner
    if diagnostic is not None and diagnostic.relaxed_candidate is not None:
        visits = {
            (trajectory.cabin_id, visit.visit_index): visit
            for trajectory in diagnostic.relaxed_candidate.trajectories
            for visit in trajectory.visits
        }
        ride_ids = {key for key, amount in diagnostic.ride_counts if amount > 0}
        ride_by_id = {
            item.id: item for item in prepared.problem.passenger_build.ride_candidates
        }
        passenger_visits = set()
        for ride_id in ride_ids:
            ride = ride_by_id[ride_id]
            passenger_visits.add((ride.cabin_id, ride.board_visit_index))
            passenger_visits.add((ride.cabin_id, ride.alight_visit_index))
        selected = _selected_arcs(prepared, diagnostic)
        targeted = []
        for arc in selected:
            visit = visits.get((arc.cabin_id, arc.visit_index))
            if visit is None:
                continue
            is_conflict = arc.id in conflict_ids
            if conflict_ids and not is_conflict:
                continue
            priority = 0 if (arc.cabin_id, arc.visit_index) in passenger_visits else 1
            for kind, value in (
                ("time", ddd_seconds_to_tick(visit.switch_time_seconds)),
                ("wait", ddd_seconds_to_tick(visit.wait_seconds)),
            ):
                key = f"{kind}::{arc.cabin_id}::{arc.visit_index}"
                partition = (
                    prepared.time_partition_by_key[key]
                    if kind == "time" else prepared.wait_partition_by_key[key]
                )
                split = _partition_split(partition, value)
                if split is not None:
                    width, boundary = split
                    targeted.append((not is_conflict, priority, -width, key, boundary))
        targeted.sort()
        result, seen = [], set()
        for _, _, _, key, boundary in targeted:
            if key in seen:
                continue
            seen.add(key)
            result.append((key, boundary))
            if len(result) == limit:
                return tuple(result)
        if result:
            return tuple(result)

    # Deterministic fallback when neither relaxation nor search exposes a candidate.
    candidates = []
    for partition in (*prepared.wait_partitions, *prepared.time_partitions):
        for cell in partition.cells:
            if cell.width_ticks <= 1:
                continue
            candidates.append((cell.width_ticks, partition.key, cell.lower_tick + cell.width_ticks // 2))
    candidates.sort(key=lambda item: (-item[0], item[1], item[2]))
    # One split per partition per round avoids repeated stale boundaries.
    result, seen = [], set()
    for _, key, boundary in candidates:
        if key in seen:
            continue
        seen.add(key)
        result.append((key, boundary))
        if len(result) == limit:
            break
    return tuple(result)


@dataclass(slots=True)
class CorridorAdaptiveOptimizer:
    config: CorridorAdaptiveConfig = CorridorAdaptiveConfig()
    formulation: CorridorArcFlowConfig = CorridorArcFlowConfig()

    def solve(
        self,
        prepared: CorridorPreparedProblem,
        *,
        seed: DddReferenceSolution | None = None,
        seed_ride_counts: dict[str, int] | None = None,
        round_callback: Callable[[CorridorAdaptiveRound], None] | None = None,
    ) -> CorridorAdaptiveResult:
        self.config.validate()
        started = perf_counter()
        inner_budget = self.config.total_time_limit_seconds * self.config.inner_share
        outer_budget = self.config.total_time_limit_seconds * self.config.outer_share
        rounds = []
        best = None
        best_lb = None
        current_seed = seed
        current_seed_rides = seed_ride_counts
        current = prepared
        last_outer = None
        deadline = started + self.config.total_time_limit_seconds
        inner_build_estimate = 0.0
        outer_build_estimate = 0.0
        for index in range(self.config.maximum_rounds):
            reserve = max(1.0, self.config.total_time_limit_seconds * 0.02)
            if perf_counter() >= deadline - reserve:
                break
            inner_slice = min(
                self.config.inner_slice_seconds,
                inner_budget,
                max(0.0, deadline - reserve - perf_counter() - inner_build_estimate),
            )
            inner = outer = None
            if inner_slice > 0.001:
                inner = CorridorArcFlowOptimizer(CorridorArcFlowSolveConfig(
                    mode=CorridorArcFlowMode.INNER, time_limit_seconds=inner_slice,
                    threads=self.config.threads, seed=self.config.seed,
                    memory_limit_gib=self.config.memory_limit_gib,
                )).solve(
                    current, seed=current_seed, seed_ride_counts=current_seed_rides
                )
                inner_budget -= inner_slice
                inner_build_estimate = max(inner_build_estimate, inner.build_seconds)
                if inner.solution is not None and (
                    best is None or inner.objective_value < best.objective_value
                ):
                    best = inner
                    current_seed = inner.solution
                    current_seed_rides = dict(inner.ride_counts)
            outer_slice = min(
                self.config.outer_slice_seconds,
                outer_budget,
                max(0.0, deadline - reserve - perf_counter() - outer_build_estimate),
            )
            if outer_slice > 0.001:
                outer = CorridorArcFlowOptimizer(CorridorArcFlowSolveConfig(
                    mode=CorridorArcFlowMode.OUTER, time_limit_seconds=outer_slice,
                    threads=self.config.threads, seed=self.config.seed,
                    memory_limit_gib=self.config.memory_limit_gib,
                )).solve(
                    current, seed=current_seed, seed_ride_counts=current_seed_rides
                )
                outer_budget -= outer_slice
                outer_build_estimate = max(outer_build_estimate, outer.build_seconds)
                if outer.certified_global_lower_bound is not None:
                    best_lb = max(best_lb or 0, outer.certified_global_lower_bound)
                if outer.relaxed_candidate is not None:
                    last_outer = outer
            candidates = _split_candidates(
                current,
                self.formulation.maximum_splits_per_round,
                outer=outer if outer is not None else last_outer,
                inner=inner,
            )
            split_keys = [key for key, _ in candidates]
            conflict_count = len(_selected_resource_conflicts(
                current, outer if outer is not None else last_outer
            ))
            if candidates:
                current = anchor_corridor_partitions(
                    current, anchors=candidates, config=self.formulation,
                    seed=current_seed,
                )
            completed_round = CorridorAdaptiveRound(
                index, inner, outer, tuple(split_keys), tuple(candidates), conflict_count
            )
            rounds.append(completed_round)
            if round_callback is not None:
                round_callback(completed_round)
            if not candidates or (inner_budget <= 0.001 and outer_budget <= 0.001):
                break
        return CorridorAdaptiveResult(
            tuple(rounds), best, best_lb, current, perf_counter() - started
        )
