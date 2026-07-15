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
from ropeway_skip_stop_optimization.optimization.ean.builders.passenger_builder import (
    EanPassengerCandidateBuilder,
)
from ropeway_skip_stop_optimization.optimization.ean.baselines import (
    EarliestAllStopEanMovementPlanBuilder,
)
from ropeway_skip_stop_optimization.optimization.ean.formulation_config import (
    EanBoardTimeFormulation,
    EanHorizonFormulation,
    EanTimeBoundFormulation,
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
    EanCabinTrajectory,
    EanMovementPlan,
    EanRouteDecision,
)
from ropeway_skip_stop_optimization.optimization.ean.time_bounds import (
    build_ean_model_time_bounds,
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


class EanMipStartStrategy(StrEnum):
    """Primal-start strategy for integrated passenger-service solves."""

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
        EanMipStartStrategy.OPTIMIZED_ALL_STOP
    )
    fixed_movement_plan: EanMovementPlan | None = None

    @property
    def kind(self) -> EanOptimizationProblemKind:
        return EanOptimizationProblemKind.PASSENGER_SERVICE


EanOptimizationProblem = EanMovementFeasibilityProblem | EanPassengerServiceProblem


@dataclass(frozen=True)
class EanModelBuildMetrics:
    passenger_candidate_generation_seconds: float
    movement_model_seconds: float
    movement_fixing_seconds: float
    passenger_model_seconds: float
    mip_start_seconds: float
    mip_start_objective_value_seconds: float | None
    gurobi_setup_total_seconds: float


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
        optimization_config = self.config.optimization_config
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
            passenger_build = (
                problem.passenger_builder
                or EanPassengerCandidateBuilder(
                    optimization_config=optimization_config
                )
            ).build(problem.scenario, problem.artifact)
            passenger_candidate_runtime = perf_counter() - candidate_started

        setup_started = perf_counter()
        model = gp.Model(f"ean_{problem.kind.value}")
        model.Params.OutputFlag = 1 if self.config.log_to_console else 0
        apply_gurobi_solver_policy(model, self.config.solver_policy)
        movement_started = perf_counter()
        movement_model = EanMovementModelBuilder().build(
            model=model,
            binary_vtype=GRB.BINARY,
            artifact=problem.artifact,
            optimization_config=optimization_config,
        )
        movement_runtime = perf_counter() - movement_started
        movement_fixing_runtime = 0.0
        passenger_model = None
        passenger_runtime = 0.0
        mip_start_runtime = 0.0
        mip_start_objective_value = None
        if isinstance(problem, EanPassengerServiceProblem):
            if problem.fixed_movement_plan is not None:
                fixing_started = perf_counter()
                movement_model.fix_to_plan(problem.fixed_movement_plan)
                movement_fixing_runtime = perf_counter() - fixing_started
            passenger_started = perf_counter()
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
            if _should_apply_mip_start(problem, self.config.checkpoint):
                mip_start_started = perf_counter()
                if (
                    problem.mip_start_strategy
                    is EanMipStartStrategy.GREEDY_ALL_STOP
                ):
                    passenger_model.apply_all_stop_mip_start()
                elif (
                    problem.mip_start_strategy
                    is EanMipStartStrategy.OPTIMIZED_ALL_STOP
                ):
                    optimized_start = _solve_optimized_all_stop_start(
                        optimizer=self,
                        problem=problem,
                    )
                    if (
                        optimized_start.movement_plan is not None
                        and optimized_start.passenger_plan is not None
                    ):
                        passenger_model.apply_mip_start(
                            optimized_start.movement_plan,
                            optimized_start.passenger_plan,
                        )
                        mip_start_objective_value = (
                            optimized_start.metadata.objective_value_seconds
                        )
                    else:
                        LOGGER.warning(
                            "Optimized all-stop MIP start produced no solution; "
                            "falling back to greedy all-stop"
                        )
                        passenger_model.apply_all_stop_mip_start()
                mip_start_runtime = perf_counter() - mip_start_started
        else:
            model.setObjective(0.0, GRB.MINIMIZE)

        _configure_checkpoints(model, self.config.checkpoint)
        model.update()
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
                ),
            )

        movement_plan = movement_model.extract_plan()
        tolerance = (
            1e-5
            if optimization_config.formulation.horizon
            is EanHorizonFormulation.EXACT_TIME_ACTIVATION
            else 1e-6
        )
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
            ),
        )


