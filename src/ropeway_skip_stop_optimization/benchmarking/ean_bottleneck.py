from __future__ import annotations

import platform
import socket
import sys
from dataclasses import dataclass, field, replace
from datetime import datetime, timezone
from enum import StrEnum
from pathlib import Path
from time import perf_counter

from ropeway_skip_stop_optimization.benchmarking.environment import (
    current_git_commit,
    git_is_dirty,
    gurobi_version,
)
from ropeway_skip_stop_optimization.benchmarking.ean_root_relaxation import (
    EanRootRelaxationDiagnostic,
    EanRootRelaxationRecorder,
)
from ropeway_skip_stop_optimization.examples.ean import EanScenarioExample
from ropeway_skip_stop_optimization.examples.registry import get_example
from ropeway_skip_stop_optimization.exports.json_codec import write_json
from ropeway_skip_stop_optimization.optimization.ean import (
    EanMipStartStrategy,
    EanMovementFeasibilityProblem,
    EanOptimizationConfig,
    EanOptimizationMetadata,
    EanOptimizationResult,
    EanOptimizer,
    EanPassengerObjective,
    EanPassengerServiceProblem,
    EanSolveConfig,
    GurobiSolverPolicy,
    GurobiSolverPolicyPreset,
    gurobi_solver_policy_for_preset,
)
from ropeway_skip_stop_optimization.optimization.solver_progress import (
    GurobiMipProgressRecorder,
)


DEFAULT_BOTTLENECK_OUTPUT_DIR = Path(
    "benchmarks/output/bottleneck_diagnostics"
)


class EanBottleneckCase(StrEnum):
    INTEGRATED = "integrated"
    MOVEMENT_ONLY = "movement_only"
    FIXED_MOVEMENT_PASSENGER = "fixed_movement_passenger"


@dataclass(frozen=True)
class EanBottleneckDiagnosticConfig:
    example_id: str = "three_station_v0"
    objective: EanPassengerObjective = EanPassengerObjective.JOURNEY_TIME
    solver_policy: GurobiSolverPolicyPreset = (
        GurobiSolverPolicyPreset.QUICK_GOOD_SOLUTION
    )
    time_limit_seconds: float = 300.0
    sample_interval_seconds: float = 5.0
    optimization_config: EanOptimizationConfig = field(
        default_factory=EanOptimizationConfig
    )
    output_dir: Path = DEFAULT_BOTTLENECK_OUTPUT_DIR
    log_to_console: bool = True
    root_diagnostics: bool = False

    def validate(self) -> None:
        if self.time_limit_seconds <= 0:
            raise ValueError("time_limit_seconds must be positive")
        if self.sample_interval_seconds <= 0:
            raise ValueError("sample_interval_seconds must be positive")


@dataclass(frozen=True)
class EanBottleneckCaseResult:
    case: EanBottleneckCase
    metadata: EanOptimizationMetadata | None
    root_relaxation: EanRootRelaxationDiagnostic | None = None
    unavailable_reason: str | None = None


@dataclass(frozen=True)
class EanBottleneckDiagnosticResult:
    run_id: str
    timestamp: str
    git_commit: str | None
    git_dirty: bool
    hostname: str
    platform: str
    python_version: str
    gurobi_version: str | None
    example_id: str
    family_id: str | None
    variant_id: str | None
    objective: EanPassengerObjective
    solver_policy: GurobiSolverPolicy
    optimization_config: EanOptimizationConfig
    time_limit_seconds_per_case: float
    scenario_build_runtime_seconds: float
    artifact_build_runtime_seconds: float
    station_count: int
    demand_group_count: int
    passenger_count: int
    cabin_count: int
    switch_visit_count: int
    headway_pair_count: int
    cases: tuple[EanBottleneckCaseResult, ...]


