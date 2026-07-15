from __future__ import annotations

import logging
import math
from dataclasses import asdict, dataclass, field
from enum import StrEnum
from pathlib import Path
from time import perf_counter
from typing import Any

from ropeway_skip_stop_optimization.models import Scenario
from ropeway_skip_stop_optimization.optimization.ean.artifact import EanBuildArtifact
from ropeway_skip_stop_optimization.optimization.ean.builders.passenger_builder import (
    EanPassengerCandidateBuilder,
)
from ropeway_skip_stop_optimization.optimization.ean.formulation_config import (
    EanBoardTimeFormulation,
    EanHorizonFormulation,
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
)


LOGGER = logging.getLogger(__name__)


class EanOptimizationProblemKind(StrEnum):
    MOVEMENT_FEASIBILITY = "movement_feasibility"
    PASSENGER_SERVICE = "passenger_service"


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
    use_all_stop_mip_start: bool = True

    @property
    def kind(self) -> EanOptimizationProblemKind:
        return EanOptimizationProblemKind.PASSENGER_SERVICE


EanOptimizationProblem = EanMovementFeasibilityProblem | EanPassengerServiceProblem


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
    skipped_visit_count: int
    visible_skipped_visit_count: int
    checkpoint_read_path: str | None
    checkpoint_solution_file_prefix: str | None
    checkpoint_final_solution_path: str | None
    optimization_config: EanOptimizationConfig
    progress_samples: tuple[GurobiMipProgressSample, ...] = ()

    def passenger_export_dict(self) -> dict[str, Any]:
        """Preserve the established passenger-result JSON metadata contract."""

        excluded = {
            "problem_kind",
            "movement_variable_count",
            "movement_constraint_count",
            "movement_nonzero_count",
        }
        return {
            key: value
            for key, value in asdict(self).items()
            if key not in excluded
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
            passenger_build = (
                problem.passenger_builder
                or EanPassengerCandidateBuilder(
                    optimization_config=optimization_config
                )
            ).build(problem.scenario, problem.artifact)

        setup_started = perf_counter()
        model = gp.Model(f"ean_{problem.kind.value}")
        model.Params.OutputFlag = 1 if self.config.log_to_console else 0
        apply_gurobi_solver_policy(model, self.config.solver_policy)
        movement_model = EanMovementModelBuilder().build(
            model=model,
            binary_vtype=GRB.BINARY,
            artifact=problem.artifact,
            optimization_config=optimization_config,
        )
        passenger_model = None
        if isinstance(problem, EanPassengerServiceProblem):
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
            if (
                problem.use_all_stop_mip_start
                and (
                    self.config.checkpoint is None
                    or self.config.checkpoint.read_solution_path is None
                )
            ):
                passenger_model.apply_all_stop_mip_start()
        else:
            model.setObjective(0.0, GRB.MINIMIZE)

        _configure_checkpoints(model, self.config.checkpoint)
        model.update()
        model_nonzero_count = int(model.NumNZs)
        setup_runtime = perf_counter() - setup_started
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
            sample_interval_seconds=self.config.progress_sample_interval_seconds,
        )
        _write_final_checkpoint(model, self.config.checkpoint)
        progress_samples = _progress_samples(
            self.config.progress_recorder,
            progress_start,
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
                progress_samples=progress_samples,
                movement_plan=movement_plan,
                passenger_plan=passenger_plan,
            ),
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
    sample_interval_seconds: float,
) -> int:
    if recorder is None:
        model.optimize()
        return 0
    begin_run = getattr(recorder, "begin_run", None)
    start = (
        int(begin_run())
        if callable(begin_run)
        else len(recorder.samples)
    )
    model.optimize(
        lambda callback_model, where: recorder.record_callback(
            callback_model,
            grb,
            where,
            sample_interval_seconds=sample_interval_seconds,
        )
    )
    recorder.record_final(model, grb)
    return start


def _progress_samples(
    recorder: Any | None,
    start: int,
) -> tuple[GurobiMipProgressSample, ...]:
    if recorder is None:
        return ()
    return tuple(recorder.samples[start:])


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
