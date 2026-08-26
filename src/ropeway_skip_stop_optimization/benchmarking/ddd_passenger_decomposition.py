from __future__ import annotations

from dataclasses import asdict, dataclass
from hashlib import sha256
import json
from pathlib import Path
from time import perf_counter
from typing import Callable

from ropeway_skip_stop_optimization.benchmarking.ddd_fixed_k_arc_flow import (
    DddFixedKArcFlowRunConfig,
    prepare_ddd_fixed_k_arc_flow_run,
)
from ropeway_skip_stop_optimization.optimization.ddd import (
    DddArcFlowProblemPreparer,
    DddFixedKMovementArcFlowConfig,
    DddFixedKMovementArcFlowOptimizer,
    DddFixedKMovementArcFlowProgress,
    DddFixedKMovementArcFlowStatus,
    DddMovementArcFlowObjectiveMode,
    DddFixedMovementPassengerRecourseOracle,
    DddPassengerLpIpComparison,
    DddPassengerRecourseConfig,
    DddReferenceSolution,
)


@dataclass(frozen=True, slots=True)
class DddPassengerDecompositionDiagnosticConfig:
    run: DddFixedKArcFlowRunConfig
    movement_time_limit_seconds: float = 120.0
    passenger_time_limit_seconds: float = 60.0
    solver_seeds: tuple[int, ...] = (0,)
    diversify_movements: bool = True

    def validate(self) -> None:
        self.run.validate()
        if self.movement_time_limit_seconds <= 0:
            raise ValueError("diagnostic Movement time limit must be positive")
        if self.passenger_time_limit_seconds <= 0:
            raise ValueError("diagnostic Passenger time limit must be positive")
        if not self.solver_seeds or min(self.solver_seeds) < 0:
            raise ValueError("diagnostic solver seeds must be nonnegative")
        if len(set(self.solver_seeds)) != len(self.solver_seeds):
            raise ValueError("diagnostic solver seeds must be unique")


@dataclass(frozen=True, slots=True)
class DddPassengerDecompositionSample:
    solver_seed: int
    movement_signature: str | None
    movement_status: str
    movement_solver_status: int
    movement_solution_count: int
    movement_node_count: float
    movement_seconds: float
    movement_variable_count: int
    movement_constraint_count: int
    resource_row_count: int
    duplicate_movement: bool
    passenger: DddPassengerLpIpComparison | None

    def to_payload(self) -> dict[str, object]:
        payload = asdict(self)
        if self.passenger is not None:
            payload["passenger"]["lp"]["assignment_domain"] = (
                self.passenger.lp.assignment_domain.value
            )
            payload["passenger"]["integer"]["assignment_domain"] = (
                self.passenger.integer.assignment_domain.value
            )
        return payload


@dataclass(frozen=True, slots=True)
class DddPassengerDecompositionDiagnosticResult:
    config: DddPassengerDecompositionDiagnosticConfig
    problem_fingerprint: str
    network_build_seconds: float
    unique_movement_count: int
    samples: tuple[DddPassengerDecompositionSample, ...]
    total_seconds: float

    def to_payload(self) -> dict[str, object]:
        return {
            "method": "complete_ddd_movement_passenger_lp_ip_diagnostic",
            "problem_fingerprint": self.problem_fingerprint,
            "example_id": self.config.run.example_id,
            "exact_active_cabin_count": self.config.run.cabin_count,
            "operating_mode": self.config.run.operating_mode.value,
            "start_policy": self.config.run.start_policy.value,
            "objective": self.config.run.objective.value,
            "movement_time_limit_seconds": (
                self.config.movement_time_limit_seconds
            ),
            "passenger_time_limit_seconds": (
                self.config.passenger_time_limit_seconds
            ),
            "solver_seeds": list(self.config.solver_seeds),
            "diversify_movements": self.config.diversify_movements,
            "network_build_seconds": self.network_build_seconds,
            "unique_movement_count": self.unique_movement_count,
            "sample_count": len(self.samples),
            "samples": [sample.to_payload() for sample in self.samples],
            "total_seconds": self.total_seconds,
        }


