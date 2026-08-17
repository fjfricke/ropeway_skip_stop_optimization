from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
import json
from time import perf_counter

from ropeway_skip_stop_optimization.optimization.ddd.ean_plan_adapter import (
    DddReferenceToEanMovementPlanAdapter,
)
from ropeway_skip_stop_optimization.optimization.ddd.network_time_space import (
    DddNetworkTimeProblem,
)
from ropeway_skip_stop_optimization.optimization.ddd.reference import (
    DddReferenceTrajectory,
    DddReferenceTrajectoryGenerator,
    find_ddd_reference_conflicts,
)
from ropeway_skip_stop_optimization.optimization.ddd.trajectory_column_generation import (
    DddTrajectoryWaitingDomain,
)
from ropeway_skip_stop_optimization.optimization.ddd.trajectory_passenger_lp import (
    DddTrajectoryPassengerMasterProblem,
    DddTrajectoryPassengerOption,
    DddTrajectoryPassengerRide,
)
from ropeway_skip_stop_optimization.optimization.ddd.trajectory_resource_windows import (
    DddTrajectoryResourceWindow,
    build_ddd_trajectory_resource_window_rows,
)
from ropeway_skip_stop_optimization.optimization.ddd.trajectory_slot import (
    ddd_trajectory_column,
)
from ropeway_skip_stop_optimization.optimization.ean.artifact import EanBuildArtifact
from ropeway_skip_stop_optimization.optimization.ean.builders.passenger_builder import (
    EanPassengerCandidateBuildResult,
)
from ropeway_skip_stop_optimization.optimization.ean.formulation_config import (
    EanHorizonFormulation,
)
from ropeway_skip_stop_optimization.optimization.ean.models import (
    EanFleetMode,
    StationWaitingMode,
)
from ropeway_skip_stop_optimization.optimization.ean.optimizers.fixed_movement_passenger_model import (
    build_ean_fixed_movement_rides,
)
from ropeway_skip_stop_optimization.optimization.ean.passenger_objective import (
    EanPassengerObjective,
    ean_passenger_objective_definition,
)
from ropeway_skip_stop_optimization.optimization.ean.plan import EanMovementPlan


class DddExhaustiveTrajectoryLimitError(RuntimeError):
    pass


@dataclass(frozen=True)
class DddExhaustiveTrajectoryMasterBuildResult:
    master_problem: DddTrajectoryPassengerMasterProblem
    reference_trajectory_by_option_id: dict[str, DddReferenceTrajectory]
    trajectory_count_by_cabin_id: dict[int, int]
    generation_branch_count: int
    self_conflict_pruned_count: int
    incompatibility_pair_check_count: int
    generation_seconds: float
    option_build_seconds: float
    incompatibility_build_seconds: float
    total_seconds: float

    @property
    def trajectory_count(self) -> int:
        return sum(self.trajectory_count_by_cabin_id.values())


@dataclass(frozen=True)
class DddTrajectoryReferenceMasterBuildResult:
    master_problem: DddTrajectoryPassengerMasterProblem
    reference_trajectory_by_option_id: dict[str, DddReferenceTrajectory]
    incompatibility_pair_check_count: int
    option_build_seconds: float
    incompatibility_build_seconds: float


