from __future__ import annotations

import logging
import math
from dataclasses import asdict, dataclass, field, replace
from enum import StrEnum
from pathlib import Path
from time import perf_counter
from typing import Any

from ropeway_skip_stop_optimization.models import Scenario
from ropeway_skip_stop_optimization.optimization.ean.artifact import EanBuildArtifact
from ropeway_skip_stop_optimization.optimization.ean.build_profile import (
    EanArtifactBuildMetrics,
    EanBuildProgressCallback,
    EanBuildProgressKind,
    EanBuildStage,
    emit_build_progress,
    peak_rss_bytes,
)
from ropeway_skip_stop_optimization.optimization.ean.builders.passenger_builder import (
    EanPassengerCandidateBuilder,
)
from ropeway_skip_stop_optimization.optimization.ean.formulation_config import (
    EanBoardTimeFormulation,
    EanHorizonFormulation,
)
from ropeway_skip_stop_optimization.optimization.ean.headway_separator import (
    EanHeadwayViolation,
    separate_all_headway_violations,
)
from ropeway_skip_stop_optimization.optimization.ean.fleet import EanFleetPlan
from ropeway_skip_stop_optimization.optimization.ean.models import EanHeadwayPairScope
from ropeway_skip_stop_optimization.optimization.ean.optimizers.fixed_movement_passenger_model import (
    EanFixedMovementPassengerModel,
    EanFixedMovementPassengerModelBuilder,
    EanPassengerAssignment,
    EanPassengerAssignmentDomain,
)
from ropeway_skip_stop_optimization.optimization.ean.optimizers.all_stop_mip_start import (
    EanAllStopMipStartSeed,
    EanAllStopMipStartSeedBuilder,
)
from ropeway_skip_stop_optimization.optimization.ean.optimization_config import (
    EanOptimizationConfig,
)
from ropeway_skip_stop_optimization.optimization.ean.optimizers.movement_model import (
    EanMovementModel,
    EanMovementModelBuilder,
)
from ropeway_skip_stop_optimization.optimization.ean.optimizers.passenger_model import (
    EanPassengerModel,
    EanPassengerModelBuilder,
    EanPassengerObjective,
)
from ropeway_skip_stop_optimization.optimization.ean.optimizers.solver_policy import (
    GurobiSolverPolicy,
    apply_gurobi_solver_policy,
)
from ropeway_skip_stop_optimization.optimization.ean.passenger_plan import (
    EanPassengerServicePlan,
)
from ropeway_skip_stop_optimization.optimization.ean.plan import (
    EanMovementPlan,
    EanRouteDecision,
)
from ropeway_skip_stop_optimization.optimization.ean.validation import (
    validate_ean_movement_plan_against_artifact,
)
from ropeway_skip_stop_optimization.optimization.solver_progress import (
    GurobiMipProgressSample,
    GurobiSolvePhaseMetrics,
)


LOGGER = logging.getLogger(__name__)


class EanOptimizationProblemKind(StrEnum):
    MOVEMENT_FEASIBILITY = "movement_feasibility"
    PASSENGER_SERVICE = "passenger_service"
    FIXED_MOVEMENT_PASSENGER = "fixed_movement_passenger"


class EanMipStartStrategy(StrEnum):
    """Primal-start strategy for integrated passenger-service solves."""

    AUTO = "auto"
    NONE = "none"
    GREEDY_ALL_STOP = "greedy_all_stop"
    OPTIMIZED_ALL_STOP = "optimized_all_stop"


@dataclass(frozen=True)
class GurobiCheckpointConfig:
    """Filesystem checkpoints containing incumbent starts, not solver trees."""

    read_solution_path: Path | None = None
    solution_file_prefix: Path | None = None
    final_solution_path: Path | None = None

    def validate(self) -> None:
        if self.read_solution_path is not None and not self.read_solution_path.exists():
            raise ValueError(
                f"checkpoint read solution does not exist: {self.read_solution_path}"
            )
        if self.solution_file_prefix is not None and not self.solution_file_prefix.name:
            raise ValueError(
                "checkpoint solution file prefix must include a filename prefix"
            )
        if (
            self.final_solution_path is not None
            and self.final_solution_path.suffix.lower() not in {".mst", ".sol"}
        ):
            raise ValueError("checkpoint final solution path must end in .mst or .sol")


@dataclass(frozen=True)
class EanSolveConfig:
    solver_policy: GurobiSolverPolicy = field(default_factory=GurobiSolverPolicy)
    optimization_config: EanOptimizationConfig = field(
        default_factory=EanOptimizationConfig
    )
    log_to_console: bool = False
    checkpoint: GurobiCheckpointConfig | None = None
    progress_recorder: Any | None = None
    diagnostic_recorders: tuple[Any, ...] = ()
    progress_sample_interval_seconds: float = 5.0
    build_only: bool = False
    build_progress_callback: EanBuildProgressCallback | None = None

    def validate(self) -> None:
        self.solver_policy.validate()
        if self.checkpoint is not None:
            self.checkpoint.validate()
        if self.progress_sample_interval_seconds <= 0:
            raise ValueError("progress_sample_interval_seconds must be positive")


@dataclass(frozen=True)
class EanMovementFeasibilityProblem:
    artifact: EanBuildArtifact

    @property
    def kind(self) -> EanOptimizationProblemKind:
        return EanOptimizationProblemKind.MOVEMENT_FEASIBILITY


@dataclass(frozen=True)
class EanPassengerServiceProblem:
    scenario: Scenario
    artifact: EanBuildArtifact
    objective: EanPassengerObjective = EanPassengerObjective.WAITING_TIME
    passenger_builder: EanPassengerCandidateBuilder | None = None
    mip_start_strategy: EanMipStartStrategy = (
        EanMipStartStrategy.AUTO
    )

    @property
    def kind(self) -> EanOptimizationProblemKind:
        return EanOptimizationProblemKind.PASSENGER_SERVICE


@dataclass(frozen=True)
class EanFixedMovementPassengerProblem:
    scenario: Scenario
    artifact: EanBuildArtifact
    movement_plan: EanMovementPlan
    objective: EanPassengerObjective = EanPassengerObjective.WAITING_TIME
    assignment_domain: EanPassengerAssignmentDomain = (
        EanPassengerAssignmentDomain.INTEGER
    )
    passenger_builder: EanPassengerCandidateBuilder | None = None

    @property
    def kind(self) -> EanOptimizationProblemKind:
        return EanOptimizationProblemKind.FIXED_MOVEMENT_PASSENGER


