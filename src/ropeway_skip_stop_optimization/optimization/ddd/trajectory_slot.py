from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from hashlib import sha256
import json
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
from ropeway_skip_stop_optimization.optimization.ddd.trajectory_column_generation import (
    DddTrajectoryBoundStatus,
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
        schedule_id_values = tuple(item.cabin_id for item in self.schedules)
        reference_id_values = tuple(
            item.cabin_id for item in self.reference_solution.trajectories
        )
        movement_id_values = tuple(
            item.cabin_id for item in self.movement_plan.trajectories
        )
        schedule_ids = set(schedule_id_values)
        reference_ids = set(reference_id_values)
        movement_ids = set(movement_id_values)
        if (
            len(schedule_ids) != len(schedule_id_values)
            or len(reference_ids) != len(reference_id_values)
            or len(movement_ids) != len(movement_id_values)
        ):
            raise ValueError("DDD trajectory-slot candidate has duplicate cabin IDs")
        if schedule_ids != reference_ids or schedule_ids != movement_ids:
            raise ValueError("DDD trajectory-slot candidate cabin sets differ")


@dataclass(frozen=True)
class DddTrajectoryColumn:
    """Canonical whole-horizon cabin column retained across DDD rounds."""

    id: str
    cabin_id: int
    signature: tuple[tuple[object, ...], ...]
    reference_trajectory: DddReferenceTrajectory


class DddTrajectoryColumnPool:
    """Append-only, deterministic archive of validated trajectory candidates."""

    def __init__(self) -> None:
        self._columns_by_id: dict[str, DddTrajectoryColumn] = {}
        self._column_payload_by_id: dict[
            str,
            tuple[DddReferenceTrajectory, EanCabinTrajectory, DddRecoveredSchedule],
        ] = {}
        self._candidates_by_fingerprint: dict[str, DddTrajectorySlotCandidate] = {}
        self._validated_candidates_by_context: dict[
            tuple[int, int, float], set[str]
        ] = {}
        self._validated_artifact_contexts: set[tuple[int, int, float]] = set()
        self._validated_passenger_build_ids: set[int] = set()
        self._passenger_build_refs: dict[int, EanPassengerCandidateBuildResult] = {}
        self._option_cache: dict[tuple[int, float], dict[str, _TrajectoryOption]] = {}
        self._master_model_states: dict[
            tuple[object, ...], _TrajectoryMasterModelState
        ] = {}
        self._template_movement_plan: EanMovementPlan | None = None
        self._instance_fingerprint: str | None = None
        self._fingerprint: str | None = None
        self._column_count_by_cabin_id: dict[int, int] = {}

    @property
    def columns(self) -> tuple[DddTrajectoryColumn, ...]:
        return tuple(self._columns_by_id[key] for key in sorted(self._columns_by_id))

    @property
    def candidates(self) -> tuple[DddTrajectorySlotCandidate, ...]:
        return tuple(
            self._candidates_by_fingerprint[key]
            for key in sorted(self._candidates_by_fingerprint)
        )

    @property
    def column_count(self) -> int:
        return len(self._columns_by_id)

    @property
    def candidate_count(self) -> int:
        return len(self._candidates_by_fingerprint)

    @property
    def fingerprint(self) -> str:
        if self._fingerprint is None:
            self._fingerprint = sha256(
                "\n".join(sorted(self._columns_by_id)).encode()
            ).hexdigest()
        return self._fingerprint

    @property
    def has_recombination_choice(self) -> bool:
        return any(count > 1 for count in self._column_count_by_cabin_id.values())

    def add_candidate(self, candidate: DddTrajectorySlotCandidate) -> int:
        candidate.validate()
        instance_fingerprint = _movement_plan_instance_fingerprint(
            candidate.movement_plan
        )
        if self._instance_fingerprint is None:
            self._instance_fingerprint = instance_fingerprint
            self._template_movement_plan = candidate.movement_plan
        elif instance_fingerprint != self._instance_fingerprint:
            raise ValueError("trajectory column pool mixes different instances")
        reference_by_cabin_id = {
            item.cabin_id: item for item in candidate.reference_solution.trajectories
        }
        ean_by_cabin_id = {
            item.cabin_id: item for item in candidate.movement_plan.trajectories
        }
        schedule_by_cabin_id = {item.cabin_id: item for item in candidate.schedules}
        columns = tuple(
            ddd_trajectory_column(
                trajectory,
                instance_fingerprint=instance_fingerprint,
            )
            for trajectory in candidate.reference_solution.trajectories
        )
        fingerprint = sha256(
            "\n".join(sorted(item.id for item in columns)).encode()
        ).hexdigest()
        added = 0
        for column in columns:
            existing = self._columns_by_id.get(column.id)
            if existing is not None:
                payload = self._column_payload_by_id[column.id]
                candidate_payload = (
                    reference_by_cabin_id[column.cabin_id],
                    ean_by_cabin_id[column.cabin_id],
                    schedule_by_cabin_id[column.cabin_id],
                )
                if (
                    existing.signature != column.signature
                    or payload[0] != candidate_payload[0]
                    or payload[1] != candidate_payload[1]
                    or _recovered_schedule_physical_signature(payload[2])
                    != _recovered_schedule_physical_signature(candidate_payload[2])
                ):
                    raise RuntimeError(
                        "trajectory column identity maps to inconsistent payloads"
                    )
                continue
            self._columns_by_id[column.id] = column
            self._column_payload_by_id[column.id] = (
                reference_by_cabin_id[column.cabin_id],
                ean_by_cabin_id[column.cabin_id],
                schedule_by_cabin_id[column.cabin_id],
            )
            self._column_count_by_cabin_id[column.cabin_id] = (
                self._column_count_by_cabin_id.get(column.cabin_id, 0) + 1
            )
            added += 1
        if added:
            self._candidates_by_fingerprint[fingerprint] = candidate
            self._fingerprint = None
        return added

    def validate_against(
        self,
        *,
        problem: DddNetworkTimeProblem,
        artifact: EanBuildArtifact,
        tolerance_seconds: float,
    ) -> None:
        context = (id(problem.movement_problem), id(artifact), tolerance_seconds)
        if context not in self._validated_artifact_contexts:
            problem.validate()
            artifact.validate()
            if artifact.scenario_id != problem.movement_problem.scenario_id:
                raise ValueError("trajectory column problem and artifact differ")
            self._validated_artifact_contexts.add(context)
        validated = self._validated_candidates_by_context.setdefault(context, set())
        expected_cabin_ids = {
            start.cabin_id for start in problem.movement_problem.starts
        }
        for fingerprint, candidate in self._candidates_by_fingerprint.items():
            if fingerprint in validated:
                continue
            if candidate.movement_plan.scenario_id != artifact.scenario_id:
                raise ValueError("trajectory column candidate scenario differs")
            if {
                item.cabin_id for item in candidate.reference_solution.trajectories
            } != expected_cabin_ids:
                raise ValueError("trajectory column candidate fixed starts differ")
            validate_ddd_reference_solution(
                problem.movement_problem,
                candidate.reference_solution,
                tolerance_seconds=tolerance_seconds,
            )
            validation = validate_ean_movement_plan_against_artifact(
                artifact,
                candidate.movement_plan,
                tolerance_seconds=max(tolerance_seconds, 1e-5),
            )
            validation.raise_for_errors()
            validated.add(fingerprint)

    @property
    def template_movement_plan(self) -> EanMovementPlan:
        if self._template_movement_plan is None:
            raise ValueError("trajectory column pool is empty")
        return self._template_movement_plan

    def payload(
        self,
        column_id: str,
    ) -> tuple[DddReferenceTrajectory, EanCabinTrajectory, DddRecoveredSchedule]:
        return self._column_payload_by_id[column_id]

    def option_cache(
        self,
        *,
        passenger_build: EanPassengerCandidateBuildResult,
        horizon_seconds: float,
    ) -> dict[str, _TrajectoryOption]:
        return self._option_cache.setdefault(
            (id(passenger_build), horizon_seconds),
            {},
        )

    def validate_passenger_build(
        self,
        passenger_build: EanPassengerCandidateBuildResult,
    ) -> None:
        build_id = id(passenger_build)
        if build_id in self._validated_passenger_build_ids:
            return
        passenger_build.validate()
        self._validated_passenger_build_ids.add(build_id)
        self._passenger_build_refs[build_id] = passenger_build

    def master_model_state(
        self,
        context_key: tuple[object, ...],
    ) -> _TrajectoryMasterModelState | None:
        return self._master_model_states.get(context_key)

    def retain_master_model_state(
        self,
        state: _TrajectoryMasterModelState,
    ) -> None:
        self._master_model_states[state.context_key] = state


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
    bound_status: DddTrajectoryBoundStatus = DddTrajectoryBoundStatus.PRIMAL_POOL_ONLY
    certified_lower_bound: float | None = None
    incompatibility_pairs: tuple[tuple[str, str], ...] = ()


@dataclass(frozen=True)
class _TrajectoryOption:
    id: str
    cabin_id: int
    reference_trajectory: DddReferenceTrajectory
    ean_trajectory: EanCabinTrajectory
    schedule: DddRecoveredSchedule
    rides: tuple[EanFixedMovementRide, ...]


@dataclass
class _TrajectoryMasterModelState:
    context_key: tuple[object, ...]
    model: Any
    options_by_id: dict[str, _TrajectoryOption]
    select: dict[str, Any]
    ride_count: dict[tuple[str, str], Any]
    choose_by_cabin_id: dict[int, Any]
    demand_by_group_id: dict[str, Any]
    group_by_id: dict[str, Any]
    unserved_cost_by_group_id: dict[str, float]
    incompatibility_pairs: set[tuple[str, str]]


def _trajectory_master_context_key(
    *,
    artifact: EanBuildArtifact,
    passenger_build: EanPassengerCandidateBuildResult,
    objective: EanPassengerObjective,
) -> tuple[object, ...]:
    return (
        id(artifact),
        id(passenger_build),
        objective,
        artifact.config.cabin_capacity,
        artifact.config.horizon_seconds,
    )


def _prepare_trajectory_master_model(
    *,
    state: _TrajectoryMasterModelState | None,
    options: tuple[_TrajectoryOption, ...],
    artifact: EanBuildArtifact,
    passenger_build: EanPassengerCandidateBuildResult,
    objective: EanPassengerObjective,
    output_flag: bool,
) -> _TrajectoryMasterModelState:
    context_key = _trajectory_master_context_key(
        artifact=artifact,
        passenger_build=passenger_build,
        objective=objective,
    )
    if state is not None and state.context_key != context_key:
        raise ValueError("trajectory restricted master context changed")
    if state is None:
        model = gp.Model("ddd_trajectory_restricted_master")
        model.Params.OutputFlag = int(output_flag)
        definition = ean_passenger_objective_definition(objective)
        group_by_id = {group.id: group for group in passenger_build.demand_groups}
        unserved_cost_by_group_id = {
            group.id: definition.unserved_cost_seconds(
                release_time_seconds=group.release_time_seconds,
                horizon_seconds=artifact.config.horizon_seconds,
            )
            for group in passenger_build.demand_groups
        }
        model.ModelSense = GRB.MINIMIZE
        model.ObjCon = sum(
            unserved_cost_by_group_id[group.id] * group.count
            for group in passenger_build.demand_groups
        )
        demand_by_group_id = {
            group.id: model.addConstr(
                gp.LinExpr() <= group.count,
                name=f"demand[{index}]",
            )
            for index, group in enumerate(passenger_build.demand_groups)
        }
        state = _TrajectoryMasterModelState(
            context_key=context_key,
            model=model,
            options_by_id={},
            select={},
            ride_count={},
            choose_by_cabin_id={},
            demand_by_group_id=demand_by_group_id,
            group_by_id=group_by_id,
            unserved_cost_by_group_id=unserved_cost_by_group_id,
            incompatibility_pairs=set(),
        )

    definition = ean_passenger_objective_definition(objective)
    for option in options:
        if option.id in state.options_by_id:
            continue
        if option.cabin_id not in state.choose_by_cabin_id:
            state.choose_by_cabin_id[option.cabin_id] = state.model.addConstr(
                gp.LinExpr() == 1,
                name=f"choose_cabin[{option.cabin_id}]",
            )
        select = state.model.addVar(
            vtype=GRB.BINARY,
            name=f"select[{len(state.select)}]",
        )
        state.select[option.id] = select
        state.model.chgCoeff(state.choose_by_cabin_id[option.cabin_id], select, 1.0)
        for ride in option.rides:
            group = state.group_by_id[ride.candidate.demand_group_id]
            upper = min(group.count, artifact.config.cabin_capacity)
            unserved_cost = state.unserved_cost_by_group_id[group.id]
            served_cost = definition.served_cost_seconds(
                release_time_seconds=group.release_time_seconds,
                boarding_time_seconds=ride.boarding_time_seconds,
                alighting_time_seconds=ride.alighting_time_seconds,
            )
            key = (option.id, ride.candidate.id)
            variable = state.model.addVar(
                lb=0.0,
                ub=float(upper),
                obj=served_cost - unserved_cost,
                vtype=GRB.INTEGER,
                name=f"ride[{len(state.ride_count)}]",
            )
            state.ride_count[key] = variable
            state.model.addConstr(
                variable <= upper * select,
                name=f"ride_activation[{len(state.ride_count) - 1}]",
            )
            state.model.chgCoeff(
                state.demand_by_group_id[group.id],
                variable,
                1.0,
            )
        for visit in option.ean_trajectory.visits:
            onboard = tuple(
                state.ride_count[option.id, ride.candidate.id]
                for ride in option.rides
                if (
                    ride.candidate.board_visit_index
                    <= visit.visit_index
                    < ride.candidate.alight_visit_index
                )
            )
            if onboard:
                state.model.addConstr(
                    gp.quicksum(onboard) <= artifact.config.cabin_capacity * select,
                    name=f"capacity[{len(state.options_by_id)},{visit.visit_index}]",
                )
        state.options_by_id[option.id] = option
    state.model.update()
    return state


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
        column_pool = DddTrajectoryColumnPool()
        for candidate in candidates:
            column_pool.add_candidate(candidate)
        return self.solve_pool(
            problem=problem,
            artifact=artifact,
            passenger_build=passenger_build,
            objective=objective,
            column_pool=column_pool,
        )

    def solve_pool(
        self,
        *,
        problem: DddNetworkTimeProblem,
        artifact: EanBuildArtifact,
        passenger_build: EanPassengerCandidateBuildResult,
        objective: EanPassengerObjective,
        column_pool: DddTrajectoryColumnPool,
    ) -> DddTrajectorySlotPoolResult:
        started = perf_counter()
        self._validate(problem, artifact, passenger_build, column_pool)
        options = _build_trajectory_options(
            column_pool=column_pool,
            passenger_build=passenger_build,
            horizon_seconds=artifact.config.horizon_seconds,
        )
        context_key = _trajectory_master_context_key(
            artifact=artifact,
            passenger_build=passenger_build,
            objective=objective,
        )
        state = _prepare_trajectory_master_model(
            state=column_pool.master_model_state(context_key),
            options=options,
            artifact=artifact,
            passenger_build=passenger_build,
            objective=objective,
            output_flag=self.output_flag,
        )
        column_pool.retain_master_model_state(state)
        model = state.model
        select = state.select
        ride_count = state.ride_count

        solve_seconds = 0.0
        incompatibility_pairs = state.incompatibility_pairs
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
            if len(selected) != len(state.choose_by_cabin_id):
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
                    incompatibility_pairs=tuple(sorted(incompatibility_pairs)),
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
        column_pool: DddTrajectoryColumnPool,
    ) -> None:
        column_pool.validate_passenger_build(passenger_build)
        if self.time_limit_seconds <= 0 or self.max_conflict_rounds <= 0:
            raise ValueError("trajectory-slot pool budgets must be positive")
        if self.tolerance_seconds < 0:
            raise ValueError("trajectory-slot pool tolerance must be nonnegative")
        if not column_pool.columns:
            raise ValueError("trajectory-slot pool needs at least one candidate")
        column_pool.validate_against(
            problem=problem,
            artifact=artifact,
            tolerance_seconds=self.tolerance_seconds,
        )

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
            incompatibility_pairs=tuple(sorted(incompatibility_pairs)),
        )


