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
    DddTrajectoryExactPricingStatus,
    DddTrajectoryPricingFormulation,
)
from ropeway_skip_stop_optimization.optimization.ddd.trajectory_exhaustive_reference import (
    build_ddd_trajectory_reference_master,
    ddd_trajectory_instance_fingerprint,
)
from ropeway_skip_stop_optimization.optimization.ddd.trajectory_passenger_lp import (
    DddTrajectoryFactorizedLpOptimizer,
    DddTrajectoryFactorizedMipReferenceOptimizer,
    DddTrajectoryMasterDualMode,
    DddTrajectoryPassengerLpStatus,
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
    StationWaitingMode,
)


class DddTrajectoryRootCgStatus(StrEnum):
    OPTIMAL_ROOT_LP = "optimal_root_lp"
    ITERATION_LIMIT = "iteration_limit"
    UNKNOWN = "unknown"


class DddTrajectoryDiversityMode(StrEnum):
    OFF = "off"
    RESOURCE_WINDOWS = "resource_windows"
    STOP_SKIP = "stop_skip"


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


@dataclass(frozen=True)
class DddTrajectoryExactRootColumnGenerationSolver:
    """Prototype exact no-wait root column generation for fixed starts."""

    max_iterations: int = 30
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
    output_flag: bool = False

    def solve(
        self,
        *,
        problem: DddNetworkTimeProblem,
        artifact: EanBuildArtifact,
        passenger_build: EanPassengerCandidateBuildResult,
        objective: EanPassengerObjective,
        initial_trajectories: tuple[DddReferenceTrajectory, ...] | None = None,
        resume_state: DddTrajectoryRootCgState | None = None,
        progress_callback: Callable[[DddTrajectoryRootCgIteration], None] | None = None,
        checkpoint_callback: Callable[[DddTrajectoryRootCgState], None] | None = None,
    ) -> DddTrajectoryRootCgResult:
        started = perf_counter()
        self._validate(problem, artifact)
        instance_fingerprint = ddd_trajectory_instance_fingerprint(artifact)
        if resume_state is not None and initial_trajectories is not None:
            raise ValueError(
                "resume state and initial trajectories are mutually exclusive"
            )
        if resume_state is not None:
            self._validate_resume_state(
                resume_state,
                instance_fingerprint=instance_fingerprint,
                objective=objective,
            )
            trajectories = resume_state.trajectories
        else:
            trajectories = (
                initial_trajectories
                if initial_trajectories is not None
                else build_ddd_all_stop_seed_trajectories(problem.movement_problem)
            )
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
        expected_cabin_ids = {item.cabin_id for item in problem.movement_problem.starts}
        if {item.cabin_id for item in trajectories} != expected_cabin_ids:
            raise ValueError("initial trajectory root pool does not cover every cabin")
        for trajectory in trajectories:
            validate_ddd_reference_trajectory(problem.movement_problem, trajectory)
        iterations = list(resume_state.iterations) if resume_state is not None else []
        global_lower_bound = (
            resume_state.certified_lower_bound if resume_state is not None else 0.0
        )
        global_upper_bound = (
            resume_state.best_upper_bound if resume_state is not None else None
        )
        incumbent_option_ids = (
            resume_state.incumbent_option_ids if resume_state is not None else ()
        )
        incumbent_ride_values_by_id = (
            dict(resume_state.incumbent_ride_values_by_id)
            if resume_state is not None
            else {}
        )
        elapsed_offset_seconds = (
            resume_state.total_seconds if resume_state is not None else 0.0
        )
        if resume_state is not None and resume_state.root_lp_certified:
            return self._result(
                status=DddTrajectoryRootCgStatus.OPTIMAL_ROOT_LP,
                lower_bound=global_lower_bound,
                upper_bound=global_upper_bound,
                iterations=iterations,
                trajectory_by_id=trajectory_by_id,
                started=started,
                elapsed_offset_seconds=elapsed_offset_seconds,
                incumbent_option_ids=incumbent_option_ids,
                incumbent_ride_values_by_id=incumbent_ride_values_by_id,
                detail=None,
                root_lp_certified=True,
            )
        pricing_oracle = DddTrajectoryExactNoWaitPricingOracle(
            time_limit_seconds=self.pricing_time_limit_seconds,
            threads=self.pricing_threads,
            output_flag=self.output_flag,
            mip_focus=self.proof_pricing_mip_focus,
            formulation=self.pricing_formulation,
        )
        resource_windows = (
            resume_state.resource_windows if resume_state is not None else ()
        )
        first_round = (
            resume_state.completed_rounds + 1 if resume_state is not None else 1
        )

        for round_index in range(first_round, self.max_iterations + 1):
            round_started = perf_counter()
            master_started = perf_counter()
            reference_master = build_ddd_trajectory_reference_master(
                problem=problem,
                artifact=artifact,
                passenger_build=passenger_build,
                objective=objective,
                reference_trajectories=tuple(trajectory_by_id.values()),
                max_incompatibility_pair_checks=(self.max_incompatibility_pair_checks),
                resource_windows=resource_windows,
            )
            master_seconds = perf_counter() - master_started
            lp_seconds = 0.0
            resource_separation_seconds = 0.0
            added_resource_window_count = 0
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
                    return self._result(
                        status=DddTrajectoryRootCgStatus.UNKNOWN,
                        lower_bound=global_lower_bound,
                        upper_bound=global_upper_bound,
                        iterations=iterations,
                        trajectory_by_id=trajectory_by_id,
                        started=started,
                        elapsed_offset_seconds=elapsed_offset_seconds,
                        incumbent_option_ids=incumbent_option_ids,
                        incumbent_ride_values_by_id=incumbent_ride_values_by_id,
                        detail="trajectory restricted LP did not solve to optimality",
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
                resource_separation_seconds += perf_counter() - separation_started
                if not separation.new_windows:
                    break
                if resource_round >= self.max_resource_window_rounds:
                    return self._result(
                        status=DddTrajectoryRootCgStatus.UNKNOWN,
                        lower_bound=global_lower_bound,
                        upper_bound=global_upper_bound,
                        iterations=iterations,
                        trajectory_by_id=trajectory_by_id,
                        started=started,
                        elapsed_offset_seconds=elapsed_offset_seconds,
                        incumbent_option_ids=incumbent_option_ids,
                        incumbent_ride_values_by_id=incumbent_ride_values_by_id,
                        detail="trajectory resource-window round limit exhausted",
                    )
                resource_windows = tuple(
                    sorted({*resource_windows, *separation.new_windows})
                )
                added_resource_window_count += len(separation.new_windows)
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
            if (
                lp.status is not DddTrajectoryPassengerLpStatus.OPTIMAL
                or lp.objective_value is None
                or lp.duals is None
            ):
                return self._result(
                    status=DddTrajectoryRootCgStatus.UNKNOWN,
                    lower_bound=global_lower_bound,
                    upper_bound=global_upper_bound,
                    iterations=iterations,
                    trajectory_by_id=trajectory_by_id,
                    started=started,
                    elapsed_offset_seconds=elapsed_offset_seconds,
                    incumbent_option_ids=incumbent_option_ids,
                    incumbent_ride_values_by_id=incumbent_ride_values_by_id,
                    detail="trajectory restricted LP did not solve to optimality",
                )
            mip = DddTrajectoryFactorizedMipReferenceOptimizer(
                output_flag=self.output_flag
            ).solve(reference_master.master_problem)
            restricted_upper = mip.objective_value
            if restricted_upper is not None:
                selected = tuple(
                    reference_master.reference_trajectory_by_option_id[option_id]
                    for option_id, value in mip.option_values_by_id.items()
                    if value >= 0.5
                )
                validate_ddd_reference_solution(
                    problem.movement_problem,
                    DddReferenceSolution(
                        trajectories=tuple(
                            sorted(selected, key=lambda item: item.cabin_id)
                        )
                    ),
                )
                if (
                    global_upper_bound is None
                    or restricted_upper < global_upper_bound - self.pricing_tolerance
                ):
                    global_upper_bound = restricted_upper
                    incumbent_option_ids = tuple(
                        sorted(
                            option_id
                            for option_id, value in mip.option_values_by_id.items()
                            if value >= 0.5
                        )
                    )
                    incumbent_ride_values_by_id = {
                        ride_id: value
                        for ride_id, value in mip.ride_values_by_id.items()
                        if value > self.pricing_tolerance
                    }

            pricing_started = perf_counter()
            pricing_results = []
            primal_pricing_results = []
            extra_pricing_call_count = 0
            proof_pricing_exclusion_count = 0
            for cabin_id in reference_master.master_problem.cabin_ids:
                excluded_sequences = {
                    trajectory.support_signature
                    for trajectory in trajectory_by_id.values()
                    if trajectory.cabin_id == cabin_id
                }
                proof_result = pricing_oracle.solve(
                    movement_problem=problem.movement_problem,
                    artifact=artifact,
                    passenger_build=passenger_build,
                    objective=objective,
                    cabin_id=cabin_id,
                    duals=lp.duals,
                    excluded_route_option_sequences=frozenset(excluded_sequences),
                    resource_window_rows=(
                        reference_master.master_problem.resource_window_rows
                    ),
                )
                pricing_results.append(proof_result)
                proof_pricing_exclusion_count += len(excluded_sequences)
                if (
                    proof_result.minimum_reduced_cost < -self.pricing_tolerance
                    and proof_result.reference_trajectory is not None
                ):
                    primal_pricing_results.append(proof_result)
                    excluded_sequences.add(
                        proof_result.reference_trajectory.support_signature
                    )
                accepted_signatures = (
                    [
                        _trajectory_diversity_signature(
                            proof_result.reference_trajectory,
                            mode=self.diversity_mode,
                            problem=problem.movement_problem,
                            resource_windows=resource_windows,
                        )
                    ]
                    if proof_result.reference_trajectory is not None
                    else []
                )
                extra_started = perf_counter()
                while (
                    proof_result.minimum_reduced_cost < -self.pricing_tolerance
                    and proof_result.reference_trajectory is not None
                    and len(accepted_signatures) < self.columns_per_cabin_per_round
                    and perf_counter() - extra_started
                    < self.extra_column_time_limit_seconds
                ):
                    remaining = self.extra_column_time_limit_seconds - (
                        perf_counter() - extra_started
                    )
                    extra_oracle = DddTrajectoryExactNoWaitPricingOracle(
                        time_limit_seconds=max(remaining, 1e-6),
                        threads=self.pricing_threads,
                        output_flag=self.output_flag,
                        mip_focus=self.extra_pricing_mip_focus,
                        formulation=self.pricing_formulation,
                    )
                    extra = extra_oracle.solve(
                        movement_problem=problem.movement_problem,
                        artifact=artifact,
                        passenger_build=passenger_build,
                        objective=objective,
                        cabin_id=cabin_id,
                        duals=lp.duals,
                        excluded_route_option_sequences=frozenset(excluded_sequences),
                        resource_window_rows=(
                            reference_master.master_problem.resource_window_rows
                        ),
                    )
                    extra_pricing_call_count += 1
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
                        resource_windows=resource_windows,
                    )
                    if self.diversity_mode is DddTrajectoryDiversityMode.OFF or all(
                        _hamming_distance(signature, prior)
                        >= self.minimum_diversity_distance
                        for prior in accepted_signatures
                    ):
                        primal_pricing_results.append(extra)
                        accepted_signatures.append(signature)
            pricing_seconds = perf_counter() - pricing_started
            pricing_diagnostics = tuple(
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
                        and result.option_id in trajectory_by_id
                    ),
                    model_variable_count=result.model_variable_count,
                    model_linear_constraint_count=(
                        result.model_linear_constraint_count
                    ),
                    model_general_constraint_count=(
                        result.model_general_constraint_count
                    ),
                    solver_node_count=result.solver_node_count,
                    solve_seconds=result.solve_seconds,
                )
                for result in pricing_results
            )
            certified_pricing_bounds = tuple(
                result.certified_reduced_cost_lower_bound
                for result in pricing_results
                if result.certified_reduced_cost_lower_bound is not None
            )
            all_pricing_bounds_available = len(certified_pricing_bounds) == len(
                pricing_results
            )
            pricing_bound_correction = (
                sum(min(0.0, value) for value in certified_pricing_bounds)
                if all_pricing_bounds_available
                else None
            )
            minimum_certified_reduced_cost_bound = (
                min(certified_pricing_bounds) if certified_pricing_bounds else None
            )
            reduced_costs = tuple(
                DddTrajectoryReducedCost(
                    cabin_id=result.cabin_id,
                    minimum_reduced_cost=result.minimum_reduced_cost,
                    exact=result.exact,
                    certified_lower_bound=(result.certified_reduced_cost_lower_bound),
                )
                for result in pricing_results
            )
            certificate = DddTrajectoryPricingCertificate(
                restricted_master_lp_value=lp.objective_value,
                expected_cabin_ids=reference_master.master_problem.cabin_ids,
                reduced_costs=reduced_costs,
                instance_fingerprint=ddd_trajectory_instance_fingerprint(artifact),
                objective_fingerprint=sha256(objective.value.encode()).hexdigest(),
                master_fingerprint=lp.master_fingerprint,
                dual_fingerprint=lp.duals.fingerprint,
                row_pool_fingerprint=_row_fingerprint(
                    reference_master.master_problem.incompatibility_pairs,
                    reference_master.master_problem.resource_window_rows,
                ),
                pricing_waiting_domain=DddTrajectoryWaitingDomain.NO_WAIT,
                target_waiting_domain=DddTrajectoryWaitingDomain.NO_WAIT,
                row_separation_complete=True,
                tolerance=self.pricing_tolerance,
            )
            corrected = certificate.certified_lower_bound
            if corrected is not None:
                global_lower_bound = max(global_lower_bound, corrected, 0.0)

            added = 0
            diverse_added = 0
            proof_result_ids = {id(item) for item in pricing_results}
            for pricing_result in primal_pricing_results:
                if (
                    pricing_result.minimum_reduced_cost >= -self.pricing_tolerance
                    or pricing_result.reference_trajectory is None
                    or pricing_result.option_id is None
                ):
                    continue
                if pricing_result.option_id in trajectory_by_id:
                    raise RuntimeError("exact pricing returned an excluded trajectory")
                trajectory_by_id[pricing_result.option_id] = (
                    pricing_result.reference_trajectory
                )
                added += 1
                if id(pricing_result) not in proof_result_ids:
                    diverse_added += 1
            minimum_reduced_cost = (
                min(item.minimum_reduced_cost for item in pricing_results)
                if pricing_results
                else None
            )
            iteration = DddTrajectoryRootCgIteration(
                round_index=round_index,
                trajectory_count=len(reference_master.master_problem.options),
                incompatibility_pair_count=len(
                    reference_master.master_problem.incompatibility_pairs
                ),
                resource_window_count=len(
                    reference_master.master_problem.resource_window_rows
                ),
                added_resource_window_count=added_resource_window_count,
                restricted_lp_value=lp.objective_value,
                pricing_corrected_lower_bound=corrected,
                pricing_bound_correction=pricing_bound_correction,
                minimum_certified_reduced_cost_bound=(
                    minimum_certified_reduced_cost_bound
                ),
                proof_pricing_exclusion_count=proof_pricing_exclusion_count,
                global_lower_bound=global_lower_bound,
                restricted_integer_upper_bound=restricted_upper,
                global_upper_bound=global_upper_bound,
                minimum_reduced_cost=minimum_reduced_cost,
                exact_pricing_cabin_count=sum(item.exact for item in pricing_results),
                added_trajectory_count=added,
                diverse_added_trajectory_count=diverse_added,
                extra_pricing_call_count=extra_pricing_call_count,
                master_build_seconds=master_seconds,
                lp_seconds=lp_seconds,
                mip_seconds=mip.total_seconds,
                pricing_seconds=pricing_seconds,
                resource_separation_seconds=resource_separation_seconds,
                total_seconds=perf_counter() - round_started,
                pricing_diagnostics=pricing_diagnostics,
            )
            iterations.append(iteration)
            if progress_callback is not None:
                progress_callback(iteration)
            if checkpoint_callback is not None:
                checkpoint_callback(
                    DddTrajectoryRootCgState(
                        instance_fingerprint=instance_fingerprint,
                        objective=objective,
                        conflict_row_mode=self.conflict_row_mode,
                        completed_rounds=round_index,
                        certified_lower_bound=global_lower_bound,
                        best_upper_bound=global_upper_bound,
                        root_lp_certified=(
                            added == 0
                            and certificate.bound_status
                            is DddTrajectoryBoundStatus.FULL_ROOT_LP_CERTIFIED
                        ),
                        incumbent_option_ids=incumbent_option_ids,
                        incumbent_ride_values_by_id=dict(incumbent_ride_values_by_id),
                        iterations=tuple(iterations),
                        trajectories=tuple(
                            trajectory_by_id[key] for key in sorted(trajectory_by_id)
                        ),
                        resource_windows=resource_windows,
                        total_seconds=(
                            elapsed_offset_seconds + perf_counter() - started
                        ),
                    )
                )
            if not all(item.exact for item in pricing_results) and added == 0:
                return self._result(
                    status=DddTrajectoryRootCgStatus.UNKNOWN,
                    lower_bound=global_lower_bound,
                    upper_bound=global_upper_bound,
                    iterations=iterations,
                    trajectory_by_id=trajectory_by_id,
                    started=started,
                    elapsed_offset_seconds=elapsed_offset_seconds,
                    incumbent_option_ids=incumbent_option_ids,
                    incumbent_ride_values_by_id=incumbent_ride_values_by_id,
                    detail=(
                        "pricing was not certified and produced no improving "
                        "incumbent column"
                    ),
                )
            if added == 0:
                if (
                    certificate.bound_status
                    is not DddTrajectoryBoundStatus.FULL_ROOT_LP_CERTIFIED
                ):
                    raise RuntimeError("converged pricing did not certify the root LP")
                return self._result(
                    status=DddTrajectoryRootCgStatus.OPTIMAL_ROOT_LP,
                    lower_bound=global_lower_bound,
                    upper_bound=global_upper_bound,
                    iterations=iterations,
                    trajectory_by_id=trajectory_by_id,
                    started=started,
                    elapsed_offset_seconds=elapsed_offset_seconds,
                    incumbent_option_ids=incumbent_option_ids,
                    incumbent_ride_values_by_id=incumbent_ride_values_by_id,
                    detail=None,
                    root_lp_certified=True,
                )

        return self._result(
            status=DddTrajectoryRootCgStatus.ITERATION_LIMIT,
            lower_bound=global_lower_bound,
            upper_bound=global_upper_bound,
            iterations=iterations,
            trajectory_by_id=trajectory_by_id,
            started=started,
            elapsed_offset_seconds=elapsed_offset_seconds,
            incumbent_option_ids=incumbent_option_ids,
            incumbent_ride_values_by_id=incumbent_ride_values_by_id,
            detail="trajectory root column-generation iteration limit exhausted",
        )

    def _validate_resume_state(
        self,
        state: DddTrajectoryRootCgState,
        *,
        instance_fingerprint: str,
        objective: EanPassengerObjective,
    ) -> None:
        if state.instance_fingerprint != instance_fingerprint:
            raise ValueError("trajectory checkpoint belongs to a different instance")
        if state.objective is not objective:
            raise ValueError("trajectory checkpoint uses a different objective")
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
        if state.root_lp_certified and (
            not state.iterations or state.iterations[-1].added_trajectory_count != 0
        ):
            raise ValueError("trajectory checkpoint root certificate is inconsistent")
        if tuple(sorted(set(state.resource_windows))) != state.resource_windows:
            raise ValueError("trajectory checkpoint resource windows are inconsistent")
        for window in state.resource_windows:
            window.validate()

    def _validate(
        self,
        problem: DddNetworkTimeProblem,
        artifact: EanBuildArtifact,
    ) -> None:
        problem.validate()
        artifact.validate()
        if problem.movement_problem.scenario_id != artifact.scenario_id:
            raise ValueError("trajectory root problem and artifact differ")
        if artifact.fleet_mode is not EanFleetMode.FIXED_STARTS:
            raise ValueError("trajectory root supports fixed starts only")
        if any(
            item.waiting_mode is not StationWaitingMode.NO_WAITING
            for item in artifact.config.station_configs
        ):
            raise ValueError("trajectory root supports no-wait only")
        if self.max_iterations <= 0:
            raise ValueError("trajectory root iteration limit must be positive")
        if self.pricing_time_limit_seconds <= 0:
            raise ValueError("trajectory root pricing limit must be positive")
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