EanOptimizationProblem = (
    EanMovementFeasibilityProblem
    | EanPassengerServiceProblem
    | EanFixedMovementPassengerProblem
)


@dataclass(frozen=True)
class EanModelBuildMetrics:
    passenger_candidate_generation_seconds: float
    movement_model_seconds: float
    movement_fixing_seconds: float
    passenger_model_seconds: float
    mip_start_seconds: float
    mip_start_objective_value_seconds: float | None
    gurobi_setup_total_seconds: float
    artifact: EanArtifactBuildMetrics | None = None
    movement_variables_seconds: float = 0.0
    headway_constraints_seconds: float = 0.0
    final_model_update_seconds: float = 0.0
    fixed_headway_pair_count: int = 0
    disjunctive_headway_pair_count: int = 0
    redundant_headway_pair_count: int = 0
    headway_order_family_count: int = 0
    shared_headway_pair_count: int = 0
    headway_order_variable_savings: int = 0
    singleton_headway_order_family_count: int = 0
    diagnostically_omitted_headway_checkpoint_count: int = 0
    diagnostically_omitted_headway_pair_count: int = 0
    peak_rss_bytes: int | None = None


@dataclass(frozen=True)
class EanOptimizationMetadata:
    problem_kind: EanOptimizationProblemKind
    status: str
    solver_status: str
    objective_kind: EanPassengerObjective | None
    objective_value_seconds: float | None
    objective_passenger_hours: float | None
    best_bound: float | None
    mip_gap: float | None
    runtime_seconds: float | None
    node_count: float | None
    solution_count: int
    mip_gap_target: float | None
    time_limit_seconds: float | None
    demand_group_count: int | None
    ride_candidate_count: int | None
    slot_variable_count: int | None
    served_passenger_count: int | None
    unserved_passenger_count: int | None
    variable_count: int
    constraint_count: int
    model_nonzero_count: int
    model_setup_runtime_seconds: float
    movement_variable_count: int
    movement_constraint_count: int
    movement_nonzero_count: int
    headway_pair_count: int
    headway_order_variable_count: int
    fixed_movement: bool
    build_metrics: EanModelBuildMetrics
    solve_phase_metrics: GurobiSolvePhaseMetrics | None
    skipped_visit_count: int
    visible_skipped_visit_count: int
    checkpoint_read_path: str | None
    checkpoint_solution_file_prefix: str | None
    checkpoint_final_solution_path: str | None
    optimization_config: EanOptimizationConfig
    progress_samples: tuple[GurobiMipProgressSample, ...] = ()
    assignment_domain: EanPassengerAssignmentDomain | None = None
    passenger_assignment_variable_count: int | None = None
    fractional_ride_count: int | None = None
    fractional_distance_sum: float | None = None
    maximum_fractional_distance: float | None = None
    resolved_mip_start_strategy: EanMipStartStrategy | None = None
    mip_start_active_cabin_count: int | None = None
    mip_start_unserved_passenger_count: int | None = None
    mip_start_passenger_objective_seconds: float | None = None
    mip_start_generation_seconds: float | None = None
    diagnostic_headway_separation_complete: bool = False
    diagnostic_headway_feasible: bool | None = None
    diagnostic_headway_violation_count: int = 0
    diagnostic_max_headway_violation_seconds: float | None = None
    diagnostic_headway_separation_seconds: float = 0.0
    diagnostically_omitted_headway_checkpoint_count: int = 0
    diagnostically_omitted_headway_pair_count: int = 0

    def passenger_export_dict(self) -> dict[str, Any]:
        """Preserve the established passenger-result JSON metadata contract."""

        export_fields = {
            "status",
            "solver_status",
            "objective_kind",
            "objective_value_seconds",
            "objective_passenger_hours",
            "best_bound",
            "mip_gap",
            "runtime_seconds",
            "node_count",
            "solution_count",
            "mip_gap_target",
            "time_limit_seconds",
            "demand_group_count",
            "ride_candidate_count",
            "slot_variable_count",
            "served_passenger_count",
            "unserved_passenger_count",
            "variable_count",
            "constraint_count",
            "model_nonzero_count",
            "model_setup_runtime_seconds",
            "skipped_visit_count",
            "visible_skipped_visit_count",
            "checkpoint_read_path",
            "checkpoint_solution_file_prefix",
            "checkpoint_final_solution_path",
            "resolved_mip_start_strategy",
            "mip_start_active_cabin_count",
            "mip_start_unserved_passenger_count",
            "mip_start_passenger_objective_seconds",
            "mip_start_generation_seconds",
            "diagnostic_headway_separation_complete",
            "diagnostic_headway_feasible",
            "diagnostic_headway_violation_count",
            "diagnostic_max_headway_violation_seconds",
            "diagnostic_headway_separation_seconds",
            "diagnostically_omitted_headway_checkpoint_count",
            "diagnostically_omitted_headway_pair_count",
            "optimization_config",
            "progress_samples",
        }
        return {
            key: value
            for key, value in asdict(self).items()
            if key in export_fields
        }


@dataclass(frozen=True)
class EanOptimizationResult:
    problem_kind: EanOptimizationProblemKind
    movement_plan: EanMovementPlan | None
    passenger_plan: EanPassengerServicePlan | None
    metadata: EanOptimizationMetadata
    passenger_assignment: EanPassengerAssignment | None = None
    fleet_plan: EanFleetPlan | None = None


