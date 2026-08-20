from __future__ import annotations

from dataclasses import dataclass, replace
from enum import StrEnum
from hashlib import sha256
from itertools import zip_longest
import json
import math
from time import perf_counter
from typing import Callable

from ropeway_skip_stop_optimization.optimization.ddd.models import (
    DddFixedStart,
    DddMovementProblem,
    DddRouteDecision,
)
from ropeway_skip_stop_optimization.optimization.ddd.ean_plan_adapter import (
    DddReferenceToEanMovementPlanAdapter,
)
from ropeway_skip_stop_optimization.optimization.ddd.network_time_space import (
    DddNetworkTimeProblem,
)
from ropeway_skip_stop_optimization.optimization.ddd.reference import (
    DddReferenceSolution,
    DddReferenceTrajectory,
    build_ddd_reference_visit,
    validate_ddd_reference_solution,
    validate_ddd_reference_trajectory,
)
from ropeway_skip_stop_optimization.optimization.ddd.trajectory_column_generation import (
    DddTrajectoryBoundStatus,
    DddTrajectoryPricingCertificate,
    DddTrajectoryReducedCost,
    DddTrajectoryWaitingDomain,
)
from ropeway_skip_stop_optimization.optimization.ddd.trajectory_exact_pricing import (
    DddTrajectoryExactNoWaitPricingOracle,
    DddTrajectoryExactOipNoWaitPricingOracle,
    DddTrajectoryExactReservoirNoWaitPricingOracle,
    DddTrajectoryReservoirAnchorPricingOracle,
    DddTrajectoryExactPricingCandidate,
    DddTrajectoryExactPricingResult,
    DddTrajectoryExactPricingStatus,
    DddTrajectoryPricingFormulation,
)
from ropeway_skip_stop_optimization.optimization.ddd.trajectory_problem import (
    DddFixedTrajectoryStartDomain,
    DddOptimizedInitialPlacementDomain,
    DddReservoirTrajectoryKind,
    DddReservoirTrajectoryStartDomain,
    DddTrajectoryFleetMode,
    DddTrajectoryProblem,
    DddTrajectoryWaitingPolicy,
)
from ropeway_skip_stop_optimization.optimization.ddd.trajectory_reservoir import (
    DDD_RESERVOIR_TIME_TOLERANCE_SECONDS,
    DddReservoirFleetPlan,
    build_ddd_reservoir_all_stop_seed,
    build_ddd_reservoir_dispatch_anchors,
    build_ddd_reservoir_reference_trajectory,
    build_ddd_stored_reservoir_trajectory,
    validate_ddd_reservoir_reference_trajectory,
    validate_ddd_reservoir_plan_against_artifact,
    validate_ddd_reservoir_solution,
)
from ropeway_skip_stop_optimization.optimization.ddd.trajectory_oip import (
    DddOipTrajectoryStart,
    build_ean_oip_plan_and_fleet,
    build_ddd_oip_reference_trajectory,
    ddd_oip_trajectories_from_ean_seed,
    validate_ddd_oip_reference_trajectory,
)
from ropeway_skip_stop_optimization.optimization.ddd.trajectory_exhaustive_reference import (
    DddTrajectoryReferenceMasterBuildResult,
    build_ddd_trajectory_reference_master,
    ddd_trajectory_instance_fingerprint,
)
from ropeway_skip_stop_optimization.optimization.ddd.trajectory_passenger_lp import (
    DddTrajectoryFactorizedLpOptimizer,
    DddTrajectoryFactorizedMipReferenceOptimizer,
    DddTrajectoryMasterDualMode,
    DddTrajectoryPassengerDuals,
    DddTrajectoryPassengerLpResult,
    DddTrajectoryPassengerLpStatus,
    DddTrajectoryPassengerMipResult,
)
from ropeway_skip_stop_optimization.optimization.ddd.trajectory_slot import (
    ddd_trajectory_column,
)
from ropeway_skip_stop_optimization.optimization.ddd.trajectory_resource_windows import (
    DddTrajectoryConflictRowMode,
    DddTrajectoryResourceWindow,
    DddTrajectoryResourceWindowRow,
    build_ddd_trajectory_resource_window_rows,
    ddd_trajectory_resource_intervals,
    separate_ddd_trajectory_resource_windows,
)
from ropeway_skip_stop_optimization.optimization.ean.artifact import EanBuildArtifact
from ropeway_skip_stop_optimization.optimization.ean.builders.passenger_builder import (
    EanPassengerCandidateBuildResult,
)
from ropeway_skip_stop_optimization.optimization.ean.passenger_objective import (
    EanPassengerObjective,
)
from ropeway_skip_stop_optimization.optimization.ean.models import (
    EanFleetMode,
)
from ropeway_skip_stop_optimization.optimization.ean.fleet import EanFleetPlan
from ropeway_skip_stop_optimization.optimization.ean.formulation_config import (
    EanHorizonFormulation,
)
from ropeway_skip_stop_optimization.optimization.ean.optimizers.all_stop_mip_start import (
    EanAllStopMipStartSeedBuilder,
    EanPeriodicRouteMipStartSeedBuilder,
)
from ropeway_skip_stop_optimization.optimization.ean.validation import (
    validate_ean_initial_boundary_against_artifact,
    validate_ean_movement_plan_against_artifact,
)


class DddTrajectoryRootCgStatus(StrEnum):
    OPTIMAL_ROOT_LP = "optimal_root_lp"
    ITERATION_LIMIT = "iteration_limit"
    TIME_LIMIT = "time_limit"
    UNKNOWN = "unknown"
    UNKNOWN_NO_FEASIBLE_SEED = "unknown_no_feasible_seed"
    INTEGER_OPTIMAL = "integer_optimal"
    ROOT_LP_CERTIFIED_WITH_INTEGER_GAP = "root_lp_certified_with_integer_gap"
    TIME_LIMIT_WITH_CERTIFIED_INTERVAL = "time_limit_with_certified_interval"
    ITERATION_LIMIT_WITH_CERTIFIED_INTERVAL = "iteration_limit_with_certified_interval"
    MOVEMENT_INFEASIBLE = "movement_infeasible"
    INTERNAL_VALIDATION_ERROR = "internal_validation_error"
    INTERNAL_CERTIFICATE_ERROR = "internal_certificate_error"


class DddTrajectoryDiversityMode(StrEnum):
    OFF = "off"
    RESOURCE_WINDOWS = "resource_windows"
    STOP_SKIP = "stop_skip"


class DddReservoirPrimalPricingMode(StrEnum):
    COMPACT_DISPATCH_WINDOWS = "compact_dispatch_windows"
    TIME_EXPANDED_ANCHORS = "time_expanded_anchors"


@dataclass(frozen=True)
class DddTrajectoryRootCgPricingDiagnostic:
    cabin_id: int
    status: DddTrajectoryExactPricingStatus
    incumbent_reduced_cost: float
    certified_reduced_cost_lower_bound: float | None
    absolute_pricing_gap: float | None
    exact: bool
    option_is_existing: bool
    model_variable_count: int
    model_linear_constraint_count: int
    model_general_constraint_count: int
    solver_node_count: float
    solve_seconds: float
    reused_from_cabin_id: int | None = None
    priced_start_class_count: int = 0
    required_start_class_count: int = 0
    bounded_start_class_count: int = 0
    relative_node_count: int = 0
    relative_arc_count: int = 0
    origin_product_count: int = 0
    model_build_seconds: float = 0.0


@dataclass(frozen=True)
class DddTrajectoryRootCgIteration:
    round_index: int
    trajectory_count: int
    incompatibility_pair_count: int
    resource_window_count: int
    added_resource_window_count: int
    restricted_lp_value: float
    pricing_corrected_lower_bound: float | None
    pricing_bound_correction: float | None
    minimum_certified_reduced_cost_bound: float | None
    proof_pricing_exclusion_count: int
    global_lower_bound: float
    restricted_integer_upper_bound: float | None
    global_upper_bound: float | None
    minimum_reduced_cost: float | None
    exact_pricing_cabin_count: int
    added_trajectory_count: int
    diverse_added_trajectory_count: int
    extra_pricing_call_count: int
    master_build_seconds: float
    lp_seconds: float
    mip_seconds: float
    pricing_seconds: float
    resource_separation_seconds: float
    total_seconds: float
    pricing_diagnostics: tuple[DddTrajectoryRootCgPricingDiagnostic, ...]
    station_start_column_count: int = 0
    rope_start_column_count: int = 0
    boundary_incompatibility_pair_count: int = 0
    proof_pricing_solve_count: int = 0
    proof_pricing_reused_cabin_count: int = 0
    priced_start_class_count: int = 0
    required_start_class_count: int = 0
    bounded_start_class_count: int = 0
    primal_pricing_call_count: int = 0
    primal_pricing_seconds: float = 0.0
    primal_pricing_candidate_count: int = 0
    primal_pricing_negative_candidate_count: int = 0
    primal_pricing_status_counts: tuple[tuple[str, int], ...] = ()
    primal_pricing_details: tuple[str, ...] = ()
    relative_node_count: int = 0
    relative_arc_count: int = 0
    origin_product_count: int = 0
    pricing_model_build_seconds: float = 0.0
    stored_column_count: int = 0
    dispatched_column_count: int = 0
    incumbent_dispatched_fleet_count: int | None = None
    waiting_column_count: int = 0
    positive_wait_visit_count: int = 0
    maximum_column_wait_seconds: float = 0.0
    pricing_tier_seconds: float = 0.0
    pricing_retry_count: int = 0
    unresolved_pricing_count: int = 0
    nonexact_certified_nonnegative_pricing_count: int = 0
    remaining_budget_seconds: float | None = None
    restricted_mip_ran: bool = True
    restricted_mip_solution_count: int = 0
    restricted_mip_solver_status: int | None = None


@dataclass(frozen=True)
class DddTrajectoryRootCgResult:
    status: DddTrajectoryRootCgStatus
    certified_lower_bound: float
    best_upper_bound: float | None
    relative_gap: float | None
    root_lp_certified: bool
    iterations: tuple[DddTrajectoryRootCgIteration, ...]
    trajectories: tuple[DddReferenceTrajectory, ...]
    incumbent_option_ids: tuple[str, ...]
    incumbent_ride_values_by_id: dict[str, float]
    total_seconds: float
    detail: str | None = None
    fleet_mode: DddTrajectoryFleetMode = DddTrajectoryFleetMode.FIXED_STARTS
    fleet_plan: EanFleetPlan | None = None
    full_start_domain_priced: bool = False
    seed_kind: str | None = None
    reservoir_fleet_plan: DddReservoirFleetPlan | None = None
    certificate_valid: bool = True
    objective_floor: float = 0.0


@dataclass(frozen=True)
class DddTrajectoryRootCgState:
    """Complete state required to continue root column generation exactly."""

    instance_fingerprint: str
    objective: EanPassengerObjective
    conflict_row_mode: DddTrajectoryConflictRowMode
    completed_rounds: int
    certified_lower_bound: float
    best_upper_bound: float | None
    root_lp_certified: bool
    incumbent_option_ids: tuple[str, ...]
    incumbent_ride_values_by_id: dict[str, float]
    iterations: tuple[DddTrajectoryRootCgIteration, ...]
    trajectories: tuple[DddReferenceTrajectory, ...]
    resource_windows: tuple[DddTrajectoryResourceWindow, ...]
    total_seconds: float
    fleet_mode: DddTrajectoryFleetMode = DddTrajectoryFleetMode.FIXED_STARTS
    reservoir_start_domain: DddReservoirTrajectoryStartDomain | None = None
    waiting_policy: DddTrajectoryWaitingPolicy = DddTrajectoryWaitingPolicy()


@dataclass
class _DddTrajectoryRootCgRun:
    instance_fingerprint: str
    trajectory_by_id: dict[str, DddReferenceTrajectory]
    iterations: list[DddTrajectoryRootCgIteration]
    lower_bound: float
    upper_bound: float | None
    incumbent_option_ids: tuple[str, ...]
    incumbent_ride_values_by_id: dict[str, float]
    elapsed_offset_seconds: float
    resource_windows: tuple[DddTrajectoryResourceWindow, ...]
    first_round: int
    trajectory_problem: DddTrajectoryProblem
    fleet_plan: EanFleetPlan | None = None
    seed_kind: str | None = None
    reservoir_fleet_plan: DddReservoirFleetPlan | None = None


@dataclass(frozen=True)
class _DddTrajectoryRestrictedMasterRound:
    reference_master: DddTrajectoryReferenceMasterBuildResult
    lp: DddTrajectoryPassengerLpResult
    mip: DddTrajectoryPassengerMipResult
    resource_windows: tuple[DddTrajectoryResourceWindow, ...]
    added_resource_window_count: int
    master_seconds: float
    lp_seconds: float
    resource_separation_seconds: float


@dataclass(frozen=True)
class _DddTrajectoryPricingRound:
    results: tuple[DddTrajectoryExactPricingResult, ...]
    candidate_results: tuple[DddTrajectoryExactPricingResult, ...]
    diagnostics: tuple[DddTrajectoryRootCgPricingDiagnostic, ...]
    certificate: DddTrajectoryPricingCertificate
    bound_correction: float | None
    minimum_certified_reduced_cost_bound: float | None
    proof_exclusion_count: int
    extra_call_count: int
    seconds: float
    proof_solve_count: int = 0
    proof_reused_cabin_count: int = 0
    primal_call_count: int = 0
    primal_seconds: float = 0.0
    primal_candidate_option_ids: frozenset[str] = frozenset()
    primal_negative_candidate_count: int = 0
    primal_status_counts: tuple[tuple[str, int], ...] = ()
    primal_details: tuple[str, ...] = ()
    maximum_tier_seconds: float = 0.0
    retry_count: int = 0
    unresolved_count: int = 0


class _DddTrajectoryRootCgAbort(RuntimeError):
    """Expected round failure that preserves the last certified bounds."""


class _DddNoFeasibleSeed(RuntimeError):
    pass


class _DddCertificateInvariantError(RuntimeError):
    pass


class _DddTotalBudgetExhausted(_DddTrajectoryRootCgAbort):
    pass


