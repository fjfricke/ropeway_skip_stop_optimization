from __future__ import annotations

import math
from collections import defaultdict
from dataclasses import asdict, dataclass

from ..ean.models import StationWaitingMode
from ..ean.passenger_objective import EanPassengerObjective
from .artifact_adapter import EanArtifactToDddMovementProblemAdapter
from .fixed_k import DddFixedKTrajectoryProblem
from .models import DddRouteDecision
from .reference import (
    DddReferenceSolution,
    DddReferenceTrajectory,
    validate_ddd_reference_solution,
)
from .route_topology import deterministic_route_state_ids, unique_stop_route_option
from .time_ticks import (
    DDD_TIME_TICKS_PER_SECOND,
    ddd_seconds_to_tick,
    ddd_tick_to_seconds,
)
from .trajectory_column_generation import DddTrajectoryWaitingDomain


def build_ddd_fixed_k_domain_manifest(problem: DddFixedKTrajectoryProblem) -> dict:
    """Reject unsupported domains before interpreting any CP bound as global."""
    problem.validate()
    resolved = problem.resolved_trajectory_problem
    movement = resolved.structural_movement_problem
    if problem.objective is not EanPassengerObjective.JOURNEY_TIME:
        raise ValueError("integrated CP-SAT v1 requires Journey Time")
    policy = resolved.waiting_policy
    if any(
        station.waiting_mode
        not in (StationWaitingMode.NO_WAITING, StationWaitingMode.END_OF_PLATFORM_WAIT)
        for station in problem.artifact.config.station_configs
    ):
        raise ValueError(
            "integrated CP-SAT supports only No-Wait or end-of-platform waiting"
        )
    adapter = EanArtifactToDddMovementProblemAdapter(
        waiting_step_seconds=policy.step_seconds or 1.0
    )
    expected_policy = adapter.build_waiting_policy(problem.artifact)
    if policy != expected_policy:
        raise ValueError(
            "CP-SAT waiting policy differs from artifact (No-Wait/exit-wait domain)"
        )
    if policy.step_seconds is not None:
        for t in (
            policy.step_seconds,
            policy.earliest_wait_time_seconds,
            *(w for _, w in policy.maximum_wait_seconds_by_station_id),
        ):
            if not math.isclose(
                t, ddd_tick_to_seconds(ddd_seconds_to_tick(t)), rel_tol=0, abs_tol=1e-10
            ):
                raise ValueError(
                    "CP-SAT waiting values must lie on the canonical tick grid"
                )
        if ddd_seconds_to_tick(policy.step_seconds) <= 0:
            raise ValueError("CP-SAT waiting grid must contain at least one tick")
    if (
        type(problem.artifact.config.cabin_capacity) is not int
        or problem.artifact.config.cabin_capacity <= 0
    ):
        raise ValueError("CP-SAT cabin capacity must be a positive integer")
    if any(
        type(g.count) is not int or g.count < 0
        for g in problem.passenger_build.demand_groups
    ):
        raise ValueError("CP-SAT demand counts must be nonnegative integers")
    # Arc-Flow uses original release/horizon seconds in its cost constant.
    # Do not silently shift that constant when constructing an integer objective.
    objective_times = [
        problem.artifact.config.horizon_seconds,
        problem.artifact.config.model_end_seconds,
        *(g.release_time_seconds for g in problem.passenger_build.demand_groups),
    ]
    if any(
        not math.isfinite(t)
        or not math.isclose(
            t, ddd_tick_to_seconds(ddd_seconds_to_tick(t)), rel_tol=0.0, abs_tol=1e-10
        )
        for t in objective_times
    ):
        raise ValueError(
            "CP-SAT releases and horizons must lie on the canonical tick grid"
        )
    adapted = adapter.build_trajectory_problem(problem.artifact)
    if adapted.movement_core != problem.trajectory_problem.movement_core:
        raise ValueError("CP-SAT artifact and Movement core differ")
    if adapted.start_domain != problem.trajectory_problem.start_domain:
        raise ValueError("CP-SAT artifact and fixed start domain differ")
    ring = problem.artifact.circulation_state_ids
    if not ring or len(set(ring)) != len(ring):
        raise ValueError("CP-SAT requires one immutable directed ring")
    options = movement.route_options_by_state_id
    for i, state in enumerate(ring):
        if {o.to_state_id for o in options[state]} != {ring[(i + 1) % len(ring)]}:
            raise ValueError("CP-SAT requires one immutable directed ring")
        stop = unique_stop_route_option(
            movement, state, error_context="integrated CP-SAT"
        )
        if (
            stop.platform_entry_offset_seconds is None
            or stop.platform_exit_offset_seconds is None
        ):
            raise ValueError("CP-SAT STOP requires platform event offsets")
        if not (
            0
            <= ddd_seconds_to_tick(stop.platform_entry_offset_seconds)
            <= ddd_seconds_to_tick(stop.platform_exit_offset_seconds)
            <= stop.duration_tick
        ):
            raise ValueError(
                "CP-SAT platform events must be ordered within their route"
            )
    if set(options) != set(ring):
        raise ValueError("CP-SAT Movement contains states outside its ring")
    if any(o.boundary_only for o in problem.boundary_context.resource_occurrences):
        raise ValueError("CP-SAT v1 does not support boundary-only reduced resources")
    states_by_cabin = {}
    for start in movement.starts:
        states = deterministic_route_state_ids(
            movement,
            start_state_id=start.state_id,
            max_visit_count=start.max_visit_count,
            error_context="integrated CP-SAT",
        )
        earliest_end = start.time_tick + sum(
            min(o.duration_tick for o in options[s]) for s in states[:-1]
        )
        if earliest_end <= movement.operational_end_tick:
            raise ValueError(
                "CP-SAT visit bound does not cover the fastest continuation"
            )
        states_by_cabin[start.cabin_id] = states
    groups = {g.id: g for g in problem.passenger_build.demand_groups}
    for q in problem.passenger_build.ride_candidates:
        states = states_by_cabin.get(q.cabin_id, ())
        if not 0 <= q.board_visit_index < q.alight_visit_index < len(states) - 1:
            raise ValueError("CP-SAT passenger candidate exceeds its visit domain")
        g = groups[q.demand_group_id]
        if (
            unique_stop_route_option(
                movement, states[q.board_visit_index], error_context="CP boarding"
            ).station_id
            != g.origin_station_id
            or unique_stop_route_option(
                movement, states[q.alight_visit_index], error_context="CP alighting"
            ).station_id
            != g.destination_station_id
        ):
            raise ValueError("CP-SAT passenger candidate station mismatch")
    # The existing historical fingerprint omits capacity, route timing and rides.
    # Serialize the actual domain, independently of the chosen solver encoding.
    return {
        "schema": "fixed_k_domain_v1",
        **(
            {"waiting_policy": asdict(policy)}
            if policy.domain is DddTrajectoryWaitingDomain.BOUNDED_WAIT
            else {}
        ),
        "time_ticks_per_second": DDD_TIME_TICKS_PER_SECOND,
        "tick_horizons": [
            movement.passenger_service_end_tick,
            movement.operational_end_tick,
        ],
        "tick_starts": [
            [s.cabin_id, s.state_id, s.time_tick, s.max_visit_count]
            for s in sorted(movement.starts, key=lambda s: s.cabin_id)
        ],
        "tick_routes": [
            {
                "id": o.id,
                "duration": o.duration_tick,
                "platform_entry": None
                if o.platform_entry_offset_seconds is None
                else ddd_seconds_to_tick(o.platform_entry_offset_seconds),
                "platform_exit": None
                if o.platform_exit_offset_seconds is None
                else ddd_seconds_to_tick(o.platform_exit_offset_seconds),
                "usages": [
                    [
                        u.resource_id,
                        u.follower_enter_offset_tick,
                        u.leader_clear_offset_tick,
                        u.separation_after_tick(
                            movement.resources_by_id[u.resource_id].minimum_headway_tick
                        ),
                    ]
                    for u in o.resource_usages
                ],
            }
            for o in sorted(movement.route_options, key=lambda o: o.id)
        ],
        "tick_releases": [
            [g.id, ddd_seconds_to_tick(g.release_time_seconds)]
            for g in sorted(groups.values(), key=lambda g: g.id)
        ],
        "movement_core": asdict(movement.core),
        "starts": [
            asdict(s) for s in sorted(movement.starts, key=lambda s: s.cabin_id)
        ],
        "boundary": asdict(problem.boundary_context),
        "cabin_capacity": problem.artifact.config.cabin_capacity,
        "demand_groups": [
            asdict(g) for g in sorted(groups.values(), key=lambda g: g.id)
        ],
        "ride_candidates": [
            asdict(q)
            for q in sorted(problem.passenger_build.ride_candidates, key=lambda q: q.id)
        ],
        "operating_mode": problem.operating_mode.value,
        "start_policy": problem.start_policy.value,
        "objective": problem.objective.value,
        "objective_floor": problem.objective_floor,
    }


