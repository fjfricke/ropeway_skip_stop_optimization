from __future__ import annotations

from dataclasses import dataclass, replace
import math
from pathlib import Path

from ropeway_skip_stop_optimization.examples.registry import get_example
from ropeway_skip_stop_optimization.exports.artifacts import (
    ArtifactKind,
    ArtifactSet,
    ArtifactSetBackend,
    ExportArtifact,
)
from ropeway_skip_stop_optimization.exports.json_codec import write_json
from ropeway_skip_stop_optimization.exports.manifest import merge_and_write_manifest
from ropeway_skip_stop_optimization.optimization.ddd.ean_plan_adapter import (
    DddReferenceToEanMovementPlanAdapter,
)
from ropeway_skip_stop_optimization.optimization.ddd.artifact_adapter import (
    EanArtifactToDddMovementProblemAdapter,
)
from ropeway_skip_stop_optimization.optimization.ddd.reference import (
    DddReferenceSolution,
)
from ropeway_skip_stop_optimization.optimization.ddd.trajectory_exhaustive_reference import (
    ddd_trajectory_instance_fingerprint,
)
from ropeway_skip_stop_optimization.optimization.ddd.trajectory_root_checkpoint import (
    read_ddd_trajectory_root_cg_checkpoint,
    write_ddd_trajectory_root_cg_checkpoint,
)
from ropeway_skip_stop_optimization.optimization.ddd.trajectory_slot import (
    ddd_trajectory_column,
)
from ropeway_skip_stop_optimization.optimization.ean.builders.network_artifact_builder import (
    NetworkEanBuildArtifactBuilder,
)
from ropeway_skip_stop_optimization.optimization.ean.builders.passenger_builder import (
    EanPassengerCandidateBuildResult,
    EanPassengerCandidateBuilder,
)
from ropeway_skip_stop_optimization.optimization.ean.builders.headway_pair_builder import (
    SparseHeadwayPairBuilder,
)
from ropeway_skip_stop_optimization.optimization.ean.optimizers.fixed_movement_passenger_model import (
    EanPassengerAssignmentDomain,
    build_ean_fixed_movement_rides,
)
from ropeway_skip_stop_optimization.optimization.ean.optimizers.solver import (
    EanFixedMovementPassengerProblem,
    EanOptimizer,
    EanSolveConfig,
)
from ropeway_skip_stop_optimization.optimization.ean.optimizers.solver_policy import (
    GurobiSolverPolicy,
)
from ropeway_skip_stop_optimization.optimization.ean.passenger_objective import (
    ean_passenger_objective_definition,
)
from ropeway_skip_stop_optimization.optimization.ean.passenger_plan import (
    EanPassengerServicePlan,
    EanServedRideGroup,
)
from ropeway_skip_stop_optimization.optimization.ean.plan import EanRouteDecision
from ropeway_skip_stop_optimization.optimization.ean.projection import (
    project_ean_movement_plan_to_physical_replay,
)


@dataclass(frozen=True)
class DddRootCgFrontendExportResult:
    checkpoint_path: Path
    passenger_assignment_recovered: bool
    objective_value_seconds: float
    artifact_paths: tuple[Path, ...]
    manifest_path: Path


@dataclass(frozen=True)
class _PrebuiltPassengerCandidateBuilder:
    result: EanPassengerCandidateBuildResult

    def build(self, scenario, artifact) -> EanPassengerCandidateBuildResult:
        del scenario, artifact
        return self.result