@dataclass(frozen=True)
class DddTrajectoryExactRootColumnGenerationSolver:
    """Exact root column generation for the supported finite trajectory domains."""

    max_iterations: int = 30
    total_time_limit_seconds: float | None = None
    pricing_time_limit_seconds: float = 5.0
    pricing_threads: int = 1
    master_dual_mode: DddTrajectoryMasterDualMode = DddTrajectoryMasterDualMode.DEFAULT
    proof_pricing_mip_focus: int = 2
    extra_pricing_mip_focus: int = 1
    pricing_formulation: DddTrajectoryPricingFormulation = (
        DddTrajectoryPricingFormulation.TIME_EXPANDED_PATH
    )
    pricing_tolerance: float = 1e-7
    max_incompatibility_pair_checks: int = 2_000_000
    conflict_row_mode: DddTrajectoryConflictRowMode = (
        DddTrajectoryConflictRowMode.PAIR_ONLY
    )
    max_resource_window_rounds: int = 100
    columns_per_cabin_per_round: int = 1
    diversity_mode: DddTrajectoryDiversityMode = DddTrajectoryDiversityMode.OFF
    minimum_diversity_distance: int = 1
    extra_column_time_limit_seconds: float = 10.0
    oip_primal_pricing_time_limit_seconds: float = 0.0
    reservoir_primal_pricing_time_limit_seconds: float = 0.0
    reservoir_primal_pricing_mode: DddReservoirPrimalPricingMode = (
        DddReservoirPrimalPricingMode.COMPACT_DISPATCH_WINDOWS
    )
    reservoir_primal_maximum_cabin_calls_per_round: int = 4
    reservoir_dispatch_anchor_count: int = 32
    reservoir_primal_maximum_arc_count: int = 25_000
    reservoir_primal_maximum_passenger_arc_product: int = 250_000
    output_flag: bool = False
    certified_fixed_k_mode: bool = False
    objective_floor: float = 0.0
    pricing_time_limit_tiers_seconds: tuple[float, ...] = ()
    restricted_mip_interval: int = 1
    restricted_mip_time_limit_seconds: float | None = None
    final_mip_time_limit_seconds: float = 0.0
    restricted_mip_focus: int = 1

    def solve(
        self,
        *,
        problem: DddNetworkTimeProblem,
        trajectory_problem: DddTrajectoryProblem | None = None,
        artifact: EanBuildArtifact,
        passenger_build: EanPassengerCandidateBuildResult,
        objective: EanPassengerObjective,
        initial_trajectories: tuple[DddReferenceTrajectory, ...] | None = None,
        resume_state: DddTrajectoryRootCgState | None = None,
        progress_callback: Callable[[DddTrajectoryRootCgIteration], None] | None = None,
        checkpoint_callback: Callable[[DddTrajectoryRootCgState], None] | None = None,
    ) -> DddTrajectoryRootCgResult:
        started = perf_counter()
        trajectory_problem = trajectory_problem or DddTrajectoryProblem(
            movement_core=problem.movement_problem.core,
            start_domain=DddFixedTrajectoryStartDomain(problem.movement_problem.starts),
        )
        self._validate(problem, artifact, trajectory_problem)
        try:
            run = self._initialize_run(
                problem=problem,
                trajectory_problem=trajectory_problem,
                artifact=artifact,
                objective=objective,
                initial_trajectories=initial_trajectories,
                resume_state=resume_state,
            )
        except _DddNoFeasibleSeed as error:
            return DddTrajectoryRootCgResult(
                status=DddTrajectoryRootCgStatus.UNKNOWN_NO_FEASIBLE_SEED,
                certified_lower_bound=self.objective_floor,
                best_upper_bound=None,
                relative_gap=None,
                root_lp_certified=False,
                iterations=(),
                trajectories=(),
                incumbent_option_ids=(),
                incumbent_ride_values_by_id={},
                total_seconds=perf_counter() - started,
                detail=str(error),
                fleet_mode=trajectory_problem.fleet_mode,
                full_start_domain_priced=False,
                objective_floor=self.objective_floor,
            )
        if resume_state is not None and resume_state.root_lp_certified:
            return self._run_result(
                status=self._root_completion_status(run),
                run=run,
                started=started,
                detail=None,
                root_lp_certified=True,
            )
        pricing_oracle = self._proof_pricing_oracle(trajectory_problem)
        try:
            for round_index in range(run.first_round, self.max_iterations + 1):
                if (
                    self.total_time_limit_seconds is not None
                    and run.elapsed_offset_seconds + perf_counter() - started
                    >= self.total_time_limit_seconds
                ):
                    return self._run_result(
                        status=(
                            DddTrajectoryRootCgStatus.TIME_LIMIT_WITH_CERTIFIED_INTERVAL
                            if self.certified_fixed_k_mode
                            else DddTrajectoryRootCgStatus.TIME_LIMIT
                        ),
                        run=run,
                        started=started,
                        detail=(
                            "trajectory root column-generation total time limit "
                            "reached between completed rounds"
                        ),
                    )
                round_started = perf_counter()
                master_round = self._solve_restricted_master_round(
                    round_index=round_index,
                    problem=problem,
                    trajectory_problem=trajectory_problem,
                    artifact=artifact,
                    passenger_build=passenger_build,
                    objective=objective,
                    run=run,
                    remaining_budget_seconds=self._remaining_budget_seconds(
                        run=run, started=started
                    ),
                    pricing_tolerance=self.pricing_tolerance,
                )
                self._validate_bound_invariants(
                    run=run,
                    restricted_lp_value=master_round.lp.objective_value,
                    stage=f"round {round_index} restricted LP",
                )
                run.resource_windows = master_round.resource_windows
                restricted_upper = self._update_incumbent(
                    problem=problem,
                    trajectory_problem=trajectory_problem,
                    artifact=artifact,
                    master_round=master_round,
                    run=run,
                )
                pricing_round = self._solve_pricing_round(
                    round_index=round_index,
                    problem=problem,
                    trajectory_problem=trajectory_problem,
                    artifact=artifact,
                    passenger_build=passenger_build,
                    objective=objective,
                    run=run,
                    master_round=master_round,
                    pricing_oracle=pricing_oracle,
                    remaining_budget_seconds=self._remaining_budget_seconds(
                        run=run, started=started
                    ),
                )
                corrected = pricing_round.certificate.certified_lower_bound
                if (
                    corrected is not None
                    and corrected
                    > master_round.lp.objective_value + self._bound_tolerance(
                        master_round.lp.objective_value
                    )
                ):
                    raise _DddCertificateInvariantError(
                        "pricing-corrected lower bound exceeds its restricted LP"
                    )
                if corrected is not None:
                    run.lower_bound = max(
                        run.lower_bound, corrected, self.objective_floor
                    )
                self._validate_bound_invariants(
                    run=run,
                    restricted_lp_value=master_round.lp.objective_value,
                    stage=f"round {round_index} pricing",
                )
                added, diverse_added = self._add_priced_columns(
                    run=run,
                    pricing_round=pricing_round,
                )
                iteration = self._build_iteration(
                    round_index=round_index,
                    round_started=round_started,
                    run=run,
                    master_round=master_round,
                    pricing_round=pricing_round,
                    restricted_upper=restricted_upper,
                    added=added,
                    diverse_added=diverse_added,
                    remaining_budget_seconds=self._remaining_budget_seconds(
                        run=run, started=started
                    ),
                )
                run.iterations.append(iteration)
                root_lp_certified = (
                    added == 0
                    and pricing_round.certificate.bound_status
                    is DddTrajectoryBoundStatus.FULL_ROOT_LP_CERTIFIED
                )
                final_mip_limit = self._clamped_time_limit(
                    self.final_mip_time_limit_seconds,
                    self._remaining_budget_seconds(run=run, started=started),
                )
                if (
                    root_lp_certified
                    and final_mip_limit is not None
                    and final_mip_limit > 1e-6
                ):
                    final_mip = self._solve_restricted_mip(
                        master_round.reference_master.master_problem,
                        run=run,
                        time_limit_seconds=final_mip_limit,
                    )
                    master_round = replace(master_round, mip=final_mip)
                    restricted_upper = self._update_incumbent(
                        problem=problem,
                        trajectory_problem=trajectory_problem,
                        artifact=artifact,
                        master_round=master_round,
                        run=run,
                    )
                    iteration = replace(
                        iteration,
                        restricted_integer_upper_bound=restricted_upper,
                        global_upper_bound=run.upper_bound,
                        mip_seconds=iteration.mip_seconds + final_mip.total_seconds,
                        restricted_mip_ran=True,
                        restricted_mip_solution_count=final_mip.solution_count,
                        restricted_mip_solver_status=final_mip.solver_status,
                    )
                    run.iterations[-1] = iteration
                if progress_callback is not None:
                    progress_callback(iteration)
                if checkpoint_callback is not None:
                    checkpoint_callback(
                        self._checkpoint_state(
                            run=run,
                            objective=objective,
                            round_index=round_index,
                            root_lp_certified=root_lp_certified,
                            started=started,
                        )
                    )
                if (
                    pricing_round.certificate.bound_status
                    is not DddTrajectoryBoundStatus.FULL_ROOT_LP_CERTIFIED
                    and added == 0
                ):
                    return self._run_result(
                        status=DddTrajectoryRootCgStatus.UNKNOWN,
                        run=run,
                        started=started,
                        detail=(
                            "pricing was not certified and produced no improving "
                            "incumbent column"
                        ),
                    )
                if added == 0:
                    if not root_lp_certified:
                        return self._run_result(
                            status=DddTrajectoryRootCgStatus.UNKNOWN,
                            run=run,
                            started=started,
                            detail=(
                                "pricing found no new distinct column but did not "
                                "certify the root LP"
                            ),
                        )
                    return self._run_result(
                        status=self._root_completion_status(run),
                        run=run,
                        started=started,
                        detail=None,
                        root_lp_certified=True,
                    )
        except _DddCertificateInvariantError as error:
            run.lower_bound = self.objective_floor
            return self._run_result(
                status=DddTrajectoryRootCgStatus.INTERNAL_CERTIFICATE_ERROR,
                run=run,
                started=started,
                detail=str(error),
                certificate_valid=False,
            )
        except _DddTotalBudgetExhausted as error:
            return self._run_result(
                status=(
                    DddTrajectoryRootCgStatus.TIME_LIMIT_WITH_CERTIFIED_INTERVAL
                    if self.certified_fixed_k_mode
                    else DddTrajectoryRootCgStatus.TIME_LIMIT
                ),
                run=run,
                started=started,
                detail=str(error),
            )
        except _DddTrajectoryRootCgAbort as error:
            return self._run_result(
                status=DddTrajectoryRootCgStatus.UNKNOWN,
                run=run,
                started=started,
                detail=str(error),
            )

        return self._run_result(
            status=(
                DddTrajectoryRootCgStatus.ITERATION_LIMIT_WITH_CERTIFIED_INTERVAL
                if self.certified_fixed_k_mode
                else DddTrajectoryRootCgStatus.ITERATION_LIMIT
            ),
            run=run,
            started=started,
            detail="trajectory root column-generation iteration limit exhausted",
        )

    def _initialize_run(
        self,
        *,
        problem: DddNetworkTimeProblem,
        trajectory_problem: DddTrajectoryProblem,
        artifact: EanBuildArtifact,
        objective: EanPassengerObjective,
        initial_trajectories: tuple[DddReferenceTrajectory, ...] | None,
        resume_state: DddTrajectoryRootCgState | None,
    ) -> _DddTrajectoryRootCgRun:
        instance_fingerprint = ddd_trajectory_problem_instance_fingerprint(
            artifact,
            trajectory_problem,
        )
        if resume_state is not None and initial_trajectories is not None:
            raise ValueError(
                "resume state and initial trajectories are mutually exclusive"
            )
        if resume_state is not None:
            self._validate_resume_state(
                resume_state,
                instance_fingerprint=instance_fingerprint,
                objective=objective,
                fleet_mode=trajectory_problem.fleet_mode,
                reservoir_start_domain=(
                    trajectory_problem.start_domain
                    if isinstance(
                        trajectory_problem.start_domain,
                        DddReservoirTrajectoryStartDomain,
                    )
                    else None
                ),
                waiting_policy=trajectory_problem.waiting_policy,
            )
            trajectories = resume_state.trajectories
            seed_kind = "checkpoint"
        else:
            if initial_trajectories is not None:
                trajectories = initial_trajectories
                seed_kind = "explicit"
            elif isinstance(
                trajectory_problem.start_domain, DddFixedTrajectoryStartDomain
            ):
                trajectories = build_ddd_all_stop_seed_trajectories(
                    problem.movement_problem
                )
                seed_kind = "fixed_all_stop"
            elif isinstance(
                trajectory_problem.start_domain,
                DddOptimizedInitialPlacementDomain,
            ):
                trajectories, seed_kind = self._build_oip_seed(
                    trajectory_problem=trajectory_problem,
                    artifact=artifact,
                )
            else:
                try:
                    trajectories = build_ddd_reservoir_all_stop_seed(
                        trajectory_problem
                    )
                except ValueError as error:
                    raise _DddNoFeasibleSeed(
                        f"no validated reservoir all-stop seed is available: {error}"
                    ) from error
                seed_kind = "reservoir_all_stop"
        trajectory_by_id = {
            ddd_trajectory_column(
                trajectory,
                instance_fingerprint=instance_fingerprint,
            ).id: trajectory
            for trajectory in trajectories
        }
        if len(trajectory_by_id) != len(trajectories):
            raise ValueError("initial trajectory root pool contains duplicates")
        if resume_state is not None and not set(
            resume_state.incumbent_option_ids
        ).issubset(trajectory_by_id):
            raise ValueError("trajectory checkpoint incumbent is outside its pool")
        expected_cabin_ids = set(trajectory_problem.cabin_ids)
        if {item.cabin_id for item in trajectories} != expected_cabin_ids:
            raise ValueError("initial trajectory root pool does not cover every cabin")
        for trajectory in trajectories:
            if isinstance(
                trajectory_problem.start_domain, DddFixedTrajectoryStartDomain
            ):
                validate_ddd_reference_trajectory(
                    problem.movement_problem,
                    trajectory,
                    waiting_policy=trajectory_problem.waiting_policy,
                )
            elif isinstance(
                trajectory_problem.start_domain,
                DddOptimizedInitialPlacementDomain,
            ):
                validate_ddd_oip_reference_trajectory(
                    trajectory_problem, artifact, trajectory
                )
            else:
                validate_ddd_reservoir_reference_trajectory(
                    trajectory_problem,
                    trajectory,
                )
        if (
            self.certified_fixed_k_mode
            and isinstance(
                trajectory_problem.start_domain, DddFixedTrajectoryStartDomain
            )
        ):
            validate_ddd_reference_solution(
                problem.movement_problem,
                DddReferenceSolution(tuple(trajectories)),
                waiting_policy=trajectory_problem.waiting_policy,
            )
        run = _DddTrajectoryRootCgRun(
            instance_fingerprint=instance_fingerprint,
            trajectory_by_id=trajectory_by_id,
            iterations=(
                list(resume_state.iterations) if resume_state is not None else []
            ),
            lower_bound=(
                resume_state.certified_lower_bound
                if resume_state is not None
                else self.objective_floor
            ),
            upper_bound=(
                resume_state.best_upper_bound if resume_state is not None else None
            ),
            incumbent_option_ids=(
                resume_state.incumbent_option_ids if resume_state is not None else ()
            ),
            incumbent_ride_values_by_id=(
                dict(resume_state.incumbent_ride_values_by_id)
                if resume_state is not None
                else {}
            ),
            elapsed_offset_seconds=(
                resume_state.total_seconds if resume_state is not None else 0.0
            ),
            resource_windows=(
                resume_state.resource_windows if resume_state is not None else ()
            ),
            first_round=(
                resume_state.completed_rounds + 1 if resume_state is not None else 1
            ),
            trajectory_problem=trajectory_problem,
            seed_kind=seed_kind,
        )
        if (
            resume_state is not None
            and resume_state.incumbent_option_ids
            and isinstance(
                trajectory_problem.start_domain,
                DddOptimizedInitialPlacementDomain,
            )
        ):
            _, run.fleet_plan = build_ean_oip_plan_and_fleet(
                problem=trajectory_problem,
                artifact=artifact,
                trajectories=tuple(
                    run.trajectory_by_id[option_id]
                    for option_id in resume_state.incumbent_option_ids
                ),
            )
        elif (
            resume_state is not None
            and resume_state.incumbent_option_ids
            and isinstance(
                trajectory_problem.start_domain,
                DddReservoirTrajectoryStartDomain,
            )
        ):
            run.reservoir_fleet_plan = validate_ddd_reservoir_solution(
                trajectory_problem,
                tuple(
                    run.trajectory_by_id[option_id]
                    for option_id in resume_state.incumbent_option_ids
                ),
            )
        return run

    @staticmethod
    def _build_oip_seed(
        *,
        trajectory_problem: DddTrajectoryProblem,
        artifact: EanBuildArtifact,
    ) -> tuple[tuple[DddReferenceTrajectory, ...], str]:
        errors = []
        for builder in (
            EanPeriodicRouteMipStartSeedBuilder(),
            EanAllStopMipStartSeedBuilder(),
        ):
            try:
                seed = builder.build(
                    artifact,
                    EanHorizonFormulation.EXACT_TIME_ACTIVATION,
                )
                return (
                    ddd_oip_trajectories_from_ean_seed(
                        problem=trajectory_problem,
                        artifact=artifact,
                        seed=seed,
                    ),
                    (
                        "periodic_route"
                        if isinstance(builder, EanPeriodicRouteMipStartSeedBuilder)
                        else "all_stop"
                    ),
                )
            except (ValueError, RuntimeError) as error:
                errors.append(str(error))
        raise _DddNoFeasibleSeed(
            "no validated exact-K OIP seed is available: " + " | ".join(errors)
        )

    def _proof_pricing_oracle(
        self, trajectory_problem: DddTrajectoryProblem
    ) -> (
        DddTrajectoryExactNoWaitPricingOracle
        | DddTrajectoryExactOipNoWaitPricingOracle
        | DddTrajectoryExactReservoirNoWaitPricingOracle
    ):
        if isinstance(
            trajectory_problem.start_domain, DddOptimizedInitialPlacementDomain
        ):
            return DddTrajectoryExactOipNoWaitPricingOracle(
                time_limit_seconds=self.pricing_time_limit_seconds,
                threads=self.pricing_threads,
                output_flag=self.output_flag,
                mip_focus=self.proof_pricing_mip_focus,
                formulation=self.pricing_formulation,
            )
        if isinstance(
            trajectory_problem.start_domain,
            DddReservoirTrajectoryStartDomain,
        ):
            return DddTrajectoryExactReservoirNoWaitPricingOracle(
                time_limit_seconds=self.pricing_time_limit_seconds,
                threads=self.pricing_threads,
                output_flag=self.output_flag,
                mip_focus=self.proof_pricing_mip_focus,
            )
        return DddTrajectoryExactNoWaitPricingOracle(
            time_limit_seconds=self.pricing_time_limit_seconds,
            threads=self.pricing_threads,
            output_flag=self.output_flag,
            mip_focus=self.proof_pricing_mip_focus,
            formulation=self.pricing_formulation,
        )

    def _solve_restricted_master_round(
        self,
        *,
        round_index: int,
        problem: DddNetworkTimeProblem,
        trajectory_problem: DddTrajectoryProblem,
        artifact: EanBuildArtifact,
        passenger_build: EanPassengerCandidateBuildResult,
        objective: EanPassengerObjective,
        run: _DddTrajectoryRootCgRun,
        remaining_budget_seconds: float | None,
        pricing_tolerance: float,
    ) -> _DddTrajectoryRestrictedMasterRound:
        master_started = perf_counter()
        reference_master = build_ddd_trajectory_reference_master(
            trajectory_problem=trajectory_problem,
            artifact=artifact,
            passenger_build=passenger_build,
            objective=objective,
            reference_trajectories=tuple(run.trajectory_by_id.values()),
            max_incompatibility_pair_checks=self.max_incompatibility_pair_checks,
            resource_windows=run.resource_windows,
            instance_fingerprint=run.instance_fingerprint,
        )
        master_seconds = perf_counter() - master_started
        lp_seconds = 0.0
        separation_seconds = 0.0
        added_window_count = 0
        resource_windows = run.resource_windows
        for resource_round in range(self.max_resource_window_rounds + 1):
            lp = DddTrajectoryFactorizedLpOptimizer(
                output_flag=self.output_flag,
                dual_mode=self.master_dual_mode,
            ).solve(reference_master.master_problem)
            lp_seconds += lp.total_seconds
            if (
                lp.status is not DddTrajectoryPassengerLpStatus.OPTIMAL
                or lp.objective_value is None
                or lp.duals is None
            ):
                raise _DddTrajectoryRootCgAbort(
                    "trajectory restricted LP did not solve to optimality"
                )
            if self.conflict_row_mode is DddTrajectoryConflictRowMode.PAIR_ONLY:
                break
            separation_started = perf_counter()
            separation = separate_ddd_trajectory_resource_windows(
                movement_problem=problem.movement_problem,
                trajectory_by_option_id=(
                    reference_master.reference_trajectory_by_option_id
                ),
                option_values_by_id=lp.option_values_by_id,
                existing_windows=resource_windows,
                tolerance=self.pricing_tolerance,
            )
            separation_seconds += perf_counter() - separation_started
            if not separation.new_windows:
                break
            if resource_round >= self.max_resource_window_rounds:
                raise _DddTrajectoryRootCgAbort(
                    "trajectory resource-window round limit exhausted"
                )
            resource_windows = tuple(
                sorted({*resource_windows, *separation.new_windows})
            )
            added_window_count += len(separation.new_windows)
            row_build_started = perf_counter()
            rows = build_ddd_trajectory_resource_window_rows(
                windows=resource_windows,
                movement_problem=problem.movement_problem,
                trajectory_by_option_id=(
                    reference_master.reference_trajectory_by_option_id
                ),
            )
            master_seconds += perf_counter() - row_build_started
            reference_master = replace(
                reference_master,
                master_problem=replace(
                    reference_master.master_problem,
                    resource_window_rows=rows,
                ),
            )
        else:
            raise RuntimeError("unreachable resource-window separation loop")
        run_mip = (
            self.restricted_mip_interval == 1
            or (round_index - 1) % self.restricted_mip_interval == 0
            or run.upper_bound is None
        )
        mip_limit = self._clamped_time_limit(
            self.restricted_mip_time_limit_seconds,
            remaining_budget_seconds,
        )
        if mip_limit is not None and mip_limit <= 1e-6:
            run_mip = False
        mip = (
            self._solve_restricted_mip(
                reference_master.master_problem,
                run=run,
                time_limit_seconds=mip_limit,
            )
            if run_mip
            else DddTrajectoryPassengerMipResult(
                status=DddTrajectoryPassengerLpStatus.UNKNOWN,
                objective_value=None,
                option_values_by_id={},
                ride_values_by_id={},
                build_seconds=0.0,
                optimize_seconds=0.0,
                total_seconds=0.0,
                solver_status=None,
                solution_count=0,
                best_bound=None,
            )
        )
        return _DddTrajectoryRestrictedMasterRound(
            reference_master=reference_master,
            lp=lp,
            mip=mip,
            resource_windows=resource_windows,
            added_resource_window_count=added_window_count,
            master_seconds=master_seconds,
            lp_seconds=lp_seconds,
            resource_separation_seconds=separation_seconds,
        )

    def _solve_restricted_mip(
        self,
        master_problem: object,
        *,
        run: _DddTrajectoryRootCgRun,
        time_limit_seconds: float | None,
    ) -> DddTrajectoryPassengerMipResult:
        return DddTrajectoryFactorizedMipReferenceOptimizer(
            output_flag=self.output_flag,
            time_limit_seconds=time_limit_seconds,
            mip_focus=self.restricted_mip_focus,
            threads=self.pricing_threads,
        ).solve(
            master_problem,
            initial_option_values_by_id={
                option_id: 1.0 for option_id in run.incumbent_option_ids
            },
            initial_ride_values_by_id=run.incumbent_ride_values_by_id,
        )

    def _update_incumbent(
        self,
        *,
        problem: DddNetworkTimeProblem,
        trajectory_problem: DddTrajectoryProblem,
        artifact: EanBuildArtifact,
        master_round: _DddTrajectoryRestrictedMasterRound,
        run: _DddTrajectoryRootCgRun,
    ) -> float | None:
        restricted_upper = master_round.mip.objective_value
        if restricted_upper is None:
            return None
        selected = tuple(
            master_round.reference_master.reference_trajectory_by_option_id[option_id]
            for option_id, value in master_round.mip.option_values_by_id.items()
            if value >= 0.5
        )
        selected = tuple(sorted(selected, key=lambda item: item.cabin_id))
        candidate_fleet_plan: EanFleetPlan | None = None
        candidate_reservoir_plan: DddReservoirFleetPlan | None = None
        if isinstance(trajectory_problem.start_domain, DddFixedTrajectoryStartDomain):
            reference_solution = DddReferenceSolution(trajectories=selected)
            validate_ddd_reference_solution(
                problem.movement_problem,
                reference_solution,
                waiting_policy=trajectory_problem.waiting_policy,
            )
            movement_plan = DddReferenceToEanMovementPlanAdapter(
                waiting_policy=trajectory_problem.waiting_policy,
            ).build(
                problem=problem.movement_problem,
                solution=reference_solution,
                artifact=artifact,
            )
            validate_ean_movement_plan_against_artifact(
                artifact,
                movement_plan,
            ).raise_for_errors()
        elif isinstance(
            trajectory_problem.start_domain,
            DddOptimizedInitialPlacementDomain,
        ):
            movement_plan, candidate_fleet_plan = build_ean_oip_plan_and_fleet(
                problem=trajectory_problem,
                artifact=artifact,
                trajectories=selected,
            )
            validate_ean_movement_plan_against_artifact(
                artifact, movement_plan
            ).raise_for_errors()
            validate_ean_initial_boundary_against_artifact(
                artifact, movement_plan, candidate_fleet_plan
            ).raise_for_errors()
        else:
            _, candidate_reservoir_plan = validate_ddd_reservoir_plan_against_artifact(
                problem=trajectory_problem,
                artifact=artifact,
                trajectories=selected,
            )
        if (
            run.upper_bound is None
            or restricted_upper < run.upper_bound - self.pricing_tolerance
        ):
            run.upper_bound = restricted_upper
            run.fleet_plan = candidate_fleet_plan
            if isinstance(
                trajectory_problem.start_domain,
                DddReservoirTrajectoryStartDomain,
            ):
                assert candidate_reservoir_plan is not None
                run.reservoir_fleet_plan = candidate_reservoir_plan
            run.incumbent_option_ids = tuple(
                sorted(
                    option_id
                    for option_id, value in master_round.mip.option_values_by_id.items()
                    if value >= 0.5
                )
            )
            run.incumbent_ride_values_by_id = {
                ride_id: value
                for ride_id, value in master_round.mip.ride_values_by_id.items()
                if value > self.pricing_tolerance
            }
        return restricted_upper

    def _solve_pricing_round(
        self,
        *,
        round_index: int,
        problem: DddNetworkTimeProblem,
        trajectory_problem: DddTrajectoryProblem,
        artifact: EanBuildArtifact,
        passenger_build: EanPassengerCandidateBuildResult,
        objective: EanPassengerObjective,
        run: _DddTrajectoryRootCgRun,
        master_round: _DddTrajectoryRestrictedMasterRound,
        pricing_oracle: (
            DddTrajectoryExactNoWaitPricingOracle
            | DddTrajectoryExactOipNoWaitPricingOracle
            | DddTrajectoryExactReservoirNoWaitPricingOracle
        ),
        remaining_budget_seconds: float | None,
    ) -> _DddTrajectoryPricingRound:
        if master_round.lp.objective_value is None or master_round.lp.duals is None:
            raise RuntimeError("optimal restricted LP is missing objective or duals")
        pricing_started = perf_counter()
        pricing_results: list[DddTrajectoryExactPricingResult] = []
        candidate_results: list[DddTrajectoryExactPricingResult] = []
        candidate_option_ids: set[str] = set()
        extra_call_count = 0
        proof_exclusion_count = 0
        maximum_tier_seconds = 0.0
        retry_count = 0
        cabin_ids = master_round.reference_master.master_problem.cabin_ids
        shared_oip_results: dict[int, DddTrajectoryExactPricingResult] = {}
        shared_reservoir_results: dict[int, DddTrajectoryExactPricingResult] = {}
        fixed_start_results: dict[int, DddTrajectoryExactPricingResult] = {}
        reused_from_cabin_id: dict[int, int] = {}
        proof_solve_count = 0
        if isinstance(pricing_oracle, DddTrajectoryExactOipNoWaitPricingOracle):
            (
                shared_oip_results,
                reused_from_cabin_id,
                proof_solve_count,
            ) = self._solve_shared_oip_proof_pricing(
                trajectory_problem=trajectory_problem,
                artifact=artifact,
                passenger_build=passenger_build,
                objective=objective,
                cabin_ids=cabin_ids,
                duals=master_round.lp.duals,
                resource_window_rows=(
                    master_round.reference_master.master_problem.resource_window_rows
                ),
                pricing_oracle=pricing_oracle,
            )
        elif isinstance(
            pricing_oracle,
            DddTrajectoryExactReservoirNoWaitPricingOracle,
        ):
            (
                shared_reservoir_results,
                reused_from_cabin_id,
                proof_solve_count,
            ) = self._solve_shared_reservoir_proof_pricing(
                trajectory_problem=trajectory_problem,
                artifact=artifact,
                passenger_build=passenger_build,
                objective=objective,
                cabin_ids=cabin_ids,
                duals=master_round.lp.duals,
                pricing_oracle=pricing_oracle,
                instance_fingerprint=run.instance_fingerprint,
            )
        else:
            (
                fixed_start_results,
                maximum_tier_seconds,
                retry_count,
                proof_solve_count,
            ) = self._solve_fixed_start_proof_pricing_batch(
                movement_problem=problem.movement_problem,
                artifact=artifact,
                passenger_build=passenger_build,
                objective=objective,
                cabin_ids=cabin_ids,
                duals=master_round.lp.duals,
                resource_window_rows=(
                    master_round.reference_master.master_problem.resource_window_rows
                ),
                waiting_policy=trajectory_problem.waiting_policy,
                instance_fingerprint=run.instance_fingerprint,
                trajectory_by_id=run.trajectory_by_id,
                remaining_budget_seconds=remaining_budget_seconds,
            )
        for cabin_id in cabin_ids:
            bounded_waiting = (
                trajectory_problem.waiting_policy.domain
                is DddTrajectoryWaitingDomain.BOUNDED_WAIT
            )
            excluded_sequences = (
                set()
                if bounded_waiting
                else {
                    trajectory.support_signature
                    for trajectory in run.trajectory_by_id.values()
                    if trajectory.cabin_id == cabin_id
                }
            )
            excluded_timed_signatures = (
                {
                    trajectory.timed_support_signature
                    for trajectory in run.trajectory_by_id.values()
                    if trajectory.cabin_id == cabin_id
                }
                if bounded_waiting
                else set()
            )
            if isinstance(pricing_oracle, DddTrajectoryExactOipNoWaitPricingOracle):
                proof_result = shared_oip_results[cabin_id]
                proof_exclusion_count += 0
            elif isinstance(
                pricing_oracle,
                DddTrajectoryExactReservoirNoWaitPricingOracle,
            ):
                proof_result = shared_reservoir_results[cabin_id]
            else:
                proof_result = fixed_start_results[cabin_id]
                proof_exclusion_count += len(excluded_sequences) + len(
                    excluded_timed_signatures
                )
            pricing_results.append(proof_result)
            if (
                proof_result.minimum_reduced_cost < -self.pricing_tolerance
                and proof_result.reference_trajectory is not None
                and proof_result.option_id not in run.trajectory_by_id
                and proof_result.option_id not in candidate_option_ids
            ):
                candidate_results.append(proof_result)
                assert proof_result.option_id is not None
                candidate_option_ids.add(proof_result.option_id)
                excluded_sequences.add(
                    proof_result.reference_trajectory.support_signature
                )
            accepted_signatures = (
                [
                    _trajectory_diversity_signature(
                        proof_result.reference_trajectory,
                        mode=self.diversity_mode,
                        problem=problem.movement_problem,
                        resource_windows=run.resource_windows,
                    )
                ]
                if proof_result.reference_trajectory is not None
                else []
            )
            extra_started = perf_counter()
            while (
                isinstance(pricing_oracle, DddTrajectoryExactNoWaitPricingOracle)
                and proof_result.minimum_reduced_cost < -self.pricing_tolerance
                and proof_result.reference_trajectory is not None
                and len(accepted_signatures) < self.columns_per_cabin_per_round
                and perf_counter() - extra_started
                < self.extra_column_time_limit_seconds
            ):
                remaining = self.extra_column_time_limit_seconds - (
                    perf_counter() - extra_started
                )
                extra = DddTrajectoryExactNoWaitPricingOracle(
                    time_limit_seconds=max(remaining, 1e-6),
                    threads=self.pricing_threads,
                    output_flag=self.output_flag,
                    mip_focus=self.extra_pricing_mip_focus,
                    formulation=self.pricing_formulation,
                ).solve(
                    movement_problem=problem.movement_problem,
                    artifact=artifact,
                    passenger_build=passenger_build,
                    objective=objective,
                    cabin_id=cabin_id,
                    duals=master_round.lp.duals,
                    excluded_route_option_sequences=frozenset(excluded_sequences),
                    resource_window_rows=(
                        master_round.reference_master.master_problem.resource_window_rows
                    ),
                )
                extra_call_count += 1
                if (
                    extra.minimum_reduced_cost >= -self.pricing_tolerance
                    or extra.reference_trajectory is None
                ):
                    break
                excluded_sequences.add(extra.reference_trajectory.support_signature)
                signature = _trajectory_diversity_signature(
                    extra.reference_trajectory,
                    mode=self.diversity_mode,
                    problem=problem.movement_problem,
                    resource_windows=run.resource_windows,
                )
                if self.diversity_mode is DddTrajectoryDiversityMode.OFF or all(
                    _hamming_distance(signature, prior)
                    >= self.minimum_diversity_distance
                    for prior in accepted_signatures
                ):
                    candidate_results.append(extra)
                    assert extra.option_id is not None
                    candidate_option_ids.add(extra.option_id)
                    accepted_signatures.append(signature)
        primal_call_count = 0
        primal_seconds = 0.0
        primal_results: tuple[DddTrajectoryExactPricingResult, ...] = ()
        primal_candidate_option_ids: set[str] = set()
        primal_negative_candidate_count = 0
        if isinstance(pricing_oracle, DddTrajectoryExactOipNoWaitPricingOracle):
            primal_started = perf_counter()
            primal_results, primal_call_count = self._solve_oip_primal_sweep(
                round_index=round_index,
                trajectory_problem=trajectory_problem,
                artifact=artifact,
                passenger_build=passenger_build,
                objective=objective,
                cabin_ids=cabin_ids,
                duals=master_round.lp.duals,
                resource_window_rows=(
                    master_round.reference_master.master_problem.resource_window_rows
                ),
                proof_results=shared_oip_results,
            )
            primal_seconds = perf_counter() - primal_started
            extra_call_count += primal_call_count
            for primal_result in primal_results:
                if (
                    primal_result.minimum_reduced_cost < -self.pricing_tolerance
                    and primal_result.reference_trajectory is not None
                    and primal_result.option_id is not None
                    and primal_result.option_id not in run.trajectory_by_id
                    and primal_result.option_id not in candidate_option_ids
                ):
                    candidate_results.append(primal_result)
                    candidate_option_ids.add(primal_result.option_id)
                    primal_candidate_option_ids.add(primal_result.option_id)
                    primal_negative_candidate_count += 1
        elif isinstance(
            pricing_oracle,
            DddTrajectoryExactReservoirNoWaitPricingOracle,
        ):
            primal_started = perf_counter()
            primal_results, primal_call_count = self._solve_reservoir_primal_sweep(
                round_index=round_index,
                trajectory_problem=trajectory_problem,
                artifact=artifact,
                passenger_build=passenger_build,
                objective=objective,
                cabin_ids=cabin_ids,
                duals=master_round.lp.duals,
                instance_fingerprint=run.instance_fingerprint,
                proof_results=shared_reservoir_results,
            )
            primal_seconds = perf_counter() - primal_started
            extra_call_count += primal_call_count
            for primal_result in primal_results:
                if (
                    primal_result.reference_trajectory is not None
                    and primal_result.option_id is not None
                    and primal_result.option_id not in run.trajectory_by_id
                    and primal_result.option_id not in candidate_option_ids
                ):
                    # Restricted dispatch windows are a primal intensification
                    # domain, not part of the reduced-cost certificate.  A
                    # nonnegative column can combine much better than the
                    # time-identical shared proof incumbent.
                    candidate_results.append(primal_result)
                    candidate_option_ids.add(primal_result.option_id)
                    primal_candidate_option_ids.add(primal_result.option_id)
                    if (
                        primal_result.minimum_reduced_cost
                        < -self.pricing_tolerance
                    ):
                        primal_negative_candidate_count += 1
        pricing_result_tuple = tuple(pricing_results)
        diagnostics = tuple(
            DddTrajectoryRootCgPricingDiagnostic(
                cabin_id=result.cabin_id,
                status=result.status,
                incumbent_reduced_cost=result.minimum_reduced_cost,
                certified_reduced_cost_lower_bound=(
                    result.certified_reduced_cost_lower_bound
                ),
                absolute_pricing_gap=(
                    result.minimum_reduced_cost
                    - result.certified_reduced_cost_lower_bound
                    if result.certified_reduced_cost_lower_bound is not None
                    else None
                ),
                exact=result.exact,
                option_is_existing=(
                    result.option_id is not None
                    and result.option_id in run.trajectory_by_id
                ),
                model_variable_count=result.model_variable_count,
                model_linear_constraint_count=result.model_linear_constraint_count,
                model_general_constraint_count=result.model_general_constraint_count,
                solver_node_count=result.solver_node_count,
                solve_seconds=result.solve_seconds,
                reused_from_cabin_id=reused_from_cabin_id.get(result.cabin_id),
                priced_start_class_count=result.priced_start_class_count,
                required_start_class_count=result.required_start_class_count,
                bounded_start_class_count=result.bounded_start_class_count,
                relative_node_count=result.relative_node_count,
                relative_arc_count=result.relative_arc_count,
                origin_product_count=result.origin_product_count,
                model_build_seconds=result.model_build_seconds,
            )
            for result in pricing_result_tuple
        )
        certified_bounds = tuple(
            result.certified_reduced_cost_lower_bound
            for result in pricing_result_tuple
            if result.certified_reduced_cost_lower_bound is not None
        )
        all_bounds_available = len(certified_bounds) == len(pricing_result_tuple)
        bound_correction = (
            sum(min(0.0, value) for value in certified_bounds)
            if all_bounds_available
            else None
        )
        reduced_costs = tuple(
            DddTrajectoryReducedCost(
                cabin_id=result.cabin_id,
                minimum_reduced_cost=result.minimum_reduced_cost,
                exact=result.exact,
                certified_lower_bound=result.certified_reduced_cost_lower_bound,
            )
            for result in pricing_result_tuple
        )
        certificate = DddTrajectoryPricingCertificate(
            restricted_master_lp_value=master_round.lp.objective_value,
            expected_cabin_ids=master_round.reference_master.master_problem.cabin_ids,
            reduced_costs=reduced_costs,
            instance_fingerprint=run.instance_fingerprint,
            objective_fingerprint=sha256(objective.value.encode()).hexdigest(),
            master_fingerprint=master_round.lp.master_fingerprint,
            dual_fingerprint=master_round.lp.duals.fingerprint,
            row_pool_fingerprint=_row_fingerprint(
                master_round.reference_master.master_problem.incompatibility_pairs,
                master_round.reference_master.master_problem.resource_window_rows,
            ),
            pricing_waiting_domain=trajectory_problem.waiting_policy.domain,
            target_waiting_domain=trajectory_problem.waiting_policy.domain,
            row_separation_complete=True,
            tolerance=self.pricing_tolerance,
        )
        return _DddTrajectoryPricingRound(
            results=pricing_result_tuple,
            candidate_results=tuple(candidate_results),
            diagnostics=diagnostics,
            certificate=certificate,
            bound_correction=bound_correction,
            minimum_certified_reduced_cost_bound=(
                min(certified_bounds) if certified_bounds else None
            ),
            proof_exclusion_count=proof_exclusion_count,
            extra_call_count=extra_call_count,
            seconds=perf_counter() - pricing_started,
            proof_solve_count=proof_solve_count or len(pricing_result_tuple),
            proof_reused_cabin_count=len(reused_from_cabin_id),
            primal_call_count=primal_call_count,
            primal_seconds=primal_seconds,
            primal_candidate_option_ids=frozenset(primal_candidate_option_ids),
            primal_negative_candidate_count=primal_negative_candidate_count,
            primal_status_counts=tuple(
                sorted(
                    (
                        status.value,
                        sum(result.status is status for result in primal_results),
                    )
                    for status in DddTrajectoryExactPricingStatus
                    if any(result.status is status for result in primal_results)
                )
            ),
            primal_details=tuple(
                result.detail for result in primal_results if result.detail
            ),
            maximum_tier_seconds=maximum_tier_seconds,
            retry_count=retry_count,
            unresolved_count=sum(
                not result.exact
                and (
                    result.certified_reduced_cost_lower_bound is None
                    or result.certified_reduced_cost_lower_bound
                    < -self.pricing_tolerance
                )
                and not (
                    result.minimum_reduced_cost < -self.pricing_tolerance
                    and result.reference_trajectory is not None
                )
                for result in pricing_result_tuple
            ),
        )

    def _solve_fixed_start_proof_pricing_batch(
        self,
        *,
        movement_problem: DddMovementProblem,
        artifact: EanBuildArtifact,
        passenger_build: EanPassengerCandidateBuildResult,
        objective: EanPassengerObjective,
        cabin_ids: tuple[int, ...],
        duals: DddTrajectoryPassengerDuals,
        resource_window_rows: tuple[DddTrajectoryResourceWindowRow, ...],
        waiting_policy: DddTrajectoryWaitingPolicy,
        instance_fingerprint: str,
        trajectory_by_id: dict[str, DddReferenceTrajectory],
        remaining_budget_seconds: float | None,
    ) -> tuple[dict[int, DddTrajectoryExactPricingResult], float, int, int]:
        """Price all cabins breadth-first over deterministic time tiers."""

        tiers = (
            self.pricing_time_limit_tiers_seconds
            or (self.pricing_time_limit_seconds,)
        )
        started = perf_counter()
        results: dict[int, DddTrajectoryExactPricingResult] = {}
        unresolved = set(cabin_ids)
        retry_count = 0
        solve_count = 0
        maximum_tier_seconds = 0.0
        bounded_waiting = (
            waiting_policy.domain is DddTrajectoryWaitingDomain.BOUNDED_WAIT
        )
        excluded_sequences_by_cabin = {
            cabin_id: frozenset(
                trajectory.support_signature
                for trajectory in trajectory_by_id.values()
                if trajectory.cabin_id == cabin_id
            )
            if not bounded_waiting
            else frozenset()
            for cabin_id in cabin_ids
        }
        excluded_timed_by_cabin = {
            cabin_id: frozenset(
                trajectory.timed_support_signature
                for trajectory in trajectory_by_id.values()
                if trajectory.cabin_id == cabin_id
            )
            if bounded_waiting
            else frozenset()
            for cabin_id in cabin_ids
        }
        for tier_index, configured_tier in enumerate(tiers):
            if not unresolved:
                break
            for cabin_id in tuple(sorted(unresolved)):
                remaining = (
                    None
                    if remaining_budget_seconds is None
                    else remaining_budget_seconds - (perf_counter() - started)
                )
                time_limit = self._clamped_time_limit(configured_tier, remaining)
                if time_limit is None or time_limit <= 1e-6:
                    if cabin_id not in results:
                        raise _DddTotalBudgetExhausted(
                            "no total budget remained for required proof pricing"
                        )
                    return (
                        results,
                        maximum_tier_seconds,
                        retry_count,
                        solve_count,
                    )
                maximum_tier_seconds = max(maximum_tier_seconds, time_limit)
                result = DddTrajectoryExactNoWaitPricingOracle(
                    time_limit_seconds=time_limit,
                    threads=self.pricing_threads,
                    output_flag=self.output_flag,
                    mip_focus=self.proof_pricing_mip_focus,
                    formulation=self.pricing_formulation,
                ).solve(
                    movement_problem=movement_problem,
                    artifact=artifact,
                    passenger_build=passenger_build,
                    objective=objective,
                    cabin_id=cabin_id,
                    duals=duals,
                    excluded_route_option_sequences=(
                        excluded_sequences_by_cabin[cabin_id]
                    ),
                    excluded_timed_support_signatures=(
                        excluded_timed_by_cabin[cabin_id]
                    ),
                    resource_window_rows=resource_window_rows,
                    waiting_policy=waiting_policy,
                    instance_fingerprint=instance_fingerprint,
                )
                solve_count += 1
                if cabin_id in results:
                    retry_count += 1
                results[cabin_id] = result
                certified_nonnegative = (
                    result.certified_reduced_cost_lower_bound is not None
                    and result.certified_reduced_cost_lower_bound
                    >= -self.pricing_tolerance
                )
                found_negative = (
                    result.minimum_reduced_cost < -self.pricing_tolerance
                    and result.reference_trajectory is not None
                )
                if result.exact or certified_nonnegative or found_negative:
                    unresolved.remove(cabin_id)
            if tier_index == len(tiers) - 1:
                break
        if set(results) != set(cabin_ids):
            raise _DddTotalBudgetExhausted(
                "no total budget remained for required proof pricing"
            )
        return results, maximum_tier_seconds, retry_count, solve_count

    def _solve_shared_reservoir_proof_pricing(
        self,
        *,
        trajectory_problem: DddTrajectoryProblem,
        artifact: EanBuildArtifact,
        passenger_build: EanPassengerCandidateBuildResult,
        objective: EanPassengerObjective,
        cabin_ids: tuple[int, ...],
        duals: DddTrajectoryPassengerDuals,
        pricing_oracle: DddTrajectoryExactReservoirNoWaitPricingOracle,
        instance_fingerprint: str,
    ) -> tuple[
        dict[int, DddTrajectoryExactPricingResult],
        dict[int, int],
        int,
    ]:
        groups: dict[tuple[tuple[str, int, int], ...], list[int]] = {}
        for cabin_id in cabin_ids:
            groups.setdefault(
                _oip_pricing_equivalence_key(
                    cabin_id=cabin_id,
                    passenger_build=passenger_build,
                ),
                [],
            ).append(cabin_id)
        results: dict[int, DddTrajectoryExactPricingResult] = {}
        reused_from: dict[int, int] = {}
        for grouped_cabin_ids in groups.values():
            representative_id = grouped_cabin_ids[0]
            representative = pricing_oracle.solve(
                trajectory_problem=trajectory_problem,
                artifact=artifact,
                passenger_build=passenger_build,
                objective=objective,
                cabin_id=representative_id,
                duals=duals,
                instance_fingerprint=instance_fingerprint,
            )
            results[representative_id] = representative
            for cabin_id in grouped_cabin_ids[1:]:
                results[cabin_id] = _remap_shared_reservoir_pricing_result(
                    result=representative,
                    source_cabin_id=representative_id,
                    target_cabin_id=cabin_id,
                    trajectory_problem=trajectory_problem,
                    passenger_build=passenger_build,
                    duals=duals,
                    instance_fingerprint=instance_fingerprint,
                )
                reused_from[cabin_id] = representative_id
        return results, reused_from, len(groups)

    def _solve_reservoir_primal_sweep(
        self,
        *,
        round_index: int,
        trajectory_problem: DddTrajectoryProblem,
        artifact: EanBuildArtifact,
        passenger_build: EanPassengerCandidateBuildResult,
        objective: EanPassengerObjective,
        cabin_ids: tuple[int, ...],
        duals: DddTrajectoryPassengerDuals,
        instance_fingerprint: str,
        proof_results: dict[int, DddTrajectoryExactPricingResult],
    ) -> tuple[tuple[DddTrajectoryExactPricingResult, ...], int]:
        if self.reservoir_primal_pricing_time_limit_seconds <= 0:
            return (), 0
        domain = trajectory_problem.start_domain
        if not isinstance(domain, DddReservoirTrajectoryStartDomain):
            raise ValueError("reservoir primal sweep requires a reservoir domain")
        eligible_cabin_ids = tuple(
            cabin_id
            for cabin_id in cabin_ids
            if proof_results[cabin_id].certified_reduced_cost_lower_bound
            is not None
            and proof_results[cabin_id].certified_reduced_cost_lower_bound
            < -self.pricing_tolerance
        )
        if not eligible_cabin_ids:
            return (), 0
        maximum_calls = min(
            len(eligible_cabin_ids),
            self.reservoir_primal_maximum_cabin_calls_per_round,
        )
        position_by_cabin_id = {
            cabin_id: position for position, cabin_id in enumerate(cabin_ids)
        }
        middle_position = 0.5 * (len(cabin_ids) - 1)
        # The proof oracle is shared because interchangeable cabins have the
        # same reduced-cost problem.  The primal sweep deliberately starts at
        # the centre of the canonical dispatch train and expands outwards:
        # those windows stay closest to the feasible proof incumbent instead
        # of spending the first rounds on the two extreme warm-up boundaries.
        ordered_eligible_cabin_ids = tuple(
            sorted(
                eligible_cabin_ids,
                key=lambda cabin_id: (
                    abs(position_by_cabin_id[cabin_id] - middle_position),
                    position_by_cabin_id[cabin_id],
                ),
            )
        )
        offset = ((round_index - 1) * maximum_calls) % len(eligible_cabin_ids)
        selected_cabin_ids = tuple(
            ordered_eligible_cabin_ids[
                (offset + index) % len(ordered_eligible_cabin_ids)
            ]
            for index in range(maximum_calls)
        )
        results = []
        if (
            self.reservoir_primal_pricing_mode
            is DddReservoirPrimalPricingMode.COMPACT_DISPATCH_WINDOWS
        ):
            oracle = DddTrajectoryExactReservoirNoWaitPricingOracle(
                time_limit_seconds=self.reservoir_primal_pricing_time_limit_seconds,
                threads=self.pricing_threads,
                output_flag=self.output_flag,
                mip_focus=self.extra_pricing_mip_focus,
            )
            terminal_epsilon = max(
                self.pricing_tolerance,
                DDD_RESERVOIR_TIME_TOLERANCE_SECONDS,
            )
            proof_dispatch_times = tuple(
                state.dispatch_time_seconds
                for result in proof_results.values()
                if result.reference_trajectory is not None
                and (state := result.reference_trajectory.reservoir_state) is not None
                and state.kind is DddReservoirTrajectoryKind.DISPATCHED
                and state.dispatch_time_seconds is not None
            )
            center = (
                sum(proof_dispatch_times) / len(proof_dispatch_times)
                if proof_dispatch_times
                else -0.5 * domain.warmup_seconds
            )
            dispatch_spacing = _reservoir_primal_dispatch_spacing_seconds(
                trajectory_problem
            )
            total_span = dispatch_spacing * max(0, len(cabin_ids) - 1)
            first_target = center - 0.5 * total_span
            if first_target < -domain.warmup_seconds:
                first_target = -domain.warmup_seconds
            if first_target + total_span >= -terminal_epsilon:
                first_target = -terminal_epsilon - total_span
            half_window = min(
                0.25 * dispatch_spacing,
                max(terminal_epsilon, 0.02 * domain.warmup_seconds),
            )
            for cabin_id in selected_cabin_ids:
                position = position_by_cabin_id[cabin_id]
                target = first_target + position * dispatch_spacing
                lower = max(-domain.warmup_seconds, target - half_window)
                upper = min(
                    -terminal_epsilon,
                    target + half_window,
                )
                if upper - lower <= terminal_epsilon:
                    continue
                results.append(
                    oracle.solve(
                        trajectory_problem=trajectory_problem,
                        artifact=artifact,
                        passenger_build=passenger_build,
                        objective=objective,
                        cabin_id=cabin_id,
                        duals=duals,
                        instance_fingerprint=instance_fingerprint,
                        dispatch_time_bounds_seconds=(lower, upper),
                        certify_complete_domain=False,
                        dispatch_only=True,
                    )
                )
        elif (
            self.reservoir_primal_pricing_mode
            is DddReservoirPrimalPricingMode.TIME_EXPANDED_ANCHORS
        ):
            anchors = build_ddd_reservoir_dispatch_anchors(
                domain,
                anchor_count=self.reservoir_dispatch_anchor_count,
            )
            if not anchors:
                return (), 0
            oracle = DddTrajectoryReservoirAnchorPricingOracle(
                time_limit_seconds=self.reservoir_primal_pricing_time_limit_seconds,
                threads=self.pricing_threads,
                output_flag=self.output_flag,
                mip_focus=self.extra_pricing_mip_focus,
                maximum_time_expanded_arc_count=(
                    self.reservoir_primal_maximum_arc_count
                ),
                maximum_passenger_arc_product=(
                    self.reservoir_primal_maximum_passenger_arc_product
                ),
            )
            for cabin_id in selected_cabin_ids:
                position = position_by_cabin_id[cabin_id]
                anchor = anchors[(position + round_index - 1) % len(anchors)]
                results.append(oracle.solve(
                    trajectory_problem=trajectory_problem,
                    artifact=artifact,
                    passenger_build=passenger_build,
                    objective=objective,
                    cabin_id=cabin_id,
                    dispatch_time_seconds=anchor,
                    duals=duals,
                    instance_fingerprint=instance_fingerprint,
                ))
        else:
            raise RuntimeError("unsupported reservoir primal pricing mode")
        return tuple(results), len(results)

    def _solve_shared_oip_proof_pricing(
        self,
        *,
        trajectory_problem: DddTrajectoryProblem,
        artifact: EanBuildArtifact,
        passenger_build: EanPassengerCandidateBuildResult,
        objective: EanPassengerObjective,
        cabin_ids: tuple[int, ...],
        duals: DddTrajectoryPassengerDuals,
        resource_window_rows: tuple[DddTrajectoryResourceWindowRow, ...],
        pricing_oracle: DddTrajectoryExactOipNoWaitPricingOracle,
    ) -> tuple[
        dict[int, DddTrajectoryExactPricingResult],
        dict[int, int],
        int,
    ]:
        groups: dict[tuple[tuple[str, int, int], ...], list[int]] = {}
        for cabin_id in cabin_ids:
            groups.setdefault(
                _oip_pricing_equivalence_key(
                    cabin_id=cabin_id,
                    passenger_build=passenger_build,
                ),
                [],
            ).append(cabin_id)
        results: dict[int, DddTrajectoryExactPricingResult] = {}
        reused_from: dict[int, int] = {}
        for grouped_cabin_ids in groups.values():
            representative_id = grouped_cabin_ids[0]
            representative = pricing_oracle.solve(
                trajectory_problem=trajectory_problem,
                artifact=artifact,
                passenger_build=passenger_build,
                objective=objective,
                cabin_id=representative_id,
                duals=duals,
                resource_window_rows=resource_window_rows,
            )
            results[representative_id] = representative
            for cabin_id in grouped_cabin_ids[1:]:
                results[cabin_id] = _remap_shared_oip_pricing_result(
                    result=representative,
                    source_cabin_id=representative_id,
                    target_cabin_id=cabin_id,
                    trajectory_problem=trajectory_problem,
                    artifact=artifact,
                    passenger_build=passenger_build,
                    duals=duals,
                )
                reused_from[cabin_id] = representative_id
        return results, reused_from, len(groups)

    def _solve_oip_primal_sweep(
        self,
        *,
        round_index: int,
        trajectory_problem: DddTrajectoryProblem,
        artifact: EanBuildArtifact,
        passenger_build: EanPassengerCandidateBuildResult,
        objective: EanPassengerObjective,
        cabin_ids: tuple[int, ...],
        duals: DddTrajectoryPassengerDuals,
        resource_window_rows: tuple[DddTrajectoryResourceWindowRow, ...],
        proof_results: dict[int, DddTrajectoryExactPricingResult],
    ) -> tuple[tuple[DddTrajectoryExactPricingResult, ...], int]:
        fallback_assignments: dict[
            tuple[tuple[tuple[str, int, int], ...], int], list[int]
        ] = {}
        position_by_group: dict[tuple[tuple[str, int, int], ...], int] = {}
        results: list[DddTrajectoryExactPricingResult] = []
        for cabin_id in cabin_ids:
            key = _oip_pricing_equivalence_key(
                cabin_id=cabin_id,
                passenger_build=passenger_build,
            )
            position = position_by_group.get(key, 0)
            position_by_group[key] = position + 1
            required = proof_results[cabin_id].required_start_class_count
            if required <= 0:
                continue
            proof_result = proof_results[cabin_id]
            available_candidates = tuple(
                candidate
                for candidate in proof_result.start_class_candidates
                if candidate.reduced_cost < -self.pricing_tolerance
                and candidate.option_id != proof_result.option_id
            )
            if available_candidates:
                candidate = available_candidates[
                    (position + round_index - 1) % len(available_candidates)
                ]
                results.append(
                    _pricing_result_from_start_class_candidate(
                        proof_result=proof_result,
                        candidate=candidate,
                    )
                )
                continue
            if self.oip_primal_pricing_time_limit_seconds > 0:
                start_class_index = (position + round_index - 1) % required
                fallback_assignments.setdefault((key, start_class_index), []).append(
                    cabin_id
                )
        if not fallback_assignments:
            return tuple(sorted(results, key=lambda item: item.cabin_id)), 0
        oracle = DddTrajectoryExactOipNoWaitPricingOracle(
            time_limit_seconds=self.oip_primal_pricing_time_limit_seconds,
            threads=self.pricing_threads,
            output_flag=self.output_flag,
            mip_focus=self.extra_pricing_mip_focus,
            formulation=self.pricing_formulation,
        )
        fallback_call_count = 0
        for (_, start_class_index), grouped_cabin_ids in fallback_assignments.items():
            representative_id = grouped_cabin_ids[0]
            representative = oracle.solve(
                trajectory_problem=trajectory_problem,
                artifact=artifact,
                passenger_build=passenger_build,
                objective=objective,
                cabin_id=representative_id,
                duals=duals,
                resource_window_rows=resource_window_rows,
                start_class_indices=(start_class_index,),
                certify_complete_domain=False,
            )
            fallback_call_count += 1
            results.append(representative)
            results.extend(
                _remap_shared_oip_pricing_result(
                    result=representative,
                    source_cabin_id=representative_id,
                    target_cabin_id=cabin_id,
                    trajectory_problem=trajectory_problem,
                    artifact=artifact,
                    passenger_build=passenger_build,
                    duals=duals,
                )
                for cabin_id in grouped_cabin_ids[1:]
            )
        return tuple(
            sorted(results, key=lambda item: item.cabin_id)
        ), fallback_call_count

    def _add_priced_columns(
        self,
        *,
        run: _DddTrajectoryRootCgRun,
        pricing_round: _DddTrajectoryPricingRound,
    ) -> tuple[int, int]:
        added = 0
        diverse_added = 0
        proof_result_ids = {id(item) for item in pricing_round.results}
        for pricing_result in pricing_round.candidate_results:
            if (
                pricing_result.reference_trajectory is None
                or pricing_result.option_id is None
            ):
                continue
            if (
                pricing_result.minimum_reduced_cost >= -self.pricing_tolerance
                and (
                    self.certified_fixed_k_mode
                    or pricing_result.option_id
                    not in pricing_round.primal_candidate_option_ids
                )
            ):
                continue
            if pricing_result.option_id in run.trajectory_by_id:
                raise RuntimeError("exact pricing returned an excluded trajectory")
            run.trajectory_by_id[pricing_result.option_id] = (
                pricing_result.reference_trajectory
            )
            added += 1
            if id(pricing_result) not in proof_result_ids:
                diverse_added += 1
        return added, diverse_added

    def _build_iteration(
        self,
        *,
        round_index: int,
        round_started: float,
        run: _DddTrajectoryRootCgRun,
        master_round: _DddTrajectoryRestrictedMasterRound,
        pricing_round: _DddTrajectoryPricingRound,
        restricted_upper: float | None,
        added: int,
        diverse_added: int,
        remaining_budget_seconds: float | None,
    ) -> DddTrajectoryRootCgIteration:
        minimum_reduced_cost = (
            min(item.minimum_reduced_cost for item in pricing_round.results)
            if pricing_round.results
            else None
        )
        master_problem = master_round.reference_master.master_problem
        master_trajectories = tuple(
            master_round.reference_master.reference_trajectory_by_option_id.values()
        )
        return DddTrajectoryRootCgIteration(
            round_index=round_index,
            trajectory_count=len(master_problem.options),
            incompatibility_pair_count=len(master_problem.incompatibility_pairs),
            resource_window_count=len(master_problem.resource_window_rows),
            added_resource_window_count=master_round.added_resource_window_count,
            restricted_lp_value=master_round.lp.objective_value,
            pricing_corrected_lower_bound=(
                pricing_round.certificate.certified_lower_bound
            ),
            pricing_bound_correction=pricing_round.bound_correction,
            minimum_certified_reduced_cost_bound=(
                pricing_round.minimum_certified_reduced_cost_bound
            ),
            proof_pricing_exclusion_count=pricing_round.proof_exclusion_count,
            global_lower_bound=run.lower_bound,
            restricted_integer_upper_bound=restricted_upper,
            global_upper_bound=run.upper_bound,
            minimum_reduced_cost=minimum_reduced_cost,
            exact_pricing_cabin_count=sum(item.exact for item in pricing_round.results),
            added_trajectory_count=added,
            diverse_added_trajectory_count=diverse_added,
            extra_pricing_call_count=pricing_round.extra_call_count,
            master_build_seconds=master_round.master_seconds,
            lp_seconds=master_round.lp_seconds,
            mip_seconds=master_round.mip.total_seconds,
            pricing_seconds=pricing_round.seconds,
            resource_separation_seconds=master_round.resource_separation_seconds,
            total_seconds=perf_counter() - round_started,
            pricing_diagnostics=pricing_round.diagnostics,
            station_start_column_count=sum(
                trajectory.initial_state is not None
                and trajectory.initial_state.kind.value != "rope"
                for trajectory in master_trajectories
            ),
            rope_start_column_count=sum(
                trajectory.initial_state is not None
                and trajectory.initial_state.kind.value == "rope"
                for trajectory in master_trajectories
            ),
            boundary_incompatibility_pair_count=(
                master_round.reference_master.boundary_incompatibility_pair_count
            ),
            proof_pricing_solve_count=pricing_round.proof_solve_count,
            proof_pricing_reused_cabin_count=(pricing_round.proof_reused_cabin_count),
            priced_start_class_count=sum(
                item.priced_start_class_count for item in pricing_round.results
            ),
            required_start_class_count=sum(
                item.required_start_class_count for item in pricing_round.results
            ),
            bounded_start_class_count=sum(
                item.bounded_start_class_count for item in pricing_round.results
            ),
            primal_pricing_call_count=pricing_round.primal_call_count,
            primal_pricing_seconds=pricing_round.primal_seconds,
            primal_pricing_candidate_count=len(
                pricing_round.primal_candidate_option_ids
            ),
            primal_pricing_negative_candidate_count=(
                pricing_round.primal_negative_candidate_count
            ),
            primal_pricing_status_counts=pricing_round.primal_status_counts,
            primal_pricing_details=pricing_round.primal_details,
            relative_node_count=sum(
                item.relative_node_count for item in pricing_round.results
            ),
            relative_arc_count=sum(
                item.relative_arc_count for item in pricing_round.results
            ),
            origin_product_count=sum(
                item.origin_product_count for item in pricing_round.results
            ),
            pricing_model_build_seconds=sum(
                item.model_build_seconds for item in pricing_round.results
            ),
            stored_column_count=sum(
                trajectory.reservoir_state is not None
                and trajectory.reservoir_state.kind
                is DddReservoirTrajectoryKind.STORED
                for trajectory in master_trajectories
            ),
            dispatched_column_count=sum(
                trajectory.reservoir_state is not None
                and trajectory.reservoir_state.kind
                is DddReservoirTrajectoryKind.DISPATCHED
                for trajectory in master_trajectories
            ),
            incumbent_dispatched_fleet_count=(
                None
                if run.reservoir_fleet_plan is None
                else run.reservoir_fleet_plan.dispatched_fleet_count
            ),
            waiting_column_count=sum(
                any(visit.wait_seconds > 1e-9 for visit in trajectory.visits)
                for trajectory in master_trajectories
            ),
            positive_wait_visit_count=sum(
                visit.wait_seconds > 1e-9
                for trajectory in master_trajectories
                for visit in trajectory.visits
            ),
            maximum_column_wait_seconds=max(
                (
                    visit.wait_seconds
                    for trajectory in master_trajectories
                    for visit in trajectory.visits
                ),
                default=0.0,
            ),
            pricing_tier_seconds=pricing_round.maximum_tier_seconds,
            pricing_retry_count=pricing_round.retry_count,
            unresolved_pricing_count=pricing_round.unresolved_count,
            nonexact_certified_nonnegative_pricing_count=sum(
                not result.exact
                and result.certified_reduced_cost_lower_bound is not None
                and result.certified_reduced_cost_lower_bound
                >= -self.pricing_tolerance
                for result in pricing_round.results
            ),
            remaining_budget_seconds=remaining_budget_seconds,
            restricted_mip_ran=master_round.mip.solver_status is not None,
            restricted_mip_solution_count=master_round.mip.solution_count,
            restricted_mip_solver_status=master_round.mip.solver_status,
        )

    def _checkpoint_state(
        self,
        *,
        run: _DddTrajectoryRootCgRun,
        objective: EanPassengerObjective,
        round_index: int,
        root_lp_certified: bool,
        started: float,
    ) -> DddTrajectoryRootCgState:
        return DddTrajectoryRootCgState(
            instance_fingerprint=run.instance_fingerprint,
            objective=objective,
            conflict_row_mode=self.conflict_row_mode,
            completed_rounds=round_index,
            certified_lower_bound=run.lower_bound,
            best_upper_bound=run.upper_bound,
            root_lp_certified=root_lp_certified,
            incumbent_option_ids=run.incumbent_option_ids,
            incumbent_ride_values_by_id=dict(run.incumbent_ride_values_by_id),
            iterations=tuple(run.iterations),
            trajectories=tuple(
                run.trajectory_by_id[key] for key in sorted(run.trajectory_by_id)
            ),
            resource_windows=run.resource_windows,
            total_seconds=run.elapsed_offset_seconds + perf_counter() - started,
            fleet_mode=run.trajectory_problem.fleet_mode,
            reservoir_start_domain=(
                run.trajectory_problem.start_domain
                if isinstance(
                    run.trajectory_problem.start_domain,
                    DddReservoirTrajectoryStartDomain,
                )
                else None
            ),
            waiting_policy=run.trajectory_problem.waiting_policy,
        )

    def _run_result(
        self,
        *,
        status: DddTrajectoryRootCgStatus,
        run: _DddTrajectoryRootCgRun,
        started: float,
        detail: str | None,
        root_lp_certified: bool = False,
        certificate_valid: bool = True,
    ) -> DddTrajectoryRootCgResult:
        return self._result(
            status=status,
            lower_bound=run.lower_bound,
            upper_bound=run.upper_bound,
            iterations=run.iterations,
            trajectory_by_id=run.trajectory_by_id,
            started=started,
            elapsed_offset_seconds=run.elapsed_offset_seconds,
            incumbent_option_ids=run.incumbent_option_ids,
            incumbent_ride_values_by_id=run.incumbent_ride_values_by_id,
            detail=detail,
            root_lp_certified=root_lp_certified,
            fleet_mode=run.trajectory_problem.fleet_mode,
            fleet_plan=run.fleet_plan,
            reservoir_fleet_plan=run.reservoir_fleet_plan,
            seed_kind=run.seed_kind,
            certificate_valid=certificate_valid,
            objective_floor=self.objective_floor,
        )

    def _remaining_budget_seconds(
        self,
        *,
        run: _DddTrajectoryRootCgRun,
        started: float,
    ) -> float | None:
        if self.total_time_limit_seconds is None:
            return None
        return max(
            0.0,
            self.total_time_limit_seconds
            - run.elapsed_offset_seconds
            - (perf_counter() - started),
        )

    @staticmethod
    def _clamped_time_limit(
        configured_seconds: float | None,
        remaining_seconds: float | None,
    ) -> float | None:
        if configured_seconds is None:
            return remaining_seconds
        if configured_seconds <= 0:
            return None
        return (
            configured_seconds
            if remaining_seconds is None
            else min(configured_seconds, max(0.0, remaining_seconds))
        )

    def _bound_tolerance(self, value: float) -> float:
        return max(self.pricing_tolerance, 1e-9 * max(1.0, abs(value)))

    def _validate_bound_invariants(
        self,
        *,
        run: _DddTrajectoryRootCgRun,
        restricted_lp_value: float,
        stage: str,
    ) -> None:
        tolerance = self._bound_tolerance(restricted_lp_value)
        if run.lower_bound > restricted_lp_value + tolerance:
            raise _DddCertificateInvariantError(
                f"{stage}: certified LB {run.lower_bound} exceeds restricted LP "
                f"{restricted_lp_value}"
            )
        if run.upper_bound is not None and (
            run.lower_bound > run.upper_bound + self._bound_tolerance(run.upper_bound)
        ):
            raise _DddCertificateInvariantError(
                f"{stage}: certified LB {run.lower_bound} exceeds validated UB "
                f"{run.upper_bound}"
            )
        if run.iterations:
            previous = run.iterations[-1]
            if run.lower_bound + tolerance < previous.global_lower_bound:
                raise _DddCertificateInvariantError(
                    f"{stage}: certified lower bound decreased"
                )
            if (
                run.upper_bound is not None
                and previous.global_upper_bound is not None
                and run.upper_bound
                > previous.global_upper_bound
                + self._bound_tolerance(previous.global_upper_bound)
            ):
                raise _DddCertificateInvariantError(
                    f"{stage}: validated upper bound increased"
                )

    def _root_completion_status(
        self, run: _DddTrajectoryRootCgRun
    ) -> DddTrajectoryRootCgStatus:
        if not self.certified_fixed_k_mode:
            return DddTrajectoryRootCgStatus.OPTIMAL_ROOT_LP
        if (
            run.upper_bound is not None
            and run.upper_bound - run.lower_bound
            <= self._bound_tolerance(run.upper_bound)
        ):
            return DddTrajectoryRootCgStatus.INTEGER_OPTIMAL
        return DddTrajectoryRootCgStatus.ROOT_LP_CERTIFIED_WITH_INTEGER_GAP

    def _validate_resume_state(
        self,
        state: DddTrajectoryRootCgState,
        *,
        instance_fingerprint: str,
        objective: EanPassengerObjective,
        fleet_mode: DddTrajectoryFleetMode,
        reservoir_start_domain: DddReservoirTrajectoryStartDomain | None,
        waiting_policy: DddTrajectoryWaitingPolicy,
    ) -> None:
        if state.instance_fingerprint != instance_fingerprint:
            raise ValueError("trajectory checkpoint belongs to a different instance")
        if state.objective is not objective:
            raise ValueError("trajectory checkpoint uses a different objective")
        if state.fleet_mode is not fleet_mode:
            raise ValueError("trajectory checkpoint uses a different fleet mode")
        if state.reservoir_start_domain != reservoir_start_domain:
            raise ValueError("trajectory checkpoint uses a different reservoir domain")
        if state.waiting_policy != waiting_policy:
            raise ValueError("trajectory checkpoint uses a different waiting policy")
        if state.conflict_row_mode is not self.conflict_row_mode:
            raise ValueError("trajectory checkpoint uses a different conflict-row mode")
        if state.completed_rounds != len(state.iterations):
            raise ValueError("trajectory checkpoint round history is inconsistent")
        if tuple(item.round_index for item in state.iterations) != tuple(
            range(1, state.completed_rounds + 1)
        ):
            raise ValueError("trajectory checkpoint round indices are inconsistent")
        if state.completed_rounds < 0 or state.completed_rounds > self.max_iterations:
            raise ValueError("trajectory checkpoint exceeds the requested round limit")
        previous_lower = self.objective_floor
        previous_upper: float | None = None
        for iteration in state.iterations:
            tolerance = self._bound_tolerance(iteration.restricted_lp_value)
            if iteration.global_lower_bound > iteration.restricted_lp_value + tolerance:
                raise ValueError(
                    "trajectory checkpoint lower bound exceeds a restricted LP"
                )
            if iteration.global_lower_bound + tolerance < previous_lower:
                raise ValueError("trajectory checkpoint lower bound decreases")
            if (
                iteration.global_upper_bound is not None
                and iteration.global_lower_bound
                > iteration.global_upper_bound
                + self._bound_tolerance(iteration.global_upper_bound)
            ):
                raise ValueError("trajectory checkpoint bound interval is inverted")
            if (
                previous_upper is not None
                and iteration.global_upper_bound is not None
                and iteration.global_upper_bound
                > previous_upper + self._bound_tolerance(previous_upper)
            ):
                raise ValueError("trajectory checkpoint upper bound increases")
            previous_lower = iteration.global_lower_bound
            if iteration.global_upper_bound is not None:
                previous_upper = iteration.global_upper_bound
        if state.certified_lower_bound < 0 or not math.isfinite(
            state.certified_lower_bound
        ):
            raise ValueError("trajectory checkpoint lower bound is invalid")
        if state.best_upper_bound is not None and (
            not math.isfinite(state.best_upper_bound)
            or state.best_upper_bound + self.pricing_tolerance
            < state.certified_lower_bound
        ):
            raise ValueError("trajectory checkpoint upper bound is invalid")
        if state.total_seconds < 0 or not math.isfinite(state.total_seconds):
            raise ValueError("trajectory checkpoint elapsed time is invalid")
        if not state.trajectories:
            raise ValueError("trajectory checkpoint pool is empty")
        if state.best_upper_bound is None and state.incumbent_option_ids:
            raise ValueError("trajectory checkpoint has an incumbent without a bound")
        if state.best_upper_bound is not None and not state.incumbent_option_ids:
            raise ValueError("trajectory checkpoint bound has no incumbent")
        if state.best_upper_bound is None and state.incumbent_ride_values_by_id:
            raise ValueError(
                "trajectory checkpoint has passenger rides without a bound"
            )
        if any(
            not ride_id or not math.isfinite(value) or value <= 0
            for ride_id, value in state.incumbent_ride_values_by_id.items()
        ):
            raise ValueError("trajectory checkpoint passenger rides are invalid")
        if any(
            not any(
                ride_id.startswith(f"{option_id}::")
                for option_id in state.incumbent_option_ids
            )
            for ride_id in state.incumbent_ride_values_by_id
        ):
            raise ValueError(
                "trajectory checkpoint passenger ride is outside incumbent"
            )
        if state.root_lp_certified:
            final_iteration = state.iterations[-1] if state.iterations else None
            checkpoint_cabin_count = len(
                {trajectory.cabin_id for trajectory in state.trajectories}
            )
            if (
                final_iteration is None
                or final_iteration.added_trajectory_count != 0
                or final_iteration.minimum_reduced_cost is None
                or final_iteration.minimum_reduced_cost < -self.pricing_tolerance
                or (
                    final_iteration.exact_pricing_cabin_count
                    + final_iteration.nonexact_certified_nonnegative_pricing_count
                    != checkpoint_cabin_count
                )
            ):
                raise ValueError(
                    "trajectory checkpoint root certificate is inconsistent"
                )
        if tuple(sorted(set(state.resource_windows))) != state.resource_windows:
            raise ValueError("trajectory checkpoint resource windows are inconsistent")
        for window in state.resource_windows:
            window.validate()

    def _validate(
        self,
        problem: DddNetworkTimeProblem,
        artifact: EanBuildArtifact,
        trajectory_problem: DddTrajectoryProblem,
    ) -> None:
        problem.validate()
        trajectory_problem.validate()
        artifact.validate()
        if problem.movement_problem.scenario_id != artifact.scenario_id:
            raise ValueError("trajectory root problem and artifact differ")
        is_fixed = isinstance(
            trajectory_problem.start_domain, DddFixedTrajectoryStartDomain
        )
        is_oip = isinstance(
            trajectory_problem.start_domain, DddOptimizedInitialPlacementDomain
        )
        is_reservoir = isinstance(
            trajectory_problem.start_domain, DddReservoirTrajectoryStartDomain
        )
        expected_mode = (
            EanFleetMode.FIXED_STARTS
            if is_fixed
            else EanFleetMode.OPTIMIZED_INITIAL_PLACEMENT
        )
        if not is_reservoir and artifact.fleet_mode is not expected_mode:
            raise ValueError("trajectory root fleet mode and start domain differ")
        if is_oip and (
            self.pricing_formulation
            not in {
                DddTrajectoryPricingFormulation.TIGHT_CONVEX_HULL,
                DddTrajectoryPricingFormulation.RELATIVE_TIME_EXPANDED_OIP,
                DddTrajectoryPricingFormulation.RELATIVE_TIME_EXPANDED_OIP_FLOW,
            }
        ):
            raise ValueError(
                "OIP pricing supports tight_convex_hull or a relative-time-expanded "
                "OIP formulation"
            )
        if is_fixed and self.pricing_formulation in {
            DddTrajectoryPricingFormulation.RELATIVE_TIME_EXPANDED_OIP,
            DddTrajectoryPricingFormulation.RELATIVE_TIME_EXPANDED_OIP_FLOW,
        }:
            raise ValueError(
                "relative_time_expanded_oip is only valid for optimized placement"
            )
        if is_reservoir and self.pricing_formulation is not (
            DddTrajectoryPricingFormulation.TIGHT_CONVEX_HULL
        ):
            raise ValueError(
                "continuous reservoir proof pricing requires tight_convex_hull"
            )
        if (
            (
                is_oip
                or is_reservoir
                or trajectory_problem.waiting_policy.domain
                is DddTrajectoryWaitingDomain.BOUNDED_WAIT
            )
            and self.conflict_row_mode is not DddTrajectoryConflictRowMode.PAIR_ONLY
        ):
            raise ValueError(
                "continuous starts and bounded waiting require pair_only conflict rows"
            )
        if (
            is_oip
            and trajectory_problem.waiting_policy.domain
            is DddTrajectoryWaitingDomain.BOUNDED_WAIT
        ):
            raise ValueError("trajectory OIP does not support bounded waiting")
        if (
            is_fixed
            and trajectory_problem.waiting_policy.domain
            is DddTrajectoryWaitingDomain.BOUNDED_WAIT
            and self.pricing_formulation
            is not DddTrajectoryPricingFormulation.TIME_EXPANDED_PATH
        ):
            raise ValueError(
                "fixed-start bounded waiting requires time_expanded_path pricing"
            )
        if (
            is_reservoir
            and trajectory_problem.waiting_policy.domain
            is DddTrajectoryWaitingDomain.BOUNDED_WAIT
            and self.reservoir_primal_pricing_mode
            is DddReservoirPrimalPricingMode.TIME_EXPANDED_ANCHORS
        ):
            raise ValueError(
                "bounded-wait reservoir pricing does not support time-expanded anchors"
            )
        if self.max_iterations <= 0:
            raise ValueError("trajectory root iteration limit must be positive")
        if self.total_time_limit_seconds is not None and (
            self.total_time_limit_seconds <= 0
            or not math.isfinite(self.total_time_limit_seconds)
        ):
            raise ValueError("trajectory root total time limit must be positive")
        if self.pricing_time_limit_seconds <= 0:
            raise ValueError("trajectory root pricing limit must be positive")
        if self.pricing_time_limit_tiers_seconds:
            if tuple(sorted(set(self.pricing_time_limit_tiers_seconds))) != (
                self.pricing_time_limit_tiers_seconds
            ) or any(
                not math.isfinite(value) or value <= 0
                for value in self.pricing_time_limit_tiers_seconds
            ):
                raise ValueError(
                    "trajectory root pricing tiers must be increasing positive values"
                )
        if self.pricing_threads <= 0:
            raise ValueError("trajectory root pricing threads must be positive")
        if not isinstance(self.master_dual_mode, DddTrajectoryMasterDualMode):
            raise ValueError("trajectory root master dual mode is invalid")
        if self.proof_pricing_mip_focus not in range(4):
            raise ValueError("trajectory root proof-pricing focus is invalid")
        if self.extra_pricing_mip_focus not in range(4):
            raise ValueError("trajectory root extra-pricing focus is invalid")
        if not isinstance(self.pricing_formulation, DddTrajectoryPricingFormulation):
            raise ValueError("trajectory root pricing formulation is invalid")
        if self.pricing_tolerance < 0 or not math.isfinite(self.pricing_tolerance):
            raise ValueError("trajectory root pricing tolerance is invalid")
        if not isinstance(self.conflict_row_mode, DddTrajectoryConflictRowMode):
            raise ValueError("trajectory root conflict-row mode is invalid")
        if self.max_resource_window_rounds <= 0:
            raise ValueError("trajectory root resource-window limit must be positive")
        if self.columns_per_cabin_per_round <= 0:
            raise ValueError("trajectory root column batch size must be positive")
        if not isinstance(self.diversity_mode, DddTrajectoryDiversityMode):
            raise ValueError("trajectory root diversity mode is invalid")
        if self.minimum_diversity_distance <= 0:
            raise ValueError("trajectory root diversity distance must be positive")
        if self.extra_column_time_limit_seconds <= 0 or not math.isfinite(
            self.extra_column_time_limit_seconds
        ):
            raise ValueError("trajectory root extra-column limit is invalid")
        if self.oip_primal_pricing_time_limit_seconds < 0 or not math.isfinite(
            self.oip_primal_pricing_time_limit_seconds
        ):
            raise ValueError("trajectory root OIP primal-pricing limit is invalid")
        if (
            self.reservoir_primal_pricing_time_limit_seconds < 0
            or not math.isfinite(self.reservoir_primal_pricing_time_limit_seconds)
        ):
            raise ValueError(
                "trajectory root reservoir primal-pricing limit is invalid"
            )
        if not isinstance(
            self.reservoir_primal_pricing_mode,
            DddReservoirPrimalPricingMode,
        ):
            raise ValueError("trajectory root reservoir primal-pricing mode is invalid")
        if self.reservoir_primal_maximum_cabin_calls_per_round <= 0:
            raise ValueError(
                "trajectory root reservoir primal cabin-call limit must be positive"
            )
        if self.reservoir_dispatch_anchor_count <= 0:
            raise ValueError("trajectory root reservoir anchor count must be positive")
        if self.reservoir_primal_maximum_arc_count <= 0:
            raise ValueError("trajectory root reservoir arc cap must be positive")
        if self.reservoir_primal_maximum_passenger_arc_product <= 0:
            raise ValueError(
                "trajectory root reservoir passenger-product cap must be positive"
            )
        if not math.isfinite(self.objective_floor):
            raise ValueError("trajectory root objective floor must be finite")
        if self.restricted_mip_interval <= 0:
            raise ValueError("trajectory restricted MIP interval must be positive")
        if self.restricted_mip_time_limit_seconds is not None and (
            not math.isfinite(self.restricted_mip_time_limit_seconds)
            or self.restricted_mip_time_limit_seconds <= 0
        ):
            raise ValueError("trajectory restricted MIP limit must be positive")
        if not math.isfinite(self.final_mip_time_limit_seconds) or (
            self.final_mip_time_limit_seconds < 0
        ):
            raise ValueError("trajectory final MIP limit must be nonnegative")
        if self.restricted_mip_focus not in range(4):
            raise ValueError("trajectory restricted MIP focus is invalid")
        if self.certified_fixed_k_mode:
            if not is_fixed:
                raise ValueError("certified Fixed-K mode requires fixed starts")
            if (
                self.oip_primal_pricing_time_limit_seconds > 0
                or self.reservoir_primal_pricing_time_limit_seconds > 0
            ):
                raise ValueError(
                    "certified Fixed-K mode forbids independent primal pricing"
                )

    @staticmethod
    def _result(
        *,
        status: DddTrajectoryRootCgStatus,
        lower_bound: float,
        upper_bound: float | None,
        iterations: list[DddTrajectoryRootCgIteration],
        trajectory_by_id: dict[str, DddReferenceTrajectory],
        started: float,
        elapsed_offset_seconds: float,
        incumbent_option_ids: tuple[str, ...],
        incumbent_ride_values_by_id: dict[str, float],
        detail: str | None,
        root_lp_certified: bool = False,
        fleet_mode: DddTrajectoryFleetMode = DddTrajectoryFleetMode.FIXED_STARTS,
        fleet_plan: EanFleetPlan | None = None,
        reservoir_fleet_plan: DddReservoirFleetPlan | None = None,
        seed_kind: str | None = None,
        certificate_valid: bool = True,
        objective_floor: float = 0.0,
    ) -> DddTrajectoryRootCgResult:
        relative_gap = (
            max(0.0, upper_bound - lower_bound) / abs(upper_bound)
            if upper_bound is not None and abs(upper_bound) > 1e-9
            else None
        )
        return DddTrajectoryRootCgResult(
            status=status,
            certified_lower_bound=lower_bound,
            best_upper_bound=upper_bound,
            relative_gap=relative_gap,
            root_lp_certified=root_lp_certified,
            iterations=tuple(iterations),
            trajectories=tuple(
                trajectory_by_id[key] for key in sorted(trajectory_by_id)
            ),
            incumbent_option_ids=incumbent_option_ids,
            incumbent_ride_values_by_id=dict(incumbent_ride_values_by_id),
            total_seconds=elapsed_offset_seconds + perf_counter() - started,
            detail=detail,
            fleet_mode=fleet_mode,
            fleet_plan=fleet_plan,
            reservoir_fleet_plan=reservoir_fleet_plan,
            full_start_domain_priced=(
                fleet_mode
                in {
                    DddTrajectoryFleetMode.OPTIMIZED_INITIAL_PLACEMENT,
                    DddTrajectoryFleetMode.RESERVOIR_DISPATCH,
                }
                and bool(iterations)
                and all(
                    item.pricing_bound_correction is not None for item in iterations
                )
            ),
            seed_kind=seed_kind,
            certificate_valid=certificate_valid,
            objective_floor=objective_floor,
        )


