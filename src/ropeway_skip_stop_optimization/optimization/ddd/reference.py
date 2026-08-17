from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from itertools import combinations

from ropeway_skip_stop_optimization.optimization.ddd.models import (
    DddFixedStart,
    DddMovementProblem,
    DddResource,
    DddResourceUsage,
    DddRouteDecision,
    DddRouteOption,
)
from ropeway_skip_stop_optimization.optimization.ddd.time_ticks import (
    ddd_quantize_time_seconds,
    ddd_seconds_to_tick,
    ddd_tick_to_seconds,
)


class DddReferenceHorizonCoverageError(ValueError):
    pass


class DddReferenceResourceConflictError(ValueError):
    pass


class DddReferenceStatus(StrEnum):
    FEASIBLE = "feasible"
    INFEASIBLE = "infeasible"


class DddReferenceSearchLimitError(RuntimeError):
    pass


@dataclass(frozen=True)
class DddReferenceResourceOccurrence:
    resource_id: str
    cabin_id: int
    visit_index: int
    leader_clear_time_seconds: float
    follower_enter_time_seconds: float

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "leader_clear_time_seconds",
            ddd_quantize_time_seconds(self.leader_clear_time_seconds),
        )
        object.__setattr__(
            self,
            "follower_enter_time_seconds",
            ddd_quantize_time_seconds(self.follower_enter_time_seconds),
        )


@dataclass(frozen=True)
class DddReferenceVisit:
    cabin_id: int
    visit_index: int
    state_id: str
    route_option_id: str
    decision: DddRouteDecision
    switch_time_seconds: float
    next_switch_time_seconds: float
    resource_occurrences: tuple[DddReferenceResourceOccurrence, ...]

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "switch_time_seconds",
            ddd_quantize_time_seconds(self.switch_time_seconds),
        )
        object.__setattr__(
            self,
            "next_switch_time_seconds",
            ddd_quantize_time_seconds(self.next_switch_time_seconds),
        )


@dataclass(frozen=True)
class DddReferenceTrajectory:
    cabin_id: int
    visits: tuple[DddReferenceVisit, ...]

    @property
    def support_signature(self) -> tuple[str, ...]:
        return tuple(visit.route_option_id for visit in self.visits)

    @property
    def resource_occurrences(self) -> tuple[DddReferenceResourceOccurrence, ...]:
        return tuple(
            occurrence
            for visit in self.visits
            for occurrence in visit.resource_occurrences
        )


@dataclass(frozen=True)
class DddReferenceSolution:
    trajectories: tuple[DddReferenceTrajectory, ...]

    @property
    def support_fingerprint(self) -> str:
        return "||".join(
            f"{trajectory.cabin_id}:" + ",".join(trajectory.support_signature)
            for trajectory in self.trajectories
        )


@dataclass(frozen=True)
class DddReferenceConflict:
    resource_id: str
    first_cabin_id: int
    first_visit_index: int
    second_cabin_id: int
    second_visit_index: int
    violation_seconds: float


@dataclass(frozen=True)
class DddReferenceSearchMetrics:
    generated_trajectory_count: int
    generation_branch_count: int
    self_conflict_pruned_count: int
    combination_attempt_count: int
    cross_conflict_pruned_count: int
    symmetry_pruned_count: int
    feasible_solution_count: int
    search_complete: bool


@dataclass(frozen=True)
class DddReferenceResult:
    status: DddReferenceStatus
    solution: DddReferenceSolution | None
    retained_solutions: tuple[DddReferenceSolution, ...]
    feasible_support_fingerprints: tuple[str, ...]
    metrics: DddReferenceSearchMetrics


@dataclass(frozen=True)
class _TrajectoryGenerationResult:
    by_cabin_id: dict[int, tuple[DddReferenceTrajectory, ...]]
    branch_count: int
    self_conflict_pruned_count: int


