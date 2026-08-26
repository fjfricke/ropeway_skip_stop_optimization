from __future__ import annotations

from dataclasses import asdict, dataclass, replace
import json
import math
from pathlib import Path
from time import perf_counter
from typing import Callable

from ropeway_skip_stop_optimization.benchmarking.ddd_scaling import (
    build_initial_ddd_network_problem,
)
from ropeway_skip_stop_optimization.examples.registry import get_example
from ropeway_skip_stop_optimization.models import Scenario
from ropeway_skip_stop_optimization.optimization.headway_resource_reduction import (
    HeadwayResourceReductionMode,
)
from ropeway_skip_stop_optimization.optimization.ddd import (
    DddFixedKArcFlowOptimizer,
    DddFixedKArcFlowProgress,
    DddFixedKArcFlowResult,
    DddFixedKArcFlowSolveConfig,
    DddBalancedReferenceStartBuilder,
    DddFixedKBoundaryContext,
    DddFixedKOperatingMode,
    DddFixedKSeedCoordinator,
    DddFixedKSeedStatus,
    DddFixedKStartPolicy,
    DddFixedKTrajectoryProblem,
    DddEanPassengerPrimalEvaluator,
    DddPrimalEvaluationStatus,
    DddReferenceResourceOccurrence,
    DddReferenceSolution,
    DddReferenceTrajectory,
    EanArtifactToDddMovementProblemAdapter,
    build_ddd_reference_visit,
    validate_ddd_reference_solution,
)
from ropeway_skip_stop_optimization.optimization.ean import (
    CanonicalFixedKRopeCabinStartBuilder,
    EanCabinStart,
    EanCabinStartKind,
    EanFleetCardinalityMode,
    EanFleetConfig,
    EanFleetMode,
    EanPassengerCandidateBuilder,
    EanPassengerObjective,
    EvenlySpacedAllStopCabinStartBuilder,
    ExplicitEanCabinStartBuilder,
    NetworkEanBuildArtifactBuilder,
    SparseHeadwayPairBuilder,
    analyze_all_stop_start_capacity,
)


@dataclass(frozen=True, slots=True)
class DddFixedKArcFlowRunConfig:
    example_id: str
    cabin_count: int
    operating_mode: DddFixedKOperatingMode
    objective: EanPassengerObjective = EanPassengerObjective.JOURNEY_TIME
    start_policy: DddFixedKStartPolicy = DddFixedKStartPolicy.CANONICAL_ROPE
    start_layout_time_limit_seconds: float = 120.0
    total_time_limit_seconds: float = 600.0
    cp_seed_time_limit_seconds: float = 60.0
    cp_seed_workers: int = 8
    solver_threads: int | None = None
    mip_gap: float = 0.0
    mip_focus: int = 0
    seed: int = 0
    output_flag: bool = False
    root_cg_result_path: Path | None = None

    def validate(self) -> None:
        if not self.example_id or self.cabin_count <= 0:
            raise ValueError("arc-flow run needs an example and positive K")
        if not isinstance(self.operating_mode, DddFixedKOperatingMode):
            raise ValueError("arc-flow run operating mode is invalid")
        if not isinstance(self.objective, EanPassengerObjective):
            raise ValueError("arc-flow run objective is invalid")
        if not isinstance(self.start_policy, DddFixedKStartPolicy):
            raise ValueError("arc-flow run start policy is invalid")
        if (
            self.total_time_limit_seconds <= 0
            or self.cp_seed_time_limit_seconds < 0
            or self.start_layout_time_limit_seconds <= 0
        ):
            raise ValueError("arc-flow run budgets are invalid")
        if self.cp_seed_workers <= 0:
            raise ValueError("arc-flow CP-SAT workers must be positive")
        if self.solver_threads is not None and self.solver_threads <= 0:
            raise ValueError("arc-flow solver threads must be positive")
        if not math.isfinite(self.mip_gap) or not 0 <= self.mip_gap <= 1:
            raise ValueError("arc-flow MIP gap must lie in [0, 1]")
        if self.mip_focus not in range(4) or self.seed < 0:
            raise ValueError("arc-flow solver controls are invalid")