def ddd_trajectory_problem_instance_fingerprint(
    artifact: EanBuildArtifact,
    trajectory_problem: DddTrajectoryProblem,
) -> str:
    base = ddd_trajectory_instance_fingerprint(artifact)
    domain = trajectory_problem.start_domain
    waiting_policy = trajectory_problem.waiting_policy
    bounded_waiting = (
        waiting_policy.domain is DddTrajectoryWaitingDomain.BOUNDED_WAIT
    )
    if not isinstance(domain, DddReservoirTrajectoryStartDomain) and not bounded_waiting:
        return base
    payload: dict[str, object] = {
        "base": base,
    }
    if isinstance(domain, DddReservoirTrajectoryStartDomain):
        payload.update(
            {
                "fleet_mode": domain.mode.value,
                "cabin_ids": domain.cabin_ids,
                "boundary": {
                    "id": domain.boundary.id,
                    "entry_state_id": domain.boundary.entry_state_id,
                    "boundary_mode": domain.boundary.boundary_mode.value,
                    "dispatch_resource_usages": [
                        {
                            "resource_id": usage.resource_id,
                            "leader_clear_offset_seconds": (
                                usage.leader_clear_offset_seconds
                            ),
                            "follower_enter_offset_seconds": (
                                usage.follower_enter_offset_seconds
                            ),
                            "separation_after_seconds": (
                                usage.separation_after_seconds
                            ),
                        }
                        for usage in domain.boundary.dispatch_resource_usages
                    ],
                    "required_entry_resource_ids": (
                        domain.boundary.required_entry_resource_ids
                    ),
                    "allowed_first_route_option_ids": (
                        domain.boundary.allowed_first_route_option_ids
                    ),
                },
                "warmup_seconds": domain.warmup_seconds,
                "maximum_visit_count": domain.maximum_visit_count,
                "cardinality_mode": domain.cardinality_mode.value,
            }
        )
    if bounded_waiting:
        payload["waiting_policy"] = {
            "domain": waiting_policy.domain.value,
            "step_seconds": waiting_policy.step_seconds,
            "maximum_wait_seconds_by_station_id": (
                waiting_policy.maximum_wait_seconds_by_station_id
            ),
            "earliest_wait_time_seconds": (
                waiting_policy.earliest_wait_time_seconds
            ),
        }
    return sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def _oip_pricing_equivalence_key(
    *,
    cabin_id: int,
    passenger_build: EanPassengerCandidateBuildResult,
) -> tuple[tuple[str, int, int], ...]:
    """Cabin-independent ride structure used by the current OIP pricing MILP."""

    return tuple(
        sorted(
            (
                candidate.demand_group_id,
                candidate.board_visit_index,
                candidate.alight_visit_index,
            )
            for candidate in passenger_build.ride_candidates
            if candidate.cabin_id == cabin_id
        )
    )