@dataclass(frozen=True)
class DddReferenceTrajectoryGenerator:
    tolerance_seconds: float = 1e-9
    max_trajectories_per_start: int = 100_000

    def generate(self, problem: DddMovementProblem) -> _TrajectoryGenerationResult:
        problem.validate()
        if self.tolerance_seconds < 0:
            raise ValueError("DDD generator tolerance_seconds must be nonnegative")
        if self.max_trajectories_per_start <= 0:
            raise ValueError("max_trajectories_per_start must be positive")
        options_by_state_id = problem.route_options_by_state_id
        resources_by_id = problem.resources_by_id
        by_cabin_id: dict[int, tuple[DddReferenceTrajectory, ...]] = {}
        total_branch_count = 0
        total_self_conflicts = 0
        for start in sorted(problem.starts, key=lambda item: item.cabin_id):
            trajectories: list[DddReferenceTrajectory] = []
            branch_count = 0
            self_conflicts = 0

            def visit(
                *,
                state_id: str,
                switch_time_seconds: float,
                visits: tuple[DddReferenceVisit, ...],
                occurrences: tuple[DddReferenceResourceOccurrence, ...],
            ) -> None:
                nonlocal branch_count, self_conflicts
                if len(visits) >= start.max_visit_count:
                    raise ValueError(
                        f"DDD visit bound exhausted for cabin {start.cabin_id} at "
                        f"t={switch_time_seconds}"
                    )
                route_options = options_by_state_id.get(state_id, ())
                if not route_options:
                    raise ValueError(f"DDD state {state_id!r} has no route option")
                for option in route_options:
                    branch_count += 1
                    reference_visit = build_ddd_reference_visit(
                        start=start,
                        visit_index=len(visits),
                        switch_time_seconds=switch_time_seconds,
                        option=option,
                        operational_end_seconds=problem.operational_end_seconds,
                        tolerance_seconds=self.tolerance_seconds,
                    )
                    new_occurrences = reference_visit.resource_occurrences
                    if _occurrence_sets_conflict(
                        occurrences,
                        new_occurrences,
                        resources_by_id,
                        self.tolerance_seconds,
                    ):
                        self_conflicts += 1
                        continue
                    next_visits = (*visits, reference_visit)
                    next_occurrences = (*occurrences, *new_occurrences)
                    if ddd_seconds_to_tick(
                        reference_visit.next_switch_time_seconds
                    ) > problem.operational_end_tick:
                        if len(trajectories) >= self.max_trajectories_per_start:
                            raise DddReferenceSearchLimitError(
                                "DDD trajectory limit exceeded for cabin "
                                f"{start.cabin_id}: {self.max_trajectories_per_start}"
                            )
                        trajectories.append(
                            DddReferenceTrajectory(
                                cabin_id=start.cabin_id,
                                visits=next_visits,
                            )
                        )
                        continue
                    visit(
                        state_id=option.to_state_id,
                        switch_time_seconds=reference_visit.next_switch_time_seconds,
                        visits=next_visits,
                        occurrences=next_occurrences,
                    )

            visit(
                state_id=start.state_id,
                switch_time_seconds=start.time_seconds,
                visits=(),
                occurrences=(),
            )
            by_cabin_id[start.cabin_id] = tuple(
                sorted(trajectories, key=lambda item: item.support_signature)
            )
            total_branch_count += branch_count
            total_self_conflicts += self_conflicts
        return _TrajectoryGenerationResult(
            by_cabin_id=by_cabin_id,
            branch_count=total_branch_count,
            self_conflict_pruned_count=total_self_conflicts,
        )