def export_ddd_root_cg_checkpoint_to_frontend(
    *,
    example_id: str,
    checkpoint_path: Path,
    output_root: Path = Path("frontend/public/generated/examples"),
    passenger_time_limit_seconds: float = 30.0,
) -> DddRootCgFrontendExportResult:
    if passenger_time_limit_seconds <= 0:
        raise ValueError("DDD frontend Passenger time limit must be positive")
    example = get_example(example_id)
    scenario = example.build_scenario()
    config = example.build_ean_config(scenario)
    base_builder = example.build_ean_artifact_builder(scenario, config)
    if not isinstance(base_builder, NetworkEanBuildArtifactBuilder):
        raise ValueError("DDD frontend export requires the network EAN builder")
    artifact = replace(
        base_builder,
        headway_pair_builder=SparseHeadwayPairBuilder(),
    ).build(scenario, config)
    movement_problem = EanArtifactToDddMovementProblemAdapter().build(artifact)
    state = read_ddd_trajectory_root_cg_checkpoint(checkpoint_path)
    if state.instance_fingerprint != ddd_trajectory_instance_fingerprint(artifact):
        raise ValueError("DDD frontend checkpoint belongs to a different instance")
    if state.best_upper_bound is None or not state.incumbent_option_ids:
        raise ValueError("DDD frontend checkpoint has no feasible incumbent")

    trajectory_by_option_id = {
        ddd_trajectory_column(
            trajectory,
            instance_fingerprint=state.instance_fingerprint,
        ).id: trajectory
        for trajectory in state.trajectories
    }
    missing = set(state.incumbent_option_ids) - set(trajectory_by_option_id)
    if missing:
        raise ValueError("DDD frontend incumbent references a missing trajectory")
    selected = tuple(
        trajectory_by_option_id[option_id] for option_id in state.incumbent_option_ids
    )
    solution = DddReferenceSolution(
        trajectories=tuple(sorted(selected, key=lambda item: item.cabin_id))
    )
    movement_plan = DddReferenceToEanMovementPlanAdapter().build(
        problem=movement_problem,
        solution=solution,
        artifact=artifact,
    )
    passenger_build = EanPassengerCandidateBuilder().build(scenario, artifact)
    recovered = not state.incumbent_ride_values_by_id
    solver_metadata = None
    if recovered:
        fixed_result = EanOptimizer(
            EanSolveConfig(
                solver_policy=GurobiSolverPolicy(
                    mip_gap=0.0,
                    time_limit_seconds=passenger_time_limit_seconds,
                    threads=1,
                    mip_focus=1,
                ),
            )
        ).solve(
            EanFixedMovementPassengerProblem(
                scenario=scenario,
                artifact=artifact,
                movement_plan=movement_plan,
                objective=state.objective,
                assignment_domain=EanPassengerAssignmentDomain.INTEGER,
                passenger_builder=_PrebuiltPassengerCandidateBuilder(passenger_build),
            )
        )
        if (
            fixed_result.passenger_assignment is None
            or fixed_result.passenger_plan is None
            or fixed_result.metadata.objective_value_seconds is None
        ):
            raise RuntimeError("fixed DDD incumbent Passenger Assignment failed")
        option_id_by_cabin_id = {
            trajectory_by_option_id[option_id].cabin_id: option_id
            for option_id in state.incumbent_option_ids
        }
        candidate_by_id = {
            candidate.id: candidate for candidate in passenger_build.ride_candidates
        }
        ride_values = {
            f"{option_id_by_cabin_id[candidate_by_id[candidate_id].cabin_id]}::{candidate_id}": value
            for candidate_id, value in fixed_result.passenger_assignment.ride_counts_by_candidate_id.items()
            if value > 1e-7
        }
        state = replace(state, incumbent_ride_values_by_id=ride_values)
        write_ddd_trajectory_root_cg_checkpoint(checkpoint_path, state)
        solver_metadata = fixed_result.metadata.passenger_export_dict()

    passenger_plan, objective_value = _passenger_plan_from_checkpoint(
        state=state,
        movement_plan=movement_plan,
        passenger_build=passenger_build,
        artifact=artifact,
    )
    if not math.isclose(
        objective_value,
        state.best_upper_bound,
        rel_tol=0.0,
        abs_tol=1e-4,
    ):
        raise RuntimeError(
            "DDD frontend Passenger objective differs from the certified incumbent: "
            f"{objective_value} != {state.best_upper_bound}"
        )
    physical_replay = project_ean_movement_plan_to_physical_replay(
        scenario,
        artifact,
        movement_plan,
    )
    metadata = _frontend_metadata(
        state=state,
        movement_plan=movement_plan,
        passenger_plan=passenger_plan,
        passenger_build=passenger_build,
        objective_value=objective_value,
        solver_metadata=solver_metadata,
        checkpoint_path=checkpoint_path,
    )
    prefix = "ddd_root_cg_journey_time"
    relative_root = Path(example_id)
    artifacts = (
        ExportArtifact(
            id="scenario",
            kind=ArtifactKind.SCENARIO,
            relative_path=relative_root / "scenario.json",
            payload={
                "scenario_id": scenario.id,
                **{
                    key: value
                    for key, value in scenario.__dict__.items()
                    if key != "id"
                },
            },
            label="Physical scenario",
        ),
        ExportArtifact(
            id=f"{prefix}_ean_input",
            kind=ArtifactKind.EAN_INPUT,
            relative_path=relative_root / f"{prefix}_ean_build_artifact.json",
            payload=artifact,
            label="DDD root-CG EAN input",
        ),
        ExportArtifact(
            id=f"{prefix}_movement_plan",
            kind=ArtifactKind.EAN_RESULT,
            relative_path=relative_root / f"{prefix}_movement_plan.json",
            payload=movement_plan,
            label="DDD root-CG movement plan",
        ),
        ExportArtifact(
            id=f"{prefix}_physical_replay",
            kind=ArtifactKind.EAN_REPLAY,
            relative_path=relative_root / f"{prefix}_physical_replay.json",
            payload=physical_replay,
            label="DDD root-CG physical replay",
        ),
        ExportArtifact(
            id=prefix,
            kind=ArtifactKind.MILP_RESULT,
            relative_path=relative_root / f"{prefix}.json",
            payload={
                "movement_plan": movement_plan,
                "passenger_plan": passenger_plan,
                "fleet_plan": None,
                "metadata": metadata,
            },
            label="DDD root-CG journey-time result",
        ),
    )
    artifact_paths = []
    for export_artifact in artifacts:
        path = output_root / export_artifact.relative_path
        write_json(path, export_artifact.payload)
        artifact_paths.append(path)
    artifact_set = ArtifactSet(
        id="ddd_root_cg_journey_time",
        label="DDD root CG journey-time incumbent",
        builders=(),
        backend=ArtifactSetBackend.EAN,
        is_default=True,
    )
    manifest_path = merge_and_write_manifest(
        output_root,
        example,
        artifact_set,
        artifacts,
    )
    return DddRootCgFrontendExportResult(
        checkpoint_path=checkpoint_path,
        passenger_assignment_recovered=recovered,
        objective_value_seconds=objective_value,
        artifact_paths=tuple(artifact_paths),
        manifest_path=manifest_path,
    )


