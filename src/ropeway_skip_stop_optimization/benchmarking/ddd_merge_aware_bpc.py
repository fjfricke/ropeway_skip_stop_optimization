from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
import json
from pathlib import Path
from time import perf_counter
from typing import Callable

from ropeway_skip_stop_optimization.benchmarking.ddd_fixed_k_arc_flow import (
    DddFixedKArcFlowRunConfig,
    prepare_ddd_fixed_k_arc_flow_run,
)
from ropeway_skip_stop_optimization.benchmarking.ddd_scaling import (
    build_initial_ddd_network_problem,
)
from ropeway_skip_stop_optimization.exports.json_codec import to_jsonable
from ropeway_skip_stop_optimization.optimization.ddd.arc_flow_network import (
    DddArcFlowBuildTimeLimitError,
)
from ropeway_skip_stop_optimization.optimization.ddd import (
    DddArcFlowProblemPreparer,
    DddArcFlowRelaxationConfig,
    DddArcFlowRelaxationMethod,
    DddArcFlowRelaxationOptimizer,
    DddFixedKOperatingMode,
    DddFixedKStartPolicy,
    DddTrajectoryCompatibleBatchMode,
    DddTrajectoryConflictRowMode,
    DddTrajectoryDiversityMode,
    DddTrajectoryExactRootColumnGenerationSolver,
    DddTrajectoryRootCgIteration,
)
from ropeway_skip_stop_optimization.optimization.ean import EanPassengerObjective


class DddMergeAwareRootVariant(StrEnum):
    PAIR_ONLY = "pair_only"
    UNIVERSAL_RESOURCE_WINDOWS = "universal_resource_windows"
    MERGE_AWARE_WINDOWS = "merge_aware_windows"
    MERGE_AWARE_COMPATIBLE_BATCH = "merge_aware_compatible_batch"
    MERGE_TIME_CORRIDOR = "merge_time_corridor"


@dataclass(frozen=True, slots=True)
class DddMergeAwareRootGateConfig:
    example_id: str
    cabin_count: int
    output_path: Path
    variants: tuple[DddMergeAwareRootVariant, ...] = (
        DddMergeAwareRootVariant.PAIR_ONLY,
        DddMergeAwareRootVariant.UNIVERSAL_RESOURCE_WINDOWS,
        DddMergeAwareRootVariant.MERGE_AWARE_WINDOWS,
        DddMergeAwareRootVariant.MERGE_AWARE_COMPATIBLE_BATCH,
        DddMergeAwareRootVariant.MERGE_TIME_CORRIDOR,
    )
    objective: EanPassengerObjective = EanPassengerObjective.JOURNEY_TIME
    start_policy: DddFixedKStartPolicy = DddFixedKStartPolicy.BALANCED_REFERENCE
    root_time_limit_seconds: float = 900.0
    reference_lp_time_limit_seconds: float = 900.0
    start_layout_time_limit_seconds: float = 600.0
    maximum_iterations: int = 60
    pricing_tiers_seconds: tuple[float, ...] = (5.0, 15.0, 60.0)
    compatible_batch_time_limit_seconds: float = 15.0
    merge_corridor_time_limit_seconds: float = 30.0
    merge_corridor_interval: int = 3
    merge_corridor_window_widths_seconds: tuple[float, ...] = (
        120.0,
        240.0,
        480.0,
    )
    restricted_mip_time_limit_seconds: float = 30.0
    final_mip_time_limit_seconds: float = 300.0
    threads: int | None = None
    solver_output: bool = False

    def validate(self) -> None:
        if not self.example_id or self.cabin_count <= 0:
            raise ValueError("merge-aware root gate needs an example and positive K")
        if not self.variants or len(set(self.variants)) != len(self.variants):
            raise ValueError("merge-aware root variants must be unique and nonempty")
        if min(
            self.root_time_limit_seconds,
            self.reference_lp_time_limit_seconds,
            self.start_layout_time_limit_seconds,
            self.compatible_batch_time_limit_seconds,
            self.merge_corridor_time_limit_seconds,
            self.restricted_mip_time_limit_seconds,
        ) <= 0:
            raise ValueError("merge-aware root gate budgets must be positive")
        if self.final_mip_time_limit_seconds < 0 or self.maximum_iterations <= 0:
            raise ValueError("merge-aware root gate finishing controls are invalid")
        if self.merge_corridor_interval <= 0:
            raise ValueError("merge corridor interval must be positive")
        if (
            tuple(sorted(set(self.merge_corridor_window_widths_seconds)))
            != self.merge_corridor_window_widths_seconds
            or any(value <= 0 for value in self.merge_corridor_window_widths_seconds)
        ):
            raise ValueError("merge corridor widths must increase and be positive")
        if tuple(sorted(set(self.pricing_tiers_seconds))) != (
            self.pricing_tiers_seconds
        ) or any(value <= 0 for value in self.pricing_tiers_seconds):
            raise ValueError("merge-aware pricing tiers must increase and be positive")
        if self.threads is not None and self.threads <= 0:
            raise ValueError("merge-aware root gate threads must be positive")