@dataclass(frozen=True, slots=True)
class DddFixedKArcFlowRunResult:
    problem: DddFixedKTrajectoryProblem
    scenario: Scenario
    solve_result: DddFixedKArcFlowResult
    setup_seconds: float
    seed_status: str
    seed_seconds: float
    independent_validation_status: str
    independent_validation_objective: float | None
    independent_validation_seconds: float
    total_seconds: float
    all_stop_maximum_cabin_count: int | None = None
    start_layout_kind: str = "canonical_rope"
    start_layout_cycle_seconds: float | None = None
    start_layout_bottleneck_headway_seconds: float | None = None
    start_layout_service_station_count: int | None = None
    start_layout_candidate_count: int = 0
    start_layout_incompatibility_pair_count: int = 0
    start_layout_minimum_station_stop_count: int | None = None
    start_layout_maximum_service_gap_seconds: float | None = None
    start_layout_seconds: float = 0.0
    start_layout_objective_proven: bool | None = None

    def to_payload(self) -> dict[str, object]:
        raw = asdict(self.solve_result)
        raw.pop("solution", None)
        raw["status"] = self.solve_result.status.value
        raw.update(
            {
                "example_id": self.scenario.id,
                "exact_active_cabin_count": self.problem.fleet_cardinality,
                "operating_mode": self.problem.operating_mode.value,
                "objective": self.problem.objective.value,
                "start_policy": self.problem.start_policy.value,
                "start_layout_kind": self.start_layout_kind,
                "all_stop_maximum_cabin_count": (
                    self.all_stop_maximum_cabin_count
                ),
                "start_layout_cycle_seconds": self.start_layout_cycle_seconds,
                "start_layout_bottleneck_headway_seconds": (
                    self.start_layout_bottleneck_headway_seconds
                ),
                "start_layout_service_station_count": (
                    self.start_layout_service_station_count
                ),
                "start_layout_candidate_count": self.start_layout_candidate_count,
                "start_layout_incompatibility_pair_count": (
                    self.start_layout_incompatibility_pair_count
                ),
                "start_layout_minimum_station_stop_count": (
                    self.start_layout_minimum_station_stop_count
                ),
                "start_layout_maximum_service_gap_seconds": (
                    self.start_layout_maximum_service_gap_seconds
                ),
                "start_layout_seconds": self.start_layout_seconds,
                "start_layout_objective_proven": (
                    self.start_layout_objective_proven
                ),
                "setup_seconds": self.setup_seconds,
                "seed_status": self.seed_status,
                "seed_seconds": self.seed_seconds,
                "independent_validation_status": self.independent_validation_status,
                "independent_validation_objective": (
                    self.independent_validation_objective
                ),
                "independent_validation_seconds": (self.independent_validation_seconds),
                "total_seconds": self.total_seconds,
                "trajectory_supports": [
                    {
                        "cabin_id": trajectory.cabin_id,
                        "route_option_ids": list(trajectory.support_signature),
                        "switch_times_seconds": [
                            visit.switch_time_seconds for visit in trajectory.visits
                        ],
                    }
                    for trajectory in (
                        ()
                        if self.solve_result.solution is None
                        else self.solve_result.solution.trajectories
                    )
                ],
            }
        )
        return raw


@dataclass(frozen=True, slots=True)
class DddPreparedFixedKArcFlowRun:
    scenario: Scenario
    problem: DddFixedKTrajectoryProblem
    all_stop_maximum_cabin_count: int | None
    start_layout_kind: str
    start_layout_cycle_seconds: float | None = None
    start_layout_bottleneck_headway_seconds: float | None = None
    start_layout_service_station_count: int | None = None
    start_layout_candidate_count: int = 0
    start_layout_incompatibility_pair_count: int = 0
    start_layout_minimum_station_stop_count: int | None = None
    start_layout_maximum_service_gap_seconds: float | None = None
    start_layout_seconds: float = 0.0
    start_layout_objective_proven: bool | None = None
    seed_trajectories: tuple[DddReferenceTrajectory, ...] = ()


