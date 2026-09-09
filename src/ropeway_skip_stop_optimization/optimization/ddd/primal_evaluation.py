from __future__ import annotations

from dataclasses import dataclass, field, replace
from enum import StrEnum
import math
from time import perf_counter
from typing import Protocol

from ropeway_skip_stop_optimization.models import Scenario
from ropeway_skip_stop_optimization.optimization.ddd.ean_plan_adapter import (
    DddReferenceToEanMovementPlanAdapter,
)
from ropeway_skip_stop_optimization.optimization.ddd.network_time_space import (
    DddNetworkTimeProblem,
)
from ropeway_skip_stop_optimization.optimization.ddd.reference import (
    DddReferenceSolution,
)
from ropeway_skip_stop_optimization.optimization.ddd.trajectory_slot import (
    DddTrajectoryColumnPool,
    DddTrajectoryRestrictedMaster,
    DddTrajectorySlotPoolResult,
    DddTrajectorySlotPoolStatus,
    build_ddd_trajectory_passenger_master_problem,
)
from ropeway_skip_stop_optimization.optimization.ddd.trajectory_passenger_lp import (
    DddTrajectoryFactorizedLpOptimizer,
    DddTrajectoryPassengerLpResult,
    DddTrajectoryPassengerLpStatus,
)
from ropeway_skip_stop_optimization.optimization.ddd.trajectory_pricing import (
    DddTrajectoryHeuristicPricingSignal,
    build_ddd_trajectory_heuristic_pricing_signal,
)
from ropeway_skip_stop_optimization.optimization.ddd.trajectory_problem import (
    DddTrajectoryWaitingPolicy,
)
from ropeway_skip_stop_optimization.optimization.ean.artifact import EanBuildArtifact
from ropeway_skip_stop_optimization.optimization.ean.builders.passenger_builder import (
    EanPassengerCandidateBuildResult,
    EanPassengerCandidateBuilder,
)
from ropeway_skip_stop_optimization.optimization.ean.optimization_config import (
    EanOptimizationConfig,
)
from ropeway_skip_stop_optimization.optimization.ean.optimizers.fixed_movement_passenger_model import (
    EanPassengerAssignmentDomain,
)
from ropeway_skip_stop_optimization.optimization.ean.passenger_objective import (
    EanPassengerObjective,
    ean_passenger_objective_definition,
)
from ropeway_skip_stop_optimization.optimization.ean.optimizers.solver import (
    EanFixedMovementPassengerProblem,
    EanOptimizer,
    EanSolveConfig,
)
from ropeway_skip_stop_optimization.optimization.ean.optimizers.solver_policy import (
    GurobiSolverPolicy,
)
from ropeway_skip_stop_optimization.optimization.ean.passenger_plan import (
    EanPassengerServicePlan,
)
from ropeway_skip_stop_optimization.optimization.ean.plan import EanMovementPlan


class DddPrimalEvaluationStatus(StrEnum):
    NOT_RUN = "not_run"
    FEASIBLE = "feasible"
    UNKNOWN = "unknown"


@dataclass(frozen=True)
class DddPrimalEvaluationResult:
    status: DddPrimalEvaluationStatus
    objective_value: float | None
    objective_kind: EanPassengerObjective | None
    objective_unit: str | None
    movement_plan: EanMovementPlan | None
    passenger_plan: EanPassengerServicePlan | None
    solver_status: str | None
    passenger_candidate_count: int
    assignment_variable_count: int
    served_passenger_count: int | None
    unserved_passenger_count: int | None
    setup_seconds: float
    solve_seconds: float
    total_seconds: float
    proposal_source: str = "single_timetable"
    trajectory_pool_option_count: int = 0
    trajectory_pool_conflict_round_count: int = 0
    trajectory_pool_incompatibility_count: int = 0

    @property
    def summary(self) -> DddPrimalEvaluationSummary:
        return DddPrimalEvaluationSummary(
            status=self.status,
            objective_value=self.objective_value,
            served_passenger_count=self.served_passenger_count,
            unserved_passenger_count=self.unserved_passenger_count,
            total_seconds=self.total_seconds,
        )


