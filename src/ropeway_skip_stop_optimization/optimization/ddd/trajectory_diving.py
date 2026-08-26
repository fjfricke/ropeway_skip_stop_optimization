from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
import math
from time import perf_counter
from typing import Callable

from ropeway_skip_stop_optimization.optimization.ddd.network_time_space import (
    DddNetworkTimeProblem,
)
from ropeway_skip_stop_optimization.optimization.ddd.reference import (
    DddReferenceResourceOccurrence,
    DddReferenceTrajectory,
)
from ropeway_skip_stop_optimization.optimization.ddd.trajectory_branching import (
    DddTrajectoryBranchCandidateEvaluator,
    DddTrajectoryBranchDomain,
    DddTrajectoryBranchPredicate,
)
from ropeway_skip_stop_optimization.optimization.ddd.trajectory_exhaustive_reference import (
    build_ddd_trajectory_reference_master,
)
from ropeway_skip_stop_optimization.optimization.ddd.trajectory_passenger_lp import (
    DddTrajectoryFactorizedLpOptimizer,
    DddTrajectoryPassengerLpStatus,
)
from ropeway_skip_stop_optimization.optimization.ddd.trajectory_problem import (
    DddFixedTrajectoryStartDomain,
    DddTrajectoryProblem,
)
from ropeway_skip_stop_optimization.optimization.ddd.trajectory_root_column_generation import (
    DddTrajectoryExactRootColumnGenerationSolver,
    DddTrajectoryRootCgResult,
    ddd_trajectory_problem_instance_fingerprint,
)
from ropeway_skip_stop_optimization.optimization.ean.artifact import EanBuildArtifact
from ropeway_skip_stop_optimization.optimization.ean.builders.passenger_builder import (
    EanPassengerCandidateBuildResult,
)
from ropeway_skip_stop_optimization.optimization.ean.passenger_objective import (
    EanPassengerObjective,
)


class DddTrajectoryDiveStatus(StrEnum):
    NO_FRACTIONAL_BRANCH = "no_fractional_branch"
    COMPLETED = "completed"
    TIME_LIMIT = "time_limit"
    NODE_UNKNOWN = "node_unknown"
    INVALID_ROOT_CERTIFICATE = "invalid_root_certificate"


@dataclass(frozen=True)
class DddTrajectoryDiveConfig:
    maximum_depth: int = 12
    maximum_dives: int = 4
    total_time_limit_seconds: float = 300.0
    node_time_limit_seconds: float = 60.0
    node_maximum_iterations: int = 20
    pricing_time_limit_tiers_seconds: tuple[float, ...] = (5.0, 15.0)
    restricted_mip_time_limit_seconds: float = 15.0
    final_mip_time_limit_seconds: float = 30.0
    tolerance: float = 1e-7

    def validate(self) -> None:
        if (
            min(self.maximum_depth, self.maximum_dives, self.node_maximum_iterations)
            <= 0
        ):
            raise ValueError("trajectory dive count limits must be positive")
        if any(
            not math.isfinite(value) or value <= 0
            for value in (
                self.total_time_limit_seconds,
                self.node_time_limit_seconds,
                self.restricted_mip_time_limit_seconds,
                self.final_mip_time_limit_seconds,
            )
        ):
            raise ValueError("trajectory dive time limits must be positive")
        if not self.pricing_time_limit_tiers_seconds or any(
            not math.isfinite(value) or value <= 0
            for value in self.pricing_time_limit_tiers_seconds
        ):
            raise ValueError("trajectory dive pricing tiers are invalid")
        if not math.isfinite(self.tolerance) or self.tolerance < 0:
            raise ValueError("trajectory dive tolerance is invalid")


@dataclass(frozen=True)
class DddTrajectoryDiveStep:
    dive_index: int
    depth: int
    domain_fingerprint: str
    predicate: DddTrajectoryBranchPredicate
    required: bool
    true_mass: float
    false_mass: float
    node_lower_bound: float
    node_upper_bound: float | None
    node_root_lp_certified: bool
    node_trajectory_count: int
    node_seconds: float


@dataclass(frozen=True)
class DddTrajectoryDiveProgress:
    phase: str
    dive_index: int
    depth: int
    global_lower_bound: float
    best_upper_bound: float | None
    remaining_seconds: float