@dataclass(frozen=True)
class EanOptimizer:
    config: EanSolveConfig = field(default_factory=EanSolveConfig)

    def solve(self, problem: EanOptimizationProblem) -> EanOptimizationResult:
        try:
            import gurobipy as gp
            from gurobipy import GRB
        except ImportError as error:
            raise RuntimeError("gurobipy is required for EAN optimization") from error

        self.config.validate()
        problem.artifact.validate()
        if isinstance(problem, EanFixedMovementPassengerProblem):
            return _solve_fixed_movement_passenger(
                optimizer=self,
                problem=problem,
                gp=gp,
                grb=GRB,
            )
        optimization_config = (
            self.config.optimization_config.resolved_for_fleet_mode(
                problem.artifact.fleet_mode
            )
        )
        passenger_build = None
        passenger_candidate_runtime = 0.0
        if isinstance(problem, EanPassengerServiceProblem):
            if problem.scenario.id != problem.artifact.scenario_id:
                raise ValueError(
                    "EAN passenger problem scenario does not match the build "
                    f"artifact: {problem.scenario.id!r} != "
                    f"{problem.artifact.scenario_id!r}"
                )
            optimization_config = (
                optimization_config.resolved_for_passenger_objective(
                    problem.objective
                )
            )
            if (
                problem.objective is EanPassengerObjective.WAITING_TIME
                and optimization_config.formulation.board_time
                is EanBoardTimeFormulation.PROJECTED_JOURNEY_TIME
            ):
                raise ValueError(
                    "board_time_projected_journey_time requires journey_time objective"
                )
            candidate_started = perf_counter()
            emit_build_progress(
                self.config.build_progress_callback,
                stage=EanBuildStage.PASSENGER_CANDIDATES,
                kind=EanBuildProgressKind.STARTED,
                started=candidate_started,
            )
            passenger_build = (
                problem.passenger_builder
                or EanPassengerCandidateBuilder(
                    optimization_config=optimization_config
                )
            ).build(problem.scenario, problem.artifact)
            passenger_candidate_runtime = perf_counter() - candidate_started
            emit_build_progress(
                self.config.build_progress_callback,
                stage=EanBuildStage.PASSENGER_CANDIDATES,
                kind=EanBuildProgressKind.FINISHED,
                started=candidate_started,
                candidate_count=len(passenger_build.ride_candidates),
            )

        setup_started = perf_counter()
        if problem.artifact.headway_pair_scope is EanHeadwayPairScope.SPARSE:
            raise ValueError(
                "sparse headway artifacts require the delayed fixed-K capacity optimizer"
            )
        model = gp.Model(f"ean_{problem.kind.value}")
        model.Params.OutputFlag = 1 if self.config.log_to_console else 0
        apply_gurobi_solver_policy(model, self.config.solver_policy)
        movement_started = perf_counter()
        movement_model = EanMovementModelBuilder().build(
            model=model,
            binary_vtype=GRB.BINARY,
            artifact=problem.artifact,
            optimization_config=optimization_config,
            progress_callback=self.config.build_progress_callback,
        )
        movement_runtime = perf_counter() - movement_started
        movement_fixing_runtime = 0.0
        passenger_model = None
        passenger_runtime = 0.0
        mip_start_runtime = 0.0
        mip_start_objective_value = None
        mip_start_passenger_objective = None
        mip_start_active_cabin_count = None
        mip_start_unserved_count = None
        resolved_mip_start_strategy = None
        if isinstance(problem, EanPassengerServiceProblem):
            mip_start_strategy = _resolved_mip_start_strategy(
                problem,
                build_only=self.config.build_only,
            )
            resolved_mip_start_strategy = mip_start_strategy
            passenger_started = perf_counter()
            emit_build_progress(
                self.config.build_progress_callback,
                stage=EanBuildStage.PASSENGER_MODEL,
                kind=EanBuildProgressKind.STARTED,
                started=passenger_started,
                candidate_count=len(passenger_build.ride_candidates),
                variable_count=int(model.NumVars),
                constraint_count=int(model.NumConstrs),
            )
            passenger_model = EanPassengerModelBuilder().build(
                scenario=problem.scenario,
                movement_model=movement_model,
                objective=problem.objective,
                optimization_config=optimization_config,
                gp=gp,
                grb=GRB,
                passenger_builder=problem.passenger_builder,
                passenger_build=passenger_build,
            )
            passenger_runtime = perf_counter() - passenger_started
            emit_build_progress(
                self.config.build_progress_callback,
                stage=EanBuildStage.PASSENGER_MODEL,
                kind=EanBuildProgressKind.FINISHED,
                started=passenger_started,
                candidate_count=len(passenger_build.ride_candidates),
                variable_count=int(model.NumVars),
                constraint_count=int(model.NumConstrs),
                nonzero_count=int(model.NumNZs),
            )
            if _should_apply_mip_start(mip_start_strategy, self.config.checkpoint):
                mip_start_started = perf_counter()
                emit_build_progress(
                    self.config.build_progress_callback,
                    stage=EanBuildStage.MIP_START,
                    kind=EanBuildProgressKind.STARTED,
                    started=mip_start_started,
                    variable_count=int(model.NumVars),
                    constraint_count=int(model.NumConstrs),
                )
                seed = EanAllStopMipStartSeedBuilder().build(
                    problem.artifact,
                    optimization_config.formulation.horizon,
                )
                mip_start_active_cabin_count = _seed_active_cabin_count(seed)
                if (
                    mip_start_strategy
                    is EanMipStartStrategy.GREEDY_ALL_STOP
                ):
                    (
                        mip_start_unserved_count,
                        mip_start_passenger_objective,
                    ) = passenger_model.apply_all_stop_mip_start(
                        seed.movement_plan,
                        seed.fleet_plan,
                    )
                    mip_start_objective_value = mip_start_passenger_objective
                elif (
                    mip_start_strategy
                    is EanMipStartStrategy.OPTIMIZED_ALL_STOP
                ):
                    optimized_start = _solve_optimized_all_stop_start(
                        optimizer=self,
                        problem=problem,
                        seed=seed,
                    )
                    if (
                        optimized_start.movement_plan is not None
                        and optimized_start.passenger_plan is not None
                    ):
                        passenger_model.apply_mip_start(
                            optimized_start.movement_plan,
                            optimized_start.passenger_plan,
                            seed.fleet_plan,
                        )
                        mip_start_objective_value = (
                            optimized_start.metadata.objective_value_seconds
                        )
                        mip_start_unserved_count = (
                            optimized_start.metadata.unserved_passenger_count
                        )
                        mip_start_passenger_objective = (
                            _seed_passenger_objective_seconds(
                                passenger_model,
                                optimized_start.passenger_plan,
                            )
                        )
                    else:
                        LOGGER.warning(
                            "Optimized all-stop MIP start produced no solution; "
                            "falling back to greedy all-stop"
                        )
                        (
                            mip_start_unserved_count,
                            mip_start_passenger_objective,
                        ) = passenger_model.apply_all_stop_mip_start(
                            seed.movement_plan,
                            seed.fleet_plan,
                        )
                        mip_start_objective_value = (
                            mip_start_passenger_objective
                        )
                mip_start_runtime = perf_counter() - mip_start_started
                emit_build_progress(
                    self.config.build_progress_callback,
                    stage=EanBuildStage.MIP_START,
                    kind=EanBuildProgressKind.FINISHED,
                    started=mip_start_started,
                    variable_count=int(model.NumVars),
                    constraint_count=int(model.NumConstrs),
                    nonzero_count=int(model.NumNZs),
                )
        else:
            model.setObjective(0.0, GRB.MINIMIZE)

        _configure_checkpoints(model, self.config.checkpoint)
        final_update_started = perf_counter()
        emit_build_progress(
            self.config.build_progress_callback,
            stage=EanBuildStage.FINAL_MODEL_UPDATE,
            kind=EanBuildProgressKind.STARTED,
            started=final_update_started,
            variable_count=int(model.NumVars),
            constraint_count=int(model.NumConstrs),
        )
        model.update()
        final_update_runtime = perf_counter() - final_update_started
        emit_build_progress(
            self.config.build_progress_callback,
            stage=EanBuildStage.FINAL_MODEL_UPDATE,
            kind=EanBuildProgressKind.FINISHED,
            started=final_update_started,
            variable_count=int(model.NumVars),
            constraint_count=int(model.NumConstrs),
            nonzero_count=int(model.NumNZs),
        )
        _bind_diagnostic_recorders(
            self.config.diagnostic_recorders,
            movement_model,
            passenger_model,
        )
        model_nonzero_count = int(model.NumNZs)
        setup_runtime = perf_counter() - setup_started
        build_metrics = EanModelBuildMetrics(
            passenger_candidate_generation_seconds=(
                passenger_candidate_runtime
            ),
            movement_model_seconds=movement_runtime,
            movement_fixing_seconds=movement_fixing_runtime,
            passenger_model_seconds=passenger_runtime,
            mip_start_seconds=mip_start_runtime,
            mip_start_objective_value_seconds=mip_start_objective_value,
            gurobi_setup_total_seconds=setup_runtime,
            artifact=problem.artifact.build_metrics,
            movement_variables_seconds=(
                movement_model.build_metrics.variables_and_base_constraints_seconds
            ),
            headway_constraints_seconds=(
                movement_model.build_metrics.headway_constraints_seconds
            ),
            final_model_update_seconds=final_update_runtime,
            fixed_headway_pair_count=(
                movement_model.build_metrics.fixed_headway_pair_count
            ),
            disjunctive_headway_pair_count=(
                movement_model.build_metrics.disjunctive_headway_pair_count
            ),
            redundant_headway_pair_count=(
                movement_model.build_metrics.redundant_headway_pair_count
            ),
            headway_order_family_count=(
                movement_model.build_metrics.headway_order_family_count
            ),
            shared_headway_pair_count=(
                movement_model.build_metrics.shared_headway_pair_count
            ),
            headway_order_variable_savings=(
                movement_model.build_metrics.headway_order_variable_savings
            ),
            singleton_headway_order_family_count=(
                movement_model.build_metrics.singleton_headway_order_family_count
            ),
            diagnostically_omitted_headway_checkpoint_count=(
                movement_model.build_metrics.diagnostically_omitted_headway_checkpoint_count
            ),
            diagnostically_omitted_headway_pair_count=(
                movement_model.build_metrics.diagnostically_omitted_headway_pair_count
            ),
            peak_rss_bytes=peak_rss_bytes(),
        )
        _log_model_summary(
            model=model,
            problem=problem,
            movement_model=movement_model,
            passenger_model=passenger_model,
            setup_runtime=setup_runtime,
            solver_policy=self.config.solver_policy,
            enabled=self.config.log_to_console,
        )
        if self.config.build_only:
            progress_samples = ()
            solve_phase_metrics = None
            diagnostics = _build_only_diagnostics(self.config.solver_policy)
        else:
            _prepare_diagnostic_recorders(
                self.config.diagnostic_recorders,
                model,
                GRB,
            )
            progress_start = _optimize(
                model=model,
                grb=GRB,
                recorder=self.config.progress_recorder,
                diagnostic_recorders=self.config.diagnostic_recorders,
                sample_interval_seconds=self.config.progress_sample_interval_seconds,
            )
            _write_final_checkpoint(model, self.config.checkpoint)
            progress_samples = _progress_samples(
                self.config.progress_recorder,
                progress_start,
            )
            solve_phase_metrics = _progress_phase_metrics(
                self.config.progress_recorder
            )
            diagnostics = _solver_diagnostics(
                model,
                GRB,
                self.config.solver_policy,
            )
        checkpoint_diagnostics = _checkpoint_diagnostics(self.config.checkpoint)
        if model.SolCount <= 0:
            return EanOptimizationResult(
                problem_kind=problem.kind,
                movement_plan=None,
                passenger_plan=None,
                metadata=_metadata(
                    problem=problem,
                    optimization_config=optimization_config,
                    diagnostics=diagnostics,
                    checkpoint_diagnostics=checkpoint_diagnostics,
                    movement_model=movement_model,
                    passenger_model=passenger_model,
                    model=model,
                    model_nonzero_count=model_nonzero_count,
                    setup_runtime=setup_runtime,
                    build_metrics=build_metrics,
                    solve_phase_metrics=solve_phase_metrics,
                    progress_samples=progress_samples,
                    resolved_mip_start_strategy=resolved_mip_start_strategy,
                    mip_start_active_cabin_count=mip_start_active_cabin_count,
                    mip_start_unserved_passenger_count=mip_start_unserved_count,
                    mip_start_passenger_objective_seconds=(
                        mip_start_passenger_objective
                    ),
                ),
            )

        movement_plan = movement_model.extract_plan()
        tolerance = (
            1e-5
            if optimization_config.formulation.horizon
            is EanHorizonFormulation.EXACT_TIME_ACTIVATION
            else 1e-6
        )
        diagnostic_headway_violations: tuple[EanHeadwayViolation, ...] = ()
        diagnostic_headway_separation_seconds = 0.0
        if optimization_config.enable_diagnostic_relax_merge_headways:
            retained_pair_ids = (
                movement_model.headway_constraint_pool.materialized_pair_ids
            )
            retained_artifact = replace(
                problem.artifact,
                headway_pairs=tuple(
                    pair
                    for pair in problem.artifact.headway_pairs
                    if pair.id in retained_pair_ids
                ),
            )
            validate_ean_movement_plan_against_artifact(
                retained_artifact,
                movement_plan,
                tolerance_seconds=tolerance,
            ).raise_for_errors()
            separation_started = perf_counter()
            diagnostic_headway_violations = separate_all_headway_violations(
                problem.artifact,
                movement_plan,
                tolerance_seconds=tolerance,
            )
            diagnostic_headway_separation_seconds = (
                perf_counter() - separation_started
            )
            materialized_violations = {
                violation.pair.id
                for violation in diagnostic_headway_violations
            } & retained_pair_ids
            if materialized_violations:
                raise RuntimeError(
                    "diagnostic solution violates retained headway pairs: "
                    f"{sorted(materialized_violations)[:10]!r}"
                )
        else:
            validate_ean_movement_plan_against_artifact(
                problem.artifact,
                movement_plan,
                tolerance_seconds=tolerance,
            ).raise_for_errors()
        passenger_plan = (
            passenger_model.extract_passenger_plan()
            if passenger_model is not None
            else None
        )
        return EanOptimizationResult(
            problem_kind=problem.kind,
            movement_plan=movement_plan,
            passenger_plan=passenger_plan,
            metadata=_metadata(
                problem=problem,
                optimization_config=optimization_config,
                diagnostics=diagnostics,
                checkpoint_diagnostics=checkpoint_diagnostics,
                movement_model=movement_model,
                passenger_model=passenger_model,
                model=model,
                model_nonzero_count=model_nonzero_count,
                setup_runtime=setup_runtime,
                build_metrics=build_metrics,
                solve_phase_metrics=solve_phase_metrics,
                progress_samples=progress_samples,
                movement_plan=movement_plan,
                passenger_plan=passenger_plan,
                resolved_mip_start_strategy=resolved_mip_start_strategy,
                mip_start_active_cabin_count=mip_start_active_cabin_count,
                mip_start_unserved_passenger_count=mip_start_unserved_count,
                mip_start_passenger_objective_seconds=(
                    mip_start_passenger_objective
                ),
                diagnostic_headway_violations=(
                    diagnostic_headway_violations
                ),
                diagnostic_headway_separation_seconds=(
                    diagnostic_headway_separation_seconds
                ),
            ),
            fleet_plan=(
                movement_model.fleet_model.extract_plan()
                if movement_model.fleet_model is not None
                else None
            ),
        )