@dataclass(frozen=True)
class DddPrimalEvaluationSummary:
    status: DddPrimalEvaluationStatus
    objective_value: float | None
    served_passenger_count: int | None
    unserved_passenger_count: int | None
    total_seconds: float


class DddPrimalEvaluator(Protocol):
    def validate_problem(self, problem: DddNetworkTimeProblem) -> None: ...

    def evaluate(
        self,
        problem: DddNetworkTimeProblem,
        solution: DddReferenceSolution,
    ) -> DddPrimalEvaluationResult: ...

    def evaluate_trajectory_pool(
        self,
        problem: DddNetworkTimeProblem,
        column_pool: DddTrajectoryColumnPool,
    ) -> DddPrimalPoolEvaluationResult: ...


@dataclass(frozen=True)
class DddPrimalPoolEvaluationResult:
    pool_result: DddTrajectorySlotPoolResult
    evaluation: DddPrimalEvaluationResult | None
    lp_result: DddTrajectoryPassengerLpResult | None = None


@dataclass(frozen=True)
class _PrebuiltPassengerCandidateBuilder:
    result: EanPassengerCandidateBuildResult

    def build(
        self,
        scenario: Scenario,
        artifact: EanBuildArtifact,
    ) -> EanPassengerCandidateBuildResult:
        del scenario, artifact
        return self.result