@dataclass(frozen=True, slots=True)
class DddMergeAwareRootGateResult:
    problem_fingerprint: str
    reference_lp: dict[str, object]
    variants: tuple[dict[str, object], ...]
    setup_seconds: float
    total_seconds: float


ProgressHook = Callable[[dict[str, object]], None]


@dataclass(slots=True)
class DddMergeAwareRootGateRunner:
    def run(
        self,
        config: DddMergeAwareRootGateConfig,
        *,
        progress_hook: ProgressHook | None = None,
    ) -> DddMergeAwareRootGateResult:
        config.validate()
        started = perf_counter()
        prepared = prepare_ddd_fixed_k_arc_flow_run(
            DddFixedKArcFlowRunConfig(
                example_id=config.example_id,
                cabin_count=config.cabin_count,
                operating_mode=DddFixedKOperatingMode.SKIP_STOP,
                objective=config.objective,
                start_policy=config.start_policy,
                start_layout_time_limit_seconds=(
                    config.start_layout_time_limit_seconds
                ),
                total_time_limit_seconds=max(
                    config.root_time_limit_seconds,
                    config.start_layout_time_limit_seconds,
                ),
                solver_threads=config.threads,
            )
        )
        setup_seconds = perf_counter() - started
        fixed_k_problem = prepared.problem
        trajectory_problem = fixed_k_problem.resolved_trajectory_problem
        network_problem = build_initial_ddd_network_problem(
            trajectory_problem.structural_movement_problem
        )
        if progress_hook is not None:
            progress_hook(
                {
                    "phase": "reference_lp_build",
                    "variant": "complete_arc_flow_lp",
                    "elapsed_seconds": perf_counter() - started,
                }
            )
        reference_started = perf_counter()
        try:
            arc_flow_prepared = DddArcFlowProblemPreparer().build(
                fixed_k_problem,
                phase_hook=(
                    None
                    if progress_hook is None
                    else lambda phase: progress_hook(
                        {
                            "phase": f"reference_lp_{phase}",
                            "variant": "complete_arc_flow_lp",
                            "elapsed_seconds": perf_counter() - reference_started,
                            "remaining_seconds": max(
                                0.0,
                                config.reference_lp_time_limit_seconds
                                - (perf_counter() - reference_started),
                            ),
                        }
                    )
                ),
                deadline_monotonic=(
                    reference_started + config.reference_lp_time_limit_seconds
                ),
            )
            remaining_reference_seconds = max(
                0.001,
                config.reference_lp_time_limit_seconds
                - (perf_counter() - reference_started),
            )
            reference = to_jsonable(
                DddArcFlowRelaxationOptimizer(
                    DddArcFlowRelaxationConfig(
                        time_limit_seconds=remaining_reference_seconds,
                        method=DddArcFlowRelaxationMethod.BARRIER_NO_CROSSOVER,
                        threads=config.threads,
                        output_flag=config.solver_output,
                    )
                ).solve(
                    arc_flow_prepared,
                    progress_hook=(
                        None
                        if progress_hook is None
                        else lambda event: progress_hook(
                            {
                                "phase": f"reference_lp_{event.phase}",
                                "variant": "complete_arc_flow_lp",
                                "elapsed_seconds": (
                                    perf_counter() - reference_started
                                ),
                                "remaining_seconds": event.remaining_seconds,
                                "local_primal_objective": (
                                    event.local_primal_objective
                                ),
                                "local_dual_objective": event.local_dual_objective,
                                "movement_variable_count": (
                                    event.movement_variable_count
                                ),
                                "passenger_variable_count": (
                                    event.passenger_variable_count
                                ),
                                "linear_constraint_count": (
                                    event.linear_constraint_count
                                ),
                            }
                        )
                    ),
                )
            )
        except DddArcFlowBuildTimeLimitError as error:
            reference = {
                "status": "build_time_limit",
                "problem_fingerprint": fixed_k_problem.fingerprint,
                "certified_lower_bound": fixed_k_problem.objective_floor,
                "lp_primal_objective": None,
                "total_seconds": perf_counter() - reference_started,
                "detail": str(error),
            }
        variant_payloads = []
        per_variant_solve_budget = max(
            0.001,
            config.root_time_limit_seconds - setup_seconds,
        )
        _write_gate_payload(
            config=config,
            problem_fingerprint=fixed_k_problem.fingerprint,
            reference_lp=reference,
            variants=variant_payloads,
            setup_seconds=setup_seconds,
            total_seconds=perf_counter() - started,
            status="running",
        )
        for variant in config.variants:
            variant_started = perf_counter()

            def publish(iteration: DddTrajectoryRootCgIteration) -> None:
                if progress_hook is None:
                    return
                progress_hook(
                    {
                        "phase": "root_cg",
                        "variant": variant.value,
                        "round": iteration.round_index,
                        "elapsed_seconds": perf_counter() - variant_started,
                        "certified_lower_bound": iteration.global_lower_bound,
                        "restricted_lp_value": iteration.restricted_lp_value,
                        "validated_upper_bound": iteration.global_upper_bound,
                        "trajectory_count": iteration.trajectory_count,
                        "resource_window_count": iteration.resource_window_count,
                        "compatible_batch_candidate_count": (
                            iteration.compatible_batch_candidate_count
                        ),
                        "compatible_batch_selected_count": (
                            iteration.compatible_batch_selected_count
                        ),
                        "merge_corridor_status": (
                            iteration.merge_corridor_primal_status
                        ),
                        "merge_corridor_released_cabin_count": (
                            iteration.merge_corridor_released_cabin_count
                        ),
                        "merge_corridor_released_decision_count": (
                            iteration.merge_corridor_released_decision_count
                        ),
                        "merge_corridor_candidate_count": (
                            iteration.merge_corridor_primal_candidate_count
                        ),
                        "remaining_seconds": iteration.remaining_budget_seconds,
                    }
                )

            result = DddTrajectoryExactRootColumnGenerationSolver(
                max_iterations=config.maximum_iterations,
                total_time_limit_seconds=per_variant_solve_budget,
                pricing_time_limit_seconds=config.pricing_tiers_seconds[0],
                pricing_time_limit_tiers_seconds=config.pricing_tiers_seconds,
                pricing_threads=1,
                conflict_row_mode=_conflict_row_mode(variant),
                max_resource_window_rounds=100,
                columns_per_cabin_per_round=(
                    3
                    if variant
                    is DddMergeAwareRootVariant.MERGE_AWARE_COMPATIBLE_BATCH
                    else 1
                ),
                diversity_mode=(
                    DddTrajectoryDiversityMode.STOP_SKIP
                    if variant
                    is DddMergeAwareRootVariant.MERGE_AWARE_COMPATIBLE_BATCH
                    else DddTrajectoryDiversityMode.OFF
                ),
                compatible_batch_mode=(
                    DddTrajectoryCompatibleBatchMode.MAXIMUM_COMPATIBLE
                    if variant
                    is DddMergeAwareRootVariant.MERGE_AWARE_COMPATIBLE_BATCH
                    else DddTrajectoryCompatibleBatchMode.OFF
                ),
                compatible_batch_time_limit_seconds=(
                    config.compatible_batch_time_limit_seconds
                ),
                merge_corridor_primal_time_limit_seconds=(
                    config.merge_corridor_time_limit_seconds
                    if variant is DddMergeAwareRootVariant.MERGE_TIME_CORRIDOR
                    else 0.0
                ),
                merge_corridor_primal_interval=config.merge_corridor_interval,
                merge_corridor_window_widths_seconds=(
                    config.merge_corridor_window_widths_seconds
                ),
                restricted_mip_interval=3,
                restricted_mip_time_limit_seconds=(
                    config.restricted_mip_time_limit_seconds
                ),
                final_mip_time_limit_seconds=config.final_mip_time_limit_seconds,
                output_flag=config.solver_output,
                certified_fixed_k_mode=True,
            ).solve(
                problem=network_problem,
                trajectory_problem=trajectory_problem,
                artifact=fixed_k_problem.artifact,
                passenger_build=fixed_k_problem.passenger_build,
                objective=config.objective,
                initial_trajectories=(prepared.seed_trajectories or None),
                progress_callback=publish,
                boundary_occurrences=(
                    fixed_k_problem.boundary_context.resource_occurrences
                ),
            )
            variant_payloads.append(
                {
                    "variant": variant.value,
                    "status": result.status.value,
                    "certified_lower_bound": result.certified_lower_bound,
                    "validated_upper_bound": result.best_upper_bound,
                    "relative_gap": result.relative_gap,
                    "root_lp_certified": result.root_lp_certified,
                    "certificate_valid": result.certificate_valid,
                    "trajectory_count": len(result.trajectories),
                    "total_seconds": result.total_seconds,
                    "iterations": to_jsonable(result.iterations),
                    "detail": result.detail,
                }
            )
            _write_gate_payload(
                config=config,
                problem_fingerprint=fixed_k_problem.fingerprint,
                reference_lp=reference,
                variants=variant_payloads,
                setup_seconds=setup_seconds,
                total_seconds=perf_counter() - started,
                status="running",
            )
        gate = DddMergeAwareRootGateResult(
            problem_fingerprint=fixed_k_problem.fingerprint,
            reference_lp=reference,
            variants=tuple(variant_payloads),
            setup_seconds=setup_seconds,
            total_seconds=perf_counter() - started,
        )
        _write_gate_payload(
            config=config,
            problem_fingerprint=gate.problem_fingerprint,
            reference_lp=gate.reference_lp,
            variants=list(gate.variants),
            setup_seconds=gate.setup_seconds,
            total_seconds=gate.total_seconds,
            status="complete",
        )
        return gate


def _conflict_row_mode(
    variant: DddMergeAwareRootVariant,
) -> DddTrajectoryConflictRowMode:
    if variant is DddMergeAwareRootVariant.PAIR_ONLY:
        return DddTrajectoryConflictRowMode.PAIR_ONLY
    if variant is DddMergeAwareRootVariant.UNIVERSAL_RESOURCE_WINDOWS:
        return DddTrajectoryConflictRowMode.RESOURCE_WINDOWS_WITH_PAIR_FALLBACK
    return DddTrajectoryConflictRowMode.MERGE_AWARE_RESOURCE_WINDOWS


def _write_gate_payload(
    *,
    config: DddMergeAwareRootGateConfig,
    problem_fingerprint: str,
    reference_lp: dict[str, object],
    variants: list[dict[str, object]],
    setup_seconds: float,
    total_seconds: float,
    status: str,
) -> None:
    config.output_path.parent.mkdir(parents=True, exist_ok=True)
    config.output_path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "status": status,
                "config": to_jsonable(config),
                "result": {
                    "problem_fingerprint": problem_fingerprint,
                    "reference_lp": reference_lp,
                    "variants": variants,
                    "setup_seconds": setup_seconds,
                    "total_seconds": total_seconds,
                },
            },
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
