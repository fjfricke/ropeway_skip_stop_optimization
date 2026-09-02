from __future__ import annotations

from dataclasses import dataclass, replace

from ropeway_skip_stop_optimization.optimization.ddd.cp_sat_primal import (
    DddCpSatFixedCabinRoute,
    DddCpSatFixedRouteDecision,
    DddCpSatPrimalOracle,
    DddCpSatPrimalStatus,
)
from ropeway_skip_stop_optimization.optimization.ddd.network_time_space import (
    DddNetworkTimeProblem,
)
from ropeway_skip_stop_optimization.optimization.ddd.reference import (
    DddReferenceResourceOccurrence,
    DddReferenceTrajectory,
    ddd_reference_solution_from_recovered_schedules,
    validate_ddd_reference_solution,
)
from ropeway_skip_stop_optimization.optimization.ddd.time_refinement import (
    DddExactTimedEvent,
    DddRecoveredSchedule,
)
from ropeway_skip_stop_optimization.optimization.ddd.trajectory_passenger_lp import (
    DddTrajectoryPassengerLpResult,
)
from ropeway_skip_stop_optimization.optimization.ddd.trajectory_pricing import (
    build_ddd_trajectory_heuristic_pricing_signal,
)
from ropeway_skip_stop_optimization.optimization.ddd.trajectory_problem import (
    DddTrajectoryWaitingPolicy,
)
from ropeway_skip_stop_optimization.optimization.ean.artifact import EanBuildArtifact
from ropeway_skip_stop_optimization.optimization.ean.builders.passenger_builder import (
    EanPassengerCandidateBuildResult,
)
from ropeway_skip_stop_optimization.optimization.ean.passenger_objective import (
    EanPassengerObjective,
)


@dataclass(frozen=True)
class DddTrajectoryCoordinatedPrimalResult:
    """Complete conflict-free trajectory batches with no proof semantics."""

    status: DddCpSatPrimalStatus
    trajectory_batches: tuple[tuple[DddReferenceTrajectory, ...], ...]
    schedule_batches: tuple[tuple[DddRecoveredSchedule, ...], ...]
    wall_seconds: float
    preference_count: int
    objective_value: float | None
    objective_bound: float | None
    solver_status_name: str
    detail: str | None = None


@dataclass(frozen=True)
class DddTrajectoryCoordinatedPrimalGenerator:
    """Use CP-SAT to generate jointly feasible Passenger-guided columns.

    The CP objective is deliberately heuristic because it omits shared cabin
    loading. Every returned batch is nevertheless a complete physical
    schedule. Adding its columns to an exact restricted master is safe; the
    generator never contributes to the pricing certificate or global lower
    bound.
    """

    time_limit_seconds: float
    num_workers: int = 8
    max_candidate_count: int = 1
    minimum_hamming_distance: int = 1
    maximum_preference_count: int = 2_000

    def generate(
        self,
        *,
        problem: DddNetworkTimeProblem,
        artifact: EanBuildArtifact,
        passenger_build: EanPassengerCandidateBuildResult,
        objective: EanPassengerObjective,
        lp_result: DddTrajectoryPassengerLpResult,
        waiting_policy: DddTrajectoryWaitingPolicy,
        boundary_occurrences: tuple[DddReferenceResourceOccurrence, ...] = (),
        excluded_schedules: tuple[tuple[DddRecoveredSchedule, ...], ...] = (),
        hint_trajectories: tuple[DddReferenceTrajectory, ...] = (),
        fixed_trajectories: tuple[DddReferenceTrajectory, ...] = (),
        fixed_route_decisions: tuple[DddCpSatFixedRouteDecision, ...] = (),
        exclude_hint_schedule: bool = False,
    ) -> DddTrajectoryCoordinatedPrimalResult:
        if self.time_limit_seconds <= 0:
            raise ValueError("coordinated primal time limit must be positive")
        if self.num_workers <= 0:
            raise ValueError("coordinated primal worker count must be positive")
        if self.max_candidate_count <= 0:
            raise ValueError("coordinated primal candidate count must be positive")
        if self.maximum_preference_count <= 0:
            raise ValueError("coordinated primal preference limit must be positive")
        signal = build_ddd_trajectory_heuristic_pricing_signal(
            movement_problem=problem.movement_problem,
            artifact=artifact,
            passenger_build=passenger_build,
            objective=objective,
            lp_result=lp_result,
            maximum_preference_count=self.maximum_preference_count,
        )
        preferences = signal.preferences
        if fixed_trajectories and fixed_route_decisions:
            raise ValueError(
                "coordinated primal fixed trajectories and sparse route decisions "
                "are mutually exclusive"
            )
        fixed_routes = tuple(
            DddCpSatFixedCabinRoute(
                cabin_id=trajectory.cabin_id,
                route_option_ids=trajectory.support_signature,
            )
            for trajectory in sorted(
                fixed_trajectories, key=lambda item: item.cabin_id
            )
        )
        hint_schedules = ddd_recovered_schedules_from_reference_trajectories(
            problem,
            hint_trajectories,
        )
        effective_excluded_schedules = excluded_schedules
        if (
            exclude_hint_schedule
            and hint_schedules
            and hint_schedules not in effective_excluded_schedules
        ):
            effective_excluded_schedules = (
                *effective_excluded_schedules,
                hint_schedules,
            )
        raw = DddCpSatPrimalOracle(
            time_limit_seconds=self.time_limit_seconds,
            num_workers=self.num_workers,
            max_candidate_count=self.max_candidate_count,
            minimum_hamming_distance=self.minimum_hamming_distance,
        ).solve(
            problem,
            hint_schedules=hint_schedules,
            passenger_ride_preferences=preferences,
            fixed_cabin_routes=fixed_routes,
            fixed_route_decisions=fixed_route_decisions,
            excluded_schedules=effective_excluded_schedules,
            boundary_occurrences=boundary_occurrences,
        )
        trajectory_batches: list[tuple[DddReferenceTrajectory, ...]] = []
        schedule_batches = (
            raw.candidate_schedules
            if raw.candidate_schedules
            else ((raw.schedules,) if raw.schedules else ())
        )
        try:
            for schedules in schedule_batches:
                solution = ddd_reference_solution_from_recovered_schedules(
                    problem.movement_problem,
                    schedules,
                    waiting_policy=waiting_policy,
                )
                if boundary_occurrences:
                    occurrences_by_cabin: dict[
                        int, list[DddReferenceResourceOccurrence]
                    ] = {}
                    for occurrence in boundary_occurrences:
                        occurrences_by_cabin.setdefault(
                            occurrence.cabin_id, []
                        ).append(occurrence)
                    solution = replace(
                        solution,
                        trajectories=tuple(
                            replace(
                                trajectory,
                                boundary_resource_occurrences=tuple(
                                    occurrences_by_cabin.get(
                                        trajectory.cabin_id, ()
                                    )
                                ),
                            )
                            for trajectory in solution.trajectories
                        ),
                    )
                    validate_ddd_reference_solution(
                        problem.movement_problem,
                        solution,
                        waiting_policy=waiting_policy,
                    )
                trajectory_batches.append(solution.trajectories)
                _validate_fixed_routes_preserved(
                    fixed_trajectories=fixed_trajectories,
                    candidate_trajectories=solution.trajectories,
                )
                _validate_fixed_route_decisions_preserved(
                    fixed_route_decisions=fixed_route_decisions,
                    candidate_trajectories=solution.trajectories,
                )
        except ValueError as error:
            return DddTrajectoryCoordinatedPrimalResult(
                status=raw.status,
                trajectory_batches=(),
                schedule_batches=(),
                wall_seconds=raw.wall_seconds,
                preference_count=len(preferences),
                objective_value=raw.passenger_pricing_objective_value,
                objective_bound=raw.passenger_pricing_objective_bound,
                solver_status_name=raw.solver_status_name,
                detail=f"coordinated CP-SAT candidate failed validation: {error}",
            )
        return DddTrajectoryCoordinatedPrimalResult(
            status=raw.status,
            trajectory_batches=tuple(trajectory_batches),
            schedule_batches=schedule_batches,
            wall_seconds=raw.wall_seconds,
            preference_count=len(preferences),
            objective_value=raw.passenger_pricing_objective_value,
            objective_bound=raw.passenger_pricing_objective_bound,
            solver_status_name=raw.solver_status_name,
        )


