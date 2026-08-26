from __future__ import annotations

from dataclasses import dataclass
import math
from time import perf_counter

from ortools.sat.python import cp_model

from ropeway_skip_stop_optimization.optimization.ddd.models import DddRouteDecision
from ropeway_skip_stop_optimization.optimization.ddd.reference import (
    DddReferenceTrajectory,
    find_ddd_reference_conflicts,
)
from ropeway_skip_stop_optimization.optimization.ddd.trajectory_oip import (
    DddOipTrajectoryStart,
    build_ddd_oip_reference_trajectory,
    build_ean_oip_plan_and_fleet,
)
from ropeway_skip_stop_optimization.optimization.ddd.trajectory_problem import (
    DddOptimizedInitialPlacementDomain,
    DddTrajectoryProblem,
)
from ropeway_skip_stop_optimization.optimization.ean.artifact import EanBuildArtifact
from ropeway_skip_stop_optimization.optimization.ean.fleet import (
    EanInitialPlacementStateKind,
)
from ropeway_skip_stop_optimization.optimization.ean.periodic_route import (
    EanPeriodicRouteCapacityBoundBuilder,
)
from ropeway_skip_stop_optimization.optimization.ean.primal_seed import EanPrimalSeed
from ropeway_skip_stop_optimization.optimization.ean.validation import (
    validate_ean_initial_boundary_against_artifact,
    validate_ean_movement_plan_against_artifact,
)


@dataclass(frozen=True, slots=True)
class DddBalancedReferenceStartResult:
    seed: EanPrimalSeed
    trajectories: tuple[DddReferenceTrajectory, ...]
    candidate_count: int
    incompatibility_pair_count: int
    selected_stop_count: int
    served_station_count: int
    minimum_station_stop_count: int
    maximum_station_service_gap_seconds: float | None
    solve_seconds: float
    solver_status_name: str
    objective_proven: bool