def build_ddd_trajectory_reference_master(
    *,
    problem: DddNetworkTimeProblem,
    artifact: EanBuildArtifact,
    passenger_build: EanPassengerCandidateBuildResult,
    objective: EanPassengerObjective,
    reference_trajectories: tuple[DddReferenceTrajectory, ...],
    trajectory_columns_complete: bool = False,
    resource_windows: tuple[DddTrajectoryResourceWindow, ...] = (),
    max_incompatibility_pair_checks: int = 2_000_000,
    tolerance_seconds: float = 1e-9,
) -> DddTrajectoryReferenceMasterBuildResult:
    """Build a factorized master over a declared reference-trajectory pool."""

    problem.validate()
    artifact.validate()
    passenger_build.validate()
    if max_incompatibility_pair_checks <= 0:
        raise ValueError("trajectory reference pair-check limit must be positive")
    if tolerance_seconds < 0:
        raise ValueError("trajectory reference tolerance must be nonnegative")
    expected_cabin_ids = tuple(
        sorted(start.cabin_id for start in problem.movement_problem.starts)
    )
    actual_cabin_ids = {item.cabin_id for item in reference_trajectories}
    if actual_cabin_ids != set(expected_cabin_ids):
        raise ValueError("trajectory reference pool must cover every fixed cabin")

    option_started = perf_counter()
    adapter = DddReferenceToEanMovementPlanAdapter(tolerance_seconds=tolerance_seconds)
    definition = ean_passenger_objective_definition(objective)
    group_by_id = {group.id: group for group in passenger_build.demand_groups}
    unserved_cost_by_group_id = {
        group.id: definition.unserved_cost_seconds(
            release_time_seconds=group.release_time_seconds,
            horizon_seconds=artifact.config.horizon_seconds,
        )
        for group in passenger_build.demand_groups
    }
    instance_fingerprint = ddd_trajectory_instance_fingerprint(artifact)
    reference_by_option_id: dict[str, DddReferenceTrajectory] = {}
    master_options: list[DddTrajectoryPassengerOption] = []
    for trajectory in sorted(
        reference_trajectories,
        key=lambda item: (item.cabin_id, item.support_signature),
    ):
        ean_trajectory = adapter.build_trajectory(
            problem=problem.movement_problem,
            trajectory=trajectory,
        )
        one_trajectory_plan = EanMovementPlan(
            scenario_id=artifact.scenario_id,
            horizon_seconds=artifact.config.horizon_seconds,
            model_end_seconds=artifact.config.model_end_seconds,
            trajectories=(ean_trajectory,),
            horizon_formulation=EanHorizonFormulation.EXACT_TIME_ACTIVATION,
            fleet_mode=artifact.fleet_mode,
        )
        one_trajectory_plan.validate()
        column = ddd_trajectory_column(
            trajectory,
            instance_fingerprint=instance_fingerprint,
        )
        existing = reference_by_option_id.get(column.id)
        if existing is not None:
            if existing != trajectory:
                raise RuntimeError("trajectory reference column identity collision")
            continue
        reference_by_option_id[column.id] = trajectory
        rides = []
        for ride in build_ean_fixed_movement_rides(
            passenger_build=passenger_build,
            movement_plan=one_trajectory_plan,
            horizon_seconds=artifact.config.horizon_seconds,
        ):
            group = group_by_id[ride.candidate.demand_group_id]
            served_cost = definition.served_cost_seconds(
                release_time_seconds=group.release_time_seconds,
                boarding_time_seconds=ride.boarding_time_seconds,
                alighting_time_seconds=ride.alighting_time_seconds,
            )
            rides.append(
                DddTrajectoryPassengerRide(
                    id=f"{column.id}::{ride.candidate.id}",
                    demand_group_id=group.id,
                    upper_bound=float(min(group.count, artifact.config.cabin_capacity)),
                    objective_delta=(served_cost - unserved_cost_by_group_id[group.id]),
                    onboard_segment_ids=tuple(
                        f"visit:{visit.visit_index:08d}"
                        for visit in ean_trajectory.visits
                        if (
                            ride.candidate.board_visit_index
                            <= visit.visit_index
                            < ride.candidate.alight_visit_index
                        )
                    ),
                )
            )
        master_options.append(
            DddTrajectoryPassengerOption(
                id=column.id,
                cabin_id=trajectory.cabin_id,
                rides=tuple(sorted(rides, key=lambda item: item.id)),
            )
        )
    master_options.sort(key=lambda item: item.id)
    option_build_seconds = perf_counter() - option_started

    count_by_cabin_id = {
        cabin_id: sum(option.cabin_id == cabin_id for option in master_options)
        for cabin_id in expected_cabin_ids
    }
    pair_check_count = sum(
        count_by_cabin_id[first] * count_by_cabin_id[second]
        for first_index, first in enumerate(expected_cabin_ids)
        for second in expected_cabin_ids[first_index + 1 :]
    )
    if pair_check_count > max_incompatibility_pair_checks:
        raise DddExhaustiveTrajectoryLimitError(
            "trajectory reference exceeds incompatibility-pair limit: "
            f"{pair_check_count} > {max_incompatibility_pair_checks}"
        )
    incompatibility_started = perf_counter()
    incompatibility_pairs = []
    for first_index, first in enumerate(master_options):
        for second in master_options[first_index + 1 :]:
            if first.cabin_id == second.cabin_id:
                continue
            occurrences = (
                *reference_by_option_id[first.id].resource_occurrences,
                *reference_by_option_id[second.id].resource_occurrences,
            )
            if find_ddd_reference_conflicts(
                occurrences,
                problem.movement_problem,
                tolerance_seconds=tolerance_seconds,
            ):
                incompatibility_pairs.append(tuple(sorted((first.id, second.id))))
    incompatibility_build_seconds = perf_counter() - incompatibility_started
    resource_window_rows = build_ddd_trajectory_resource_window_rows(
        windows=resource_windows,
        movement_problem=problem.movement_problem,
        trajectory_by_option_id=reference_by_option_id,
    )
    master_problem = DddTrajectoryPassengerMasterProblem(
        cabin_ids=expected_cabin_ids,
        demand_by_group_id={
            group.id: float(group.count)
            for group in sorted(passenger_build.demand_groups, key=lambda item: item.id)
        },
        options=tuple(master_options),
        cabin_capacity=float(artifact.config.cabin_capacity),
        objective_constant=sum(
            unserved_cost_by_group_id[group.id] * group.count
            for group in passenger_build.demand_groups
        ),
        incompatibility_pairs=tuple(sorted(incompatibility_pairs)),
        resource_window_rows=resource_window_rows,
        incompatibility_rows_complete=True,
        trajectory_columns_complete=trajectory_columns_complete,
        waiting_domain=DddTrajectoryWaitingDomain.NO_WAIT,
    )
    master_problem.validate()
    return DddTrajectoryReferenceMasterBuildResult(
        master_problem=master_problem,
        reference_trajectory_by_option_id=reference_by_option_id,
        incompatibility_pair_check_count=pair_check_count,
        option_build_seconds=option_build_seconds,
        incompatibility_build_seconds=incompatibility_build_seconds,
    )


