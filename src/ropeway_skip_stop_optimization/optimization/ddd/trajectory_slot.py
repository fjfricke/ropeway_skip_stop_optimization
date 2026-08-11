from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from time import perf_counter
from typing import Any

import gurobipy as gp
from gurobipy import GRB

from ropeway_skip_stop_optimization.optimization.ddd.network_time_space import (
    DddNetworkTimeProblem,
)
from ropeway_skip_stop_optimization.optimization.ddd.reference import (
    DddReferenceSolution,
    DddReferenceTrajectory,
    find_ddd_reference_conflicts,
    validate_ddd_reference_solution,
)
from ropeway_skip_stop_optimization.optimization.ddd.time_refinement import (
    DddRecoveredSchedule,
)
from ropeway_skip_stop_optimization.optimization.ddd.time_ticks import (
    ddd_seconds_to_tick,
)
from ropeway_skip_stop_optimization.optimization.ean.artifact import EanBuildArtifact
from ropeway_skip_stop_optimization.optimization.ean.builders.passenger_builder import (
    EanPassengerCandidateBuildResult,
)
from ropeway_skip_stop_optimization.optimization.ean.formulation_config import (
    EanHorizonFormulation,
)
from ropeway_skip_stop_optimization.optimization.ean.optimizers.fixed_movement_passenger_model import (
    EanFixedMovementRide,
    build_ean_fixed_movement_rides,
)
from ropeway_skip_stop_optimization.optimization.ean.passenger_objective import (
    EanPassengerObjective,
    ean_passenger_objective_definition,
)
from ropeway_skip_stop_optimization.optimization.ean.plan import (
    EanCabinTrajectory,
    EanMovementPlan,
)
from ropeway_skip_stop_optimization.optimization.ean.validation import (
    validate_ean_movement_plan_against_artifact,
)


class DddTrajectorySlotPoolStatus(StrEnum):
    FEASIBLE = "feasible"
    POOL_INFEASIBLE = "pool_infeasible"
    UNKNOWN = "unknown"
    INVALID_INTERNAL = "invalid_internal"


@dataclass(frozen=True)
class DddTrajectorySlotCandidate:
    schedules: tuple[DddRecoveredSchedule, ...]
    reference_solution: DddReferenceSolution
    movement_plan: EanMovementPlan

    def validate(self) -> None:
        self.movement_plan.validate()
        schedule_ids = {item.cabin_id for item in self.schedules}
        reference_ids = {item.cabin_id for item in self.reference_solution.trajectories}
        movement_ids = {item.cabin_id for item in self.movement_plan.trajectories}
        if schedule_ids != reference_ids or schedule_ids != movement_ids:
            raise ValueError("DDD trajectory-slot candidate cabin sets differ")


@dataclass(frozen=True)
class DddTrajectorySlotPoolResult:
    status: DddTrajectorySlotPoolStatus
    movement_plan: EanMovementPlan | None
    reference_solution: DddReferenceSolution | None
    schedules: tuple[DddRecoveredSchedule, ...]
    restricted_objective_value: float | None
    trajectory_option_count: int
    ride_variable_count: int
    selection_variable_count: int
    conflict_round_count: int
    incompatibility_constraint_count: int
    solve_seconds: float
    total_seconds: float
    detail: str | None = None


@dataclass(frozen=True)
class _TrajectoryOption:
    id: str
    cabin_id: int
    reference_trajectory: DddReferenceTrajectory
    ean_trajectory: EanCabinTrajectory
    schedule: DddRecoveredSchedule
    rides: tuple[EanFixedMovementRide, ...]