class DddAnalyticAllStopInfeasible(ValueError):
    def __init__(self, *, cabin_count: int, maximum_cabin_count: int) -> None:
        self.cabin_count = cabin_count
        self.maximum_cabin_count = maximum_cabin_count
        super().__init__(
            "exact-K all-stop is analytically infeasible: "
            f"K={cabin_count} > K_max_AS={maximum_cabin_count}"
        )


def build_ddd_fixed_k_arc_flow_problem(
    config: DddFixedKArcFlowRunConfig,
) -> tuple[Scenario, DddFixedKTrajectoryProblem]:
    prepared = prepare_ddd_fixed_k_arc_flow_run(config)
    return prepared.scenario, prepared.problem


def prepare_ddd_fixed_k_arc_flow_run(
    config: DddFixedKArcFlowRunConfig,
) -> DddPreparedFixedKArcFlowRun:
    config.validate()
    example = get_example(config.example_id)
    scenario = example.build_scenario()
    ean_config = example.build_ean_config(scenario)
    original_builder = example.build_ean_artifact_builder(scenario, ean_config)
    if not isinstance(original_builder, NetworkEanBuildArtifactBuilder):
        raise ValueError("fixed-K arc-flow requires the network EAN builder")
    builder = replace(
        original_builder,
        fleet_config=replace(
            original_builder.fleet_config,
            mode=EanFleetMode.FIXED_STARTS,
            available_fleet_count=None,
        ),
        headway_pair_builder=SparseHeadwayPairBuilder(),
    )

    if config.start_policy is DddFixedKStartPolicy.CANONICAL_ROPE:
        artifact = replace(
            builder,
            start_builder=CanonicalFixedKRopeCabinStartBuilder(config.cabin_count),
        ).build(scenario, ean_config)
        problem = _fixed_k_problem_from_artifact(
            config=config,
            scenario=scenario,
            artifact=artifact,
            boundary_context=DddFixedKBoundaryContext(source="canonical_rope"),
        )
        return DddPreparedFixedKArcFlowRun(
            scenario=scenario,
            problem=problem,
            all_stop_maximum_cabin_count=None,
            start_layout_kind="canonical_rope",
        )
    if config.start_policy is not DddFixedKStartPolicy.BALANCED_REFERENCE:
        raise ValueError(
            "complete DDD arc-flow does not support the selected start policy"
        )

    analysis_artifact = replace(
        builder,
        start_builder=EvenlySpacedAllStopCabinStartBuilder(1),
    ).build(scenario, ean_config)
    analysis = analyze_all_stop_start_capacity(analysis_artifact)
    if config.cabin_count <= analysis.maximum_cabin_count:
        artifact = replace(
            builder,
            start_builder=EvenlySpacedAllStopCabinStartBuilder(config.cabin_count),
        ).build(scenario, ean_config)
        problem = _fixed_k_problem_from_artifact(
            config=config,
            scenario=scenario,
            artifact=artifact,
            boundary_context=DddFixedKBoundaryContext(
                source="evenly_spaced_all_stop"
            ),
        )
        return DddPreparedFixedKArcFlowRun(
            scenario=scenario,
            problem=problem,
            all_stop_maximum_cabin_count=analysis.maximum_cabin_count,
            start_layout_kind="evenly_spaced_all_stop",
            start_layout_cycle_seconds=analysis.cycle_seconds,
            start_layout_bottleneck_headway_seconds=(
                analysis.limiting_headway_seconds
            ),
            start_layout_service_station_count=len(artifact.timings),
        )
    if config.operating_mode is DddFixedKOperatingMode.ALL_STOP:
        raise DddAnalyticAllStopInfeasible(
            cabin_count=config.cabin_count,
            maximum_cabin_count=analysis.maximum_cabin_count,
        )

    return _prepare_periodic_balanced_skip_stop_problem(
        config=config,
        scenario=scenario,
        ean_config=ean_config,
        builder=builder,
        all_stop_maximum_cabin_count=analysis.maximum_cabin_count,
    )


