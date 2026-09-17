from __future__ import annotations

from dataclasses import asdict, dataclass, replace
from enum import StrEnum
import json
import math
from pathlib import Path
from time import perf_counter
from typing import Callable
from ropeway_skip_stop_optimization.optimization.ddd.arc_flow_passenger_formulation import DddArcFlowPassengerFormulationConfig

from ropeway_skip_stop_optimization.benchmarking.ddd_scaling import (
    build_initial_ddd_network_problem,
)
from ropeway_skip_stop_optimization.examples.registry import get_example
from ropeway_skip_stop_optimization.models import Scenario
from ropeway_skip_stop_optimization.optimization.headway_resource_reduction import (
    HeadwayResourceReductionMode,
)
from ropeway_skip_stop_optimization.optimization.ddd import (
    DddArcFlowResourceRowMode,
    DddFixedKArcFlowOptimizer,
    DddFixedKArcFlowProgress,
    DddFixedKArcFlowResult,
    DddFixedKArcFlowSolveConfig,
    DddFixedKArcFlowStatus,
    DddExactAnonymousArcFlowOptimizer,
    DddExactAnonymousArcFlowResult,
    DddBalancedReferenceStartBuilder,
    DddFixedKBoundaryContext,
    DddFixedKOperatingMode,
    DddFixedKSeedCoordinator,
    DddFixedKSeedStatus,
    DddFixedKStartPolicy,
    DddFixedKTrajectoryProblem,
    DddFixedKPrimalSeed,
    DddFixedKPrimalSeedFactory,
    DddEanPassengerPrimalEvaluator,
    DddPrimalEvaluationStatus,
    DddReferenceResourceOccurrence,
    DddReferenceSolution,
    DddReferenceTrajectory,
    EanArtifactToDddMovementProblemAdapter,
    build_ddd_reference_visit,
    load_ddd_fixed_k_root_cg_seed_trajectories,
    validate_ddd_reference_solution,
)
from ropeway_skip_stop_optimization.optimization.ean import (
    CanonicalFixedKRopeCabinStartBuilder,
    EanConfig,
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
    HeadwayCheckpointKind,
    StationWaitingMode,
    analyze_all_stop_start_capacity,
)