def ddd_recovered_schedules_from_reference_trajectories(
    problem: DddNetworkTimeProblem,
    trajectories: tuple[DddReferenceTrajectory, ...],
) -> tuple[DddRecoveredSchedule, ...]:
    if not trajectories:
        return ()
    options_by_id = {
        option.id: option for option in problem.movement_problem.route_options
    }
    schedules = []
    for trajectory in sorted(trajectories, key=lambda item: item.cabin_id):
        if not trajectory.visits:
            raise ValueError("coordinated primal hint trajectory has no visits")
        last = trajectory.visits[-1]
        terminal_state_id = options_by_id[last.route_option_id].to_state_id
        events = (
            *(
                DddExactTimedEvent(
                    event_index=visit.visit_index,
                    state_id=visit.state_id,
                    time_seconds=visit.switch_time_seconds,
                )
                for visit in trajectory.visits
            ),
            DddExactTimedEvent(
                event_index=len(trajectory.visits),
                state_id=terminal_state_id,
                time_seconds=last.next_switch_time_seconds,
            ),
        )
        route_ids = trajectory.support_signature
        schedules.append(
            DddRecoveredSchedule(
                cabin_id=trajectory.cabin_id,
                route_option_ids=route_ids,
                events=events,
                objective_value=problem.objective.exact_value(
                    route_ids,
                    terminal_state_id,
                    last.next_switch_time_seconds,
                    tolerance_seconds=0.0,
                ),
            )
        )
    return tuple(schedules)


def _validate_fixed_routes_preserved(
    *,
    fixed_trajectories: tuple[DddReferenceTrajectory, ...],
    candidate_trajectories: tuple[DddReferenceTrajectory, ...],
) -> None:
    expected_by_cabin = {
        trajectory.cabin_id: trajectory.support_signature
        for trajectory in fixed_trajectories
    }
    actual_by_cabin = {
        trajectory.cabin_id: trajectory.support_signature
        for trajectory in candidate_trajectories
    }
    for cabin_id, expected in expected_by_cabin.items():
        if actual_by_cabin.get(cabin_id) != expected:
            raise ValueError(
                "coordinated CP-SAT neighborhood changed fixed cabin route: "
                f"cabin={cabin_id}"
            )


def _validate_fixed_route_decisions_preserved(
    *,
    fixed_route_decisions: tuple[DddCpSatFixedRouteDecision, ...],
    candidate_trajectories: tuple[DddReferenceTrajectory, ...],
) -> None:
    actual = {
        (trajectory.cabin_id, visit.visit_index): visit.route_option_id
        for trajectory in candidate_trajectories
        for visit in trajectory.visits
    }
    for fixed in fixed_route_decisions:
        if actual.get((fixed.cabin_id, fixed.visit_index)) != fixed.route_option_id:
            raise ValueError(
                "coordinated CP-SAT neighborhood changed fixed route decision: "
                f"cabin={fixed.cabin_id}, visit={fixed.visit_index}"
            )