@dataclass(frozen=True)
class EanBottleneckDiagnosticRunner:
    config: EanBottleneckDiagnosticConfig

    def run(self) -> tuple[EanBottleneckDiagnosticResult, Path]:
        self.config.validate()
        example = get_example(self.config.example_id)
        if not isinstance(example, EanScenarioExample):
            raise ValueError(
                f"example {self.config.example_id!r} does not support EAN"
            )

        scenario_started = perf_counter()
        scenario = example.build_scenario()
        scenario_runtime = perf_counter() - scenario_started
        ean_config = example.build_ean_config(scenario)
        artifact_started = perf_counter()
        artifact = example.build_ean_artifact_builder(
            scenario,
            ean_config,
        ).build(scenario, ean_config)
        artifact_runtime = perf_counter() - artifact_started

        solver_policy = replace(
            gurobi_solver_policy_for_preset(self.config.solver_policy),
            time_limit_seconds=self.config.time_limit_seconds,
        )
        integrated, integrated_root = self._solve(
            EanPassengerServiceProblem(
                scenario=scenario,
                artifact=artifact,
                objective=self.config.objective,
            ),
            solver_policy,
        )
        movement_only, movement_only_root = self._solve(
            EanMovementFeasibilityProblem(artifact),
            solver_policy,
        )
        if integrated.movement_plan is None:
            fixed_movement = EanBottleneckCaseResult(
                case=EanBottleneckCase.FIXED_MOVEMENT_PASSENGER,
                metadata=None,
                root_relaxation=None,
                unavailable_reason=(
                    "integrated case produced no movement incumbent"
                ),
            )
        else:
            fixed_movement_result, fixed_movement_root = self._solve(
                EanPassengerServiceProblem(
                    scenario=scenario,
                    artifact=artifact,
                    objective=self.config.objective,
                    mip_start_strategy=EanMipStartStrategy.NONE,
                    fixed_movement_plan=integrated.movement_plan,
                ),
                solver_policy,
            )
            fixed_movement = EanBottleneckCaseResult(
                case=EanBottleneckCase.FIXED_MOVEMENT_PASSENGER,
                metadata=fixed_movement_result.metadata,
                root_relaxation=fixed_movement_root,
            )

        run_id = _run_id(self.config)
        result = EanBottleneckDiagnosticResult(
            run_id=run_id,
            timestamp=datetime.now(timezone.utc).isoformat(
                timespec="seconds"
            ),
            git_commit=current_git_commit(),
            git_dirty=git_is_dirty(),
            hostname=socket.gethostname(),
            platform=platform.platform(),
            python_version=sys.version.split()[0],
            gurobi_version=gurobi_version(),
            example_id=example.metadata.id,
            family_id=example.metadata.family_id,
            variant_id=example.metadata.variant_id,
            objective=self.config.objective,
            solver_policy=solver_policy,
            optimization_config=self.config.optimization_config,
            time_limit_seconds_per_case=self.config.time_limit_seconds,
            scenario_build_runtime_seconds=scenario_runtime,
            artifact_build_runtime_seconds=artifact_runtime,
            station_count=len(scenario.stations),
            demand_group_count=len(scenario.demands),
            passenger_count=sum(demand.count for demand in scenario.demands),
            cabin_count=len(artifact.cabin_starts),
            switch_visit_count=len(artifact.switch_visits),
            headway_pair_count=len(artifact.headway_pairs),
            cases=(
                EanBottleneckCaseResult(
                    case=EanBottleneckCase.INTEGRATED,
                    metadata=integrated.metadata,
                    root_relaxation=integrated_root,
                ),
                EanBottleneckCaseResult(
                    case=EanBottleneckCase.MOVEMENT_ONLY,
                    metadata=movement_only.metadata,
                    root_relaxation=movement_only_root,
                ),
                fixed_movement,
            ),
        )
        output_path = self.config.output_dir / f"{run_id}.json"
        write_json(output_path, result)
        return result, output_path

    def _solve(
        self,
        problem: EanMovementFeasibilityProblem | EanPassengerServiceProblem,
        solver_policy: GurobiSolverPolicy,
    ) -> tuple[
        EanOptimizationResult,
        EanRootRelaxationDiagnostic | None,
    ]:
        recorder = GurobiMipProgressRecorder()
        root_recorder = (
            EanRootRelaxationRecorder(
                sample_interval_seconds=self.config.sample_interval_seconds,
            )
            if self.config.root_diagnostics
            else None
        )
        optimizer = EanOptimizer(
            EanSolveConfig(
                solver_policy=solver_policy,
                optimization_config=self.config.optimization_config,
                log_to_console=self.config.log_to_console,
                progress_recorder=recorder,
                diagnostic_recorders=(
                    (root_recorder,)
                    if root_recorder is not None
                    else ()
                ),
                progress_sample_interval_seconds=(
                    self.config.sample_interval_seconds
                ),
            )
        )
        result = optimizer.solve(problem)
        return (
            result,
            root_recorder.diagnostic
            if root_recorder is not None
            else None,
        )


def _run_id(config: EanBottleneckDiagnosticConfig) -> str:
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    return "__".join(
        (
            timestamp,
            config.example_id,
            config.objective.value,
            config.optimization_config.selection_label().replace(",", "+"),
        )
    )