def _reservoir_primal_dispatch_spacing_seconds(
    trajectory_problem: DddTrajectoryProblem,
) -> float:
    domain = trajectory_problem.start_domain
    if not isinstance(domain, DddReservoirTrajectoryStartDomain):
        raise ValueError("reservoir dispatch spacing requires a reservoir domain")
    movement = trajectory_problem.structural_movement_problem
    allowed = set(domain.boundary.allowed_first_route_option_ids)
    first_stop_options = tuple(
        option
        for option in movement.route_options_by_state_id[domain.boundary.entry_state_id]
        if option.decision is DddRouteDecision.STOP
        and (not allowed or option.id in allowed)
    )
    if not first_stop_options:
        raise ValueError("reservoir warm-up boundary has no permitted STOP route")
    resources_by_id = movement.resources_by_id
    required = [
        usage.separation_after_seconds
        if usage.separation_after_seconds is not None
        else resources_by_id[usage.resource_id].minimum_headway_seconds
        for option in first_stop_options
        for usage in option.resource_usages
    ]
    required.extend(
        usage.separation_after_seconds
        if usage.separation_after_seconds is not None
        else resources_by_id[usage.resource_id].minimum_headway_seconds
        for usage in domain.boundary.dispatch_resource_usages
    )
    return max(required, default=DDD_RESERVOIR_TIME_TOLERANCE_SECONDS)