@dataclass(frozen=True)
class DddValidatedFixedKPlan:
    solution: DddReferenceSolution
    ride_counts: dict[str, int]
    unserved_counts: dict[str, int]
    objective_tick: int
    provenance: str

    @property
    def objective(self) -> float:
        return self.objective_tick / DDD_TIME_TICKS_PER_SECOND

    def to_payload(self) -> dict:
        return {
            "objective_tick": self.objective_tick,
            "objective": self.objective,
            "provenance": self.provenance,
            "ride_counts": self.ride_counts,
            "unserved_counts": self.unserved_counts,
            "trajectory_supports": [
                {
                    "cabin_id": t.cabin_id,
                    "route_option_ids": [v.route_option_id for v in t.visits],
                    "switch_times_tick": [
                        ddd_seconds_to_tick(v.switch_time_seconds) for v in t.visits
                    ],
                    "switch_times_seconds": [v.switch_time_seconds for v in t.visits],
                    "wait_seconds": [v.wait_seconds for v in t.visits],
                    "wait_ticks": [
                        ddd_seconds_to_tick(v.wait_seconds) for v in t.visits
                    ],
                }
                for t in self.solution.trajectories
            ],
        }


def _validate_fixed_k_plan(
    problem: DddFixedKTrajectoryProblem,
    solution: DddReferenceSolution,
    ride_counts: dict[str, int],
    *,
    provenance: str,
    expected_objective_tick: int | None = None,
) -> DddValidatedFixedKPlan:
    """Independent physical and integer assignment check; no CP expressions."""
    movement = problem.resolved_trajectory_problem.structural_movement_problem
    boundary = defaultdict(list)
    for occurrence in problem.boundary_context.resource_occurrences:
        boundary[occurrence.cabin_id].append(occurrence)
    # Boundary provenance comes from the problem, never from an imported solution.
    solution = DddReferenceSolution(
        tuple(
            DddReferenceTrajectory(
                t.cabin_id,
                t.visits,
                boundary_resource_occurrences=tuple(boundary[t.cabin_id]),
            )
            for t in sorted(solution.trajectories, key=lambda t: t.cabin_id)
        )
    )
    validate_ddd_reference_solution(
        movement,
        solution,
        tolerance_seconds=1e-9,
        waiting_policy=problem.resolved_trajectory_problem.waiting_policy,
    )
    protected = defaultdict(list)
    for trajectory in solution.trajectories:
        for occurrence in trajectory.resource_occurrences:
            resource = movement.resources_by_id[occurrence.resource_id]
            entry = max(0, ddd_seconds_to_tick(occurrence.follower_enter_time_seconds))
            end = ddd_seconds_to_tick(
                occurrence.leader_clear_time_seconds
            ) + occurrence.separation_after_tick(resource)
            if end > entry:
                protected[resource.id].append((entry, end))
    for intervals in protected.values():
        end = -1
        for entry, clear in sorted(intervals):
            if entry < end:
                raise ValueError("CP-SAT incumbent has an integer resource conflict")
            end = clear
    visits = {
        (v.cabin_id, v.visit_index): v for t in solution.trajectories for v in t.visits
    }
    options = {o.id: o for o in movement.route_options}
    groups = {g.id: g for g in problem.passenger_build.demand_groups}
    candidates = {q.id: q for q in problem.passenger_build.ride_candidates}
    capacity = problem.artifact.config.cabin_capacity
    horizon = movement.passenger_service_end_tick
    served, loads = defaultdict(int), defaultdict(int)
    # Recompute original served/unserved costs, not the aggregate CP formula.
    served_cost = 0
    for candidate_id, count in ride_counts.items():
        if candidate_id not in candidates or type(count) is not int or count <= 0:
            raise ValueError("CP-SAT incumbent has an invalid integer ride count")
        q = candidates[candidate_id]
        group = groups[q.demand_group_id]
        board = visits.get((q.cabin_id, q.board_visit_index))
        alight = visits.get((q.cabin_id, q.alight_visit_index))
        if (
            board is None
            or alight is None
            or board.decision is not DddRouteDecision.STOP
            or alight.decision is not DddRouteDecision.STOP
        ):
            raise ValueError("CP-SAT incumbent ride lacks an active STOP endpoint")
        board_option, alight_option = (
            options[board.route_option_id],
            options[alight.route_option_id],
        )
        board_tick = (
            ddd_seconds_to_tick(board.switch_time_seconds)
            + ddd_seconds_to_tick(board_option.platform_exit_offset_seconds)
            + ddd_seconds_to_tick(board.wait_seconds)
        )
        alight_tick = ddd_seconds_to_tick(
            alight.switch_time_seconds
        ) + ddd_seconds_to_tick(alight_option.platform_entry_offset_seconds)
        release = ddd_seconds_to_tick(group.release_time_seconds)
        if not 0 <= board_tick <= alight_tick <= horizon or board_tick < release:
            raise ValueError(
                "CP-SAT incumbent ride violates release or service horizon"
            )
        if (
            board_option.station_id != group.origin_station_id
            or alight_option.station_id != group.destination_station_id
        ):
            raise ValueError("CP-SAT incumbent ride has incorrect OD")
        served[group.id] += count
        served_cost += count * max(0, alight_tick - release)
        for visit in range(q.board_visit_index, q.alight_visit_index):
            loads[q.cabin_id, visit] += count
    if any(value > capacity for value in loads.values()):
        raise ValueError("CP-SAT incumbent exceeds cabin capacity")
    unserved = {g.id: g.count - served[g.id] for g in groups.values()}
    if any(value < 0 for value in unserved.values()):
        raise ValueError("CP-SAT incumbent exceeds demand")
    objective = served_cost + sum(
        unserved[g.id] * max(0, horizon - ddd_seconds_to_tick(g.release_time_seconds))
        for g in groups.values()
    )
    if expected_objective_tick is not None and expected_objective_tick != objective:
        raise ValueError("CP-SAT incumbent objective disagrees with independent costs")
    return DddValidatedFixedKPlan(
        solution, dict(ride_counts), unserved, objective, provenance
    )


@dataclass(frozen=True, slots=True)
class DddFixedKPrimalValidator:
    """Shared solver-free certificate for the current fixed-K tick domain."""

    def validate(
        self,
        problem: DddFixedKTrajectoryProblem,
        solution: DddReferenceSolution,
        ride_counts: dict[str, int],
        *,
        provenance: str,
        expected_objective_tick: int | None = None,
    ) -> DddValidatedFixedKPlan:
        return _validate_fixed_k_plan(
            problem,
            solution,
            ride_counts,
            provenance=provenance,
            expected_objective_tick=expected_objective_tick,
        )