def _solve_fixed_movement_passenger(
    *,
    optimizer: EanOptimizer,
    problem: EanFixedMovementPassengerProblem,
    gp: Any,
    grb: Any,
) -> EanOptimizationResult:
    config = optimizer.config
    if (
        problem.assignment_domain
        is EanPassengerAssignmentDomain.LP_RELAXATION
        and config.checkpoint is not None
    ):
        raise ValueError(
            "checkpoints are not supported for fixed-movement passenger LP relaxations"
        )
    if config.diagnostic_recorders:
        raise ValueError(
            "movement root diagnostic recorders are not supported for the "
            "fixed-movement passenger problem"
        )
    if problem.scenario.id != problem.artifact.scenario_id:
        raise ValueError(
            "fixed-movement passenger scenario does not match the build artifact: "
            f"{problem.scenario.id!r} != {problem.artifact.scenario_id!r}"
        )

    optimization_config = (
        config.optimization_config.resolved_for_fleet_mode(
            problem.artifact.fleet_mode
        ).resolved_for_passenger_objective(problem.objective)
    )
    candidate_started = perf_counter()
    passenger_build = (
        problem.passenger_builder
        or EanPassengerCandidateBuilder(
            optimization_config=optimization_config
        )
    ).build(problem.scenario, problem.artifact)
    passenger_candidate_runtime = perf_counter() - candidate_started

    setup_started = perf_counter()
    model = gp.Model(f"ean_{problem.kind.value}_{problem.assignment_domain.value}")
    model.Params.OutputFlag = 1 if config.log_to_console else 0
    apply_gurobi_solver_policy(model, config.solver_policy)
    passenger_started = perf_counter()
    fixed_model = EanFixedMovementPassengerModelBuilder().build(
        model=model,
        scenario=problem.scenario,
        artifact=problem.artifact,
        movement_plan=problem.movement_plan,
        passenger_build=passenger_build,
        objective=problem.objective,
        assignment_domain=problem.assignment_domain,
        grb=grb,
        gp=gp,
    )
    passenger_runtime = perf_counter() - passenger_started
    _configure_checkpoints(model, config.checkpoint)
    model.update()
    model_nonzero_count = int(model.NumNZs)
    setup_runtime = perf_counter() - setup_started
    build_metrics = EanModelBuildMetrics(
        passenger_candidate_generation_seconds=passenger_candidate_runtime,
        movement_model_seconds=0.0,
        movement_fixing_seconds=0.0,
        passenger_model_seconds=passenger_runtime,
        mip_start_seconds=0.0,
        mip_start_objective_value_seconds=None,
        gurobi_setup_total_seconds=setup_runtime,
    )
    if config.log_to_console:
        LOGGER.info(
            "ean.optimize kind=%s domain=%s variables=%s constraints=%s "
            "nonzeros=%s demand_groups=%s ride_candidates=%s setup_seconds=%.3f "
            "solver_policy=%s",
            problem.kind.value,
            problem.assignment_domain.value,
            model.NumVars,
            model.NumConstrs,
            model.NumNZs,
            len(fixed_model.passenger_build.demand_groups),
            len(fixed_model.passenger_build.ride_candidates),
            setup_runtime,
            config.solver_policy,
        )
    progress_start = _optimize(
        model=model,
        grb=grb,
        recorder=config.progress_recorder,
        diagnostic_recorders=(),
        sample_interval_seconds=config.progress_sample_interval_seconds,
    )
    _write_final_checkpoint(model, config.checkpoint)
    progress_samples = _progress_samples(
        config.progress_recorder,
        progress_start,
    )
    solve_phase_metrics = _progress_phase_metrics(config.progress_recorder)
    diagnostics = _solver_diagnostics(
        model,
        grb,
        config.solver_policy,
    )
    if problem.assignment_domain is EanPassengerAssignmentDomain.LP_RELAXATION:
        diagnostics["mip_gap"] = None
        diagnostics["mip_gap_target"] = None
        diagnostics["node_count"] = None
    checkpoint_diagnostics = _checkpoint_diagnostics(config.checkpoint)
    assignment = (
        fixed_model.extract_assignment()
        if int(model.SolCount) > 0
        else None
    )
    passenger_plan = (
        fixed_model.extract_passenger_plan(assignment)
        if (
            assignment is not None
            and problem.assignment_domain
            is EanPassengerAssignmentDomain.INTEGER
        )
        else None
    )
    metadata = _fixed_movement_metadata(
        problem=problem,
        optimization_config=optimization_config,
        diagnostics=diagnostics,
        checkpoint_diagnostics=checkpoint_diagnostics,
        fixed_model=fixed_model,
        model=model,
        model_nonzero_count=model_nonzero_count,
        setup_runtime=setup_runtime,
        build_metrics=build_metrics,
        solve_phase_metrics=solve_phase_metrics,
        progress_samples=progress_samples,
        assignment=assignment,
        passenger_plan=passenger_plan,
    )
    return EanOptimizationResult(
        problem_kind=problem.kind,
        movement_plan=problem.movement_plan,
        passenger_plan=passenger_plan,
        metadata=metadata,
        passenger_assignment=assignment,
    )