def _remap_shared_oip_pricing_result(
    *,
    result: DddTrajectoryExactPricingResult,
    source_cabin_id: int,
    target_cabin_id: int,
    trajectory_problem: DddTrajectoryProblem,
    artifact: EanBuildArtifact,
    passenger_build: EanPassengerCandidateBuildResult,
    duals: DddTrajectoryPassengerDuals,
) -> DddTrajectoryExactPricingResult:
    if result.cabin_id != source_cabin_id or source_cabin_id == target_cabin_id:
        raise ValueError("shared OIP pricing remap has invalid cabin IDs")
    if _oip_pricing_equivalence_key(
        cabin_id=source_cabin_id,
        passenger_build=passenger_build,
    ) != _oip_pricing_equivalence_key(
        cabin_id=target_cabin_id,
        passenger_build=passenger_build,
    ):
        raise ValueError("shared OIP pricing cabins are not equivalent")
    source_alpha = duals.cabin_choice_raw_by_cabin_id[source_cabin_id]
    target_alpha = duals.cabin_choice_raw_by_cabin_id[target_cabin_id]
    reduced_cost_shift = source_alpha - target_alpha
    target_trajectory: DddReferenceTrajectory | None = None
    target_option_id: str | None = None
    target_ride_counts: dict[str, int] = {}
    if result.reference_trajectory is not None:
        target_trajectory, target_option_id, target_ride_counts = (
            _remap_oip_pricing_column_payload(
                source_trajectory=result.reference_trajectory,
                source_ride_counts=result.ride_counts_by_candidate_id,
                target_cabin_id=target_cabin_id,
                trajectory_problem=trajectory_problem,
                artifact=artifact,
                passenger_build=passenger_build,
            )
        )
    target_class_candidates = tuple(
        DddTrajectoryExactPricingCandidate(
            start_class_index=candidate.start_class_index,
            reduced_cost=candidate.reduced_cost + reduced_cost_shift,
            option_id=remapped[1],
            reference_trajectory=remapped[0],
            ride_counts_by_candidate_id=remapped[2],
        )
        for candidate in result.start_class_candidates
        for remapped in (
            _remap_oip_pricing_column_payload(
                source_trajectory=candidate.reference_trajectory,
                source_ride_counts=candidate.ride_counts_by_candidate_id,
                target_cabin_id=target_cabin_id,
                trajectory_problem=trajectory_problem,
                artifact=artifact,
                passenger_build=passenger_build,
            ),
        )
    )
    return replace(
        result,
        cabin_id=target_cabin_id,
        minimum_reduced_cost=result.minimum_reduced_cost + reduced_cost_shift,
        certified_reduced_cost_lower_bound=(
            None
            if result.certified_reduced_cost_lower_bound is None
            else result.certified_reduced_cost_lower_bound + reduced_cost_shift
        ),
        option_id=target_option_id,
        reference_trajectory=target_trajectory,
        ride_counts_by_candidate_id=target_ride_counts,
        start_class_candidates=target_class_candidates,
        solve_seconds=0.0,
        detail=f"shared OIP pricing reused from cabin {source_cabin_id}",
        model_variable_count=0,
        model_linear_constraint_count=0,
        model_general_constraint_count=0,
        solver_node_count=0.0,
        relative_node_count=0,
        relative_arc_count=0,
        origin_product_count=0,
        model_build_seconds=0.0,
    )