@dataclass(frozen=True, slots=True)
class DddBalancedReferenceStartBuilder:
    """Select a compatible, service-rich exact-K boundary snapshot.

    Candidate trajectories come from certified homogeneous periodic routes, but
    CP-SAT may mix their phases and route templates. The selected reference is
    used only up to the fixed boundary; the passenger MILP remains unrestricted
    after that boundary.
    """

    time_limit_seconds: float = 120.0

    def build(
        self,
        *,
        problem: DddTrajectoryProblem,
        artifact: EanBuildArtifact,
    ) -> DddBalancedReferenceStartResult:
        problem.validate()
        artifact.validate()
        if not isinstance(problem.start_domain, DddOptimizedInitialPlacementDomain):
            raise ValueError("balanced reference starts require exact-K OIP")
        if self.time_limit_seconds <= 0:
            raise ValueError("balanced reference solver controls are invalid")
        started = perf_counter()
        cabin_count = len(problem.cabin_ids)
        candidates = self._candidates(problem=problem, artifact=artifact)
        if len(candidates) < cabin_count:
            raise ValueError("balanced reference has fewer candidates than cabins")

        movement = problem.structural_movement_problem
        incompatible: list[tuple[int, int]] = []
        for first_index, first in enumerate(candidates):
            if perf_counter() - started >= self.time_limit_seconds:
                raise TimeoutError(
                    "balanced reference budget expired during conflict indexing"
                )
            for second_index in range(first_index + 1, len(candidates)):
                second = candidates[second_index]
                if find_ddd_reference_conflicts(
                    (*first.resource_occurrences, *second.resource_occurrences),
                    movement,
                ):
                    incompatible.append((first_index, second_index))

        station_ids = tuple(
            sorted({option.station_id for option in problem.movement_core.route_options})
        )
        station_by_option_id = {
            option.id: option.station_id
            for option in problem.movement_core.route_options
        }
        stop_counts = tuple(
            {
                station_id: sum(
                    visit.decision is DddRouteDecision.STOP
                    and station_by_option_id[visit.route_option_id] == station_id
                    for visit in candidate.visits
                )
                for station_id in station_ids
            }
            for candidate in candidates
        )
        model = cp_model.CpModel()
        selected = [
            model.new_bool_var(f"candidate[{index}]")
            for index in range(len(candidates))
        ]
        model.add(sum(selected) == cabin_count)
        for first_index, second_index in incompatible:
            model.add(selected[first_index] + selected[second_index] <= 1)
        maximum_visits = max(len(candidate.visits) for candidate in candidates)
        minimum_stops = model.new_int_var(
            0,
            cabin_count * maximum_visits,
            "minimum_station_stop_count",
        )
        for station_id in station_ids:
            model.add(
                minimum_stops
                <= sum(
                    stop_counts[index][station_id] * selected[index]
                    for index in range(len(candidates))
                )
            )
        total_stops = sum(
            sum(stop_counts[index].values()) * selected[index]
            for index in range(len(candidates))
        )
        tie_break = sum(
            (index + 1) * selected[index] for index in range(len(candidates))
        )
        maximum_total_stops = cabin_count * maximum_visits
        maximum_tie = cabin_count * len(candidates)
        total_weight = maximum_tie + 1
        minimum_weight = (maximum_total_stops + 1) * total_weight
        model.maximize(
            minimum_stops * minimum_weight
            + total_stops * total_weight
            - tie_break
        )

        solver = cp_model.CpSolver()
        remaining_seconds = self.time_limit_seconds - (perf_counter() - started)
        if remaining_seconds <= 0:
            raise TimeoutError("balanced reference budget expired before CP-SAT")
        solver.parameters.max_time_in_seconds = remaining_seconds
        # A single worker makes the physical start snapshot reproducible.  The
        # start layout enters the problem fingerprint, so parallel CP-SAT race
        # order must not silently change the experiment instance.
        solver.parameters.num_search_workers = 1
        solver.parameters.random_seed = 0
        status = solver.solve(model)
        if status not in (cp_model.FEASIBLE, cp_model.OPTIMAL):
            raise ValueError(
                "balanced reference CP-SAT found no compatible exact-K snapshot: "
                f"{solver.status_name(status)}"
            )
        selected_candidates = tuple(
            candidates[index]
            for index, variable in enumerate(selected)
            if solver.value(variable)
        )
        if len(selected_candidates) != cabin_count:
            raise RuntimeError("balanced reference CP-SAT returned the wrong cardinality")
        trajectories = self._canonicalize(
            problem=problem,
            artifact=artifact,
            candidates=selected_candidates,
        )
        if find_ddd_reference_conflicts(
            tuple(
                occurrence
                for trajectory in trajectories
                for occurrence in trajectory.resource_occurrences
            ),
            movement,
        ):
            raise RuntimeError("balanced reference reconstruction introduced a conflict")
        movement_plan, fleet_plan = build_ean_oip_plan_and_fleet(
            problem=problem,
            artifact=artifact,
            trajectories=trajectories,
        )
        validate_ean_movement_plan_against_artifact(
            artifact,
            movement_plan,
        ).raise_for_errors()
        validate_ean_initial_boundary_against_artifact(
            artifact,
            movement_plan,
            fleet_plan,
        ).raise_for_errors()
        selected_stop_counts = {
            station_id: sum(
                visit.decision is DddRouteDecision.STOP
                and station_by_option_id[visit.route_option_id] == station_id
                for trajectory in trajectories
                for visit in trajectory.visits
            )
            for station_id in station_ids
        }
        return DddBalancedReferenceStartResult(
            seed=EanPrimalSeed(fleet_plan=fleet_plan, movement_plan=movement_plan),
            trajectories=trajectories,
            candidate_count=len(candidates),
            incompatibility_pair_count=len(incompatible),
            selected_stop_count=sum(selected_stop_counts.values()),
            served_station_count=sum(
                count > 0 for count in selected_stop_counts.values()
            ),
            minimum_station_stop_count=min(selected_stop_counts.values()),
            maximum_station_service_gap_seconds=_maximum_service_gap(
                problem,
                trajectories,
                station_ids,
            ),
            solve_seconds=perf_counter() - started,
            solver_status_name=solver.status_name(status),
            objective_proven=status == cp_model.OPTIMAL,
        )

    @staticmethod
    def _candidates(
        *,
        problem: DddTrajectoryProblem,
        artifact: EanBuildArtifact,
    ) -> tuple[DddReferenceTrajectory, ...]:
        domain = problem.start_domain
        assert isinstance(domain, DddOptimizedInitialPlacementDomain)
        result: dict[tuple[object, ...], DddReferenceTrajectory] = {}
        option_by_state_and_decision = {
            (option.from_state_id, option.decision): option
            for option in problem.movement_core.route_options
        }
        phase_count = len(domain.phase_state_ids)
        for bound in EanPeriodicRouteCapacityBoundBuilder().build_candidates(artifact):
            options = tuple(
                option_by_state_and_decision[
                    (
                        leg.switch_id,
                        (
                            DddRouteDecision.STOP
                            if leg.decision.value == "stop"
                            else DddRouteDecision.SKIP
                        ),
                    )
                ]
                for leg in bound.legs
            )
            boundaries = [0.0]
            for option in options:
                boundaries.append(boundaries[-1] + option.duration_seconds)
            spacing = bound.cycle_seconds / bound.fleet_lower_bound
            for slot in range(bound.fleet_lower_bound):
                phase_seconds = slot * spacing
                position = next(
                    index
                    for index, upper in enumerate(boundaries[1:])
                    if phase_seconds < upper - 1e-9
                    or math.isclose(phase_seconds, boundaries[index], abs_tol=1e-9)
                )
                offset = phase_seconds - boundaries[position]
                current_option = options[position]
                if offset <= 1e-9:
                    start = DddOipTrajectoryStart(
                        phase_index=position,
                        station_start=True,
                        first_switch_time_seconds=0.0,
                    )
                    first_position = position
                elif offset <= current_option.exit_switch_offset_seconds + 1e-9:
                    start = DddOipTrajectoryStart(
                        phase_index=position,
                        station_start=True,
                        first_switch_time_seconds=-offset,
                    )
                    first_position = position
                else:
                    next_position = (position + 1) % phase_count
                    start = DddOipTrajectoryStart(
                        phase_index=next_position,
                        station_start=False,
                        first_switch_time_seconds=(
                            current_option.duration_seconds - offset
                        ),
                        previous_service=(
                            current_option.decision is DddRouteDecision.STOP
                        ),
                    )
                    first_position = next_position
                route_option_ids = tuple(
                    options[(first_position + index) % phase_count].id
                    for index in range(
                        domain.maximum_visit_count - start.phase_index
                    )
                )
                trajectory = build_ddd_oip_reference_trajectory(
                    problem=problem,
                    artifact=artifact,
                    cabin_id=0,
                    start=start,
                    route_option_ids=route_option_ids,
                )
                state = trajectory.initial_state
                assert state is not None
                signature = (
                    state.kind.value,
                    state.switch_id,
                    state.visit_index,
                    round(state.previous_event_time_seconds, 6),
                    round(state.next_event_time_seconds, 6),
                    state.previous_service,
                    trajectory.timed_support_signature,
                )
                result.setdefault(signature, trajectory)
        return tuple(result[key] for key in sorted(result, key=repr))

    @staticmethod
    def _canonicalize(
        *,
        problem: DddTrajectoryProblem,
        artifact: EanBuildArtifact,
        candidates: tuple[DddReferenceTrajectory, ...],
    ) -> tuple[DddReferenceTrajectory, ...]:
        ordered = sorted(candidates, key=_initial_state_key)
        result = []
        for cabin_id, source in enumerate(ordered):
            state = source.initial_state
            assert state is not None and source.visits
            result.append(
                build_ddd_oip_reference_trajectory(
                    problem=problem,
                    artifact=artifact,
                    cabin_id=cabin_id,
                    start=DddOipTrajectoryStart(
                        phase_index=state.visit_index,
                        station_start=(
                            state.kind is not EanInitialPlacementStateKind.ROPE
                        ),
                        first_switch_time_seconds=(
                            source.visits[0].switch_time_seconds
                        ),
                        previous_service=state.previous_service,
                    ),
                    route_option_ids=source.support_signature,
                )
            )
        return tuple(result)