@dataclass(frozen=True)
class DddExhaustiveTrajectoryMasterBuilder:
    """Build the complete finite no-wait trajectory master for tiny cases only."""

    max_trajectories_per_start: int = 100_000
    max_total_trajectories: int = 100_000
    max_incompatibility_pair_checks: int = 2_000_000
    tolerance_seconds: float = 1e-9

    def build(
        self,
        *,
        problem: DddNetworkTimeProblem,
        artifact: EanBuildArtifact,
        passenger_build: EanPassengerCandidateBuildResult,
        objective: EanPassengerObjective,
    ) -> DddExhaustiveTrajectoryMasterBuildResult:
        started = perf_counter()
        self._validate(problem, artifact, passenger_build)

        generation_started = perf_counter()
        generated = DddReferenceTrajectoryGenerator(
            tolerance_seconds=self.tolerance_seconds,
            max_trajectories_per_start=self.max_trajectories_per_start,
        ).generate(problem.movement_problem)
        generation_seconds = perf_counter() - generation_started
        count_by_cabin_id = {
            cabin_id: len(trajectories)
            for cabin_id, trajectories in sorted(generated.by_cabin_id.items())
        }
        trajectory_count = sum(count_by_cabin_id.values())
        if trajectory_count > self.max_total_trajectories:
            raise DddExhaustiveTrajectoryLimitError(
                "complete trajectory reference exceeds total trajectory limit: "
                f"{trajectory_count} > {self.max_total_trajectories}"
            )

        reference_master = build_ddd_trajectory_reference_master(
            problem=problem,
            artifact=artifact,
            passenger_build=passenger_build,
            objective=objective,
            reference_trajectories=tuple(
                trajectory
                for trajectories in generated.by_cabin_id.values()
                for trajectory in trajectories
            ),
            trajectory_columns_complete=True,
            max_incompatibility_pair_checks=(self.max_incompatibility_pair_checks),
            tolerance_seconds=self.tolerance_seconds,
        )
        return DddExhaustiveTrajectoryMasterBuildResult(
            master_problem=reference_master.master_problem,
            reference_trajectory_by_option_id=(
                reference_master.reference_trajectory_by_option_id
            ),
            trajectory_count_by_cabin_id=count_by_cabin_id,
            generation_branch_count=generated.branch_count,
            self_conflict_pruned_count=generated.self_conflict_pruned_count,
            incompatibility_pair_check_count=(
                reference_master.incompatibility_pair_check_count
            ),
            generation_seconds=generation_seconds,
            option_build_seconds=reference_master.option_build_seconds,
            incompatibility_build_seconds=(
                reference_master.incompatibility_build_seconds
            ),
            total_seconds=perf_counter() - started,
        )

    def _validate(
        self,
        problem: DddNetworkTimeProblem,
        artifact: EanBuildArtifact,
        passenger_build: EanPassengerCandidateBuildResult,
    ) -> None:
        problem.validate()
        artifact.validate()
        passenger_build.validate()
        if problem.movement_problem.scenario_id != artifact.scenario_id:
            raise ValueError("complete trajectory problem and artifact differ")
        if artifact.fleet_mode is not EanFleetMode.FIXED_STARTS:
            raise ValueError("complete trajectory reference supports fixed starts only")
        if any(
            config.waiting_mode is not StationWaitingMode.NO_WAITING
            for config in artifact.config.station_configs
        ):
            raise ValueError("complete trajectory reference supports no-wait only")
        if self.max_total_trajectories <= 0:
            raise ValueError("complete trajectory total limit must be positive")
        if self.max_incompatibility_pair_checks <= 0:
            raise ValueError("complete trajectory pair-check limit must be positive")
        if self.tolerance_seconds < 0:
            raise ValueError("complete trajectory tolerance must be nonnegative")


def ddd_trajectory_instance_fingerprint(artifact: EanBuildArtifact) -> str:
    payload = {
        "scenario_id": artifact.scenario_id,
        "horizon_seconds": artifact.config.horizon_seconds,
        "model_end_seconds": artifact.config.model_end_seconds,
        "fleet_mode": artifact.fleet_mode.value,
        "cabin_ids": sorted(start.cabin_id for start in artifact.cabin_starts),
    }
    return sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
