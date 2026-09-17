from __future__ import annotations

from dataclasses import dataclass, field, replace
from time import perf_counter

from ...reservoir_cp_sat_certificate import validate_reservoir_cp_plan
from ..preparation import PreparedLineProblem
from .decoder import decode_no_wait
from .model import CandidateEvaluation, LineGenome, PassengerEvaluation
from .passengers import optimize_fixed_movement_passengers, evaluate_passenger_potential


class EvaluationDeadline(Exception):
    """Stop a library batch between evaluations, retaining its valid archive."""


@dataclass(slots=True)
class LineEvolutionEvaluator:
    problem: object
    prepared: PreparedLineProblem
    passenger_time_limit_seconds: float = 2.0
    evaluate_infeasible_potential: bool = False
    deadline: float | None = None
    dispatch_decoder: str = "legacy"
    waiting_repair_seconds: float = 0.0
    # None: each new candidate gets its own repair budget throughout the run.
    waiting_budget_seconds: float | None = None
    waiting_workers: int = 12
    seed: int = 0
    waiting_construction: str = "no_wait_first"
    passenger_objective: str = "unserved"
    repair_spent_seconds: float = field(default=0.0, init=False)
    _interval_decoder: object = field(default=None, init=False, repr=False)
    _phenotypes: dict = field(default_factory=dict, init=False, repr=False)
    _cache: dict = field(default_factory=dict, init=False, repr=False)

    @property
    def cache_size(self):
        return len(self._cache)

    def evaluate(self, genome: LineGenome) -> CandidateEvaluation:
        if self.dispatch_decoder not in ("legacy", "intervals"):
            raise ValueError("unknown dispatch decoder")
        if self.waiting_repair_seconds and self.dispatch_decoder != "intervals":
            raise ValueError("integrated waiting repair requires the interval decoder")
        if self.waiting_construction not in ("no_wait_first", "prefix_first"):
            raise ValueError("unknown waiting construction policy")
        if self.waiting_construction == "prefix_first" and self.dispatch_decoder != "intervals":
            raise ValueError("prefix_first requires the interval decoder")
        if self.deadline is not None and perf_counter() >= self.deadline:
            raise EvaluationDeadline
        key = (self.problem.fingerprint, self.waiting_construction, genome.identity)
        if key in self._cache:
            value = self._cache[key]
            return replace(value, cached=True, decoder=(None if value.decoder is None else
                {**value.decoder, 'cache_kind': 'genotype', 'decode_seconds_this_call': 0.0}))
        diagnostics = None
        if self.dispatch_decoder == "intervals":
            from .interval_decoder import IntervalDispatchDecoder
            if self._interval_decoder is None:
                self._interval_decoder = IntervalDispatchDecoder(self.problem, self.prepared)
            movement, diagnostics = self._interval_decoder.decode(
                genome, allow_waiting_candidate=(self.waiting_construction == "prefix_first"
                                                or self.waiting_repair_seconds > 0), deadline=self.deadline,
                waiting_construction=self.waiting_construction)
            diagnostics = {**diagnostics, 'input_genome': {
                'pattern_ids': genome.pattern_ids, 'phase_tick': genome.phase_tick,
                'extra_gap_ticks': genome.extra_gap_ticks},
                'cache_kind': None, 'decode_seconds_this_call': movement.decode_seconds}
        else:
            movement = decode_no_wait(self.problem, self.prepared, genome)
        phenotype = movement.genome.identity
        if self.dispatch_decoder == "intervals" and phenotype in self._phenotypes and (movement.plan or movement.relaxed_timetable):
            value = replace(self._phenotypes[phenotype], cached=True,
                            decoder={**diagnostics, 'cache_kind': 'phenotype'})
            self._cache[key] = value
            return value
        passengers = None
        potential = None
        repair = None
        budget = self.passenger_time_limit_seconds
        if self.deadline is not None:
            budget = min(budget, max(0.001, self.deadline - perf_counter()))
        if movement.feasible:
            passengers = optimize_fixed_movement_passengers(
                self.problem,
                movement.plan,
                time_limit_seconds=budget,
                objective=self.passenger_objective,
            )
            validate_reservoir_cp_plan(self.problem, passengers.plan)
        elif self.waiting_repair_seconds > 0 and movement.relaxed_timetable is not None:
            from .waiting_repair import solve_waiting_only_repair
            repair_budget = self.waiting_repair_seconds
            if self.waiting_budget_seconds is not None:
                repair_budget = min(repair_budget,
                                    self.waiting_budget_seconds-self.repair_spent_seconds)
            if self.deadline is not None:
                repair_budget = min(repair_budget, self.deadline-perf_counter())
            if repair_budget > 0.01:
                result = solve_waiting_only_repair(
                    self.problem, movement.relaxed_timetable,
                    dispatch_end_tick=self.prepared.dispatch_window_end_tick,
                    time_limit_seconds=repair_budget,
                    passenger_seconds=min(self.passenger_time_limit_seconds, repair_budget),
                    workers=self.waiting_workers, seed=self.seed)
                self.repair_spent_seconds += result['total_wall_seconds']
                repair = {k:v for k,v in result.items() if k not in ('plan', 'passengers', 'metrics', 'response_stats')}
                if result['plan'] is not None:
                    if result['status'] == 'REPAIRED':
                        passengers = PassengerEvaluation(plan=result['plan'], **result['passengers'])
                    else:
                        # A validated repaired movement with zero passengers is
                        # a real fallback, but no passenger optimality claim.
                        passengers = PassengerEvaluation(result['plan'], 0,
                            sum(g.count for g in self.problem.demand_groups), False, None, (),
                            0.0, 0.0, result.get('movement_validation_seconds', 0.0), 'PENDING')
                    movement = replace(movement, feasible=True,
                        plan=result['plan'], conflicts=(), total_overlap_ticks=0,
                        reason=None, relaxed_timetable=None)
            else:
                repair = {'status': 'REPAIR_BUDGET_EXHAUSTED', 'total_wall_seconds': 0.0}
        if (passengers is None and self.evaluate_infeasible_potential
                and movement.relaxed_timetable is not None
                and (self.deadline is None or perf_counter() < self.deadline)):
            if self.deadline is not None:
                budget = min(budget, self.deadline-perf_counter())
            try:
                potential = evaluate_passenger_potential(
                    self.problem, movement.relaxed_timetable, time_limit_seconds=budget,
                )
            except ValueError as error:
                # Self-conflicts/lifecycle errors are not relaxed search objectives.
                movement = replace(movement, reason=f"invalid individual trajectory: {error}",
                                   relaxed_timetable=None)
        value = CandidateEvaluation(movement, passengers, potential=potential, decoder=diagnostics, repair=repair)
        self._cache[key] = value
        if self.dispatch_decoder == "intervals" and (movement.plan or movement.relaxed_timetable):
            self._phenotypes[phenotype] = value
        return value