class DddFixedKArcFlowFormulation(StrEnum):
    LABELED = "labeled"
    EXACT_ANONYMOUS = "exact_anonymous"


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
    primal_seed_checkpoint_path: Path | None = None
    primal_seed_result_path: Path | None = None
    seed_passenger_time_limit_seconds: float = 60.0
    formulation: DddFixedKArcFlowFormulation = DddFixedKArcFlowFormulation.LABELED
    waiting_headway_multiplier: float = 0.0
    waiting_step_seconds: float = 1.0
    resource_row_mode: DddArcFlowResourceRowMode = (
        DddArcFlowResourceRowMode.EAGER_MAXIMAL_CLIQUES
    )
    passenger_formulation: DddArcFlowPassengerFormulationConfig = DddArcFlowPassengerFormulationConfig()
    require_full_service: bool = False
    horizon_seconds: float | None = None
    use_primal_start: bool = True

    def validate(self) -> None:
        if not self.example_id or self.cabin_count <= 0:
            raise ValueError("arc-flow run needs an example and positive K")
        if not isinstance(self.operating_mode, DddFixedKOperatingMode):
            raise ValueError("arc-flow run operating mode is invalid")
        if not isinstance(self.objective, EanPassengerObjective):
            raise ValueError("arc-flow run objective is invalid")
        if not isinstance(self.start_policy, DddFixedKStartPolicy):
            raise ValueError("arc-flow run start policy is invalid")
        if not isinstance(self.formulation, DddFixedKArcFlowFormulation):
            raise ValueError("arc-flow run formulation is invalid")
        if self.formulation is not DddFixedKArcFlowFormulation.LABELED and self.passenger_formulation.profile != "legacy":
            raise ValueError("passenger profiles are available only for labeled arc-flow")
        if not isinstance(self.resource_row_mode, DddArcFlowResourceRowMode):
            raise ValueError("arc-flow resource-row mode is invalid")
        if type(self.require_full_service) is not bool:
            raise ValueError("require_full_service must be boolean")
        if type(self.use_primal_start) is not bool:
            raise ValueError("use_primal_start must be boolean")
        if not self.use_primal_start and (
            self.primal_seed_checkpoint_path is not None
            or self.primal_seed_result_path is not None
        ):
            raise ValueError("external primal starts require use_primal_start")
        if self.horizon_seconds is not None and (
            not math.isfinite(self.horizon_seconds) or self.horizon_seconds <= 0
        ):
            raise ValueError("arc-flow horizon override must be positive")
        if (
            self.formulation is DddFixedKArcFlowFormulation.EXACT_ANONYMOUS
            and self.resource_row_mode
            is not DddArcFlowResourceRowMode.EAGER_MAXIMAL_CLIQUES
        ):
            raise ValueError(
                "delayed selected cliques are available only for labeled arc-flow"
            )
        if (
            self.total_time_limit_seconds <= 0
            or self.cp_seed_time_limit_seconds < 0
            or self.start_layout_time_limit_seconds <= 0
            or self.seed_passenger_time_limit_seconds <= 0
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
        if (
            not math.isfinite(self.waiting_headway_multiplier)
            or self.waiting_headway_multiplier < 0
            or not math.isfinite(self.waiting_step_seconds)
            or self.waiting_step_seconds <= 0
        ):
            raise ValueError("arc-flow waiting controls are invalid")


@dataclass(frozen=True, slots=True)
class DddFixedKArcFlowRunResult:
    problem: DddFixedKTrajectoryProblem
    scenario: Scenario
    solve_result: DddFixedKArcFlowResult | DddExactAnonymousArcFlowResult
    formulation: DddFixedKArcFlowFormulation
    setup_seconds: float
    seed_status: str
    seed_seconds: float
    independent_validation_status: str
    independent_validation_objective: float | None
    independent_validation_seconds: float
    total_seconds: float
    validated_passenger_plan: dict | None = None
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
    waiting_headway_multiplier: float = 0.0
    waiting_reference_headway_seconds_by_station_id: tuple[tuple[str, float], ...] = ()
    resource_row_mode: DddArcFlowResourceRowMode = (
        DddArcFlowResourceRowMode.EAGER_MAXIMAL_CLIQUES
    )

    def to_payload(self) -> dict[str, object]:
        raw = asdict(self.solve_result)
        raw.pop("solution", None)
        raw["status"] = self.solve_result.status.value
        if isinstance(self.solve_result, DddExactAnonymousArcFlowResult):
            raw["movement_compression_ratio"] = (
                self.solve_result.movement_compression_ratio
            )
        raw.update(
            {
                "example_id": self.scenario.id,
                "fixed_k_problem_manifest": self.problem.certificate_manifest,
                "proof_scope": "FIXED_K_GLOBAL",
                "validated_passenger_plan": self.validated_passenger_plan,
                "exact_active_cabin_count": self.problem.fleet_cardinality,
                "operating_mode": self.problem.operating_mode.value,
                "objective": self.problem.objective.value,
                "formulation": self.formulation.value,
                "resource_row_mode": self.resource_row_mode.value,
                "start_policy": self.problem.start_policy.value,
                "start_layout_kind": self.start_layout_kind,
                "all_stop_maximum_cabin_count": (self.all_stop_maximum_cabin_count),
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
                "start_layout_objective_proven": (self.start_layout_objective_proven),
                "waiting_headway_multiplier": self.waiting_headway_multiplier,
                "waiting_policy": {
                    "domain": (
                        self.problem.resolved_trajectory_problem.waiting_policy.domain.value
                    ),
                    "step_seconds": (
                        self.problem.resolved_trajectory_problem.waiting_policy.step_seconds
                    ),
                    "reference_headway_seconds_by_station_id": dict(
                        self.waiting_reference_headway_seconds_by_station_id
                    ),
                    "maximum_wait_seconds_by_station_id": dict(
                        self.problem.resolved_trajectory_problem.waiting_policy.maximum_wait_seconds_by_station_id
                    ),
                },
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
                        "wait_seconds": [
                            visit.wait_seconds for visit in trajectory.visits
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
    waiting_reference_headway_seconds_by_station_id: tuple[tuple[str, float], ...] = ()


class DddAnalyticAllStopInfeasible(ValueError):
    def __init__(self, *, cabin_count: int, maximum_cabin_count: int) -> None:
        self.cabin_count = cabin_count
        self.maximum_cabin_count = maximum_cabin_count
        super().__init__(
            "exact-K all-stop is analytically infeasible: "
            f"K={cabin_count} > K_max_AS={maximum_cabin_count}"
        )


def _headway_scaled_waiting_config(
    *,
    scenario: Scenario,
    builder: NetworkEanBuildArtifactBuilder,
    ean_config: EanConfig,
    multiplier: float,
    step_seconds: float,
) -> tuple[EanConfig, tuple[tuple[str, float], ...]]:
    """Derive station wait caps from local exit-merge headways.

    The requested multiplier is rounded upward to the configured DDD time grid,
    so a nominal policy such as ``0.5 h`` is never made smaller by
    discretization.
    """

    no_wait_config = replace(
        ean_config,
        station_configs=tuple(
            replace(
                station,
                waiting_mode=StationWaitingMode.NO_WAITING,
                fifo_capacity=None,
                max_wait_seconds=None,
            )
            for station in ean_config.station_configs
        ),
    )
    probe = replace(
        builder,
        start_builder=EvenlySpacedAllStopCabinStartBuilder(1),
    ).build(scenario, no_wait_config)
    headway_by_station: dict[str, float] = {}
    for checkpoint in probe.headway_checkpoints:
        if checkpoint.kind is not HeadwayCheckpointKind.EXIT_SWITCH:
            continue
        headway = probe.headway_rule_for_checkpoint(checkpoint).maximum_seconds
        headway_by_station[checkpoint.station_id] = max(
            headway,
            headway_by_station.get(checkpoint.station_id, 0.0),
        )
    missing = tuple(
        sorted(
            {station.station_id for station in ean_config.station_configs}
            - set(headway_by_station)
        )
    )
    if missing:
        raise ValueError(
            "headway-scaled waiting needs one exit-switch headway per station: "
            f"{missing}"
        )
    reference = tuple(sorted(headway_by_station.items()))
    if multiplier == 0:
        return no_wait_config, reference
    maximum_by_station = {
        station_id: max(
            step_seconds,
            math.ceil(multiplier * headway / step_seconds - 1e-12) * step_seconds,
        )
        for station_id, headway in reference
    }
    result = replace(
        ean_config,
        station_configs=tuple(
            replace(
                station,
                waiting_mode=StationWaitingMode.END_OF_PLATFORM_WAIT,
                fifo_capacity=None,
                max_wait_seconds=maximum_by_station[station.station_id],
            )
            for station in ean_config.station_configs
        ),
    )
    result.validate()
    return result, reference


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
    if config.horizon_seconds is not None:
        ean_config = replace(ean_config, horizon_seconds=config.horizon_seconds)
        ean_config.validate()
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
    ean_config, waiting_reference_headways = _headway_scaled_waiting_config(
        scenario=scenario,
        builder=builder,
        ean_config=ean_config,
        multiplier=config.waiting_headway_multiplier,
        step_seconds=config.waiting_step_seconds,
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
            waiting_reference_headway_seconds_by_station_id=(
                waiting_reference_headways
            ),
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
            boundary_context=DddFixedKBoundaryContext(source="evenly_spaced_all_stop"),
        )
        return DddPreparedFixedKArcFlowRun(
            scenario=scenario,
            problem=problem,
            all_stop_maximum_cabin_count=analysis.maximum_cabin_count,
            start_layout_kind="evenly_spaced_all_stop",
            start_layout_cycle_seconds=analysis.cycle_seconds,
            start_layout_bottleneck_headway_seconds=(analysis.limiting_headway_seconds),
            start_layout_service_station_count=len(artifact.timings),
            waiting_reference_headway_seconds_by_station_id=(
                waiting_reference_headways
            ),
        )
    if config.operating_mode is DddFixedKOperatingMode.ALL_STOP:
        raise DddAnalyticAllStopInfeasible(
            cabin_count=config.cabin_count,
            maximum_cabin_count=analysis.maximum_cabin_count,
        )

    prepared = _prepare_periodic_balanced_skip_stop_problem(
        config=config,
        scenario=scenario,
        ean_config=ean_config,
        builder=builder,
        all_stop_maximum_cabin_count=analysis.maximum_cabin_count,
    )
    return replace(
        prepared,
        waiting_reference_headway_seconds_by_station_id=(waiting_reference_headways),
    )


def _fixed_k_problem_from_artifact(
    *,
    config: DddFixedKArcFlowRunConfig,
    scenario: Scenario,
    artifact,
    boundary_context: DddFixedKBoundaryContext,
) -> DddFixedKTrajectoryProblem:
    trajectory_problem = EanArtifactToDddMovementProblemAdapter(
        waiting_step_seconds=config.waiting_step_seconds
    ).build_trajectory_problem(artifact)
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
    oip_problem = EanArtifactToDddMovementProblemAdapter(
        waiting_step_seconds=config.waiting_step_seconds
    ).build_trajectory_problem(oip_artifact)
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
            waiting_step_seconds=config.waiting_step_seconds,
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
        start_layout_incompatibility_pair_count=(balanced.incompatibility_pair_count),
        start_layout_minimum_station_stop_count=(balanced.minimum_station_stop_count),
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
    waiting_step_seconds: float = 1.0,
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
    boundary_occurrences: dict[tuple[object, ...], DddReferenceResourceOccurrence] = {}
    resources = (
        EanArtifactToDddMovementProblemAdapter(
            waiting_step_seconds=waiting_step_seconds
        )
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
            clear_with_headway = occurrence.leader_clear_time_seconds + (
                occurrence.separation_after_seconds
                if occurrence.separation_after_seconds is not None
                else resource.minimum_headway_seconds
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
                follower_enter_time_seconds=(occurrence.follower_enter_time_seconds),
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
            if previous is None or (
                previous.boundary_only and not candidate.boundary_only
            ):
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


def _load_ddd_fixed_k_arc_flow_result_seed(
    path: Path,
    *,
    problem: DddFixedKTrajectoryProblem,
) -> tuple[tuple[DddReferenceTrajectory, ...], float | None]:
    """Load one complete earlier arc-flow timetable across waiting domains."""

    payload = json.loads(path.read_text(encoding="utf-8"))
    expected_metadata = {
        "example_id": problem.artifact.scenario_id,
        "exact_active_cabin_count": problem.fleet_cardinality,
        "operating_mode": problem.operating_mode.value,
        "start_policy": problem.start_policy.value,
        "objective": problem.objective.value,
    }
    for key, expected in expected_metadata.items():
        if payload.get(key) != expected:
            raise ValueError(f"arc-flow primal seed has incompatible {key}")
    raw_supports = payload.get("trajectory_supports")
    if not isinstance(raw_supports, list) or not raw_supports:
        raise ValueError("arc-flow primal seed contains no trajectory supports")
    movement = problem.resolved_trajectory_problem.structural_movement_problem
    starts = {start.cabin_id: start for start in movement.starts}
    options = {option.id: option for option in movement.route_options}
    trajectories: list[DddReferenceTrajectory] = []
    for raw in raw_supports:
        cabin_id = int(raw["cabin_id"])
        route_option_ids = tuple(str(item) for item in raw["route_option_ids"])
        switch_times = tuple(float(item) for item in raw["switch_times_seconds"])
        waits = tuple(float(item) for item in raw["wait_seconds"])
        if not (
            len(route_option_ids) == len(switch_times) == len(waits)
            and route_option_ids
        ):
            raise ValueError("arc-flow primal-seed support dimensions differ")
        try:
            start = starts[cabin_id]
            visits = tuple(
                build_ddd_reference_visit(
                    start=start,
                    visit_index=visit_index,
                    switch_time_seconds=switch_time,
                    option=options[option_id],
                    operational_end_seconds=movement.operational_end_seconds,
                    tolerance_seconds=1e-9,
                    wait_seconds=wait_seconds,
                )
                for visit_index, (option_id, switch_time, wait_seconds) in enumerate(
                    zip(route_option_ids, switch_times, waits, strict=True)
                )
            )
        except KeyError as error:
            raise ValueError(
                "arc-flow primal seed references an unknown cabin or route"
            ) from error
        trajectories.append(DddReferenceTrajectory(cabin_id, visits))
    result = tuple(sorted(trajectories, key=lambda item: item.cabin_id))
    validate_ddd_reference_solution(
        movement,
        DddReferenceSolution(result),
        waiting_policy=problem.resolved_trajectory_problem.waiting_policy,
    )
    expected_cabins = problem.resolved_trajectory_problem.cabin_ids
    if tuple(item.cabin_id for item in result) != expected_cabins:
        raise ValueError(
            "arc-flow primal seed does not contain every cabin exactly once"
        )
    raw_upper_bound = payload.get("validated_upper_bound")
    upper_bound = (
        float(raw_upper_bound) if isinstance(raw_upper_bound, (int, float)) else None
    )
    return result, upper_bound


def _validate_prepared_run_compatibility(
    config: DddFixedKArcFlowRunConfig,
    prepared: DddPreparedFixedKArcFlowRun,
) -> None:
    problem = prepared.problem
    mismatches: list[str] = []
    if prepared.scenario.id != config.example_id:
        mismatches.append(f"scenario {prepared.scenario.id!r} != {config.example_id!r}")
    if problem.fleet_cardinality != config.cabin_count:
        mismatches.append(f"K {problem.fleet_cardinality} != {config.cabin_count}")
    if problem.operating_mode is not config.operating_mode:
        mismatches.append(
            f"mode {problem.operating_mode.value!r} != {config.operating_mode.value!r}"
        )
    if problem.objective is not config.objective:
        mismatches.append(
            f"objective {problem.objective.value!r} != {config.objective.value!r}"
        )
    if problem.start_policy is not config.start_policy:
        mismatches.append(
            f"start policy {problem.start_policy.value!r} != {config.start_policy.value!r}"
        )
    if mismatches:
        raise ValueError(
            "prepared fixed-K run is incompatible with solve config: "
            + "; ".join(mismatches)
        )


def run_ddd_fixed_k_arc_flow(
    config: DddFixedKArcFlowRunConfig,
    *,
    progress_hook: Callable[[DddFixedKArcFlowProgress], None] | None = None,
    prepared_run: DddPreparedFixedKArcFlowRun | None = None,
) -> DddFixedKArcFlowRunResult:
    config.validate()
    started = perf_counter()
    prepared = prepared_run or prepare_ddd_fixed_k_arc_flow_run(config)
    _validate_prepared_run_compatibility(config, prepared)
    scenario, problem = prepared.scenario, prepared.problem
    setup_seconds = perf_counter() - started
    movement = problem.resolved_trajectory_problem.structural_movement_problem
    network_problem = build_initial_ddd_network_problem(movement)

    seed_candidates: list[
        tuple[str, tuple[DddReferenceTrajectory, ...], float | None]
    ] = []
    if not config.use_primal_start:
        seed_trajectories = ()
        seed_status, seed_kind, seed_seconds = "disabled", None, 0.0
    elif prepared.seed_trajectories:
        seed_trajectories = prepared.seed_trajectories
        seed_status = DddFixedKSeedStatus.FEASIBLE.value
        seed_kind = prepared.start_layout_kind
        seed_seconds = 0.0
        seed_candidates.append((seed_kind, seed_trajectories, None))
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
        if seed_trajectories:
            seed_candidates.append((seed_kind or "cp_sat", seed_trajectories, None))

    if config.primal_seed_checkpoint_path is not None:
        checkpoint_trajectories, checkpoint_upper_bound = (
            load_ddd_fixed_k_root_cg_seed_trajectories(
                config.primal_seed_checkpoint_path,
                problem=problem,
            )
        )
        seed_candidates.append(
            ("root_cg_checkpoint", checkpoint_trajectories, checkpoint_upper_bound)
        )
    if config.primal_seed_result_path is not None:
        result_trajectories, result_upper_bound = (
            _load_ddd_fixed_k_arc_flow_result_seed(
                config.primal_seed_result_path,
                problem=problem,
            )
        )
        seed_candidates.append(
            ("arc_flow_result", result_trajectories, result_upper_bound)
        )

    primal_seed: DddFixedKPrimalSeed | None = None
    seed_evaluation_started = perf_counter()
    for provenance, trajectories, expected_upper_bound in seed_candidates:
        remaining_seed_budget = config.total_time_limit_seconds - (
            perf_counter() - started
        )
        if remaining_seed_budget <= 0.01:
            break
        candidate = DddFixedKPrimalSeedFactory(
            scenario=scenario,
            problem=problem,
            network_problem=network_problem,
            passenger_time_limit_seconds=min(
                config.seed_passenger_time_limit_seconds,
                remaining_seed_budget,
            ),
            threads=1,
        ).build(
            trajectories,
            provenance=provenance,
        )
        if (
            expected_upper_bound is not None
            and candidate.objective_value > expected_upper_bound + 1e-4
        ):
            raise RuntimeError(
                "re-evaluated external seed is worse than its stored validated UB"
            )
        if (
            primal_seed is None
            or candidate.objective_value < primal_seed.objective_value - 1e-4
        ):
            primal_seed = candidate
    seed_seconds += perf_counter() - seed_evaluation_started
    if primal_seed is not None:
        seed_trajectories = primal_seed.solution.trajectories
        seed_kind = primal_seed.provenance

    root_cg_lower_bound = _read_compatible_root_cg_lower_bound(
        config.root_cg_result_path,
        expected_problem=problem,
    )
    remaining = config.total_time_limit_seconds - (perf_counter() - started)
    if remaining <= 0:
        raise TimeoutError("arc-flow setup and seed exhausted the total budget")
    validation_reserve = min(
        config.seed_passenger_time_limit_seconds,
        max(1.0, 0.1 * remaining),
    )
    solve_budget = max(0.001, remaining - validation_reserve)
    solve_config = DddFixedKArcFlowSolveConfig(
        passenger_formulation=config.passenger_formulation,
        time_limit_seconds=solve_budget,
        mip_gap=config.mip_gap,
        threads=config.solver_threads,
        seed=config.seed,
        mip_focus=config.mip_focus,
        output_flag=config.output_flag,
        resource_row_mode=config.resource_row_mode,
        require_full_service=config.require_full_service,
    )
    if config.formulation is DddFixedKArcFlowFormulation.EXACT_ANONYMOUS:
        solve_result = DddExactAnonymousArcFlowOptimizer(solve_config).solve(
            problem,
            primal_seed=primal_seed,
            root_cg_lower_bound=root_cg_lower_bound,
            progress_hook=progress_hook,
        )
    else:
        solve_result = DddFixedKArcFlowOptimizer(solve_config).solve(
            problem,
            seed_trajectories=seed_trajectories,
            primal_seed=primal_seed,
            seed_kind=seed_kind,
            root_cg_lower_bound=root_cg_lower_bound,
            progress_hook=progress_hook,
        )
    validation_status = "not_run"
    validation_objective = None
    validation_seconds = 0.0
    validated_passenger_plan = None
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
            waiting_policy=problem.resolved_trajectory_problem.waiting_policy,
            passenger_candidate_build=problem.passenger_build,
            require_full_service=config.require_full_service,
        ).evaluate(network_problem, solve_result.solution)
        validation_seconds = perf_counter() - validation_started
        validation_status = evaluation.status.value
        validation_objective = evaluation.objective_value
        if evaluation.status is DddPrimalEvaluationStatus.FEASIBLE:
            if config.require_full_service and evaluation.unserved_passenger_count != 0:
                raise RuntimeError("full-service validation returned unserved passengers")
            validated_passenger_plan = asdict(evaluation.passenger_plan) if evaluation.passenger_plan is not None else None
        if (
            evaluation.status is DddPrimalEvaluationStatus.FEASIBLE
            and evaluation.objective_value is not None
            and solve_result.objective_value is not None
        ):
            if evaluation.objective_value < solve_result.certified_lower_bound - 1e-4:
                raise RuntimeError(
                    "independent passenger solution violates the global arc-flow bound: "
                    f"{solve_result.certified_lower_bound} > {evaluation.objective_value}"
                )
            if abs(evaluation.objective_value - solve_result.objective_value) > 1e-4:
                solve_result = replace(
                    solve_result,
                    status=DddFixedKArcFlowStatus.TIME_LIMIT_WITH_CERTIFIED_INTERVAL,
                    objective_value=evaluation.objective_value,
                    validated_upper_bound=evaluation.objective_value,
                    relative_gap=max(
                        0.0,
                        evaluation.objective_value - solve_result.certified_lower_bound,
                    )
                    / max(abs(evaluation.objective_value), 1e-9),
                    detail=(
                        "independent Passenger recourse returned a valid incumbent "
                        "different from the integrated incumbent assignment"
                    ),
                )
        elif solve_result.solution is not None and (
            primal_seed is None or solve_result.solution != primal_seed.solution
        ):
            if primal_seed is None:
                solve_result = replace(
                    solve_result,
                    status=DddFixedKArcFlowStatus.UNKNOWN_NO_INCUMBENT,
                    objective_value=None,
                    validated_upper_bound=None,
                    relative_gap=None,
                    solution=None,
                    detail="independent Passenger validation found no incumbent",
                )
            else:
                solve_result = replace(
                    solve_result,
                    status=DddFixedKArcFlowStatus.TIME_LIMIT_WITH_CERTIFIED_INTERVAL,
                    objective_value=primal_seed.objective_value,
                    validated_upper_bound=primal_seed.objective_value,
                    relative_gap=max(
                        0.0,
                        primal_seed.objective_value
                        - solve_result.certified_lower_bound,
                    )
                    / max(abs(primal_seed.objective_value), 1e-9),
                    solution=primal_seed.solution,
                    detail="solver incumbent failed independent Passenger validation",
                )
    return DddFixedKArcFlowRunResult(
        problem=problem,
        scenario=scenario,
        solve_result=solve_result,
        formulation=config.formulation,
        setup_seconds=setup_seconds,
        seed_status=seed_status,
        seed_seconds=seed_seconds,
        independent_validation_status=validation_status,
        independent_validation_objective=validation_objective,
        independent_validation_seconds=validation_seconds,
        total_seconds=perf_counter() - started,
        validated_passenger_plan=validated_passenger_plan,
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
        start_layout_objective_proven=(prepared.start_layout_objective_proven),
        waiting_headway_multiplier=config.waiting_headway_multiplier,
        waiting_reference_headway_seconds_by_station_id=(
            prepared.waiting_reference_headway_seconds_by_station_id
        ),
        resource_row_mode=config.resource_row_mode,
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
    expected_problem: DddFixedKTrajectoryProblem,
) -> float | None:
    if path is None:
        return None
    payload = json.loads(path.read_text(encoding="utf-8"))
    from hashlib import sha256

    if payload.get("certificate_valid") is not True:
        raise ValueError("Root-CG lower bound requires an explicitly valid certificate")
    if payload.get("proof_scope") != "FIXED_K_GLOBAL":
        raise ValueError("Root-CG lower bound has missing or incompatible proof scope")
    manifest = payload.get("fixed_k_problem_manifest")
    if not isinstance(manifest, dict) or manifest.get("schema") != "fixed_k_problem_v2":
        raise ValueError("Legacy Root-CG lower bound lacks a full versioned manifest")
    fingerprint = sha256(
        json.dumps(
            manifest,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode()
    ).hexdigest()
    if (
        fingerprint != expected_problem.fingerprint
        or payload.get("fixed_k_problem_fingerprint") != fingerprint
    ):
        raise ValueError("Root-CG result fingerprint differs from arc-flow problem")
    if payload.get("status") not in {
        "optimal_root_lp",
        "integer_optimal",
        "root_lp_certified_with_integer_gap",
        "time_limit",
        "iteration_limit",
        "time_limit_with_certified_interval",
        "iteration_limit_with_certified_interval",
    }:
        raise ValueError("Root-CG lower bound has an unsupported certificate status")
    value = payload.get("certified_lower_bound")
    if type(value) not in (int, float) or not math.isfinite(value):
        raise ValueError("Root-CG result has no finite certified lower bound")
    return float(value)