def _fixed_k_problem_from_artifact(
    *,
    config: DddFixedKArcFlowRunConfig,
    scenario: Scenario,
    artifact,
    boundary_context: DddFixedKBoundaryContext,
) -> DddFixedKTrajectoryProblem:
    trajectory_problem = (
        EanArtifactToDddMovementProblemAdapter().build_trajectory_problem(artifact)
    )
    result = DddFixedKTrajectoryProblem(
        trajectory_problem=trajectory_problem,
        artifact=artifact,
        passenger_build=EanPassengerCandidateBuilder().build(scenario, artifact),
        objective=config.objective,
        operating_mode=config.operating_mode,
        start_policy=config.start_policy,
        boundary_context=boundary_context,
    )
    result.validate()
    return result


def _prepare_periodic_balanced_skip_stop_problem(
    *,
    config: DddFixedKArcFlowRunConfig,
    scenario: Scenario,
    ean_config,
    builder: NetworkEanBuildArtifactBuilder,
    all_stop_maximum_cabin_count: int,
) -> DddPreparedFixedKArcFlowRun:
    oip_artifact = replace(
        builder,
        fleet_config=EanFleetConfig(
            mode=EanFleetMode.OPTIMIZED_INITIAL_PLACEMENT,
            available_fleet_count=config.cabin_count,
            cardinality_mode=EanFleetCardinalityMode.EXACT,
        ),
        headway_resource_reduction_mode=HeadwayResourceReductionMode.DISABLED,
    ).build(scenario, ean_config)
    oip_problem = (
        EanArtifactToDddMovementProblemAdapter().build_trajectory_problem(
            oip_artifact
        )
    )
    balanced = DddBalancedReferenceStartBuilder(
        time_limit_seconds=min(
            config.start_layout_time_limit_seconds,
            config.total_time_limit_seconds,
        ),
    ).build(
        problem=oip_problem,
        artifact=oip_artifact,
    )
    oip_seed = balanced.seed
    oip_trajectories = balanced.trajectories
    starts, boundary_context, retained_visit_index_by_cabin = (
        _fixed_snapshot_from_oip_seed(
            oip_artifact=oip_artifact,
            oip_seed=oip_seed,
            oip_trajectories=oip_trajectories,
        )
    )
    fixed_artifact = replace(
        builder,
        start_builder=ExplicitEanCabinStartBuilder(starts),
        fleet_config=EanFleetConfig(mode=EanFleetMode.FIXED_STARTS),
        headway_resource_reduction_mode=HeadwayResourceReductionMode.DISABLED,
    ).build(scenario, ean_config)
    problem = _fixed_k_problem_from_artifact(
        config=config,
        scenario=scenario,
        artifact=fixed_artifact,
        boundary_context=boundary_context,
    )
    seed_trajectories = _fixed_seed_from_oip_trajectories(
        problem=problem,
        oip_trajectories=oip_trajectories,
        retained_visit_index_by_cabin=retained_visit_index_by_cabin,
    )
    return DddPreparedFixedKArcFlowRun(
        scenario=scenario,
        problem=problem,
        all_stop_maximum_cabin_count=all_stop_maximum_cabin_count,
        start_layout_kind="periodic_balanced_reference",
        start_layout_service_station_count=balanced.served_station_count,
        start_layout_candidate_count=balanced.candidate_count,
        start_layout_incompatibility_pair_count=(
            balanced.incompatibility_pair_count
        ),
        start_layout_minimum_station_stop_count=(
            balanced.minimum_station_stop_count
        ),
        start_layout_maximum_service_gap_seconds=(
            balanced.maximum_station_service_gap_seconds
        ),
        start_layout_seconds=balanced.solve_seconds,
        start_layout_objective_proven=balanced.objective_proven,
        seed_trajectories=seed_trajectories,
    )