def _fixed_movement_metadata(
    *,
    problem: EanFixedMovementPassengerProblem,
    optimization_config: EanOptimizationConfig,
    diagnostics: dict[str, Any],
    checkpoint_diagnostics: dict[str, str | None],
    fixed_model: EanFixedMovementPassengerModel,
    model: Any,
    model_nonzero_count: int,
    setup_runtime: float,
    build_metrics: EanModelBuildMetrics,
    solve_phase_metrics: GurobiSolvePhaseMetrics | None,
    progress_samples: tuple[GurobiMipProgressSample, ...],
    assignment: EanPassengerAssignment | None,
    passenger_plan: EanPassengerServicePlan | None,
) -> EanOptimizationMetadata:
    objective_value = (
        float(model.ObjVal)
        if int(model.SolCount) > 0
        else None
    )
    skipped_count = sum(
        visit.decision is EanRouteDecision.SKIP
        for trajectory in problem.movement_plan.trajectories
        for visit in trajectory.visits
    )
    visible_skipped_count = sum(
        visit.decision is EanRouteDecision.SKIP
        and visit.switch_time_seconds
        <= problem.artifact.config.horizon_seconds
        for trajectory in problem.movement_plan.trajectories
        for visit in trajectory.visits
    )
    return EanOptimizationMetadata(
        problem_kind=problem.kind,
        **diagnostics,
        objective_kind=problem.objective,
        objective_value_seconds=objective_value,
        objective_passenger_hours=(
            objective_value / 3600.0
            if objective_value is not None
            else None
        ),
        demand_group_count=len(fixed_model.passenger_build.demand_groups),
        ride_candidate_count=len(fixed_model.passenger_build.ride_candidates),
        slot_variable_count=None,
        served_passenger_count=(
            sum(ride.count for ride in passenger_plan.served_rides)
            if passenger_plan is not None
            else None
        ),
        unserved_passenger_count=(
            sum(passenger_plan.unserved_counts_by_demand_group_id.values())
            if passenger_plan is not None
            else None
        ),
        variable_count=int(model.NumVars),
        constraint_count=int(model.NumConstrs),
        model_nonzero_count=model_nonzero_count,
        model_setup_runtime_seconds=setup_runtime,
        movement_variable_count=0,
        movement_constraint_count=0,
        movement_nonzero_count=0,
        headway_pair_count=0,
        headway_order_variable_count=0,
        fixed_movement=True,
        build_metrics=build_metrics,
        solve_phase_metrics=solve_phase_metrics,
        skipped_visit_count=skipped_count,
        visible_skipped_visit_count=visible_skipped_count,
        **checkpoint_diagnostics,
        optimization_config=optimization_config,
        progress_samples=progress_samples,
        assignment_domain=problem.assignment_domain,
        passenger_assignment_variable_count=fixed_model.variable_count,
        fractional_ride_count=(
            assignment.fractional_ride_count
            if assignment is not None
            else None
        ),
        fractional_distance_sum=(
            assignment.fractional_distance_sum
            if assignment is not None
            else None
        ),
        maximum_fractional_distance=(
            assignment.maximum_fractional_distance
            if assignment is not None
            else None
        ),
    )