def _should_apply_mip_start(
    problem: EanPassengerServiceProblem,
    checkpoint: GurobiCheckpointConfig | None,
) -> bool:
    return (
        problem.mip_start_strategy is not EanMipStartStrategy.NONE
        and problem.fixed_movement_plan is None
        and (
            checkpoint is None
            or checkpoint.read_solution_path is None
        )
    )


def _solve_optimized_all_stop_start(
    *,
    optimizer: EanOptimizer,
    problem: EanPassengerServiceProblem,
) -> EanOptimizationResult:
    """Optimize passenger service for the deterministic all-stop movement.

    The auxiliary solve uses the same formulation and candidate builder as the
    integrated problem. Its fixed movement makes the solve a passenger
    assignment problem; a bounded 60-second budget prevents start generation
    from consuming an unbounded share of the main run.
    """

    all_stop_plan = _all_stop_plan_for_formulation(
        problem.artifact,
        optimizer.config.optimization_config.formulation.horizon,
    )
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
        EanPassengerServiceProblem(
            scenario=problem.scenario,
            artifact=problem.artifact,
            objective=problem.objective,
            passenger_builder=problem.passenger_builder,
            mip_start_strategy=EanMipStartStrategy.NONE,
            fixed_movement_plan=all_stop_plan,
        )
    )


def _all_stop_plan_for_formulation(
    artifact: EanBuildArtifact,
    horizon_formulation: EanHorizonFormulation,
) -> EanMovementPlan:
    plan = EarliestAllStopEanMovementPlanBuilder().build(artifact)
    if horizon_formulation is EanHorizonFormulation.LEGACY:
        return plan

    active_keys: set[tuple[int, int]]
    if (
        horizon_formulation
        is EanHorizonFormulation.CONSERVATIVE_FREE_SUFFIX
    ):
        bounds = build_ean_model_time_bounds(
            artifact,
            EanTimeBoundFormulation.DERIVED_VISIT_BOUNDS,
        )
        active_keys = {
            key
            for key, visit_bounds in bounds.by_visit.items()
            if visit_bounds.switch_lower
            <= artifact.config.operational_end_seconds
        }
    elif (
        horizon_formulation
        is EanHorizonFormulation.EXACT_TIME_ACTIVATION
    ):
        active_keys = {
            (visit.cabin_id, visit.visit_index)
            for trajectory in plan.trajectories
            for visit in trajectory.visits
            if visit.switch_time_seconds
            <= artifact.config.operational_end_seconds
        }
    else:
        raise ValueError(
            f"unsupported EAN horizon formulation: {horizon_formulation}"
        )

    return replace(
        plan,
        trajectories=tuple(
            EanCabinTrajectory(
                cabin_id=trajectory.cabin_id,
                visits=tuple(
                    visit
                    for visit in trajectory.visits
                    if (visit.cabin_id, visit.visit_index) in active_keys
                ),
            )
            for trajectory in plan.trajectories
        ),
        horizon_formulation=horizon_formulation,
    )


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
            float(model.ObjVal) if int(model.SolCount) > 0 else None
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
        fixed_movement=(
            isinstance(problem, EanPassengerServiceProblem)
            and problem.fixed_movement_plan is not None
        ),
        build_metrics=build_metrics,
        solve_phase_metrics=solve_phase_metrics,
        skipped_visit_count=skipped_count,
        visible_skipped_visit_count=visible_skipped_count,
        **checkpoint_diagnostics,
        optimization_config=optimization_config,
        progress_samples=progress_samples,
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