@dataclass(frozen=True)
class DddReferenceSolver:
    tolerance_seconds: float = 1e-9
    max_trajectories_per_start: int = 100_000
    max_retained_feasible_solutions: int = 1
    stop_after_first_feasible: bool = True

    def solve(self, problem: DddMovementProblem) -> DddReferenceResult:
        problem.validate()
        if self.max_retained_feasible_solutions <= 0:
            raise ValueError("max_retained_feasible_solutions must be positive")
        generator = DddReferenceTrajectoryGenerator(
            tolerance_seconds=self.tolerance_seconds,
            max_trajectories_per_start=self.max_trajectories_per_start,
        )
        generated = generator.generate(problem)
        resources_by_id = problem.resources_by_id
        starts = tuple(sorted(problem.starts, key=lambda item: item.cabin_id))
        selected: list[DddReferenceTrajectory] = []
        selected_index_by_identical_start: dict[tuple[str, float, int], int] = {}
        first_solution: DddReferenceSolution | None = None
        retained_solutions: list[DddReferenceSolution] = []
        feasible_support_fingerprints: list[str] = []
        feasible_solution_count = 0
        combination_attempt_count = 0
        cross_conflict_pruned_count = 0
        symmetry_pruned_count = 0
        stopped_early = False

        def combine(start_index: int) -> None:
            nonlocal first_solution
            nonlocal feasible_solution_count
            nonlocal combination_attempt_count
            nonlocal cross_conflict_pruned_count
            nonlocal symmetry_pruned_count
            nonlocal stopped_early
            if stopped_early:
                return
            if start_index == len(starts):
                solution = DddReferenceSolution(trajectories=tuple(selected))
                validate_ddd_reference_solution(
                    problem,
                    solution,
                    tolerance_seconds=self.tolerance_seconds,
                )
                feasible_solution_count += 1
                feasible_support_fingerprints.append(solution.support_fingerprint)
                if len(retained_solutions) < self.max_retained_feasible_solutions:
                    retained_solutions.append(solution)
                if first_solution is None:
                    first_solution = solution
                if self.stop_after_first_feasible:
                    stopped_early = True
                return

            start = starts[start_index]
            trajectories = generated.by_cabin_id[start.cabin_id]
            start_key = (start.state_id, start.time_seconds, start.max_visit_count)
            minimum_index = selected_index_by_identical_start.get(start_key, 0)
            symmetry_pruned_count += minimum_index
            had_previous = start_key in selected_index_by_identical_start
            previous_index = selected_index_by_identical_start.get(start_key)
            for trajectory_index in range(minimum_index, len(trajectories)):
                combination_attempt_count += 1
                trajectory = trajectories[trajectory_index]
                if any(
                    _occurrence_sets_conflict(
                        prior.resource_occurrences,
                        trajectory.resource_occurrences,
                        resources_by_id,
                        self.tolerance_seconds,
                    )
                    for prior in selected
                ):
                    cross_conflict_pruned_count += 1
                    continue
                selected.append(trajectory)
                selected_index_by_identical_start[start_key] = trajectory_index
                combine(start_index + 1)
                selected.pop()
                if stopped_early:
                    return
            if had_previous and previous_index is not None:
                selected_index_by_identical_start[start_key] = previous_index
            else:
                selected_index_by_identical_start.pop(start_key, None)

        combine(0)
        status = (
            DddReferenceStatus.FEASIBLE
            if first_solution is not None
            else DddReferenceStatus.INFEASIBLE
        )
        return DddReferenceResult(
            status=status,
            solution=first_solution,
            retained_solutions=tuple(retained_solutions),
            feasible_support_fingerprints=tuple(feasible_support_fingerprints),
            metrics=DddReferenceSearchMetrics(
                generated_trajectory_count=sum(
                    len(trajectories)
                    for trajectories in generated.by_cabin_id.values()
                ),
                generation_branch_count=generated.branch_count,
                self_conflict_pruned_count=generated.self_conflict_pruned_count,
                combination_attempt_count=combination_attempt_count,
                cross_conflict_pruned_count=cross_conflict_pruned_count,
                symmetry_pruned_count=symmetry_pruned_count,
                feasible_solution_count=feasible_solution_count,
                search_complete=not stopped_early,
            ),
        )