def _should_apply_mip_start(
    strategy: EanMipStartStrategy,
    checkpoint: GurobiCheckpointConfig | None,
) -> bool:
    return (
        strategy is not EanMipStartStrategy.NONE
        and (
            checkpoint is None
            or checkpoint.read_solution_path is None
        )
    )


def _resolved_mip_start_strategy(
    problem: EanPassengerServiceProblem,
    *,
    build_only: bool = False,
) -> EanMipStartStrategy:
    strategy = problem.mip_start_strategy
    if strategy is EanMipStartStrategy.AUTO:
        return (
            EanMipStartStrategy.NONE
            if build_only
            else EanMipStartStrategy.OPTIMIZED_ALL_STOP
        )
    if build_only and strategy is EanMipStartStrategy.OPTIMIZED_ALL_STOP:
        raise ValueError(
            "build-only mode cannot run the optimized_all_stop auxiliary solve; "
            "use --ean-mip-start none or greedy_all_stop"
        )
    return strategy


def _solve_optimized_all_stop_start(
    *,
    optimizer: EanOptimizer,
    problem: EanPassengerServiceProblem,
    seed: EanAllStopMipStartSeed,
) -> EanOptimizationResult:
    """Optimize passenger service for the deterministic all-stop movement.

    The auxiliary solve uses the same formulation and candidate builder as the
    integrated problem. Its fixed movement makes the solve a passenger
    assignment problem; a bounded 60-second budget prevents start generation
    from consuming an unbounded share of the main run.
    """

    main_limit = optimizer.config.solver_policy.time_limit_seconds
    start_limit = min(main_limit, 60.0) if main_limit is not None else 60.0
    start_policy = replace(
        optimizer.config.solver_policy,
        mip_gap=0.0,
        time_limit_seconds=start_limit,
    )
    return EanOptimizer(
        EanSolveConfig(
            solver_policy=start_policy,
            optimization_config=optimizer.config.optimization_config,
            log_to_console=False,
        )
    ).solve(
        EanFixedMovementPassengerProblem(
            scenario=problem.scenario,
            artifact=problem.artifact,
            movement_plan=seed.movement_plan,
            objective=problem.objective,
            passenger_builder=problem.passenger_builder,
        )
    )


def _seed_active_cabin_count(seed: EanAllStopMipStartSeed) -> int:
    if seed.fleet_plan is not None:
        return len(seed.fleet_plan.active_cabin_ids)
    return sum(bool(trajectory.visits) for trajectory in seed.movement_plan.trajectories)


def _seed_passenger_objective_seconds(
    passenger_model: EanPassengerModel,
    passenger_plan: EanPassengerServicePlan,
) -> float:
    total = 0.0
    for ride in passenger_plan.served_rides:
        group = passenger_model.group_by_id[ride.demand_group_id]
        service_time = (
            ride.boarding_time_seconds
            if passenger_model.objective is EanPassengerObjective.WAITING_TIME
            else ride.alighting_time_seconds
        )
        total += ride.count * (
            service_time - group.release_time_seconds
        )
    return total