@dataclass(frozen=True)
class DddTrajectorySlotPoolOptimizer:
    """Recombine exact cabin trajectories without allowing passenger transfers.

    The finite trajectory pool is a primal proposal mechanism. Missing
    trajectories restrict the model, so neither its objective nor its
    infeasibility status is a global bound or infeasibility certificate.
    """

    time_limit_seconds: float = 30.0
    max_conflict_rounds: int = 100
    output_flag: bool = False
    tolerance_seconds: float = 1e-6

    def solve(
        self,
        *,
        problem: DddNetworkTimeProblem,
        artifact: EanBuildArtifact,
        passenger_build: EanPassengerCandidateBuildResult,
        objective: EanPassengerObjective,
        candidates: tuple[DddTrajectorySlotCandidate, ...],
    ) -> DddTrajectorySlotPoolResult:
        started = perf_counter()
        self._validate(problem, artifact, passenger_build, candidates)
        options = _build_trajectory_options(
            candidates=candidates,
            passenger_build=passenger_build,
            horizon_seconds=artifact.config.horizon_seconds,
        )
        options_by_cabin: dict[int, list[_TrajectoryOption]] = {}
        for option in options:
            options_by_cabin.setdefault(option.cabin_id, []).append(option)

        model = gp.Model("ddd_trajectory_slot_pool")
        model.Params.OutputFlag = int(self.output_flag)
        select = {
            option.id: model.addVar(vtype=GRB.BINARY, name=f"select[{index}]")
            for index, option in enumerate(options)
        }
        group_by_id = {group.id: group for group in passenger_build.demand_groups}
        rides_by_option_id = {option.id: option.rides for option in options}
        ride_count: dict[tuple[str, str], Any] = {}
        for option in options:
            for ride in option.rides:
                group = group_by_id[ride.candidate.demand_group_id]
                key = (option.id, ride.candidate.id)
                upper = min(group.count, artifact.config.cabin_capacity)
                variable = model.addVar(
                    lb=0.0,
                    ub=float(upper),
                    vtype=GRB.INTEGER,
                    name=f"ride[{len(ride_count)}]",
                )
                ride_count[key] = variable
                model.addConstr(
                    variable <= upper * select[option.id],
                    name=f"ride_activation[{len(ride_count) - 1}]",
                )

        for cabin_id, cabin_options in sorted(options_by_cabin.items()):
            model.addConstr(
                gp.quicksum(select[item.id] for item in cabin_options) == 1,
                name=f"choose_cabin[{cabin_id}]",
            )

        rides_by_group_id: dict[
            str, list[tuple[_TrajectoryOption, EanFixedMovementRide]]
        ] = {group.id: [] for group in passenger_build.demand_groups}
        for option in options:
            for ride in option.rides:
                rides_by_group_id[ride.candidate.demand_group_id].append((option, ride))
        for group_index, group in enumerate(passenger_build.demand_groups):
            model.addConstr(
                gp.quicksum(
                    ride_count[option.id, ride.candidate.id]
                    for option, ride in rides_by_group_id[group.id]
                )
                <= group.count,
                name=f"demand[{group_index}]",
            )

        for option_index, option in enumerate(options):
            for visit in option.ean_trajectory.visits:
                onboard = tuple(
                    ride_count[option.id, ride.candidate.id]
                    for ride in rides_by_option_id[option.id]
                    if (
                        ride.candidate.board_visit_index
                        <= visit.visit_index
                        < ride.candidate.alight_visit_index
                    )
                )
                if onboard:
                    model.addConstr(
                        gp.quicksum(onboard)
                        <= artifact.config.cabin_capacity * select[option.id],
                        name=f"capacity[{option_index},{visit.visit_index}]",
                    )

        definition = ean_passenger_objective_definition(objective)
        objective_constant = 0.0
        objective_terms = []
        for group in passenger_build.demand_groups:
            unserved_cost = definition.unserved_cost_seconds(
                release_time_seconds=group.release_time_seconds,
                horizon_seconds=artifact.config.horizon_seconds,
            )
            objective_constant += unserved_cost * group.count
            for option, ride in rides_by_group_id[group.id]:
                served_cost = definition.served_cost_seconds(
                    release_time_seconds=group.release_time_seconds,
                    boarding_time_seconds=ride.boarding_time_seconds,
                    alighting_time_seconds=ride.alighting_time_seconds,
                )
                objective_terms.append(
                    (served_cost - unserved_cost)
                    * ride_count[option.id, ride.candidate.id]
                )
        model.setObjective(
            objective_constant + gp.quicksum(objective_terms),
            GRB.MINIMIZE,
        )
        model.update()

        solve_seconds = 0.0
        incompatibility_pairs: set[tuple[str, str]] = set()
        conflict_round_count = 0
        for _ in range(self.max_conflict_rounds + 1):
            remaining = self.time_limit_seconds - (perf_counter() - started)
            if remaining <= 0:
                return self._result(
                    status=DddTrajectorySlotPoolStatus.UNKNOWN,
                    options=options,
                    ride_count=ride_count,
                    conflict_round_count=conflict_round_count,
                    incompatibility_pairs=incompatibility_pairs,
                    solve_seconds=solve_seconds,
                    started=started,
                    detail="trajectory-slot pool time budget exhausted",
                )
            model.Params.TimeLimit = remaining
            solve_started = perf_counter()
            model.optimize()
            solve_seconds += perf_counter() - solve_started
            if model.Status == GRB.INFEASIBLE:
                return self._result(
                    status=DddTrajectorySlotPoolStatus.POOL_INFEASIBLE,
                    options=options,
                    ride_count=ride_count,
                    conflict_round_count=conflict_round_count,
                    incompatibility_pairs=incompatibility_pairs,
                    solve_seconds=solve_seconds,
                    started=started,
                    detail="no compatible combination exists in the finite pool",
                )
            if model.SolCount <= 0:
                return self._result(
                    status=DddTrajectorySlotPoolStatus.UNKNOWN,
                    options=options,
                    ride_count=ride_count,
                    conflict_round_count=conflict_round_count,
                    incompatibility_pairs=incompatibility_pairs,
                    solve_seconds=solve_seconds,
                    started=started,
                    detail=f"trajectory-slot solver status {model.Status}",
                )
            selected = tuple(option for option in options if select[option.id].X >= 0.5)
            if len(selected) != len(options_by_cabin):
                return self._result(
                    status=DddTrajectorySlotPoolStatus.INVALID_INTERNAL,
                    options=options,
                    ride_count=ride_count,
                    conflict_round_count=conflict_round_count,
                    incompatibility_pairs=incompatibility_pairs,
                    solve_seconds=solve_seconds,
                    started=started,
                    detail="trajectory-slot selection does not choose one per cabin",
                )
            reference_solution = DddReferenceSolution(
                trajectories=tuple(
                    sorted(
                        (item.reference_trajectory for item in selected),
                        key=lambda item: item.cabin_id,
                    )
                )
            )
            occurrences = tuple(
                occurrence
                for trajectory in reference_solution.trajectories
                for occurrence in trajectory.resource_occurrences
            )
            conflicts = find_ddd_reference_conflicts(
                occurrences,
                problem.movement_problem,
                tolerance_seconds=self.tolerance_seconds,
            )
            if not conflicts:
                validate_ddd_reference_solution(
                    problem.movement_problem,
                    reference_solution,
                    tolerance_seconds=self.tolerance_seconds,
                )
                movement_plan = _combine_ean_trajectories(
                    artifact=artifact,
                    selected=selected,
                )
                validation = validate_ean_movement_plan_against_artifact(
                    artifact,
                    movement_plan,
                    tolerance_seconds=max(self.tolerance_seconds, 1e-5),
                )
                validation.raise_for_errors()
                return DddTrajectorySlotPoolResult(
                    status=DddTrajectorySlotPoolStatus.FEASIBLE,
                    movement_plan=movement_plan,
                    reference_solution=reference_solution,
                    schedules=tuple(
                        sorted(
                            (item.schedule for item in selected),
                            key=lambda item: item.cabin_id,
                        )
                    ),
                    restricted_objective_value=model.ObjVal,
                    trajectory_option_count=len(options),
                    ride_variable_count=len(ride_count),
                    selection_variable_count=len(select),
                    conflict_round_count=conflict_round_count,
                    incompatibility_constraint_count=len(incompatibility_pairs),
                    solve_seconds=solve_seconds,
                    total_seconds=perf_counter() - started,
                )

            selected_by_cabin_id = {item.cabin_id: item for item in selected}
            new_pairs: set[tuple[str, str]] = set()
            for conflict in conflicts:
                if conflict.first_cabin_id == conflict.second_cabin_id:
                    return self._result(
                        status=DddTrajectorySlotPoolStatus.INVALID_INTERNAL,
                        options=options,
                        ride_count=ride_count,
                        conflict_round_count=conflict_round_count,
                        incompatibility_pairs=incompatibility_pairs,
                        solve_seconds=solve_seconds,
                        started=started,
                        detail="pooled source trajectory contains a self-conflict",
                    )
                first = selected_by_cabin_id[conflict.first_cabin_id].id
                second = selected_by_cabin_id[conflict.second_cabin_id].id
                new_pairs.add(tuple(sorted((first, second))))
            new_pairs -= incompatibility_pairs
            if not new_pairs:
                return self._result(
                    status=DddTrajectorySlotPoolStatus.INVALID_INTERNAL,
                    options=options,
                    ride_count=ride_count,
                    conflict_round_count=conflict_round_count,
                    incompatibility_pairs=incompatibility_pairs,
                    solve_seconds=solve_seconds,
                    started=started,
                    detail="trajectory conflicts produced no new incompatibility",
                )
            if conflict_round_count >= self.max_conflict_rounds:
                return self._result(
                    status=DddTrajectorySlotPoolStatus.UNKNOWN,
                    options=options,
                    ride_count=ride_count,
                    conflict_round_count=conflict_round_count,
                    incompatibility_pairs=incompatibility_pairs,
                    solve_seconds=solve_seconds,
                    started=started,
                    detail="trajectory-slot conflict-round limit exhausted",
                )
            for first, second in sorted(new_pairs):
                model.addConstr(
                    select[first] + select[second] <= 1,
                    name=f"incompatible[{len(incompatibility_pairs)}]",
                )
                incompatibility_pairs.add((first, second))
            conflict_round_count += 1
            model.update()

        return self._result(
            status=DddTrajectorySlotPoolStatus.UNKNOWN,
            options=options,
            ride_count=ride_count,
            conflict_round_count=conflict_round_count,
            incompatibility_pairs=incompatibility_pairs,
            solve_seconds=solve_seconds,
            started=started,
            detail="trajectory-slot conflict-round limit exhausted",
        )

    def _validate(
        self,
        problem: DddNetworkTimeProblem,
        artifact: EanBuildArtifact,
        passenger_build: EanPassengerCandidateBuildResult,
        candidates: tuple[DddTrajectorySlotCandidate, ...],
    ) -> None:
        problem.validate()
        artifact.validate()
        passenger_build.validate()
        if self.time_limit_seconds <= 0 or self.max_conflict_rounds <= 0:
            raise ValueError("trajectory-slot pool budgets must be positive")
        if self.tolerance_seconds < 0:
            raise ValueError("trajectory-slot pool tolerance must be nonnegative")
        if not candidates:
            raise ValueError("trajectory-slot pool needs at least one candidate")
        if artifact.scenario_id != problem.movement_problem.scenario_id:
            raise ValueError("trajectory-slot problem and artifact differ")
        expected_cabin_ids = {
            start.cabin_id for start in problem.movement_problem.starts
        }
        for candidate in candidates:
            candidate.validate()
            if candidate.movement_plan.scenario_id != artifact.scenario_id:
                raise ValueError("trajectory-slot candidate scenario differs")
            if {
                item.cabin_id for item in candidate.reference_solution.trajectories
            } != expected_cabin_ids:
                raise ValueError("trajectory-slot candidate fixed starts differ")
            validate_ddd_reference_solution(
                problem.movement_problem,
                candidate.reference_solution,
                tolerance_seconds=self.tolerance_seconds,
            )
            validation = validate_ean_movement_plan_against_artifact(
                artifact,
                candidate.movement_plan,
                tolerance_seconds=max(self.tolerance_seconds, 1e-5),
            )
            validation.raise_for_errors()

    @staticmethod
    def _result(
        *,
        status: DddTrajectorySlotPoolStatus,
        options: tuple[_TrajectoryOption, ...],
        ride_count: dict[tuple[str, str], Any],
        conflict_round_count: int,
        incompatibility_pairs: set[tuple[str, str]],
        solve_seconds: float,
        started: float,
        detail: str,
    ) -> DddTrajectorySlotPoolResult:
        return DddTrajectorySlotPoolResult(
            status=status,
            movement_plan=None,
            reference_solution=None,
            schedules=(),
            restricted_objective_value=None,
            trajectory_option_count=len(options),
            ride_variable_count=len(ride_count),
            selection_variable_count=len(options),
            conflict_round_count=conflict_round_count,
            incompatibility_constraint_count=len(incompatibility_pairs),
            solve_seconds=solve_seconds,
            total_seconds=perf_counter() - started,
            detail=detail,
        )