def _passenger_plan_from_checkpoint(
    *,
    state,
    movement_plan,
    passenger_build,
    artifact,
) -> tuple[EanPassengerServicePlan, float]:
    option_id_by_cabin_id = {
        trajectory.cabin_id: option_id
        for option_id in state.incumbent_option_ids
        for trajectory in state.trajectories
        if ddd_trajectory_column(
            trajectory,
            instance_fingerprint=state.instance_fingerprint,
        ).id
        == option_id
    }
    fixed_ride_by_candidate_id = {
        ride.candidate.id: ride
        for ride in build_ean_fixed_movement_rides(
            passenger_build=passenger_build,
            movement_plan=movement_plan,
            horizon_seconds=artifact.config.horizon_seconds,
        )
    }
    group_by_id = {group.id: group for group in passenger_build.demand_groups}
    served_by_group_id = {group.id: 0 for group in passenger_build.demand_groups}
    served_rides = []
    definition = ean_passenger_objective_definition(state.objective)
    objective_value = 0.0
    for candidate_id, ride in sorted(fixed_ride_by_candidate_id.items()):
        option_id = option_id_by_cabin_id[ride.candidate.cabin_id]
        value = state.incumbent_ride_values_by_id.get(
            f"{option_id}::{candidate_id}",
            0.0,
        )
        if not math.isclose(value, round(value), abs_tol=1e-6):
            raise ValueError("DDD frontend Passenger count is fractional")
        count = int(round(value))
        if count <= 0:
            continue
        candidate = ride.candidate
        group = group_by_id[candidate.demand_group_id]
        served_by_group_id[group.id] += count
        served_rides.append(
            EanServedRideGroup(
                demand_group_id=group.id,
                cabin_id=candidate.cabin_id,
                board_visit_index=candidate.board_visit_index,
                alight_visit_index=candidate.alight_visit_index,
                count=count,
                boarding_time_seconds=ride.boarding_time_seconds,
                alighting_time_seconds=ride.alighting_time_seconds,
            )
        )
        objective_value += count * definition.served_cost_seconds(
            release_time_seconds=group.release_time_seconds,
            boarding_time_seconds=ride.boarding_time_seconds,
            alighting_time_seconds=ride.alighting_time_seconds,
        )
    unserved = {
        group.id: group.count - served_by_group_id[group.id]
        for group in passenger_build.demand_groups
    }
    for group in passenger_build.demand_groups:
        objective_value += unserved[group.id] * definition.unserved_cost_seconds(
            release_time_seconds=group.release_time_seconds,
            horizon_seconds=artifact.config.horizon_seconds,
        )
    plan = EanPassengerServicePlan(
        scenario_id=artifact.scenario_id,
        horizon_seconds=artifact.config.horizon_seconds,
        served_rides=tuple(served_rides),
        unserved_counts_by_demand_group_id=unserved,
    )
    plan.validate()
    return plan, objective_value