def _metadata(
    *,
    problem: EanOptimizationProblem,
    optimization_config: EanOptimizationConfig,
    diagnostics: dict[str, Any],
    checkpoint_diagnostics: dict[str, str | None],
    movement_model: EanMovementModel,
    passenger_model: EanPassengerModel | None,
    model: Any,
    model_nonzero_count: int,
    setup_runtime: float,
    build_metrics: EanModelBuildMetrics,
    solve_phase_metrics: GurobiSolvePhaseMetrics | None,
    progress_samples: tuple[GurobiMipProgressSample, ...],
    movement_plan: EanMovementPlan | None = None,
    passenger_plan: EanPassengerServicePlan | None = None,
    resolved_mip_start_strategy: EanMipStartStrategy | None = None,
    mip_start_active_cabin_count: int | None = None,
    mip_start_unserved_passenger_count: int | None = None,
    mip_start_passenger_objective_seconds: float | None = None,
    diagnostic_headway_violations: tuple[EanHeadwayViolation, ...] = (),
    diagnostic_headway_separation_seconds: float = 0.0,
) -> EanOptimizationMetadata:
    if passenger_model is None:
        objective_kind = None
        objective_value = None
        demand_group_count = None
        ride_candidate_count = None
        slot_variable_count = None
        served_count = None
        unserved_count = None
    else:
        objective_kind = passenger_model.objective
        objective_value = (
            float(passenger_model.objective_expression.getValue())
            if int(model.SolCount) > 0
            else None
        )
        demand_group_count = len(passenger_model.passenger_build.demand_groups)
        ride_candidate_count = len(passenger_model.passenger_build.ride_candidates)
        slot_variable_count = len(passenger_model.variables.slot)
        served_count = (
            sum(ride.count for ride in passenger_plan.served_rides)
            if passenger_plan is not None
            else 0
        )
        unserved_count = (
            sum(passenger_plan.unserved_counts_by_demand_group_id.values())
            if passenger_plan is not None
            else 0
        )
    skipped_count = (
        sum(
            visit.decision is EanRouteDecision.SKIP
            for trajectory in movement_plan.trajectories
            for visit in trajectory.visits
        )
        if movement_plan is not None
        else 0
    )
    visible_skipped_count = (
        sum(
            visit.decision is EanRouteDecision.SKIP
            and visit.switch_time_seconds <= problem.artifact.config.horizon_seconds
            for trajectory in movement_plan.trajectories
            for visit in trajectory.visits
        )
        if movement_plan is not None
        else 0
    )
    return EanOptimizationMetadata(
        problem_kind=problem.kind,
        **diagnostics,
        objective_kind=objective_kind,
        objective_value_seconds=objective_value,
        objective_passenger_hours=(
            objective_value / 3600.0 if objective_value is not None else None
        ),
        demand_group_count=demand_group_count,
        ride_candidate_count=ride_candidate_count,
        slot_variable_count=slot_variable_count,
        served_passenger_count=served_count,
        unserved_passenger_count=unserved_count,
        variable_count=int(model.NumVars),
        constraint_count=int(model.NumConstrs),
        model_nonzero_count=model_nonzero_count,
        model_setup_runtime_seconds=setup_runtime,
        movement_variable_count=movement_model.variable_count,
        movement_constraint_count=movement_model.constraint_count,
        movement_nonzero_count=movement_model.nonzero_count,
        headway_pair_count=len(problem.artifact.headway_pairs),
        headway_order_variable_count=len(
            movement_model.variables.headway_order
        ),
        fixed_movement=False,
        build_metrics=build_metrics,
        solve_phase_metrics=solve_phase_metrics,
        skipped_visit_count=skipped_count,
        visible_skipped_visit_count=visible_skipped_count,
        **checkpoint_diagnostics,
        optimization_config=optimization_config,
        progress_samples=progress_samples,
        resolved_mip_start_strategy=resolved_mip_start_strategy,
        mip_start_active_cabin_count=mip_start_active_cabin_count,
        mip_start_unserved_passenger_count=mip_start_unserved_passenger_count,
        mip_start_passenger_objective_seconds=(
            mip_start_passenger_objective_seconds
        ),
        mip_start_generation_seconds=(
            build_metrics.mip_start_seconds
            if resolved_mip_start_strategy is not None
            else None
        ),
        diagnostic_headway_separation_complete=(
            optimization_config.enable_diagnostic_relax_merge_headways
            and movement_plan is not None
        ),
        diagnostic_headway_feasible=(
            not diagnostic_headway_violations
            if optimization_config.enable_diagnostic_relax_merge_headways
            and movement_plan is not None
            else None
        ),
        diagnostic_headway_violation_count=len(
            diagnostic_headway_violations
        ),
        diagnostic_max_headway_violation_seconds=(
            max(
                violation.violation_seconds
                for violation in diagnostic_headway_violations
            )
            if diagnostic_headway_violations
            else None
        ),
        diagnostic_headway_separation_seconds=(
            diagnostic_headway_separation_seconds
        ),
        diagnostically_omitted_headway_checkpoint_count=(
            build_metrics.diagnostically_omitted_headway_checkpoint_count
        ),
        diagnostically_omitted_headway_pair_count=(
            build_metrics.diagnostically_omitted_headway_pair_count
        ),
    )


def _optimize(
    *,
    model: Any,
    grb: Any,
    recorder: Any | None,
    diagnostic_recorders: tuple[Any, ...],
    sample_interval_seconds: float,
) -> int:
    callback_recorders = tuple(
        callback_recorder
        for callback_recorder in (recorder, *diagnostic_recorders)
        if callback_recorder is not None
    )
    if not callback_recorders:
        model.optimize()
        return 0
    start = 0
    for callback_recorder in callback_recorders:
        begin_run = getattr(callback_recorder, "begin_run", None)
        result = begin_run() if callable(begin_run) else None
        if callback_recorder is recorder:
            start = (
                int(result)
                if result is not None
                else len(recorder.samples)
            )
    model.optimize(
        lambda callback_model, where: _record_callbacks(
            callback_recorders,
            callback_model,
            grb,
            where,
            sample_interval_seconds,
        ),
    )
    for callback_recorder in callback_recorders:
        record_final = getattr(callback_recorder, "record_final", None)
        if callable(record_final):
            record_final(model, grb)
    return start


