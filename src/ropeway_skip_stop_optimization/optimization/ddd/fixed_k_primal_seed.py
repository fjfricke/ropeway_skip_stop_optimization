from __future__ import annotations

from dataclasses import dataclass
import math
from pathlib import Path

from ropeway_skip_stop_optimization.models import Scenario
from ropeway_skip_stop_optimization.optimization.ddd.fixed_k import (
    DddFixedKTrajectoryProblem,
)
from ropeway_skip_stop_optimization.optimization.ddd.primal_evaluation import (
    DddEanPassengerPrimalEvaluator,
    DddPrimalEvaluationStatus,
)
from ropeway_skip_stop_optimization.optimization.ddd.reference import (
    DddReferenceSolution,
    DddReferenceTrajectory,
    validate_ddd_reference_solution,
)
from ropeway_skip_stop_optimization.optimization.ddd.network_time_space import (
    DddNetworkTimeProblem,
)
from ropeway_skip_stop_optimization.optimization.ddd.trajectory_column_generation import (
    DddTrajectoryWaitingDomain,
)
from ropeway_skip_stop_optimization.optimization.ddd.trajectory_problem import (
    DddTrajectoryFleetMode,
)
from ropeway_skip_stop_optimization.optimization.ddd.trajectory_root_checkpoint import (
    read_ddd_trajectory_root_cg_checkpoint,
)
from ropeway_skip_stop_optimization.optimization.ddd.trajectory_root_column_generation import (
    ddd_trajectory_problem_instance_fingerprint,
)
from ropeway_skip_stop_optimization.optimization.ddd.trajectory_slot import (
    ddd_trajectory_column,
)


@dataclass(frozen=True, slots=True)
class DddFixedKPrimalSeed:
    """One complete, independently validated fixed-K primal solution."""

    problem_fingerprint: str
    solution: DddReferenceSolution
    ride_counts_by_candidate_id: dict[str, float]
    objective_value: float
    provenance: str

    def validate(self, problem: DddFixedKTrajectoryProblem) -> None:
        problem.validate()
        if self.problem_fingerprint != problem.fingerprint:
            raise ValueError("Fixed-K primal seed belongs to a different problem")
        if not self.provenance:
            raise ValueError("Fixed-K primal seed provenance must be nonempty")
        if not math.isfinite(self.objective_value):
            raise ValueError("Fixed-K primal seed objective must be finite")
        movement = problem.resolved_trajectory_problem.structural_movement_problem
        validate_ddd_reference_solution(
            movement,
            self.solution,
            waiting_policy=problem.resolved_trajectory_problem.waiting_policy,
        )
        expected_cabins = problem.resolved_trajectory_problem.cabin_ids
        actual_cabins = tuple(
            trajectory.cabin_id for trajectory in self.solution.trajectories
        )
        if actual_cabins != expected_cabins:
            raise ValueError("Fixed-K primal seed cabin set is not canonical")
        known_candidates = {
            candidate.id for candidate in problem.passenger_build.ride_candidates
        }
        if set(self.ride_counts_by_candidate_id) - known_candidates:
            raise ValueError("Fixed-K primal seed references an unknown ride candidate")
        if any(
            not math.isfinite(value)
            or value <= 0
            or not math.isclose(value, round(value), abs_tol=1e-6)
            for value in self.ride_counts_by_candidate_id.values()
        ):
            raise ValueError("Fixed-K primal seed ride counts must be positive integers")