def _frontend_metadata(
    *,
    state,
    movement_plan,
    passenger_plan,
    passenger_build,
    objective_value,
    solver_metadata,
    checkpoint_path,
) -> dict[str, object]:
    served = sum(item.count for item in passenger_plan.served_rides)
    unserved = sum(passenger_plan.unserved_counts_by_demand_group_id.values())
    skipped = tuple(
        visit
        for trajectory in movement_plan.trajectories
        for visit in trajectory.visits
        if visit.decision is EanRouteDecision.SKIP
    )
    cumulative_seconds = 0.0
    progress_samples = []
    for iteration in state.iterations:
        cumulative_seconds += iteration.total_seconds
        progress_samples.append(
            {
                "runtime_seconds": cumulative_seconds,
                "incumbent_objective": iteration.global_upper_bound,
                "best_bound": iteration.global_lower_bound,
                "mip_gap": (
                    None
                    if iteration.global_upper_bound is None
                    else max(
                        0.0,
                        iteration.global_upper_bound - iteration.global_lower_bound,
                    )
                    / max(abs(iteration.global_upper_bound), 1e-9)
                ),
                "solution_count": 1 if iteration.global_upper_bound is not None else 0,
                "event": "ddd_root_cg_round",
            }
        )
    last = state.iterations[-1]
    metadata = {
        "status": "optimal_root_lp" if state.root_lp_certified else "feasible",
        "solver_status": "DDD root LP certified"
        if state.root_lp_certified
        else "DDD incumbent",
        "root_lp_certified": state.root_lp_certified,
        "objective_kind": state.objective.value,
        "objective_value_seconds": objective_value,
        "objective_passenger_hours": objective_value / 3600.0,
        "best_bound": state.certified_lower_bound,
        "mip_gap": max(0.0, objective_value - state.certified_lower_bound)
        / max(abs(objective_value), 1e-9),
        "runtime_seconds": state.total_seconds,
        "node_count": None,
        "solution_count": 1,
        "mip_gap_target": 0.0,
        "time_limit_seconds": None,
        "checkpoint_read_path": str(checkpoint_path),
        "checkpoint_solution_file_prefix": None,
        "checkpoint_final_solution_path": str(checkpoint_path),
        "demand_group_count": len(passenger_build.demand_groups),
        "ride_candidate_count": len(passenger_build.ride_candidates),
        "slot_variable_count": len(state.incumbent_ride_values_by_id),
        "served_passenger_count": served,
        "unserved_passenger_count": unserved,
        "variable_count": last.trajectory_count,
        "constraint_count": last.incompatibility_pair_count,
        "model_nonzero_count": None,
        "model_setup_runtime_seconds": None,
        "skipped_visit_count": len(skipped),
        "visible_skipped_visit_count": sum(
            visit.switch_time_seconds <= movement_plan.horizon_seconds
            for visit in skipped
        ),
        "progress_samples": progress_samples,
        "ddd_root_cg": {
            "round_count": state.completed_rounds,
            "trajectory_count": len(state.trajectories),
            "root_lp_certified": state.root_lp_certified,
        },
    }
    if solver_metadata is not None:
        metadata["passenger_recovery"] = solver_metadata
    return metadata