def _bind_diagnostic_recorders(
    diagnostic_recorders: tuple[Any, ...],
    movement_model: EanMovementModel,
    passenger_model: EanPassengerModel | None,
) -> None:
    for recorder in diagnostic_recorders:
        bind_models = getattr(recorder, "bind_models", None)
        if callable(bind_models):
            bind_models(movement_model, passenger_model)


def _prepare_diagnostic_recorders(
    diagnostic_recorders: tuple[Any, ...],
    model: Any,
    grb: Any,
) -> None:
    for recorder in diagnostic_recorders:
        prepare_model = getattr(recorder, "prepare_model", None)
        if callable(prepare_model):
            prepare_model(model, grb)


def _record_callbacks(
    recorders: tuple[Any, ...],
    model: Any,
    grb: Any,
    where: int,
    sample_interval_seconds: float,
) -> None:
    for recorder in recorders:
        recorder.record_callback(
            model,
            grb,
            where,
            sample_interval_seconds=sample_interval_seconds,
        )


def _progress_samples(
    recorder: Any | None,
    start: int,
) -> tuple[GurobiMipProgressSample, ...]:
    if recorder is None:
        return ()
    return tuple(recorder.samples[start:])


def _progress_phase_metrics(
    recorder: Any | None,
) -> GurobiSolvePhaseMetrics | None:
    if recorder is None:
        return None
    metrics = getattr(recorder, "phase_metrics", None)
    return metrics if isinstance(metrics, GurobiSolvePhaseMetrics) else None


def _configure_checkpoints(
    model: Any,
    checkpoint: GurobiCheckpointConfig | None,
) -> None:
    if checkpoint is None:
        return
    if checkpoint.solution_file_prefix is not None:
        checkpoint.solution_file_prefix.parent.mkdir(parents=True, exist_ok=True)
        model.Params.SolFiles = str(checkpoint.solution_file_prefix)
    if checkpoint.read_solution_path is not None:
        model.update()
        LOGGER.info("Loading EAN checkpoint MIP start from %s", checkpoint.read_solution_path)
        model.read(str(checkpoint.read_solution_path))


def _write_final_checkpoint(
    model: Any,
    checkpoint: GurobiCheckpointConfig | None,
) -> None:
    if (
        checkpoint is None
        or checkpoint.final_solution_path is None
        or (_safe_int_attr(model, "SolCount") or 0) == 0
    ):
        return
    checkpoint.final_solution_path.parent.mkdir(parents=True, exist_ok=True)
    model.write(str(checkpoint.final_solution_path))


def _checkpoint_diagnostics(
    checkpoint: GurobiCheckpointConfig | None,
) -> dict[str, str | None]:
    if checkpoint is None:
        return {
            "checkpoint_read_path": None,
            "checkpoint_solution_file_prefix": None,
            "checkpoint_final_solution_path": None,
        }
    return {
        "checkpoint_read_path": (
            checkpoint.read_solution_path.as_posix()
            if checkpoint.read_solution_path is not None
            else None
        ),
        "checkpoint_solution_file_prefix": (
            checkpoint.solution_file_prefix.as_posix()
            if checkpoint.solution_file_prefix is not None
            else None
        ),
        "checkpoint_final_solution_path": (
            checkpoint.final_solution_path.as_posix()
            if checkpoint.final_solution_path is not None
            else None
        ),
    }


def _solver_diagnostics(
    model: Any,
    grb: Any,
    policy: GurobiSolverPolicy,
) -> dict[str, Any]:
    solver_status = _solver_status_name(int(model.Status), grb)
    solution_count = _safe_int_attr(model, "SolCount") or 0
    return {
        "status": solver_status.lower(),
        "solver_status": solver_status,
        "best_bound": _safe_finite_float_attr(model, "ObjBound"),
        "mip_gap": (
            _safe_finite_float_attr(model, "MIPGap")
            if solution_count > 0
            else None
        ),
        "runtime_seconds": _safe_finite_float_attr(model, "Runtime"),
        "node_count": _safe_finite_float_attr(model, "NodeCount"),
        "solution_count": solution_count,
        "mip_gap_target": policy.mip_gap,
        "time_limit_seconds": policy.time_limit_seconds,
    }


def _build_only_diagnostics(policy: GurobiSolverPolicy) -> dict[str, Any]:
    return {
        "status": "build_only",
        "solver_status": "NOT_STARTED",
        "best_bound": None,
        "mip_gap": None,
        "runtime_seconds": None,
        "node_count": None,
        "solution_count": 0,
        "mip_gap_target": policy.mip_gap,
        "time_limit_seconds": policy.time_limit_seconds,
    }


def _solver_status_name(status: int, grb: Any) -> str:
    names = {
        grb.OPTIMAL: "OPTIMAL",
        grb.INFEASIBLE: "INFEASIBLE",
        grb.INF_OR_UNBD: "INF_OR_UNBD",
        grb.UNBOUNDED: "UNBOUNDED",
        grb.TIME_LIMIT: "TIME_LIMIT",
        grb.INTERRUPTED: "INTERRUPTED",
    }
    return names.get(status, f"STATUS_{status}")


def _safe_finite_float_attr(model: Any, name: str) -> float | None:
    try:
        value = float(getattr(model, name))
    except Exception:
        return None
    return value if math.isfinite(value) else None


def _safe_int_attr(model: Any, name: str) -> int | None:
    try:
        return int(getattr(model, name))
    except Exception:
        return None


def _log_model_summary(
    *,
    model: Any,
    problem: EanOptimizationProblem,
    movement_model: EanMovementModel,
    passenger_model: EanPassengerModel | None,
    setup_runtime: float,
    solver_policy: GurobiSolverPolicy,
    enabled: bool,
) -> None:
    if not enabled:
        return
    LOGGER.info(
        "ean.optimize kind=%s variables=%s constraints=%s nonzeros=%s "
        "movement_variables=%s movement_constraints=%s setup_seconds=%.3f "
        "demand_groups=%s ride_candidates=%s slots=%s solver_policy=%s",
        problem.kind.value,
        model.NumVars,
        model.NumConstrs,
        model.NumNZs,
        movement_model.variable_count,
        movement_model.constraint_count,
        setup_runtime,
        (
            len(passenger_model.passenger_build.demand_groups)
            if passenger_model is not None
            else 0
        ),
        (
            len(passenger_model.passenger_build.ride_candidates)
            if passenger_model is not None
            else 0
        ),
        len(passenger_model.variables.slot) if passenger_model is not None else 0,
        solver_policy,
    )