def _fixed_snapshot_from_oip_seed(
    *,
    oip_artifact,
    oip_seed,
    oip_trajectories: tuple[DddReferenceTrajectory, ...],
) -> tuple[
    tuple[EanCabinStart, ...],
    DddFixedKBoundaryContext,
    dict[int, int],
]:
    if oip_seed.fleet_plan is None:
        raise ValueError("balanced reference seed has no fleet plan")
    ean_by_cabin = {
        trajectory.cabin_id: trajectory
        for trajectory in oip_seed.movement_plan.trajectories
    }
    oip_by_cabin = {trajectory.cabin_id: trajectory for trajectory in oip_trajectories}
    starts: list[EanCabinStart] = []
    retained_visit_index_by_cabin: dict[int, int] = {}
    boundary_occurrences: dict[
        tuple[object, ...], DddReferenceResourceOccurrence
    ] = {}
    resources = (
        EanArtifactToDddMovementProblemAdapter()
        .build_trajectory_problem(oip_artifact)
        .movement_core.resources_by_id
    )
    for cabin_id in sorted(oip_seed.fleet_plan.active_cabin_ids):
        ean_trajectory = ean_by_cabin[cabin_id]
        first = next(
            (
                visit
                for visit in ean_trajectory.visits
                if visit.switch_time_seconds >= -1e-9
            ),
            None,
        )
        if first is None:
            raise ValueError("balanced reference has no post-boundary visit")
        retained_visit_index_by_cabin[cabin_id] = first.visit_index
        starts.append(
            EanCabinStart(
                cabin_id=cabin_id,
                first_switch_id=first.switch_id,
                kind=EanCabinStartKind.FIXED,
                time_seconds=max(0.0, first.switch_time_seconds),
            )
        )
        trajectory = oip_by_cabin[cabin_id]
        for occurrence in trajectory.resource_occurrences:
            resource = resources[occurrence.resource_id]
            clear_with_headway = (
                occurrence.leader_clear_time_seconds
                + (
                    occurrence.separation_after_seconds
                    if occurrence.separation_after_seconds is not None
                    else resource.minimum_headway_seconds
                )
            )
            belongs_to_omitted_prefix = occurrence.visit_index < first.visit_index
            if not (
                clear_with_headway > 1e-9
                and (belongs_to_omitted_prefix or occurrence.boundary_origin)
            ):
                continue
            candidate = DddReferenceResourceOccurrence(
                    resource_id=occurrence.resource_id,
                    cabin_id=cabin_id,
                    visit_index=occurrence.visit_index,
                    leader_clear_time_seconds=occurrence.leader_clear_time_seconds,
                    follower_enter_time_seconds=(
                        occurrence.follower_enter_time_seconds
                    ),
                    separation_after_seconds=occurrence.separation_after_seconds,
                    boundary_only=occurrence.boundary_only,
                    boundary_origin=True,
                )
            key = (
                candidate.resource_id,
                candidate.cabin_id,
                candidate.leader_clear_time_seconds,
                candidate.follower_enter_time_seconds,
                candidate.separation_after_seconds,
            )
            previous = boundary_occurrences.get(key)
            if previous is None or (previous.boundary_only and not candidate.boundary_only):
                boundary_occurrences[key] = candidate
    context = DddFixedKBoundaryContext(
        initial_states=tuple(
            sorted(
                oip_seed.fleet_plan.initial_states,
                key=lambda state: state.cabin_id,
            )
        ),
        resource_occurrences=tuple(
            sorted(
                boundary_occurrences.values(),
                key=lambda item: (
                    item.resource_id,
                    item.follower_enter_time_seconds,
                    item.cabin_id,
                    item.visit_index,
                ),
            )
        ),
        source="periodic_balanced_reference",
    )
    return tuple(starts), context, retained_visit_index_by_cabin