def _remap_shared_reservoir_pricing_result(
    *,
    result: DddTrajectoryExactPricingResult,
    source_cabin_id: int,
    target_cabin_id: int,
    trajectory_problem: DddTrajectoryProblem,
    passenger_build: EanPassengerCandidateBuildResult,
    duals: DddTrajectoryPassengerDuals,
    instance_fingerprint: str,
) -> DddTrajectoryExactPricingResult:
    if result.cabin_id != source_cabin_id or source_cabin_id == target_cabin_id:
        raise ValueError("shared reservoir pricing remap has invalid cabin IDs")
    if _oip_pricing_equivalence_key(
        cabin_id=source_cabin_id,
        passenger_build=passenger_build,
    ) != _oip_pricing_equivalence_key(
        cabin_id=target_cabin_id,
        passenger_build=passenger_build,
    ):
        raise ValueError("shared reservoir pricing cabins are not equivalent")
    domain = trajectory_problem.start_domain
    if not isinstance(domain, DddReservoirTrajectoryStartDomain):
        raise ValueError("shared reservoir pricing needs a reservoir domain")
    source_alpha = duals.cabin_choice_raw_by_cabin_id[source_cabin_id]
    target_alpha = duals.cabin_choice_raw_by_cabin_id[target_cabin_id]
    shift = source_alpha - target_alpha
    target_trajectory = None
    target_option_id = None
    target_ride_counts: dict[str, int] = {}
    source_trajectory = result.reference_trajectory
    if source_trajectory is not None:
        state = source_trajectory.reservoir_state
        if state is None:
            raise ValueError("shared reservoir column has no boundary provenance")
        if state.kind is DddReservoirTrajectoryKind.STORED:
            target_trajectory = build_ddd_stored_reservoir_trajectory(
                cabin_id=target_cabin_id,
                domain=domain,
            )
        else:
            assert state.dispatch_time_seconds is not None
            target_trajectory = build_ddd_reservoir_reference_trajectory(
                problem=trajectory_problem,
                cabin_id=target_cabin_id,
                dispatch_time_seconds=state.dispatch_time_seconds,
                route_option_ids=source_trajectory.support_signature,
            )
        target_option_id = ddd_trajectory_column(
            target_trajectory,
            instance_fingerprint=instance_fingerprint,
        ).id
        candidate_by_id = {
            candidate.id: candidate for candidate in passenger_build.ride_candidates
        }
        target_id_by_key = {
            (
                candidate.demand_group_id,
                candidate.board_visit_index,
                candidate.alight_visit_index,
            ): candidate.id
            for candidate in passenger_build.ride_candidates
            if candidate.cabin_id == target_cabin_id
        }
        for source_candidate_id, count in result.ride_counts_by_candidate_id.items():
            source_candidate = candidate_by_id[source_candidate_id]
            key = (
                source_candidate.demand_group_id,
                source_candidate.board_visit_index,
                source_candidate.alight_visit_index,
            )
            target_ride_counts[target_id_by_key[key]] = count
    return replace(
        result,
        cabin_id=target_cabin_id,
        minimum_reduced_cost=result.minimum_reduced_cost + shift,
        certified_reduced_cost_lower_bound=(
            None
            if result.certified_reduced_cost_lower_bound is None
            else result.certified_reduced_cost_lower_bound + shift
        ),
        option_id=target_option_id,
        reference_trajectory=target_trajectory,
        ride_counts_by_candidate_id=target_ride_counts,
        solve_seconds=0.0,
        detail=f"shared reservoir pricing reused from cabin {source_cabin_id}",
        model_variable_count=0,
        model_linear_constraint_count=0,
        model_general_constraint_count=0,
        solver_node_count=0.0,
        model_build_seconds=0.0,
    )


