"""Composition root for the bounded reservation insertion diagnostic."""

from __future__ import annotations

from collections.abc import Callable, Sequence
from time import perf_counter

from ..ean.validation import validate_ean_movement_plan_against_artifact
from .ean_plan_adapter import DddReferenceToEanMovementPlanAdapter
from .fixed_k import DddFixedKTrajectoryProblem
from .fixed_k_certificate import (
    DddFixedKPrimalValidator,
    DddValidatedFixedKPlan,
    build_ddd_fixed_k_domain_manifest,
)
from .reference import DddReferenceSolution
from .reservation_calendar import DddReservationCalendar
from .reservation_models import (
    DddReservationAttemptResult,
    DddReservationInsertionConfig,
    DddReservationInsertionResult,
    DddServiceInsertionIntent,
)
from .reservation_models import DddReservationAttemptStatus as Status
from .reservation_passenger import DddReservationPassengerEvaluator
from .reservation_repair import DddReservationSuffixRepairer
from .time_ticks import ddd_seconds_to_tick


def movement_signature(solution: DddReferenceSolution) -> tuple:
    return tuple(
        (
            t.cabin_id,
            tuple(
                (
                    v.route_option_id,
                    ddd_seconds_to_tick(v.switch_time_seconds),
                    ddd_seconds_to_tick(v.wait_seconds),
                )
                for v in t.visits
            ),
        )
        for t in solution.trajectories
    )


class DddReservationInsertionOptimizer:
    def __init__(
        self, config: DddReservationInsertionConfig = DddReservationInsertionConfig()
    ) -> None:
        config.validate()
        self.config = config
        self.validator = DddFixedKPrimalValidator()
        self.passengers = DddReservationPassengerEvaluator()

    def optimize(
        self,
        *,
        problem: DddFixedKTrajectoryProblem,
        initial_plan: DddValidatedFixedKPlan,
        intents: Sequence[DddServiceInsertionIntent],
        progress_callback: Callable[[DddReservationAttemptResult], None] | None = None,
        deadline: float | None = None,
    ) -> DddReservationInsertionResult:
        started = perf_counter()
        deadline = min(
            float("inf") if deadline is None else deadline,
            started + self.config.total_time_limit_seconds,
        )
        build_ddd_fixed_k_domain_manifest(problem)
        initial = self.validator.validate(
            problem,
            initial_plan.solution,
            initial_plan.ride_counts,
            provenance=initial_plan.provenance,
            expected_objective_tick=initial_plan.objective_tick,
        )
        movement = problem.resolved_trajectory_problem.structural_movement_problem
        policy = problem.resolved_trajectory_problem.waiting_policy
        adapter = DddReferenceToEanMovementPlanAdapter(waiting_policy=policy)
        initial_ean = adapter.build(
            problem=movement, solution=initial.solution, artifact=problem.artifact
        )
        report = validate_ean_movement_plan_against_artifact(
            problem.artifact, initial_ean
        )
        if not report.is_valid:
            raise ValueError(f"invalid initial EAN plan: {report.issues[:1]}")
        repairer = DddReservationSuffixRepairer(movement, policy, self.config)
        candidates = {q.id: q for q in problem.passenger_build.ride_candidates}
        best = current = initial
        calendar = DddReservationCalendar.from_solution(movement, current.solution)
        attempts, signatures = [], set()
        finalists = {}
        for intent in intents:
            if perf_counter() >= deadline:
                break
            if intent.candidate_id not in candidates:
                raise ValueError("unknown insertion candidate")
            before = perf_counter()
            q = candidates[intent.candidate_id]
            repair = repairer.repair(
                initial=current.solution,
                calendar=calendar,
                candidate=q,
                protected_rides=tuple(candidates[k] for k in current.ride_counts),
                deadline=min(deadline, before + self.config.attempt_time_limit_seconds),
            )
            repair_seconds = perf_counter() - before
            ptime = vtime = 0.0
            objective, different = None, False
            status = Status.NO_FEASIBLE_REPAIR_FOUND
            reason = repair.reason
            if repair.solution is None:
                if reason == "budget" or perf_counter() >= min(
                    deadline, before + self.config.attempt_time_limit_seconds
                ):
                    status = Status.BUDGET_EXHAUSTED
            elif perf_counter() >= deadline:
                status, reason = (
                    Status.BUDGET_EXHAUSTED,
                    "total budget before validation",
                )
            else:
                stamp = perf_counter()
                ean = adapter.build(
                    problem=movement,
                    solution=repair.solution,
                    artifact=problem.artifact,
                )
                report = validate_ean_movement_plan_against_artifact(
                    problem.artifact, ean
                )
                if not report.is_valid:
                    raise RuntimeError(
                        f"reservation repair failed independent EAN validation: {report.issues[:1]}"
                    )
                vtime += perf_counter() - stamp
                stamp = perf_counter()
                assignment = self.passengers.evaluate(
                    problem=problem,
                    movement_plan=ean,
                    initial_plan=current,
                    intent=intent,
                    suffixes=repair.suffixes,
                )
                ptime = perf_counter() - stamp
                if assignment is None:
                    status, reason = (
                        Status.NO_CANDIDATE,
                        "service or frozen-prefix capacity unavailable",
                    )
                else:
                    stamp = perf_counter()
                    validated = self.validator.validate(
                        problem,
                        repair.solution,
                        assignment.ride_counts,
                        provenance=f"reservation:{intent.candidate_id}",
                    )
                    vtime += perf_counter() - stamp
                    status, reason = Status.FEASIBLE, "independently validated"
                    objective = validated.objective
                    signature = movement_signature(validated.solution)
                    different = signature != movement_signature(current.solution)
                    if different:
                        signatures.add(signature)
                    prior = finalists.get(signature)
                    if prior is None or validated.objective_tick < prior.objective_tick:
                        finalists[signature] = validated
                    finalists = dict(
                        sorted(
                            finalists.items(), key=lambda item: item[1].objective_tick
                        )[:3]
                    )
                    if validated.objective_tick < best.objective_tick:
                        best = validated
                    if (
                        self.config.accept_improvements
                        and validated.objective_tick < current.objective_tick
                    ):
                        # Publish a newly owned calendar only after all checks succeed.
                        current = validated
                        calendar = DddReservationCalendar.from_solution(
                            movement, current.solution
                        )
            attempt = DddReservationAttemptResult(
                intent,
                status,
                perf_counter() - before,
                tuple(sorted(repair.suffixes)),
                repair.pair_checks,
                repair.labels,
                reason,
                objective,
                different,
                repair_seconds,
                ptime,
                vtime,
            )
            attempts.append(attempt)
            if progress_callback:
                progress_callback(attempt)
        return DddReservationInsertionResult(
            initial,
            best,
            tuple(attempts),
            perf_counter() - started,
            "BUDGET_EXHAUSTED" if perf_counter() >= deadline else "REQUESTS_COMPLETED",
            len(signatures),
            tuple(finalists.values()),
        )