def validate_ddd_reference_solution(
    problem: DddMovementProblem,
    solution: DddReferenceSolution,
    *,
    tolerance_seconds: float = 1e-9,
) -> None:
    problem.validate()
    if tolerance_seconds < 0:
        raise ValueError("DDD validation tolerance_seconds must be nonnegative")
    starts_by_cabin_id = {start.cabin_id: start for start in problem.starts}
    actual_cabin_ids = tuple(
        trajectory.cabin_id for trajectory in solution.trajectories
    )
    if (
        len(set(actual_cabin_ids)) != len(actual_cabin_ids)
        or set(actual_cabin_ids) != set(starts_by_cabin_id)
    ):
        raise ValueError("DDD solution cabin set does not match fixed starts")
    all_occurrences: list[DddReferenceResourceOccurrence] = []
    for trajectory in solution.trajectories:
        validate_ddd_reference_trajectory(
            problem,
            trajectory,
            tolerance_seconds=tolerance_seconds,
        )
        all_occurrences.extend(trajectory.resource_occurrences)
    conflicts = find_ddd_reference_conflicts(
        tuple(all_occurrences),
        problem,
        tolerance_seconds=tolerance_seconds,
    )
    if conflicts:
        raise DddReferenceResourceConflictError(
            f"DDD reference solution has resource conflicts: {conflicts[0]}"
        )


def validate_ddd_reference_trajectory(
    problem: DddMovementProblem,
    trajectory: DddReferenceTrajectory,
    *,
    tolerance_seconds: float = 1e-9,
) -> None:
    """Validate one locally feasible no-wait trajectory without other cabins."""

    problem.validate()
    if tolerance_seconds < 0:
        raise ValueError("DDD validation tolerance_seconds must be nonnegative")
    starts_by_cabin_id = {start.cabin_id: start for start in problem.starts}
    start = starts_by_cabin_id.get(trajectory.cabin_id)
    if start is None:
        raise ValueError("DDD trajectory references an unknown fixed start")
    if not trajectory.visits:
        raise ValueError("DDD reference trajectory must contain an active visit")
    options_by_id = {option.id: option for option in problem.route_options}
    expected_state = start.state_id
    expected_time_tick = start.time_tick
    for visit_index, reference_visit in enumerate(trajectory.visits):
        if reference_visit.cabin_id != trajectory.cabin_id:
            raise ValueError("DDD trajectory contains a visit for another cabin")
        if reference_visit.visit_index != visit_index:
            raise ValueError("DDD trajectory visit indices must be contiguous")
        if reference_visit.state_id != expected_state:
            raise ValueError("DDD trajectory state chain is inconsistent")
        if (
            ddd_seconds_to_tick(reference_visit.switch_time_seconds)
            != expected_time_tick
        ):
            raise ValueError("DDD trajectory event-time chain is inconsistent")
        if expected_time_tick > problem.operational_end_tick:
            raise ValueError("DDD trajectory contains a post-horizon route entry")
        option = options_by_id.get(reference_visit.route_option_id)
        if option is None:
            raise ValueError("DDD trajectory references an unknown route option")
        if option.from_state_id != reference_visit.state_id:
            raise ValueError("DDD visit uses a route from another state")
        rebuilt = build_ddd_reference_visit(
            start=start,
            visit_index=visit_index,
            switch_time_seconds=reference_visit.switch_time_seconds,
            option=option,
            operational_end_seconds=problem.operational_end_seconds,
            tolerance_seconds=tolerance_seconds,
        )
        if rebuilt != reference_visit:
            raise ValueError("DDD visit timing or resource occurrences are inconsistent")
        expected_state = option.to_state_id
        expected_time_tick = ddd_seconds_to_tick(rebuilt.next_switch_time_seconds)
    if expected_time_tick <= problem.operational_end_tick:
        raise DddReferenceHorizonCoverageError(
            "DDD trajectory ends before covering the operational horizon"
        )
    if len(trajectory.visits) > start.max_visit_count:
        raise ValueError("DDD trajectory exceeds its certified visit bound")
    conflicts = find_ddd_reference_conflicts(
        trajectory.resource_occurrences,
        problem,
        tolerance_seconds=tolerance_seconds,
    )
    if conflicts:
        raise DddReferenceResourceConflictError(
            f"DDD reference trajectory has a self-conflict: {conflicts[0]}"
        )