@dataclass
class DddEanPassengerPrimalEvaluator:
    """Optimize passenger assignment on an already validated DDD timetable."""

    scenario: Scenario
    artifact: EanBuildArtifact
    objective: EanPassengerObjective = EanPassengerObjective.JOURNEY_TIME
    time_limit_seconds: float | None = 30.0
    mip_gap: float | None = 0.0
    threads: int | None = None
    log_to_console: bool = False
    trajectory_pool_time_limit_seconds: float = 30.0
    trajectory_pool_max_conflict_rounds: int = 100
    optimization_config: EanOptimizationConfig = field(
        default_factory=EanOptimizationConfig
    )
    waiting_policy: DddTrajectoryWaitingPolicy = field(
        default_factory=DddTrajectoryWaitingPolicy
    )
    passenger_candidate_build: EanPassengerCandidateBuildResult | None = None
    _passenger_build: EanPassengerCandidateBuildResult | None = field(
        init=False,
        default=None,
        repr=False,
    )
    _trajectory_master: DddTrajectoryRestrictedMaster | None = field(
        init=False,
        default=None,
        repr=False,
    )

    @property
    def passenger_build(self) -> EanPassengerCandidateBuildResult:
        """Return the canonical cached Passenger candidate universe."""

        return self._passenger_candidates()

    def build_trajectory_pricing_signal(
        self,
        problem: DddNetworkTimeProblem,
        lp_result: DddTrajectoryPassengerLpResult,
    ) -> DddTrajectoryHeuristicPricingSignal:
        self.validate_problem(problem)
        return build_ddd_trajectory_heuristic_pricing_signal(
            movement_problem=problem.movement_problem,
            artifact=self.artifact,
            passenger_build=self._passenger_candidates(),
            objective=self.objective,
            lp_result=lp_result,
        )

    def validate_problem(self, problem: DddNetworkTimeProblem) -> None:
        problem.validate()
        if self.scenario.id != self.artifact.scenario_id:
            raise ValueError("DDD passenger evaluator scenario and artifact differ")
        if problem.movement_problem.scenario_id != self.artifact.scenario_id:
            raise ValueError("DDD passenger evaluator problem and artifact differ")
        if self.time_limit_seconds is not None and self.time_limit_seconds <= 0:
            raise ValueError("DDD passenger evaluation time limit must be positive")
        if self.mip_gap is not None and not 0 <= self.mip_gap <= 1:
            raise ValueError("DDD passenger evaluation MIP gap must lie in [0, 1]")
        if self.threads is not None and self.threads <= 0:
            raise ValueError("DDD passenger evaluation threads must be positive")
        if self.trajectory_pool_time_limit_seconds <= 0:
            raise ValueError("DDD trajectory-pool time limit must be positive")
        if self.trajectory_pool_max_conflict_rounds <= 0:
            raise ValueError("DDD trajectory-pool conflict budget must be positive")
        if any(
            not math.isclose(cost.cost, 0.0, abs_tol=1e-12)
            for cost in problem.objective.route_option_costs
        ):
            raise ValueError(
                "passenger recovery currently requires a zero-cost DDD master so "
                "its bound remains a valid passenger lower bound"
            )
        if problem.objective.terminal_costs or not math.isclose(
            problem.objective.default_terminal_cost,
            0.0,
            abs_tol=1e-12,
        ):
            raise ValueError(
                "passenger recovery currently requires a zero terminal objective"
            )

    def evaluate(
        self,
        problem: DddNetworkTimeProblem,
        solution: DddReferenceSolution,
    ) -> DddPrimalEvaluationResult:
        self.validate_problem(problem)
        total_started = perf_counter()
        movement_plan = DddReferenceToEanMovementPlanAdapter(
            waiting_policy=self.waiting_policy
        ).build(
            problem=problem.movement_problem,
            solution=solution,
            artifact=self.artifact,
        )
        adapter_seconds = perf_counter() - total_started
        result = self.evaluate_movement_plan(problem, movement_plan)
        return replace(
            result,
            total_seconds=result.total_seconds + adapter_seconds,
        )

    def evaluate_movement_plan(
        self,
        problem: DddNetworkTimeProblem,
        movement_plan: EanMovementPlan,
    ) -> DddPrimalEvaluationResult:
        self.validate_problem(problem)
        objective_definition = ean_passenger_objective_definition(self.objective)
        total_started = perf_counter()
        setup_started = perf_counter()
        passenger_build = self._passenger_candidates()
        setup_seconds = perf_counter() - setup_started
        solve_started = perf_counter()
        result = EanOptimizer(
            EanSolveConfig(
                solver_policy=GurobiSolverPolicy(
                    mip_gap=self.mip_gap,
                    time_limit_seconds=self.time_limit_seconds,
                    threads=self.threads,
                    mip_focus=1,
                ),
                optimization_config=self.optimization_config,
                log_to_console=self.log_to_console,
            )
        ).solve(
            EanFixedMovementPassengerProblem(
                scenario=self.scenario,
                artifact=self.artifact,
                movement_plan=movement_plan,
                objective=self.objective,
                assignment_domain=EanPassengerAssignmentDomain.INTEGER,
                passenger_builder=_PrebuiltPassengerCandidateBuilder(passenger_build),
            )
        )
        solve_seconds = perf_counter() - solve_started
        metadata = result.metadata
        if metadata.objective_value_seconds is None or result.passenger_plan is None:
            return DddPrimalEvaluationResult(
                status=DddPrimalEvaluationStatus.UNKNOWN,
                objective_value=None,
                objective_kind=self.objective,
                objective_unit=objective_definition.unit,
                movement_plan=movement_plan,
                passenger_plan=None,
                solver_status=metadata.solver_status,
                passenger_candidate_count=(metadata.ride_candidate_count or 0),
                assignment_variable_count=(
                    metadata.passenger_assignment_variable_count or 0
                ),
                served_passenger_count=None,
                unserved_passenger_count=None,
                setup_seconds=setup_seconds,
                solve_seconds=solve_seconds,
                total_seconds=perf_counter() - total_started,
            )
        return DddPrimalEvaluationResult(
            status=DddPrimalEvaluationStatus.FEASIBLE,
            objective_value=metadata.objective_value_seconds,
            objective_kind=self.objective,
            objective_unit=objective_definition.unit,
            movement_plan=movement_plan,
            passenger_plan=result.passenger_plan,
            solver_status=metadata.solver_status,
            passenger_candidate_count=(metadata.ride_candidate_count or 0),
            assignment_variable_count=(
                metadata.passenger_assignment_variable_count or 0
            ),
            served_passenger_count=metadata.served_passenger_count,
            unserved_passenger_count=metadata.unserved_passenger_count,
            setup_seconds=setup_seconds,
            solve_seconds=solve_seconds,
            total_seconds=perf_counter() - total_started,
        )

    def evaluate_trajectory_pool(
        self,
        problem: DddNetworkTimeProblem,
        column_pool: DddTrajectoryColumnPool,
    ) -> DddPrimalPoolEvaluationResult:
        self.validate_problem(problem)
        if self._trajectory_master is None:
            self._trajectory_master = DddTrajectoryRestrictedMaster(
                time_limit_seconds=self.trajectory_pool_time_limit_seconds,
                max_conflict_rounds=self.trajectory_pool_max_conflict_rounds,
                output_flag=self.log_to_console,
            )
        pool_result = self._trajectory_master.solve(
            problem=problem,
            artifact=self.artifact,
            passenger_build=self._passenger_candidates(),
            objective=self.objective,
            column_pool=column_pool,
        )
        lp_setup_started = perf_counter()
        lp_problem = build_ddd_trajectory_passenger_master_problem(
            problem=problem,
            artifact=self.artifact,
            passenger_build=self._passenger_candidates(),
            objective=self.objective,
            column_pool=column_pool,
            incompatibility_pairs=pool_result.incompatibility_pairs,
            complete_incompatibility_separation=True,
        )
        lp_setup_seconds = perf_counter() - lp_setup_started
        lp_result = DddTrajectoryFactorizedLpOptimizer(
            output_flag=self.log_to_console
        ).solve(lp_problem)
        lp_result = replace(
            lp_result,
            build_seconds=lp_result.build_seconds + lp_setup_seconds,
            total_seconds=lp_result.total_seconds + lp_setup_seconds,
        )
        if (
            lp_result.status is DddTrajectoryPassengerLpStatus.OPTIMAL
            and lp_result.objective_value is not None
            and pool_result.restricted_objective_value is not None
            and lp_result.objective_value
            > pool_result.restricted_objective_value + 1e-5
        ):
            raise RuntimeError("trajectory LP exceeds its restricted integer master")
        if (
            pool_result.status is not DddTrajectorySlotPoolStatus.FEASIBLE
            or pool_result.movement_plan is None
        ):
            return DddPrimalPoolEvaluationResult(pool_result, None, lp_result)
        evaluation = self.evaluate_movement_plan(
            problem,
            pool_result.movement_plan,
        )
        if (
            evaluation.status is DddPrimalEvaluationStatus.FEASIBLE
            and evaluation.objective_value is not None
            and pool_result.restricted_objective_value is not None
            and not math.isclose(
                evaluation.objective_value,
                pool_result.restricted_objective_value,
                rel_tol=0.0,
                abs_tol=1e-5,
            )
        ):
            raise RuntimeError(
                "trajectory-slot objective differs from exact passenger recourse"
            )
        evaluation = replace(
            evaluation,
            proposal_source="trajectory_slot_pool",
            trajectory_pool_option_count=pool_result.trajectory_option_count,
            trajectory_pool_conflict_round_count=(pool_result.conflict_round_count),
            trajectory_pool_incompatibility_count=(
                pool_result.incompatibility_constraint_count
            ),
            total_seconds=(
                evaluation.total_seconds
                + pool_result.total_seconds
                + lp_result.total_seconds
            ),
        )
        return DddPrimalPoolEvaluationResult(pool_result, evaluation, lp_result)

    def _passenger_candidates(self) -> EanPassengerCandidateBuildResult:
        if self.passenger_candidate_build is not None:
            return self.passenger_candidate_build
        if self._passenger_build is None:
            resolved_config = self.optimization_config.resolved_for_fleet_mode(
                self.artifact.fleet_mode
            ).resolved_for_passenger_objective(self.objective)
            self._passenger_build = EanPassengerCandidateBuilder(
                optimization_config=resolved_config
            ).build(self.scenario, self.artifact)
        return self._passenger_build