DddPassengerDiagnosticProgressHook = Callable[
    [int, DddFixedKMovementArcFlowProgress], None
]
DddPassengerDiagnosticSampleHook = Callable[
    [DddPassengerDecompositionSample], None
]


def run_ddd_passenger_decomposition_diagnostic(
    config: DddPassengerDecompositionDiagnosticConfig,
    *,
    progress_hook: DddPassengerDiagnosticProgressHook | None = None,
    sample_hook: DddPassengerDiagnosticSampleHook | None = None,
) -> DddPassengerDecompositionDiagnosticResult:
    config.validate()
    started = perf_counter()
    prepared_run = prepare_ddd_fixed_k_arc_flow_run(config.run)
    prepared = DddArcFlowProblemPreparer().build(prepared_run.problem)
    oracle = DddFixedMovementPassengerRecourseOracle(
        scenario=prepared_run.scenario,
        problem=prepared_run.problem,
        config=DddPassengerRecourseConfig(
            time_limit_seconds=config.passenger_time_limit_seconds,
            threads=config.run.solver_threads,
            output_flag=config.run.output_flag,
        ),
    )
    seen_signatures: set[str] = set()
    samples: list[DddPassengerDecompositionSample] = []
    for solver_seed in config.solver_seeds:
        movement_result = DddFixedKMovementArcFlowOptimizer(
            DddFixedKMovementArcFlowConfig(
                time_limit_seconds=config.movement_time_limit_seconds,
                threads=config.run.solver_threads,
                seed=solver_seed,
                mip_focus=1,
                output_flag=config.run.output_flag,
                objective_mode=(
                    DddMovementArcFlowObjectiveMode.DETERMINISTIC_DIVERSIFICATION
                    if config.diversify_movements
                    else DddMovementArcFlowObjectiveMode.FEASIBILITY
                ),
            )
        ).solve_prepared(
            prepared,
            seed_trajectories=(
                ()
                if config.diversify_movements
                else prepared_run.seed_trajectories
            ),
            progress_hook=(
                None
                if progress_hook is None
                else lambda progress, seed=solver_seed: progress_hook(seed, progress)
            ),
        )
        solution = movement_result.solution
        signature = None if solution is None else _movement_signature(solution)
        duplicate = signature is not None and signature in seen_signatures
        passenger = None
        if (
            solution is not None
            and movement_result.status is DddFixedKMovementArcFlowStatus.FEASIBLE
            and not duplicate
        ):
            seen_signatures.add(signature)
            passenger = oracle.compare_lp_and_integer(solution)
        sample = DddPassengerDecompositionSample(
            solver_seed=solver_seed,
            movement_signature=signature,
            movement_status=movement_result.status.value,
            movement_solver_status=movement_result.solver_status,
            movement_solution_count=movement_result.solution_count,
            movement_node_count=movement_result.node_count,
            movement_seconds=movement_result.total_seconds,
            movement_variable_count=movement_result.movement_variable_count,
            movement_constraint_count=movement_result.movement_constraint_count,
            resource_row_count=movement_result.resource_row_count,
            duplicate_movement=duplicate,
            passenger=passenger,
        )
        samples.append(sample)
        if sample_hook is not None:
            sample_hook(sample)
    return DddPassengerDecompositionDiagnosticResult(
        config=config,
        problem_fingerprint=prepared.problem.fingerprint,
        network_build_seconds=prepared.network_build_seconds,
        unique_movement_count=len(seen_signatures),
        samples=tuple(samples),
        total_seconds=perf_counter() - started,
    )


def write_ddd_passenger_decomposition_diagnostic(
    result: DddPassengerDecompositionDiagnosticResult,
    output_path: Path,
) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(result.to_payload(), indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _movement_signature(solution: DddReferenceSolution) -> str:
    payload = [
        {
            "cabin_id": trajectory.cabin_id,
            "visits": [
                (
                    visit.visit_index,
                    visit.route_option_id,
                    visit.switch_time_seconds,
                    visit.wait_seconds,
                )
                for visit in trajectory.visits
            ],
        }
        for trajectory in solution.trajectories
    ]
    return sha256(
        json.dumps(payload, separators=(",", ":"), sort_keys=True).encode()
    ).hexdigest()