def _fixed_seed_from_oip_trajectories(
    *,
    problem: DddFixedKTrajectoryProblem,
    oip_trajectories: tuple[DddReferenceTrajectory, ...],
    retained_visit_index_by_cabin: dict[int, int],
) -> tuple[DddReferenceTrajectory, ...]:
    movement = problem.resolved_trajectory_problem.structural_movement_problem
    starts = {start.cabin_id: start for start in movement.starts}
    options = {option.id: option for option in movement.route_options}
    boundary_by_cabin: dict[int, list[DddReferenceResourceOccurrence]] = {}
    for occurrence in problem.boundary_context.resource_occurrences:
        boundary_by_cabin.setdefault(occurrence.cabin_id, []).append(occurrence)
    result: list[DddReferenceTrajectory] = []
    for source in sorted(oip_trajectories, key=lambda item: item.cabin_id):
        retained_index = retained_visit_index_by_cabin[source.cabin_id]
        retained = tuple(
            visit for visit in source.visits if visit.visit_index >= retained_index
        )
        visits = tuple(
            build_ddd_reference_visit(
                start=starts[source.cabin_id],
                visit_index=new_index,
                switch_time_seconds=visit.switch_time_seconds,
                option=options[visit.route_option_id],
                operational_end_seconds=movement.operational_end_seconds,
                tolerance_seconds=1e-9,
            )
            for new_index, visit in enumerate(retained)
        )
        result.append(
            DddReferenceTrajectory(
                cabin_id=source.cabin_id,
                visits=visits,
                boundary_resource_occurrences=tuple(
                    boundary_by_cabin.get(source.cabin_id, ())
                ),
            )
        )
    solution = DddReferenceSolution(tuple(result))
    validate_ddd_reference_solution(movement, solution)
    return solution.trajectories