def _remap_oip_pricing_column_payload(
    *,
    source_trajectory: DddReferenceTrajectory,
    source_ride_counts: dict[str, int],
    target_cabin_id: int,
    trajectory_problem: DddTrajectoryProblem,
    artifact: EanBuildArtifact,
    passenger_build: EanPassengerCandidateBuildResult,
) -> tuple[DddReferenceTrajectory, str, dict[str, int]]:
    if source_trajectory.initial_state is None or not source_trajectory.visits:
        raise ValueError("shared OIP pricing trajectory has no initial state")
    target_trajectory = build_ddd_oip_reference_trajectory(
        problem=trajectory_problem,
        artifact=artifact,
        cabin_id=target_cabin_id,
        start=DddOipTrajectoryStart(
            phase_index=source_trajectory.visits[0].visit_index,
            station_start=(source_trajectory.initial_state.kind.value != "rope"),
            first_switch_time_seconds=source_trajectory.visits[0].switch_time_seconds,
            previous_service=source_trajectory.initial_state.previous_service,
        ),
        route_option_ids=source_trajectory.support_signature,
    )
    target_option_id = ddd_trajectory_column(
        target_trajectory,
        instance_fingerprint=ddd_trajectory_instance_fingerprint(artifact),
    ).id
    candidate_by_id = {
        candidate.id: candidate for candidate in passenger_build.ride_candidates
    }
    target_id_by_key = {
        (
            candidate.demand_group_id,
            candidate.board_visit_index,
            candidate.alight_visit_index,
        ): candidate.id
        for candidate in passenger_build.ride_candidates
        if candidate.cabin_id == target_cabin_id
    }
    target_ride_counts: dict[str, int] = {}
    for source_candidate_id, count in source_ride_counts.items():
        source_candidate = candidate_by_id[source_candidate_id]
        key = (
            source_candidate.demand_group_id,
            source_candidate.board_visit_index,
            source_candidate.alight_visit_index,
        )
        target_ride_counts[target_id_by_key[key]] = count
    return target_trajectory, target_option_id, target_ride_counts