@dataclass(frozen=True)
class DddTrajectoryDiveResult:
    status: DddTrajectoryDiveStatus
    certified_root_lower_bound: float
    best_validated_upper_bound: float | None
    relative_gap: float | None
    steps: tuple[DddTrajectoryDiveStep, ...]
    trajectories: tuple[DddReferenceTrajectory, ...]
    incumbent_option_ids: tuple[str, ...]
    incumbent_ride_values_by_id: dict[str, float]
    instance_fingerprint: str
    total_seconds: float
    detail: str | None = None


@dataclass(frozen=True)
class DddTrajectoryDiveCoordinator:
    """Primal branch dives over exact node-CG solves.

    Siblings are deliberately not retained, so node lower bounds never replace
    the certified root lower bound in the returned global interval.
    """

    config: DddTrajectoryDiveConfig = DddTrajectoryDiveConfig()

    def solve(
        self,
        *,
        problem: DddNetworkTimeProblem,
        artifact: EanBuildArtifact,
        passenger_build: EanPassengerCandidateBuildResult,
        objective: EanPassengerObjective,
        root_result: DddTrajectoryRootCgResult,
        trajectory_problem: DddTrajectoryProblem | None = None,
        boundary_occurrences: tuple[DddReferenceResourceOccurrence, ...] = (),
        progress_callback: Callable[[DddTrajectoryDiveProgress], None] | None = None,
    ) -> DddTrajectoryDiveResult:
        self.config.validate()
        started = perf_counter()
        trajectory_problem = trajectory_problem or DddTrajectoryProblem(
            movement_core=problem.movement_problem.core,
            start_domain=DddFixedTrajectoryStartDomain(problem.movement_problem.starts),
        )
        trajectory_problem.validate()
        if not isinstance(
            trajectory_problem.start_domain,
            DddFixedTrajectoryStartDomain,
        ):
            raise ValueError("trajectory diving currently requires fixed starts")
        instance_fingerprint = ddd_trajectory_problem_instance_fingerprint(
            artifact,
            trajectory_problem,
            boundary_occurrences=boundary_occurrences,
        )
        if not root_result.certificate_valid:
            return self._result(
                status=DddTrajectoryDiveStatus.INVALID_ROOT_CERTIFICATE,
                root_result=root_result,
                trajectories=root_result.trajectories,
                incumbent_option_ids=root_result.incumbent_option_ids,
                incumbent_ride_values_by_id=root_result.incumbent_ride_values_by_id,
                instance_fingerprint=instance_fingerprint,
                steps=(),
                started=started,
                detail="root trajectory certificate is invalid",
            )
        if (
            root_result.instance_fingerprint
            and root_result.instance_fingerprint != instance_fingerprint
        ):
            raise ValueError("trajectory dive root result belongs to another instance")

        trajectory_by_identity = {
            self._trajectory_identity(item): item for item in root_result.trajectories
        }
        best_upper_bound = root_result.best_upper_bound
        best_option_ids = root_result.incumbent_option_ids
        best_ride_values = dict(root_result.incumbent_ride_values_by_id)
        steps: list[DddTrajectoryDiveStep] = []
        found_branch = False
        terminal_status = DddTrajectoryDiveStatus.COMPLETED
        terminal_detail: str | None = None

        for dive_index in range(self.config.maximum_dives):
            domain = DddTrajectoryBranchDomain()
            current_pool = tuple(trajectory_by_identity.values())
            for depth in range(self.config.maximum_depth):
                remaining = self.config.total_time_limit_seconds - (
                    perf_counter() - started
                )
                if remaining <= 1e-6:
                    terminal_status = DddTrajectoryDiveStatus.TIME_LIMIT
                    terminal_detail = "trajectory dive total time limit reached"
                    break
                candidate = self._best_candidate(
                    trajectory_problem=trajectory_problem,
                    artifact=artifact,
                    passenger_build=passenger_build,
                    objective=objective,
                    trajectories=current_pool,
                    instance_fingerprint=instance_fingerprint,
                    domain=domain,
                )
                remaining = self.config.total_time_limit_seconds - (
                    perf_counter() - started
                )
                if remaining <= 1e-6:
                    terminal_status = DddTrajectoryDiveStatus.TIME_LIMIT
                    terminal_detail = (
                        "trajectory dive total time limit reached while selecting "
                        "a branch candidate"
                    )
                    break
                if candidate is None:
                    break
                found_branch = True
                required = self._preferred_side(
                    dive_index=dive_index,
                    depth=depth,
                    preferred=candidate.preferred_required,
                )
                parent_domain = domain
                domain = parent_domain.child(candidate.predicate, required=required)
                initial_pool = domain.filter(tuple(trajectory_by_identity.values()))
                if {item.cabin_id for item in initial_pool} != set(
                    trajectory_problem.cabin_ids
                ):
                    required = not required
                    domain = parent_domain.child(
                        candidate.predicate,
                        required=required,
                    )
                    initial_pool = domain.filter(tuple(trajectory_by_identity.values()))
                if {item.cabin_id for item in initial_pool} != set(
                    trajectory_problem.cabin_ids
                ):
                    terminal_status = DddTrajectoryDiveStatus.NODE_UNKNOWN
                    terminal_detail = (
                        "both branch children lack an initial cabin column"
                    )
                    break

                node_limit = min(self.config.node_time_limit_seconds, remaining)
                node_solver = DddTrajectoryExactRootColumnGenerationSolver(
                    max_iterations=self.config.node_maximum_iterations,
                    total_time_limit_seconds=node_limit,
                    pricing_threads=1,
                    pricing_tolerance=self.config.tolerance,
                    certified_fixed_k_mode=True,
                    pricing_time_limit_tiers_seconds=(
                        self.config.pricing_time_limit_tiers_seconds
                    ),
                    restricted_mip_interval=1,
                    restricted_mip_time_limit_seconds=(
                        self.config.restricted_mip_time_limit_seconds
                    ),
                    final_mip_time_limit_seconds=(
                        self.config.final_mip_time_limit_seconds
                    ),
                    restricted_mip_focus=1,
                )
                self._progress(
                    progress_callback,
                    phase="node_started",
                    dive_index=dive_index,
                    depth=depth,
                    lower_bound=root_result.certified_lower_bound,
                    upper_bound=best_upper_bound,
                    remaining=remaining,
                )
                node_started = perf_counter()
                node = node_solver.solve(
                    problem=problem,
                    trajectory_problem=trajectory_problem,
                    artifact=artifact,
                    passenger_build=passenger_build,
                    objective=objective,
                    initial_trajectories=initial_pool,
                    branch_domain=domain,
                    boundary_occurrences=boundary_occurrences,
                )
                for trajectory in node.trajectories:
                    trajectory_by_identity.setdefault(
                        self._trajectory_identity(trajectory),
                        trajectory,
                    )
                current_pool = node.trajectories
                if {item.cabin_id for item in current_pool} != set(
                    trajectory_problem.cabin_ids
                ):
                    terminal_status = DddTrajectoryDiveStatus.NODE_UNKNOWN
                    terminal_detail = (
                        "trajectory dive node returned no complete cabin-column pool"
                    )
                if node.best_upper_bound is not None and (
                    best_upper_bound is None
                    or node.best_upper_bound < best_upper_bound - self.config.tolerance
                ):
                    best_upper_bound = node.best_upper_bound
                    best_option_ids = node.incumbent_option_ids
                    best_ride_values = dict(node.incumbent_ride_values_by_id)
                steps.append(
                    DddTrajectoryDiveStep(
                        dive_index=dive_index,
                        depth=depth,
                        domain_fingerprint=domain.fingerprint,
                        predicate=candidate.predicate,
                        required=required,
                        true_mass=candidate.true_mass,
                        false_mass=candidate.false_mass,
                        node_lower_bound=node.certified_lower_bound,
                        node_upper_bound=node.best_upper_bound,
                        node_root_lp_certified=node.root_lp_certified,
                        node_trajectory_count=len(node.trajectories),
                        node_seconds=perf_counter() - node_started,
                    )
                )
                self._progress(
                    progress_callback,
                    phase="node_completed",
                    dive_index=dive_index,
                    depth=depth,
                    lower_bound=root_result.certified_lower_bound,
                    upper_bound=best_upper_bound,
                    remaining=max(
                        0.0,
                        self.config.total_time_limit_seconds
                        - (perf_counter() - started),
                    ),
                )
                if not node.certificate_valid:
                    terminal_status = DddTrajectoryDiveStatus.NODE_UNKNOWN
                    terminal_detail = "trajectory dive node certificate is invalid"
                    break
                if terminal_status is DddTrajectoryDiveStatus.NODE_UNKNOWN:
                    break
            if terminal_status is not DddTrajectoryDiveStatus.COMPLETED:
                break

        if not found_branch and terminal_status is DddTrajectoryDiveStatus.COMPLETED:
            terminal_status = DddTrajectoryDiveStatus.NO_FRACTIONAL_BRANCH
        return self._result(
            status=terminal_status,
            root_result=root_result,
            best_upper_bound=best_upper_bound,
            trajectories=tuple(trajectory_by_identity.values()),
            incumbent_option_ids=best_option_ids,
            incumbent_ride_values_by_id=best_ride_values,
            instance_fingerprint=instance_fingerprint,
            steps=tuple(steps),
            started=started,
            detail=terminal_detail,
        )

    def _best_candidate(
        self,
        *,
        trajectory_problem: DddTrajectoryProblem,
        artifact: EanBuildArtifact,
        passenger_build: EanPassengerCandidateBuildResult,
        objective: EanPassengerObjective,
        trajectories: tuple[DddReferenceTrajectory, ...],
        instance_fingerprint: str,
        domain: DddTrajectoryBranchDomain,
    ):
        built = build_ddd_trajectory_reference_master(
            trajectory_problem=trajectory_problem,
            artifact=artifact,
            passenger_build=passenger_build,
            objective=objective,
            reference_trajectories=trajectories,
            instance_fingerprint=instance_fingerprint,
        )
        lp = DddTrajectoryFactorizedLpOptimizer().solve(built.master_problem)
        if lp.status is not DddTrajectoryPassengerLpStatus.OPTIMAL:
            return None
        candidates = DddTrajectoryBranchCandidateEvaluator(
            tolerance=self.config.tolerance,
        ).evaluate(
            trajectory_by_option_id=built.reference_trajectory_by_option_id,
            option_values_by_id=lp.option_values_by_id,
            domain=domain,
        )
        return candidates[0] if candidates else None

    @staticmethod
    def _preferred_side(*, dive_index: int, depth: int, preferred: bool) -> bool:
        if dive_index == 0:
            return preferred
        return preferred if (dive_index + depth) % 2 == 0 else not preferred

    @staticmethod
    def _trajectory_identity(trajectory: DddReferenceTrajectory) -> tuple[object, ...]:
        return (
            trajectory.cabin_id,
            trajectory.timed_support_signature,
            trajectory.initial_state,
            trajectory.reservoir_state,
        )

    @staticmethod
    def _progress(
        callback: Callable[[DddTrajectoryDiveProgress], None] | None,
        *,
        phase: str,
        dive_index: int,
        depth: int,
        lower_bound: float,
        upper_bound: float | None,
        remaining: float,
    ) -> None:
        if callback is not None:
            callback(
                DddTrajectoryDiveProgress(
                    phase=phase,
                    dive_index=dive_index,
                    depth=depth,
                    global_lower_bound=lower_bound,
                    best_upper_bound=upper_bound,
                    remaining_seconds=remaining,
                )
            )

    @staticmethod
    def _result(
        *,
        status: DddTrajectoryDiveStatus,
        root_result: DddTrajectoryRootCgResult,
        trajectories: tuple[DddReferenceTrajectory, ...],
        incumbent_option_ids: tuple[str, ...],
        incumbent_ride_values_by_id: dict[str, float],
        instance_fingerprint: str,
        steps: tuple[DddTrajectoryDiveStep, ...],
        started: float,
        detail: str | None,
        best_upper_bound: float | None = None,
    ) -> DddTrajectoryDiveResult:
        upper = (
            root_result.best_upper_bound
            if best_upper_bound is None
            else best_upper_bound
        )
        lower = root_result.certified_lower_bound
        gap = (
            max(0.0, upper - lower) / abs(upper)
            if upper is not None and abs(upper) > 1e-9
            else None
        )
        return DddTrajectoryDiveResult(
            status=status,
            certified_root_lower_bound=lower,
            best_validated_upper_bound=upper,
            relative_gap=gap,
            steps=steps,
            trajectories=trajectories,
            incumbent_option_ids=incumbent_option_ids,
            incumbent_ride_values_by_id=dict(incumbent_ride_values_by_id),
            instance_fingerprint=instance_fingerprint,
            total_seconds=perf_counter() - started,
            detail=detail,
        )