def run_ddd_fixed_k_arc_flow(
    config: DddFixedKArcFlowRunConfig,
    *,
    progress_hook: Callable[[DddFixedKArcFlowProgress], None] | None = None,
) -> DddFixedKArcFlowRunResult:
    config.validate()
    started = perf_counter()
    prepared = prepare_ddd_fixed_k_arc_flow_run(config)
    scenario, problem = prepared.scenario, prepared.problem
    setup_seconds = perf_counter() - started
    movement = problem.resolved_trajectory_problem.structural_movement_problem
    network_problem = build_initial_ddd_network_problem(movement)

    if prepared.seed_trajectories:
        seed_trajectories = prepared.seed_trajectories
        seed_status = DddFixedKSeedStatus.FEASIBLE.value
        seed_kind = prepared.start_layout_kind
        seed_seconds = 0.0
    else:
        seed_result = DddFixedKSeedCoordinator(
            cp_sat_time_limit_seconds=max(config.cp_seed_time_limit_seconds, 0.001),
            cp_sat_num_workers=config.cp_seed_workers,
        ).solve(
            network_problem,
            boundary_occurrences=problem.boundary_context.resource_occurrences,
        )
        if seed_result.status is DddFixedKSeedStatus.INTERNAL_VALIDATION_ERROR:
            raise RuntimeError(seed_result.detail or "CP-SAT seed validation failed")
        seed_trajectories = (
            seed_result.trajectories
            if seed_result.status is DddFixedKSeedStatus.FEASIBLE
            else ()
        )
        seed_status = seed_result.status.value
        seed_kind = None if seed_result.kind is None else seed_result.kind.value
        seed_seconds = seed_result.cp_sat_seconds

    root_cg_lower_bound = _read_compatible_root_cg_lower_bound(
        config.root_cg_result_path,
        expected_fingerprint=problem.fingerprint,
    )
    remaining = config.total_time_limit_seconds - (perf_counter() - started)
    if remaining <= 0:
        raise TimeoutError("arc-flow setup and seed exhausted the total budget")
    solve_result = DddFixedKArcFlowOptimizer(
        DddFixedKArcFlowSolveConfig(
            time_limit_seconds=remaining,
            mip_gap=config.mip_gap,
            threads=config.solver_threads,
            seed=config.seed,
            mip_focus=config.mip_focus,
            output_flag=config.output_flag,
        )
    ).solve(
        problem,
        seed_trajectories=seed_trajectories,
        seed_kind=seed_kind,
        root_cg_lower_bound=root_cg_lower_bound,
        progress_hook=progress_hook,
    )
    validation_status = "not_run"
    validation_objective = None
    validation_seconds = 0.0
    remaining = config.total_time_limit_seconds - (perf_counter() - started)
    if solve_result.solution is not None and remaining > 0.01:
        validation_started = perf_counter()
        evaluation = DddEanPassengerPrimalEvaluator(
            scenario=scenario,
            artifact=problem.artifact,
            objective=problem.objective,
            time_limit_seconds=remaining,
            mip_gap=0.0,
            threads=1,
        ).evaluate(network_problem, solve_result.solution)
        validation_seconds = perf_counter() - validation_started
        validation_status = evaluation.status.value
        validation_objective = evaluation.objective_value
        if (
            evaluation.status is DddPrimalEvaluationStatus.FEASIBLE
            and evaluation.objective_value is not None
            and solve_result.objective_value is not None
        ):
            if not math.isclose(
                evaluation.objective_value,
                solve_result.objective_value,
                rel_tol=0.0,
                abs_tol=1e-4,
            ):
                raise RuntimeError(
                    "integrated arc-flow and independent EAN Passenger objectives differ: "
                    f"{solve_result.objective_value} != {evaluation.objective_value}"
                )
    return DddFixedKArcFlowRunResult(
        problem=problem,
        scenario=scenario,
        solve_result=solve_result,
        setup_seconds=setup_seconds,
        seed_status=seed_status,
        seed_seconds=seed_seconds,
        independent_validation_status=validation_status,
        independent_validation_objective=validation_objective,
        independent_validation_seconds=validation_seconds,
        total_seconds=perf_counter() - started,
        all_stop_maximum_cabin_count=prepared.all_stop_maximum_cabin_count,
        start_layout_kind=prepared.start_layout_kind,
        start_layout_cycle_seconds=prepared.start_layout_cycle_seconds,
        start_layout_bottleneck_headway_seconds=(
            prepared.start_layout_bottleneck_headway_seconds
        ),
        start_layout_service_station_count=(
            prepared.start_layout_service_station_count
        ),
        start_layout_candidate_count=prepared.start_layout_candidate_count,
        start_layout_incompatibility_pair_count=(
            prepared.start_layout_incompatibility_pair_count
        ),
        start_layout_minimum_station_stop_count=(
            prepared.start_layout_minimum_station_stop_count
        ),
        start_layout_maximum_service_gap_seconds=(
            prepared.start_layout_maximum_service_gap_seconds
        ),
        start_layout_seconds=prepared.start_layout_seconds,
        start_layout_objective_proven=(
            prepared.start_layout_objective_proven
        ),
    )


def write_ddd_fixed_k_arc_flow_result(
    result: DddFixedKArcFlowRunResult,
    path: Path,
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(result.to_payload(), indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _read_compatible_root_cg_lower_bound(
    path: Path | None,
    *,
    expected_fingerprint: str,
) -> float | None:
    if path is None:
        return None
    payload = json.loads(path.read_text(encoding="utf-8"))
    fingerprint = payload.get("fixed_k_problem_fingerprint")
    if fingerprint != expected_fingerprint:
        raise ValueError("Root-CG result fingerprint differs from arc-flow problem")
    value = payload.get("certified_lower_bound")
    if value is None or not math.isfinite(float(value)):
        raise ValueError("Root-CG result has no finite certified lower bound")
    return float(value)