def _initial_state_key(trajectory: DddReferenceTrajectory) -> tuple[object, ...]:
    state = trajectory.initial_state
    if state is None:
        raise ValueError("balanced reference candidate has no initial state")
    kind_rank = {
        EanInitialPlacementStateKind.ENTRY_SWITCH: 0,
        EanInitialPlacementStateKind.SERVICE_ROUTE: 1,
        EanInitialPlacementStateKind.SKIP_ROUTE: 2,
        EanInitialPlacementStateKind.PLATFORM_WAIT: 3,
        EanInitialPlacementStateKind.EXIT_SWITCH: 4,
        EanInitialPlacementStateKind.ROPE: 5,
    }
    return (
        state.visit_index,
        kind_rank[state.kind],
        state.previous_event_time_seconds,
        state.next_event_time_seconds,
        trajectory.support_signature,
    )


def _maximum_service_gap(
    problem: DddTrajectoryProblem,
    trajectories: tuple[DddReferenceTrajectory, ...],
    station_ids: tuple[str, ...],
) -> float | None:
    station_by_option = {
        option.id: option.station_id for option in problem.movement_core.route_options
    }
    horizon = problem.movement_core.operational_end_seconds
    maximum = 0.0
    for station_id in station_ids:
        times = sorted(
            visit.switch_time_seconds
            for trajectory in trajectories
            for visit in trajectory.visits
            if visit.decision is DddRouteDecision.STOP
            and station_by_option[visit.route_option_id] == station_id
            and 0 <= visit.switch_time_seconds <= horizon
        )
        if not times:
            return None
        boundaries = (0.0, *times, horizon)
        maximum = max(
            maximum,
            max(second - first for first, second in zip(boundaries, boundaries[1:])),
        )
    if not math.isfinite(maximum):
        raise RuntimeError("balanced reference service gap is not finite")
    return maximum