def _build_trajectory_options(
    *,
    candidates: tuple[DddTrajectorySlotCandidate, ...],
    passenger_build: EanPassengerCandidateBuildResult,
    horizon_seconds: float,
) -> tuple[_TrajectoryOption, ...]:
    raw_by_cabin_id: dict[
        int,
        dict[
            tuple[tuple[str, int], ...],
            tuple[DddReferenceTrajectory, EanCabinTrajectory, DddRecoveredSchedule],
        ],
    ] = {}
    for candidate in candidates:
        reference_by_cabin_id = {
            item.cabin_id: item for item in candidate.reference_solution.trajectories
        }
        ean_by_cabin_id = {
            item.cabin_id: item for item in candidate.movement_plan.trajectories
        }
        schedule_by_cabin_id = {item.cabin_id: item for item in candidate.schedules}
        for cabin_id, reference in reference_by_cabin_id.items():
            signature = tuple(
                (
                    visit.route_option_id,
                    ddd_seconds_to_tick(visit.switch_time_seconds),
                )
                for visit in reference.visits
            )
            raw_by_cabin_id.setdefault(cabin_id, {}).setdefault(
                signature,
                (
                    reference,
                    ean_by_cabin_id[cabin_id],
                    schedule_by_cabin_id[cabin_id],
                ),
            )

    result: list[_TrajectoryOption] = []
    template = candidates[0].movement_plan
    for cabin_id, by_signature in sorted(raw_by_cabin_id.items()):
        for option_index, signature in enumerate(sorted(by_signature)):
            reference, ean_trajectory, schedule = by_signature[signature]
            one_trajectory_plan = EanMovementPlan(
                scenario_id=template.scenario_id,
                horizon_seconds=template.horizon_seconds,
                model_end_seconds=template.model_end_seconds,
                trajectories=(ean_trajectory,),
                horizon_formulation=template.horizon_formulation,
                fleet_mode=template.fleet_mode,
            )
            rides = build_ean_fixed_movement_rides(
                passenger_build=passenger_build,
                movement_plan=one_trajectory_plan,
                horizon_seconds=horizon_seconds,
            )
            result.append(
                _TrajectoryOption(
                    id=f"trajectory_slot::cabin_{cabin_id}::option_{option_index}",
                    cabin_id=cabin_id,
                    reference_trajectory=reference,
                    ean_trajectory=ean_trajectory,
                    schedule=schedule,
                    rides=rides,
                )
            )
    return tuple(result)


def _combine_ean_trajectories(
    *,
    artifact: EanBuildArtifact,
    selected: tuple[_TrajectoryOption, ...],
) -> EanMovementPlan:
    if not selected:
        raise ValueError("trajectory-slot selection must not be empty")
    plan = EanMovementPlan(
        scenario_id=artifact.scenario_id,
        horizon_seconds=artifact.config.horizon_seconds,
        model_end_seconds=artifact.config.model_end_seconds,
        trajectories=tuple(
            sorted(
                (item.ean_trajectory for item in selected),
                key=lambda item: item.cabin_id,
            )
        ),
        horizon_formulation=EanHorizonFormulation.EXACT_TIME_ACTIVATION,
        fleet_mode=artifact.fleet_mode,
    )
    plan.validate()
    return plan