@dataclass
class DddTrajectoryRestrictedMaster:
    """Phase-1 trajectory master backed by a persistent canonical column pool.

    This remains a primal restricted master.  The wrapper intentionally
    returns ``PRIMAL_POOL_ONLY`` until a future exact pricing oracle supplies a
    :class:`DddTrajectoryPricingCertificate`.
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
        column_pool: DddTrajectoryColumnPool,
    ) -> DddTrajectorySlotPoolResult:
        if not column_pool.candidates:
            raise ValueError("trajectory restricted master needs generated columns")
        result = DddTrajectorySlotPoolOptimizer(
            time_limit_seconds=self.time_limit_seconds,
            max_conflict_rounds=self.max_conflict_rounds,
            output_flag=self.output_flag,
            tolerance_seconds=self.tolerance_seconds,
        ).solve_pool(
            problem=problem,
            artifact=artifact,
            passenger_build=passenger_build,
            objective=objective,
            column_pool=column_pool,
        )
        if (
            result.bound_status is not DddTrajectoryBoundStatus.PRIMAL_POOL_ONLY
            or result.certified_lower_bound is not None
        ):
            raise RuntimeError("restricted trajectory master claimed a global bound")
        return result


def _build_trajectory_options(
    *,
    column_pool: DddTrajectoryColumnPool,
    passenger_build: EanPassengerCandidateBuildResult,
    horizon_seconds: float,
) -> tuple[_TrajectoryOption, ...]:
    cache = column_pool.option_cache(
        passenger_build=passenger_build,
        horizon_seconds=horizon_seconds,
    )
    template = column_pool.template_movement_plan
    for column in column_pool.columns:
        if column.id in cache:
            continue
        reference, ean_trajectory, schedule = column_pool.payload(column.id)
        one_trajectory_plan = EanMovementPlan(
            scenario_id=template.scenario_id,
            horizon_seconds=template.horizon_seconds,
            model_end_seconds=template.model_end_seconds,
            trajectories=(ean_trajectory,),
            horizon_formulation=template.horizon_formulation,
            fleet_mode=template.fleet_mode,
        )
        cache[column.id] = _TrajectoryOption(
            id=column.id,
            cabin_id=column.cabin_id,
            reference_trajectory=reference,
            ean_trajectory=ean_trajectory,
            schedule=schedule,
            rides=build_ean_fixed_movement_rides(
                passenger_build=passenger_build,
                movement_plan=one_trajectory_plan,
                horizon_seconds=horizon_seconds,
            ),
        )
    return tuple(cache[key] for key in sorted(cache))


def ddd_trajectory_column_signature(
    trajectory: DddReferenceTrajectory,
) -> tuple[tuple[object, ...], ...]:
    """Return the complete integer-tick signature of one physical trajectory."""

    return tuple(
        (
            visit.visit_index,
            visit.state_id,
            visit.route_option_id,
            visit.decision.value,
            ddd_seconds_to_tick(visit.switch_time_seconds),
            ddd_seconds_to_tick(visit.next_switch_time_seconds),
            tuple(
                sorted(
                    (
                        occurrence.resource_id,
                        occurrence.cabin_id,
                        occurrence.visit_index,
                        ddd_seconds_to_tick(occurrence.leader_clear_time_seconds),
                        ddd_seconds_to_tick(occurrence.follower_enter_time_seconds),
                    )
                    for occurrence in visit.resource_occurrences
                )
            ),
        )
        for visit in trajectory.visits
    )


def ddd_trajectory_column(
    trajectory: DddReferenceTrajectory,
    *,
    instance_fingerprint: str = "standalone",
) -> DddTrajectoryColumn:
    signature = ddd_trajectory_column_signature(trajectory)
    payload = json.dumps(
        {
            "instance_fingerprint": instance_fingerprint,
            "cabin_id": trajectory.cabin_id,
            "signature": signature,
        },
        separators=(",", ":"),
        sort_keys=True,
    )
    digest = sha256(payload.encode()).hexdigest()
    return DddTrajectoryColumn(
        id=f"ddd_trajectory::{digest}",
        cabin_id=trajectory.cabin_id,
        signature=signature,
        reference_trajectory=trajectory,
    )


def _movement_plan_instance_fingerprint(plan: EanMovementPlan) -> str:
    payload = json.dumps(
        {
            "scenario_id": plan.scenario_id,
            "horizon_seconds": plan.horizon_seconds,
            "model_end_seconds": plan.model_end_seconds,
            "horizon_formulation": plan.horizon_formulation.value,
            "fleet_mode": plan.fleet_mode.value,
            "cabin_ids": sorted(item.cabin_id for item in plan.trajectories),
        },
        separators=(",", ":"),
        sort_keys=True,
    )
    return sha256(payload.encode()).hexdigest()


def _recovered_schedule_physical_signature(
    schedule: DddRecoveredSchedule,
) -> tuple[object, ...]:
    return (
        schedule.cabin_id,
        schedule.route_option_ids,
        schedule.events,
    )


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
