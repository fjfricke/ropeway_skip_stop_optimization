"""Optional exact passenger recourse; movement and global bounds stay unchanged."""

from dataclasses import dataclass, replace
from time import perf_counter

from .fixed_k import DddFixedKTrajectoryProblem
from .fixed_k_certificate import DddFixedKPrimalValidator, DddValidatedFixedKPlan
from .network_time_space import DddNetworkTimeProblem
from .primal_evaluation import DddEanPassengerPrimalEvaluator
from .time_ticks import ddd_seconds_to_tick


@dataclass(frozen=True)
class DddReservationRefinementResult:
    plan: DddValidatedFixedKPlan
    status: str
    elapsed_seconds: float
    improved: bool


@dataclass(frozen=True)
class DddReservationAssignmentRefiner:
    evaluator: DddEanPassengerPrimalEvaluator
    network_problem: DddNetworkTimeProblem

    def refine(
        self,
        problem: DddFixedKTrajectoryProblem,
        plan: DddValidatedFixedKPlan,
        *,
        deadline: float,
        time_limit_seconds: float,
    ) -> DddReservationRefinementResult:
        started = perf_counter()
        remaining = min(time_limit_seconds, deadline - started)
        if remaining <= 0:
            return DddReservationRefinementResult(plan, "BUDGET_EXHAUSTED", 0, False)
        if (
            self.evaluator.passenger_build != problem.passenger_build
            or self.evaluator.artifact != problem.artifact
            or self.evaluator.objective != problem.objective
            or self.evaluator.waiting_policy
            != problem.resolved_trajectory_problem.waiting_policy
            or self.network_problem.movement_problem
            != problem.resolved_trajectory_problem.structural_movement_problem
        ):
            raise ValueError(
                "assignment refinement domain differs from fixed-K problem"
            )
        evaluator = replace(self.evaluator, time_limit_seconds=remaining)
        result = evaluator.evaluate(self.network_problem, plan.solution)
        best = plan
        if result.passenger_plan is not None and result.objective_value is not None:

            def key(q):
                return (
                    q.demand_group_id,
                    q.cabin_id,
                    q.board_visit_index,
                    q.alight_visit_index,
                )

            candidates = {key(q): q.id for q in problem.passenger_build.ride_candidates}
            counts = {}
            for ride in result.passenger_plan.served_rides:
                candidate_id = candidates[key(ride)]
                counts[candidate_id] = counts.get(candidate_id, 0) + ride.count
            validated = DddFixedKPrimalValidator().validate(
                problem,
                plan.solution,
                counts,
                provenance="reservation:fixed_movement_assignment_ip",
                expected_objective_tick=ddd_seconds_to_tick(result.objective_value),
            )
            if validated.objective_tick < plan.objective_tick:
                best = validated
        return DddReservationRefinementResult(
            best,
            result.solver_status or "NO_INCUMBENT",
            perf_counter() - started,
            best.objective_tick < plan.objective_tick,
        )