def _pricing_result_from_start_class_candidate(
    *,
    proof_result: DddTrajectoryExactPricingResult,
    candidate: DddTrajectoryExactPricingCandidate,
) -> DddTrajectoryExactPricingResult:
    return replace(
        proof_result,
        status=DddTrajectoryExactPricingStatus.UNKNOWN,
        minimum_reduced_cost=candidate.reduced_cost,
        exact=False,
        option_id=candidate.option_id,
        reference_trajectory=candidate.reference_trajectory,
        ride_counts_by_candidate_id=candidate.ride_counts_by_candidate_id,
        solve_seconds=0.0,
        certified_reduced_cost_lower_bound=None,
        detail=(
            "primal column retained from OIP proof start class "
            f"{candidate.start_class_index}"
        ),
        model_variable_count=0,
        model_linear_constraint_count=0,
        model_general_constraint_count=0,
        solver_node_count=0.0,
        relative_node_count=0,
        relative_arc_count=0,
        origin_product_count=0,
        model_build_seconds=0.0,
        priced_start_class_count=0,
        bounded_start_class_count=0,
        start_class_candidates=(),
    )


def _build_all_stop_trajectory(
    movement_problem: DddMovementProblem,
    start: DddFixedStart,
) -> DddReferenceTrajectory:
    visits = []
    state_id = start.state_id
    switch_time_seconds = start.time_seconds
    for visit_index in range(start.max_visit_count):
        options = movement_problem.route_options_by_state_id[state_id]
        stop = tuple(
            option for option in options if option.decision is DddRouteDecision.STOP
        )
        if len(stop) != 1:
            raise ValueError("all-stop seed requires exactly one STOP route")
        visit = build_ddd_reference_visit(
            start=start,
            visit_index=visit_index,
            switch_time_seconds=switch_time_seconds,
            option=stop[0],
            operational_end_seconds=movement_problem.operational_end_seconds,
            tolerance_seconds=1e-9,
        )
        visits.append(visit)
        if visit.next_switch_time_seconds > movement_problem.operational_end_seconds:
            trajectory = DddReferenceTrajectory(
                cabin_id=start.cabin_id,
                visits=tuple(visits),
            )
            validate_ddd_reference_trajectory(movement_problem, trajectory)
            return trajectory
        state_id = stop[0].to_state_id
        switch_time_seconds = visit.next_switch_time_seconds
    raise ValueError("all-stop seed does not cover the operational horizon")


def build_ddd_all_stop_seed_trajectories(
    movement_problem: DddMovementProblem,
) -> tuple[DddReferenceTrajectory, ...]:
    movement_problem.validate()
    return tuple(
        _build_all_stop_trajectory(movement_problem, start)
        for start in sorted(
            movement_problem.starts,
            key=lambda item: item.cabin_id,
        )
    )


def _row_fingerprint(
    pairs: tuple[tuple[str, str], ...],
    resource_rows: tuple[DddTrajectoryResourceWindowRow, ...] = (),
) -> str:
    return sha256(
        json.dumps(
            {
                "pairs": pairs,
                "resource_rows": [(row.id, row.coefficients) for row in resource_rows],
            },
            sort_keys=True,
            separators=(",", ":"),
        ).encode()
    ).hexdigest()


def _trajectory_diversity_signature(
    trajectory: DddReferenceTrajectory,
    *,
    mode: DddTrajectoryDiversityMode,
    problem: DddMovementProblem,
    resource_windows: tuple[DddTrajectoryResourceWindow, ...],
) -> tuple[object, ...]:
    if mode is DddTrajectoryDiversityMode.RESOURCE_WINDOWS and resource_windows:
        intervals = ddd_trajectory_resource_intervals(trajectory, problem)
        return tuple(
            any(
                interval.resource_id == window.resource_id
                and interval.contains(window.anchor_tick)
                for interval in intervals
            )
            for window in resource_windows
        )
    return trajectory.support_signature


def _hamming_distance(
    first: tuple[object, ...],
    second: tuple[object, ...],
) -> int:
    missing = object()
    return sum(
        left != right for left, right in zip_longest(first, second, fillvalue=missing)
    )