def find_ddd_reference_conflicts(
    occurrences: tuple[DddReferenceResourceOccurrence, ...],
    problem: DddMovementProblem,
    *,
    tolerance_seconds: float = 1e-9,
) -> tuple[DddReferenceConflict, ...]:
    resources_by_id = problem.resources_by_id
    result: list[DddReferenceConflict] = []
    for first, second in combinations(occurrences, 2):
        if first.resource_id != second.resource_id:
            continue
        resource = resources_by_id[first.resource_id]
        forward = ddd_seconds_to_tick(
            second.follower_enter_time_seconds
        ) - ddd_seconds_to_tick(first.leader_clear_time_seconds)
        reverse = ddd_seconds_to_tick(
            first.follower_enter_time_seconds
        ) - ddd_seconds_to_tick(second.leader_clear_time_seconds)
        violation_tick = resource.headway_tick - max(forward, reverse)
        if violation_tick > ddd_seconds_to_tick(tolerance_seconds):
            result.append(
                DddReferenceConflict(
                    resource_id=resource.id,
                    first_cabin_id=first.cabin_id,
                    first_visit_index=first.visit_index,
                    second_cabin_id=second.cabin_id,
                    second_visit_index=second.visit_index,
                    violation_seconds=ddd_tick_to_seconds(violation_tick),
                )
            )
    return tuple(
        sorted(
            result,
            key=lambda item: (
                -item.violation_seconds,
                item.resource_id,
                item.first_cabin_id,
                item.first_visit_index,
                item.second_cabin_id,
                item.second_visit_index,
            ),
        )
    )


def build_ddd_reference_visit(
    *,
    start: DddFixedStart,
    visit_index: int,
    switch_time_seconds: float,
    option: DddRouteOption,
    operational_end_seconds: float,
    tolerance_seconds: float,
) -> DddReferenceVisit:
    switch_tick = ddd_seconds_to_tick(switch_time_seconds)
    next_switch_tick = switch_tick + option.duration_tick
    next_switch_time_seconds = ddd_tick_to_seconds(next_switch_tick)
    occurrences = tuple(
        occurrence
        for usage in option.resource_usages
        if ddd_seconds_to_tick(
            (
                occurrence := _resource_occurrence(
                    start=start,
                    visit_index=visit_index,
                    switch_time_seconds=switch_time_seconds,
                    usage=usage,
                )
            ).follower_enter_time_seconds
        )
        <= ddd_seconds_to_tick(operational_end_seconds)
    )
    return DddReferenceVisit(
        cabin_id=start.cabin_id,
        visit_index=visit_index,
        state_id=option.from_state_id,
        route_option_id=option.id,
        decision=option.decision,
        switch_time_seconds=ddd_tick_to_seconds(switch_tick),
        next_switch_time_seconds=next_switch_time_seconds,
        resource_occurrences=occurrences,
    )


def _resource_occurrence(
    *,
    start: DddFixedStart,
    visit_index: int,
    switch_time_seconds: float,
    usage: DddResourceUsage,
) -> DddReferenceResourceOccurrence:
    switch_tick = ddd_seconds_to_tick(switch_time_seconds)
    return DddReferenceResourceOccurrence(
        resource_id=usage.resource_id,
        cabin_id=start.cabin_id,
        visit_index=visit_index,
        leader_clear_time_seconds=ddd_tick_to_seconds(
            switch_tick + usage.leader_clear_offset_tick
        ),
        follower_enter_time_seconds=ddd_tick_to_seconds(
            switch_tick + usage.follower_enter_offset_tick
        ),
    )


def _occurrence_sets_conflict(
    first_occurrences: tuple[DddReferenceResourceOccurrence, ...],
    second_occurrences: tuple[DddReferenceResourceOccurrence, ...],
    resources_by_id: dict[str, DddResource],
    tolerance_seconds: float,
) -> bool:
    for first in first_occurrences:
        for second in second_occurrences:
            if first.resource_id != second.resource_id:
                continue
            resource = resources_by_id[first.resource_id]
            forward = ddd_seconds_to_tick(
                second.follower_enter_time_seconds
            ) - ddd_seconds_to_tick(first.leader_clear_time_seconds)
            reverse = ddd_seconds_to_tick(
                first.follower_enter_time_seconds
            ) - ddd_seconds_to_tick(second.leader_clear_time_seconds)
            if resource.headway_tick - max(
                forward, reverse
            ) > ddd_seconds_to_tick(tolerance_seconds):
                return True
    return False
