from __future__ import annotations

from dataclasses import asdict, dataclass
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
from ropeway_skip_stop_optimization.optimization.ddd.trajectory_problem import (
    DddFixedTrajectoryStartDomain,
    DddOptimizedInitialPlacementDomain,
    DddReservoirTrajectoryKind,
    DddReservoirTrajectoryStartDomain,
    DddTrajectoryProblem,
)
from ropeway_skip_stop_optimization.optimization.ddd.trajectory_oip import (
    build_ean_oip_trajectory,
)
from ropeway_skip_stop_optimization.optimization.ddd.trajectory_reservoir import (
    build_ean_reservoir_trajectory,
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
from ropeway_skip_stop_optimization.optimization.ean.fleet import (
    EanInitialPlacementStateKind,
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
    boundary_incompatibility_pair_count: int = 0


def build_ddd_trajectory_reference_master(
    *,
    problem: DddNetworkTimeProblem | None = None,
    trajectory_problem: DddTrajectoryProblem | None = None,
    artifact: EanBuildArtifact,
    passenger_build: EanPassengerCandidateBuildResult,
    objective: EanPassengerObjective,
    reference_trajectories: tuple[DddReferenceTrajectory, ...],
    trajectory_columns_complete: bool = False,
    resource_windows: tuple[DddTrajectoryResourceWindow, ...] = (),
    max_incompatibility_pair_checks: int = 2_000_000,
    tolerance_seconds: float = 1e-9,
    enforce_oip_initial_order: bool = True,
    enforce_reservoir_dispatch_order: bool = True,
    instance_fingerprint: str | None = None,
) -> DddTrajectoryReferenceMasterBuildResult:
    """Build a factorized master over a declared reference-trajectory pool."""

    if (problem is None) == (trajectory_problem is None):
        raise ValueError(
            "provide exactly one fixed network problem or trajectory problem"
        )
    if trajectory_problem is None:
        assert problem is not None
        problem.validate()
        movement_problem = problem.movement_problem
        trajectory_problem = DddTrajectoryProblem(
            movement_core=movement_problem.core,
            start_domain=DddFixedTrajectoryStartDomain(movement_problem.starts),
        )
    trajectory_problem.validate()
    movement_problem = trajectory_problem.structural_movement_problem
    artifact.validate()
    passenger_build.validate()
    if max_incompatibility_pair_checks <= 0:
        raise ValueError("trajectory reference pair-check limit must be positive")
    if tolerance_seconds < 0:
        raise ValueError("trajectory reference tolerance must be nonnegative")
    expected_cabin_ids = trajectory_problem.cabin_ids
    actual_cabin_ids = {item.cabin_id for item in reference_trajectories}
    if actual_cabin_ids != set(expected_cabin_ids):
        raise ValueError("trajectory reference pool must cover every fixed cabin")

    option_started = perf_counter()
    adapter = DddReferenceToEanMovementPlanAdapter(
        tolerance_seconds=tolerance_seconds,
        waiting_policy=trajectory_problem.waiting_policy,
    )
    definition = ean_passenger_objective_definition(objective)
    group_by_id = {group.id: group for group in passenger_build.demand_groups}
    unserved_cost_by_group_id = {
        group.id: definition.unserved_cost_seconds(
            release_time_seconds=group.release_time_seconds,
            horizon_seconds=artifact.config.horizon_seconds,
        )
        for group in passenger_build.demand_groups
    }
    instance_fingerprint = (
        instance_fingerprint or ddd_trajectory_instance_fingerprint(artifact)
    )
    reference_by_option_id: dict[str, DddReferenceTrajectory] = {}
    master_options: list[DddTrajectoryPassengerOption] = []
    for trajectory in sorted(
        reference_trajectories,
        key=lambda item: (item.cabin_id, item.support_signature),
    ):
        if isinstance(trajectory_problem.start_domain, DddFixedTrajectoryStartDomain):
            ean_trajectory = adapter.build_trajectory(
                problem=movement_problem,
                trajectory=trajectory,
            )
        elif isinstance(
            trajectory_problem.start_domain, DddOptimizedInitialPlacementDomain
        ):
            ean_trajectory = build_ean_oip_trajectory(
                problem=trajectory_problem,
                artifact=artifact,
                trajectory=trajectory,
                tolerance_seconds=tolerance_seconds,
            )
        else:
            ean_trajectory = build_ean_reservoir_trajectory(
                problem=trajectory_problem,
                trajectory=trajectory,
            )
        one_trajectory_plan = EanMovementPlan(
            scenario_id=artifact.scenario_id,
            horizon_seconds=artifact.config.horizon_seconds,
            model_end_seconds=artifact.config.model_end_seconds,
            trajectories=(ean_trajectory,),
            horizon_formulation=EanHorizonFormulation.EXACT_TIME_ACTIVATION,
            fleet_mode=(
                EanFleetMode.OPTIMIZED_INITIAL_PLACEMENT
                if isinstance(
                    trajectory_problem.start_domain,
                    DddReservoirTrajectoryStartDomain,
                )
                else artifact.fleet_mode
            ),
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
                is_stored=(
                    isinstance(
                        trajectory_problem.start_domain,
                        DddReservoirTrajectoryStartDomain,
                    )
                    and trajectory.reservoir_state is not None
                    and trajectory.reservoir_state.kind
                    is DddReservoirTrajectoryKind.STORED
                ),
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
    boundary_incompatibility_pair_count = 0
    for first_index, first in enumerate(master_options):
        for second in master_options[first_index + 1 :]:
            if first.cabin_id == second.cabin_id:
                continue
            occurrences = (
                *reference_by_option_id[first.id].resource_occurrences,
                *reference_by_option_id[second.id].resource_occurrences,
            )
            first_trajectory = reference_by_option_id[first.id]
            second_trajectory = reference_by_option_id[second.id]
            order_violation = (
                enforce_oip_initial_order
                and isinstance(
                    trajectory_problem.start_domain,
                    DddOptimizedInitialPlacementDomain,
                )
                and abs(second.cabin_id - first.cabin_id) == 1
                and not _oip_initial_order_is_canonical(
                    (
                        first_trajectory
                        if first.cabin_id < second.cabin_id
                        else second_trajectory
                    ),
                    (
                        second_trajectory
                        if first.cabin_id < second.cabin_id
                        else first_trajectory
                    ),
                    tolerance_seconds=tolerance_seconds,
                )
            )
            reservoir_order_violation = (
                enforce_reservoir_dispatch_order
                and isinstance(
                    trajectory_problem.start_domain,
                    DddReservoirTrajectoryStartDomain,
                )
                and abs(second.cabin_id - first.cabin_id) == 1
                and not _reservoir_dispatch_order_is_canonical(
                    (
                        first_trajectory
                        if first.cabin_id < second.cabin_id
                        else second_trajectory
                    ),
                    (
                        second_trajectory
                        if first.cabin_id < second.cabin_id
                        else first_trajectory
                    ),
                    tolerance_seconds=tolerance_seconds,
                )
            )
            if order_violation or reservoir_order_violation or find_ddd_reference_conflicts(
                occurrences,
                movement_problem,
                tolerance_seconds=tolerance_seconds,
            ):
                incompatibility_pairs.append(tuple(sorted((first.id, second.id))))
                if (
                    first_trajectory.boundary_resource_occurrences
                    or second_trajectory.boundary_resource_occurrences
                ):
                    boundary_incompatibility_pair_count += 1
    incompatibility_build_seconds = perf_counter() - incompatibility_started
    resource_window_rows = (
        build_ddd_trajectory_resource_window_rows(
            windows=resource_windows,
            movement_problem=movement_problem,
            trajectory_by_option_id=reference_by_option_id,
        )
        if resource_windows
        else ()
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
        waiting_domain=trajectory_problem.waiting_policy.domain,
    )
    master_problem.validate()
    return DddTrajectoryReferenceMasterBuildResult(
        master_problem=master_problem,
        reference_trajectory_by_option_id=reference_by_option_id,
        incompatibility_pair_check_count=pair_check_count,
        option_build_seconds=option_build_seconds,
        incompatibility_build_seconds=incompatibility_build_seconds,
        boundary_incompatibility_pair_count=boundary_incompatibility_pair_count,
    )


def _oip_initial_order_is_canonical(
    first: DddReferenceTrajectory,
    second: DddReferenceTrajectory,
    *,
    tolerance_seconds: float,
) -> bool:
    first_state = first.initial_state
    second_state = second.initial_state
    if first_state is None or second_state is None:
        raise ValueError("OIP master columns need initial-state provenance")
    first_rope = first_state.kind is EanInitialPlacementStateKind.ROPE
    second_rope = second_state.kind is EanInitialPlacementStateKind.ROPE
    first_category = 2 * first_state.visit_index + int(first_rope)
    second_category = 2 * second_state.visit_index + int(second_rope)
    if first_category != second_category:
        return first_category < second_category
    first_time = (
        first_state.previous_event_time_seconds
        if first_rope
        else first.visits[0].switch_time_seconds
    )
    second_time = (
        second_state.previous_event_time_seconds
        if second_rope
        else second.visits[0].switch_time_seconds
    )
    return first_time <= second_time + tolerance_seconds


def _reservoir_dispatch_order_is_canonical(
    first: DddReferenceTrajectory,
    second: DddReferenceTrajectory,
    *,
    tolerance_seconds: float,
) -> bool:
    first_state = first.reservoir_state
    second_state = second.reservoir_state
    if first_state is None or second_state is None:
        raise ValueError("reservoir master columns need boundary provenance")
    if first_state.kind is DddReservoirTrajectoryKind.STORED:
        return second_state.kind is DddReservoirTrajectoryKind.STORED
    if second_state.kind is DddReservoirTrajectoryKind.STORED:
        return True
    assert first_state.dispatch_time_seconds is not None
    assert second_state.dispatch_time_seconds is not None
    return (
        first_state.dispatch_time_seconds
        <= second_state.dispatch_time_seconds + tolerance_seconds
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
        "headway_policy": (
            asdict(artifact.headway_policy)
            if artifact.headway_policy is not None
            else None
        ),
        "effective_headway_policy": (
            asdict(artifact.effective_headway_policy)
            if artifact.effective_headway_policy is not None
            else None
        ),
    }
    if artifact.fleet_mode is EanFleetMode.OPTIMIZED_INITIAL_PLACEMENT:
        payload["oip_domain"] = {
            "cardinality_mode": artifact.fleet_cardinality_mode.value,
            "initial_placement_parameters": (
                asdict(artifact.initial_placement_parameters)
                if artifact.initial_placement_parameters is not None
                else None
            ),
            "circulation_pattern_ids": artifact.circulation_pattern_ids,
            "circulation_state_ids": artifact.circulation_state_ids,
            "timings": [asdict(item) for item in artifact.timings],
        }
    return sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
