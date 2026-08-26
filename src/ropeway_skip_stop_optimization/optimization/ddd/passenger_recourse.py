from __future__ import annotations

from dataclasses import dataclass
import math
from time import perf_counter

from ropeway_skip_stop_optimization.models import Scenario
from ropeway_skip_stop_optimization.optimization.ddd.ean_plan_adapter import (
    DddReferenceToEanMovementPlanAdapter,
)
from ropeway_skip_stop_optimization.optimization.ddd.fixed_k import (
    DddFixedKTrajectoryProblem,
)
from ropeway_skip_stop_optimization.optimization.ddd.reference import (
    DddReferenceSolution,
)
from ropeway_skip_stop_optimization.optimization.ean.artifact import EanBuildArtifact
from ropeway_skip_stop_optimization.optimization.ean.builders.passenger_builder import (
    EanPassengerCandidateBuildResult,
)
from ropeway_skip_stop_optimization.optimization.ean.optimization_config import (
    EanOptimizationConfig,
)
from ropeway_skip_stop_optimization.optimization.ean.optimizers.fixed_movement_passenger_model import (
    EanPassengerAssignmentDomain,
)
from ropeway_skip_stop_optimization.optimization.ean.optimizers.solver import (
    EanFixedMovementPassengerProblem,
    EanOptimizer,
    EanSolveConfig,
)
from ropeway_skip_stop_optimization.optimization.ean.optimizers.solver_policy import (
    GurobiSolverPolicy,
)
from ropeway_skip_stop_optimization.optimization.ean.plan import EanMovementPlan


@dataclass(frozen=True, slots=True)
class _PrebuiltPassengerCandidateBuilder:
    result: EanPassengerCandidateBuildResult

    def build(
        self,
        scenario: Scenario,
        artifact: EanBuildArtifact,
    ) -> EanPassengerCandidateBuildResult:
        del scenario, artifact
        return self.result


@dataclass(frozen=True, slots=True)
class DddPassengerRecourseConfig:
    time_limit_seconds: float = 60.0
    threads: int | None = None
    output_flag: bool = False
    optimization_config: EanOptimizationConfig = EanOptimizationConfig()

    def validate(self) -> None:
        if not math.isfinite(self.time_limit_seconds) or self.time_limit_seconds <= 0:
            raise ValueError("Passenger recourse time limit must be positive")
        if self.threads is not None and self.threads <= 0:
            raise ValueError("Passenger recourse threads must be positive")


@dataclass(frozen=True, slots=True)
class DddPassengerRecourseResult:
    assignment_domain: EanPassengerAssignmentDomain
    solver_status: str
    objective_value: float | None
    best_bound: float | None
    optimal: bool
    has_solution: bool
    passenger_candidate_count: int
    assignment_variable_count: int
    fractional_ride_count: int
    fractional_distance_sum: float
    maximum_fractional_distance: float
    setup_seconds: float
    solve_seconds: float
    total_seconds: float


@dataclass(frozen=True, slots=True)
class DddPassengerLpIpComparison:
    lp: DddPassengerRecourseResult
    integer: DddPassengerRecourseResult
    absolute_gap: float | None
    relative_gap: float | None
    gap_is_exact: bool


@dataclass(slots=True)
class DddFixedMovementPassengerRecourseOracle:
    """Solve normalized Passenger recourse for one fixed Movement plan."""

    scenario: Scenario
    problem: DddFixedKTrajectoryProblem
    config: DddPassengerRecourseConfig = DddPassengerRecourseConfig()

    def __post_init__(self) -> None:
        self.config.validate()
        self.problem.validate()
        if self.problem.artifact.scenario_id != self.scenario.id:
            raise ValueError("Passenger recourse Scenario and artifact differ")

    def movement_plan(self, solution: DddReferenceSolution) -> EanMovementPlan:
        movement = (
            self.problem.resolved_trajectory_problem.structural_movement_problem
        )
        return DddReferenceToEanMovementPlanAdapter().build(
            problem=movement,
            solution=solution,
            artifact=self.problem.artifact,
        )

    def solve(
        self,
        movement_plan: EanMovementPlan,
        assignment_domain: EanPassengerAssignmentDomain,
    ) -> DddPassengerRecourseResult:
        total_started = perf_counter()
        result = EanOptimizer(
            EanSolveConfig(
                solver_policy=GurobiSolverPolicy(
                    mip_gap=(
                        0.0
                        if assignment_domain is EanPassengerAssignmentDomain.INTEGER
                        else None
                    ),
                    time_limit_seconds=self.config.time_limit_seconds,
                    threads=self.config.threads,
                    mip_focus=(
                        1
                        if assignment_domain is EanPassengerAssignmentDomain.INTEGER
                        else None
                    ),
                ),
                optimization_config=self.config.optimization_config,
                log_to_console=self.config.output_flag,
            )
        ).solve(
            EanFixedMovementPassengerProblem(
                scenario=self.scenario,
                artifact=self.problem.artifact,
                movement_plan=movement_plan,
                objective=self.problem.objective,
                assignment_domain=assignment_domain,
                passenger_builder=_PrebuiltPassengerCandidateBuilder(
                    self.problem.passenger_build
                ),
            )
        )
        metadata = result.metadata
        setup_seconds = metadata.model_setup_runtime_seconds
        solve_seconds = metadata.runtime_seconds or 0.0
        return DddPassengerRecourseResult(
            assignment_domain=assignment_domain,
            solver_status=metadata.solver_status,
            objective_value=metadata.objective_value_seconds,
            best_bound=metadata.best_bound,
            optimal=metadata.solver_status == "OPTIMAL",
            has_solution=metadata.solution_count > 0,
            passenger_candidate_count=metadata.ride_candidate_count or 0,
            assignment_variable_count=(
                metadata.passenger_assignment_variable_count or 0
            ),
            fractional_ride_count=metadata.fractional_ride_count or 0,
            fractional_distance_sum=metadata.fractional_distance_sum or 0.0,
            maximum_fractional_distance=(
                metadata.maximum_fractional_distance or 0.0
            ),
            setup_seconds=setup_seconds,
            solve_seconds=solve_seconds,
            total_seconds=perf_counter() - total_started,
        )

    def compare_lp_and_integer(
        self,
        solution: DddReferenceSolution,
    ) -> DddPassengerLpIpComparison:
        movement_plan = self.movement_plan(solution)
        lp = self.solve(
            movement_plan,
            EanPassengerAssignmentDomain.LP_RELAXATION,
        )
        integer = self.solve(
            movement_plan,
            EanPassengerAssignmentDomain.INTEGER,
        )
        absolute_gap = None
        relative_gap = None
        if lp.objective_value is not None and integer.objective_value is not None:
            absolute_gap = max(0.0, integer.objective_value - lp.objective_value)
            relative_gap = absolute_gap / max(1.0, abs(integer.objective_value))
        return DddPassengerLpIpComparison(
            lp=lp,
            integer=integer,
            absolute_gap=absolute_gap,
            relative_gap=relative_gap,
            gap_is_exact=lp.optimal and integer.optimal and absolute_gap is not None,
        )