@dataclass(frozen=True, slots=True)
class DddFixedKPrimalSeedFactory:
    scenario: Scenario
    problem: DddFixedKTrajectoryProblem
    network_problem: DddNetworkTimeProblem
    passenger_time_limit_seconds: float = 60.0
    threads: int | None = 1

    def build(
        self,
        trajectories: tuple[DddReferenceTrajectory, ...],
        *,
        provenance: str,
    ) -> DddFixedKPrimalSeed:
        if self.passenger_time_limit_seconds <= 0:
            raise ValueError("Fixed-K seed Passenger time limit must be positive")
        solution = DddReferenceSolution(
            tuple(sorted(trajectories, key=lambda item: item.cabin_id))
        )
        movement = self.problem.resolved_trajectory_problem.structural_movement_problem
        validate_ddd_reference_solution(
            movement,
            solution,
            waiting_policy=self.problem.resolved_trajectory_problem.waiting_policy,
        )
        evaluation = DddEanPassengerPrimalEvaluator(
            scenario=self.scenario,
            artifact=self.problem.artifact,
            objective=self.problem.objective,
            time_limit_seconds=self.passenger_time_limit_seconds,
            mip_gap=0.0,
            threads=self.threads,
            waiting_policy=self.problem.resolved_trajectory_problem.waiting_policy,
        ).evaluate(self.network_problem, solution)
        if (
            evaluation.status is not DddPrimalEvaluationStatus.FEASIBLE
            or evaluation.objective_value is None
            or evaluation.passenger_plan is None
        ):
            raise RuntimeError(
                "Fixed-K primal seed Passenger evaluation found no feasible plan"
            )
        candidate_id_by_key = {
            (
                candidate.demand_group_id,
                candidate.cabin_id,
                candidate.board_visit_index,
                candidate.alight_visit_index,
            ): candidate.id
            for candidate in self.problem.passenger_build.ride_candidates
        }
        ride_counts: dict[str, float] = {}
        for ride in evaluation.passenger_plan.served_rides:
            key = (
                ride.demand_group_id,
                ride.cabin_id,
                ride.board_visit_index,
                ride.alight_visit_index,
            )
            try:
                candidate_id = candidate_id_by_key[key]
            except KeyError as error:
                raise RuntimeError(
                    "Fixed-K seed Passenger plan references no canonical candidate"
                ) from error
            ride_counts[candidate_id] = ride_counts.get(candidate_id, 0.0) + ride.count
        result = DddFixedKPrimalSeed(
            problem_fingerprint=self.problem.fingerprint,
            solution=solution,
            ride_counts_by_candidate_id=ride_counts,
            objective_value=evaluation.objective_value,
            provenance=provenance,
        )
        result.validate(self.problem)
        return result


def load_ddd_fixed_k_root_cg_seed_trajectories(
    path: Path,
    *,
    problem: DddFixedKTrajectoryProblem,
) -> tuple[tuple[DddReferenceTrajectory, ...], float | None]:
    """Recover the selected complete incumbent from a compatible Root-CG state."""

    problem.validate()
    state = read_ddd_trajectory_root_cg_checkpoint(path)
    resolved = problem.resolved_trajectory_problem
    expected_instance_fingerprint = ddd_trajectory_problem_instance_fingerprint(
        problem.artifact,
        resolved,
        boundary_occurrences=problem.boundary_context.resource_occurrences,
    )
    if state.instance_fingerprint != expected_instance_fingerprint:
        raise ValueError("Root-CG checkpoint differs from the Fixed-K trajectory domain")
    if state.objective is not problem.objective:
        raise ValueError("Root-CG checkpoint uses another Passenger objective")
    if state.fleet_mode is not DddTrajectoryFleetMode.FIXED_STARTS:
        raise ValueError("Root-CG primal seed must use fixed starts")
    if state.waiting_policy.domain is not DddTrajectoryWaitingDomain.NO_WAIT:
        raise ValueError("Root-CG primal seed must use the No-Wait domain")
    if state.best_upper_bound is None or not state.incumbent_option_ids:
        raise ValueError("Root-CG checkpoint contains no complete incumbent")
    trajectory_by_id = {
        ddd_trajectory_column(
            trajectory,
            instance_fingerprint=state.instance_fingerprint,
        ).id: trajectory
        for trajectory in state.trajectories
    }
    missing = set(state.incumbent_option_ids) - set(trajectory_by_id)
    if missing:
        raise ValueError("Root-CG incumbent references a missing trajectory")
    selected = tuple(
        sorted(
            (trajectory_by_id[item] for item in state.incumbent_option_ids),
            key=lambda item: item.cabin_id,
        )
    )
    validate_ddd_reference_solution(
        resolved.structural_movement_problem,
        DddReferenceSolution(selected),
        waiting_policy=resolved.waiting_policy,
    )
    if tuple(item.cabin_id for item in selected) != resolved.cabin_ids:
        raise ValueError("Root-CG incumbent does not contain exactly one path per cabin")
    return selected, state.best_upper_bound
