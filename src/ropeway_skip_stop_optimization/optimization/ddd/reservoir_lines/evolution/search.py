from __future__ import annotations

from collections import Counter
from concurrent.futures import ProcessPoolExecutor, as_completed
from dataclasses import asdict, dataclass
import multiprocessing as mp
from time import perf_counter

import numpy as np

from .evaluator import LineEvolutionEvaluator, EvaluationDeadline
from .model import CandidateEvaluation, EvolutionEngine, LineGenome, OperatorProfile
from .operators import GenomeFactory
from .grouped_selection import candidate_group, passenger_score, survivor_indices, parent_index


_PATTERN_PROCESS_EVALUATOR = None


def _initialize_pattern_process(evaluator):
    global _PATTERN_PROCESS_EVALUATOR
    _PATTERN_PROCESS_EVALUATOR = evaluator


def _evaluate_pattern_process(task):
    genome, dispatch_hint_ticks = task
    return _PATTERN_PROCESS_EVALUATOR.evaluate(
        genome, dispatch_hint_ticks=dispatch_hint_ticks
    )


class SearchTargetReached(Exception):
    """Stop between validated evaluations after full service was reached."""


def construction_violation(value):
    """Search guidance only, never a physical conflict count or a bound."""
    if value.decoder and value.decoder['status'] == 'CONSTRUCTION_FAILED':
        return max(1, value.movement.genome.fleet_size-value.decoder['completed_cabins'])
    return max(1, len(value.movement.conflicts))


def passenger_scalar(passengers, objective, journey_upper_bound):
    """Scalar used only where the search library requires one objective.

    The fractional term is strictly below one, so one fewer unserved passenger
    always dominates every possible journey-time improvement.
    """
    if objective == "journey_time":
        return passengers.journey_time_tick
    if objective == "unserved":
        return passengers.unserved
    if objective == "service_then_journey":
        journey = passengers.journey_time_tick or 0
        return passengers.unserved + journey / (journey_upper_bound + 1)
    raise ValueError("unknown evolution objective")


@dataclass(frozen=True, slots=True)
class EvolutionSearchConfig:
    engine: EvolutionEngine = EvolutionEngine.GA
    operator_profile: OperatorProfile = OperatorProfile.MIXED_GLOBAL
    time_limit_seconds: float = 120.0
    population_size: int = 32
    offspring_size: int = 8
    seed: int = 0
    exploration_parent_probability: float = 0.25
    passenger_time_limit_seconds: float = 2.0
    dispatch_decoder: str = "legacy"
    waiting_repair_seconds: float = 0.0
    waiting_budget_fraction: float | None = None
    waiting_workers: int = 12
    fixed_k: int | None = None
    seed_all_stop: bool = True
    waiting_construction: str = "no_wait_first"
    selection_profile: str = "legacy"
    representation: str = "patterns_dispatch"
    dispatch_subproblem: str = "timing_then_passengers"
    evaluation_time_limit_seconds: float = 8.0
    initial_pattern_sequences: tuple[tuple[str, ...], ...] = ()
    pattern_waiting: bool = False
    objective: str = "unserved"
    stop_on_full_service: bool = False
    pattern_search: str = "independent"
    evaluation_parallelism: int = 1


class SearchRecorder:
    def __init__(self, started, minimum_gap, event_callback=None, incumbent_callback=None,
                 objective="unserved", stop_on_full_service=False):
        self.started, self.event_callback = started, event_callback
        self.incumbent_callback = incumbent_callback
        self.potential_by_k = {}
        self.evaluation_totals = Counter()
        self.minimum_gap = minimum_gap
        self.evaluations = 0
        self.feasible = 0
        self.best = None
        self.events = []
        self.operator_counts = {}
        self.parent_counts = Counter()
        self.best_by_k = {}
        self.best_mixed_by_k = {}
        self.conflict_frontier_by_k = {}
        self.last_population_snapshot = started
        self.last_snapshot = started
        self.window_evaluations = self.window_feasible = 0
        self.window_conflicts = self.window_overlap = 0
        self.window_k = Counter()
        self.last_population = None
        self.objective = objective
        self.stop_on_full_service = stop_on_full_service
        self.target_reached = False

    def _passenger_value(self, passengers):
        return passenger_score(passengers, self.objective)

    def _emit(self, event):
        self.events.append(event)
        if self.event_callback is not None:
            self.event_callback(event)

    def _schedule(self, genome, value=None):
        if value is not None:
            genome = value.movement.genome
        dispatches = (genome.dispatch_ticks(self.minimum_gap)
                      if hasattr(genome, "dispatch_ticks") else ())
        gaps = tuple(b - a for a, b in zip(dispatches, dispatches[1:]))
        result = {
            "fleet_size": genome.fleet_size,
            "pattern_ids": genome.pattern_ids,
            "pattern_counts": dict(sorted(Counter(genome.pattern_ids).items())),
            "phase_tick": getattr(genome, "phase_tick", None),
            "dispatch_ticks": dispatches,
            "minimum_dispatch_gap_tick": min(gaps) if gaps else None,
            "maximum_dispatch_gap_tick": max(gaps) if gaps else None,
            "mean_dispatch_gap_tick": sum(gaps) / len(gaps) if gaps else None,
        }
        if value is not None:
            result['decoder_status'] = None if value.decoder is None else value.decoder['status']
            result['repair_status'] = None if value.repair is None else value.repair['status']
            if value.passengers is not None:
                trips = value.passengers.plan.trips
                result['total_wait_tick'] = sum(sum(t.wait_ticks) for t in trips)
                if result['total_wait_tick']:
                    result['wait_ticks_by_cabin'] = {str(t.cabin_id): t.wait_ticks for t in trips}
                    result['return_ticks'] = [t.return_tick for t in trips]
        return result

    def _snapshot(self, now, genome, value, *, final=False):
        if not final and now - self.last_snapshot < 5:
            return
        event = {
            "kind": "evaluation_window",
            "elapsed_seconds": now - self.started,
            "evaluations_total": self.evaluations,
            "feasible_total": self.feasible,
            "window_evaluations": self.window_evaluations,
            "window_feasible": self.window_feasible,
            "window_feasible_ratio": (
                self.window_feasible / self.window_evaluations
                if self.window_evaluations else None
            ),
            "window_mean_conflicts": (
                self.window_conflicts / self.window_evaluations
                if self.window_evaluations else None
            ),
            "window_mean_overlap_ticks": (
                self.window_overlap / self.window_evaluations
                if self.window_evaluations else None
            ),
            "window_k_counts": dict(sorted(self.window_k.items())),
            "current": {
                **self._schedule(genome, value),
                "served": None if value.passengers is None else value.passengers.served,
                "potential": None if value.potential is None else asdict(value.potential),
                "conflicts": len(value.movement.conflicts),
                "overlap_ticks": value.movement.total_overlap_ticks,
                "construction_missing_cabins": (value.movement.genome.fleet_size-value.decoder['completed_cabins']
                    if value.decoder and value.decoder['status'] == 'CONSTRUCTION_FAILED' else 0),
            },
            "incumbent": None if self.best is None else {
                **self._schedule(self.best.movement.genome, self.best),
                "served": self.best.passengers.served,
                "unserved": self.best.passengers.unserved,
            },
        }
        self._emit(event)
        self.last_snapshot = now
        self.window_evaluations = self.window_feasible = 0
        self.window_conflicts = self.window_overlap = 0
        self.window_k.clear()

    def record(self, genome, value, origin):
        input_identity = genome.identity
        genome = value.movement.genome
        fresh = int(not value.cached)
        self.evaluations += fresh
        self.feasible += int(fresh and value.passengers is not None)
        self.operator_counts[origin] = self.operator_counts.get(origin, 0) + fresh
        if fresh:
            self.window_evaluations += 1
            self.window_feasible += int(value.passengers is not None)
            self.window_conflicts += len(value.movement.conflicts)
            self.window_overlap += value.movement.total_overlap_ticks
            self.window_k[genome.fleet_size] += 1
        now = perf_counter()
        if value.decoder:
            self.evaluation_totals['interval_decoder_wall_seconds'] += value.decoder['decode_seconds_this_call']
            if value.decoder['cache_kind']:
                self.evaluation_totals['cache_hits_' + value.decoder['cache_kind']] += 1
        if fresh:
            self.evaluation_totals["decode_seconds"] += value.movement.decode_seconds
            assignment = value.passengers or value.potential
            if assignment is not None:
                label = "valid" if value.passengers is not None else "relaxed"
                self.evaluation_totals[label + "_assignments"] += 1
                self.evaluation_totals[label + "_open_assignments"] += int(not assignment.proven_optimal)
                for field in ("build_seconds", "solve_seconds", "validation_seconds"):
                    self.evaluation_totals[label + "_" + field] += getattr(assignment, field)
            if value.movement.reason:
                self.evaluation_totals["structurally_rejected"] += 1
            if value.decoder:
                self.evaluation_totals['decoder_' + value.decoder['status']] += 1
                self.evaluation_totals['changed_dispatches'] += value.decoder.get('changed_dispatches', 0)
                if value.decoder.get("subproblem"):
                    self._emit({
                        "kind": "pattern_subproblem",
                        "elapsed_seconds": now - self.started,
                        "input_identity": input_identity,
                        "timing_status": value.decoder["status"],
                        "native_status": value.decoder.get("subproblem_status"),
                        "subproblem": value.decoder["subproblem"],
                        "served": value.valid_served,
                        "pattern_ids": value.decoder.get("input_pattern_ids", ()),
                        "model_stats": value.decoder.get("model_stats", {}),
                        "preparation_seconds": value.decoder.get("preparation_seconds", 0),
                        "model_build_seconds": value.decoder.get("model_build_seconds", 0),
                        "solve_seconds": value.decoder.get("solve_seconds", 0),
                        "validation_seconds": value.decoder.get("validation_seconds", 0),
                        "waiting_enabled": value.decoder.get("waiting_enabled", False),
                        "maximum_wait_tick": value.decoder.get("maximum_wait_tick"),
                        "total_wait_tick": value.decoder.get("total_wait_tick"),
                        "rounds": value.decoder.get("rounds"),
                        "objective_scope": value.decoder.get("objective_scope"),
                    })
            if value.repair:
                self.evaluation_totals['repair_' + value.repair['status']] += 1
                self.evaluation_totals['repair_wall_seconds'] += value.repair['total_wall_seconds']
                self._emit({'kind': 'waiting_repair', 'elapsed_seconds': now-self.started,
                            'input_identity': input_identity, 'decoded_identity': genome.identity,
                            **self._schedule(genome, value), 'repair': value.repair,
                            'served': value.valid_served})
            elif value.passengers is None and value.movement.relaxed_timetable is not None:
                # Full unrepaired proposals remain measurable when repair is disabled.
                # These are direct No-Wait overlap counts, not a Waiting infeasibility proof.
                self._emit({'kind': 'unrepaired_candidate', 'elapsed_seconds': now-self.started,
                            'input_identity': input_identity, 'decoded_identity': genome.identity,
                            **self._schedule(genome, value),
                            'conflicts': len(value.movement.conflicts),
                            'overlap_ticks': value.movement.total_overlap_ticks,
                            'served': None})
        if value.potential is not None:
            score = (-value.potential.assigned, len(value.movement.conflicts), value.movement.total_overlap_ticks)
            if genome.fleet_size not in self.potential_by_k or score < self.potential_by_k[genome.fleet_size][0]:
                event = {"kind": "potential_frontier", "elapsed_seconds": now - self.started,
                         "potential": asdict(value.potential), "conflicts": score[1],
                         "overlap_ticks": score[2], "origin": origin, **self._schedule(genome, value)}
                self.potential_by_k[genome.fleet_size] = (score, event)
                self._emit(event)
        if value.passengers is not None:
            passenger_value = self._passenger_value(value.passengers)
            if any(p != 'all_stop' for p in genome.pattern_ids):
                previous_mixed = self.best_mixed_by_k.get(genome.fleet_size)
                if previous_mixed is None or passenger_value < previous_mixed[0]:
                    event = {'kind': 'mixed_fleet_frontier', 'elapsed_seconds': now-self.started,
                             'served': value.passengers.served, 'unserved': value.passengers.unserved,
                             'journey_time_tick': value.passengers.journey_time_tick,
                             'origin': origin, **self._schedule(genome, value)}
                    self.best_mixed_by_k[genome.fleet_size] = (passenger_value, event)
                    self._emit(event)
            previous = self.best_by_k.get(genome.fleet_size)
            if previous is None or passenger_value < previous[0]:
                event = {
                    "kind": "fleet_frontier",
                    "elapsed_seconds": now - self.started,
                    "served": value.passengers.served,
                    "unserved": value.passengers.unserved,
                    "journey_time_tick": value.passengers.journey_time_tick,
                    "origin": origin,
                    "passenger_optimal": value.passengers.proven_optimal,
                    **self._schedule(genome, value),
                }
                self.best_by_k[genome.fleet_size] = (passenger_value, event)
                self._emit(event)
        elif fresh:
            score = (
                len(value.movement.conflicts),
                value.movement.total_overlap_ticks,
                -value.movement.optimistic_od_coverage,
            )
            previous = self.conflict_frontier_by_k.get(genome.fleet_size)
            if previous is None or score < previous[0]:
                self.conflict_frontier_by_k[genome.fleet_size] = (score, {
                    "kind": "conflict_frontier",
                    "elapsed_seconds": now - self.started,
                    "conflicts": score[0],
                    "overlap_ticks": score[1],
                    "optimistic_od_coverage": value.movement.optimistic_od_coverage,
                    "origin": origin,
                    **self._schedule(genome, value),
                })
                self._emit(self.conflict_frontier_by_k[genome.fleet_size][1])
        if value.passengers is not None and (
            self.best is None
            or self._passenger_value(value.passengers) < self._passenger_value(self.best.passengers)
        ):
            self.best = value
            if self.incumbent_callback is not None:
                self.incumbent_callback(value)
            event = {
                "kind": "incumbent",
                "elapsed_seconds": now - self.started,
                "served": value.passengers.served,
                "unserved": value.passengers.unserved,
                "journey_time_tick": value.passengers.journey_time_tick,
                "fleet_size": genome.fleet_size,
                "origin": origin,
                "passenger_optimal": value.passengers.proven_optimal,
                "input_identity": input_identity,
                **self._schedule(genome, value),
            }
            self._emit(event)
        self._snapshot(now, genome, value)
        if (self.stop_on_full_service and value.passengers is not None
                and value.passengers.unserved == 0):
            self.target_reached = True
            self._emit({"kind": "target_reached", "elapsed_seconds": now - self.started,
                        "target": "validated_full_service", "served": value.passengers.served,
                        "unserved": 0, "journey_time_tick": value.passengers.journey_time_tick})
            raise SearchTargetReached

    def population(self, entries, results, *, final=False):
        self.last_population = (entries, results)
        now = perf_counter()
        if not final and now - self.last_population_snapshot < 5:
            return
        members = []
        for item in entries:
            value = results[item.X[0].identity]
            members.append({
                **self._schedule(item.X[0], value),
                "identity": item.X[0].identity,
                "selection_group": (
                    __import__(
                        "ropeway_skip_stop_optimization.optimization.ddd.reservoir_lines.evolution.pattern_selection",
                        fromlist=["pattern_group"],
                    ).pattern_group(value)
                    if (value.decoder or {}).get("subproblem") else candidate_group(value)
                ),
                "served": value.valid_served,
                "potential": None if value.potential is None else asdict(value.potential),
                "search_objectives": item.F.tolist(),
                "structural_violation": float(item.CV[0]),
                "conflicts": len(value.movement.conflicts),
                "overlap_ticks": value.movement.total_overlap_ticks,
            })
        self._emit({"kind": "population", "elapsed_seconds": now - self.started,
                    "members": members, "parent_selection_counts": dict(self.parent_counts)})
        self.last_population_snapshot = now

    def finish(self):
        if self.last_population is not None:
            self.population(*self.last_population, final=True)
        if self.evaluations:
            # The last ordinary record may be less than five seconds after the
            # previous snapshot. Persist that tail as well.
            genome = self.best.movement.genome if self.best is not None else LineGenome((), 0, ())
            value = self.best
            if value is not None:
                self._snapshot(perf_counter(), genome, value, final=True)


def genome_from_plan(problem, prepared, plan):
    from ..certificate import representable_line_plan

    represented = representable_line_plan(problem, prepared, plan)
    mapping = represented.template_id_by_cabin
    by_template = prepared.templates_by_id
    ordered = sorted(plan.trips, key=lambda trip: (trip.switch_ticks[0], trip.cabin_id))
    factory = GenomeFactory(problem, prepared)
    return factory.from_dispatches(
        [by_template[mapping[trip.cabin_id]].pattern_id for trip in ordered],
        [trip.switch_ticks[0] for trip in ordered],
    )


def _initial(factory, reference, count, rng, *, seed_all_stop=True, pattern_sequences=(), pattern_search="independent"):
    values = []
    if reference is not None:
        values.append(reference)
    for sequence in pattern_sequences:
        values.append(factory.random(patterns=sequence, arrangement="random", rng=rng))
    all_stop = next((p for p in factory.patterns if p == "all_stop"), factory.patterns[0])
    sizes = ([factory.fixed_k] if factory.fixed_k is not None else
             sorted({1, max(1, factory.maximum_k // 4), max(1, factory.maximum_k // 2), factory.maximum_k}))
    for k in sizes if seed_all_stop else ():
        values.append(factory.random(k=k, patterns=(all_stop,) * k, arrangement="grouped", rng=rng))
    if pattern_search == "line_groups" and hasattr(factory, "demand_cover_initial"):
        values.extend(factory.demand_cover_initial(max(0, min(8, count - len(values))), rng=rng))
    non_all = list(getattr(factory, "demand_patterns", ())) or [p for p in factory.patterns if p != all_stop]
    if len(non_all) >= 2 and pattern_search == "independent":
        for arrangement in ("alternating", "grouped", "random"):
            k = factory.fixed_k or min(factory.maximum_k, max(2, factory.maximum_k * 3 // 4))
            patterns = tuple(non_all[i % len(non_all)] for i in range(k))
            values.append(factory.random(k=k, patterns=patterns, arrangement=arrangement, rng=rng))
    seen = {x.identity for x in values}
    attempts = 0
    while len(values) < count and attempts < max(64, 16 * count):
        attempts += 1
        value = factory.random(rng=rng)
        if value.identity not in seen:
            seen.add(value.identity)
            values.append(value)
    # A tiny enumerated domain can contain fewer identities than the population.
    # Pymoo may receive duplicates here; its regular duplicate elimination then
    # handles them without making initialization loop forever.
    while len(values) < count:
        values.append(factory.random(rng=rng))
    return values[:count]


def _evaluate(evaluator, recorder, genome, origin):
    value = evaluator.evaluate(genome)
    recorder.record(genome, value, origin)
    return value


def _random_search(factory, evaluator, recorder, reference, deadline):
    rng = np.random.default_rng(factory.rng.integers(2**32))
    queue = _initial(factory, reference, 32, rng)
    while perf_counter() < deadline:
        genome = queue.pop(0) if queue else factory.random(rng=rng)
        _evaluate(evaluator, recorder, genome, "initial" if recorder.evaluations < 32 else "random")


def _tpe_search(factory, evaluator, recorder, reference, deadline, seed):
    import optuna

    optuna.logging.set_verbosity(optuna.logging.WARNING)
    sampler = optuna.samplers.TPESampler(seed=seed, multivariate=True, group=True)
    study = optuna.create_study(direction="minimize", sampler=sampler)
    if reference is not None:
        study.enqueue_trial({
            "k": reference.fleet_size,
            "phase": reference.phase_tick,
            **{f"pattern_{i}": value for i, value in enumerate(reference.pattern_ids)},
            **{f"dispatch_{i+1}": tick for i, tick in enumerate(reference.dispatch_ticks(factory.minimum_gap)[1:])},
        })

    demand = sum(g.count for g in evaluator.problem.demand_groups)
    journey_upper = max(
        1, demand * evaluator.problem.resolved_core.passenger_service_end_tick
    )
    def objective(trial):
        k = trial.suggest_int("k", 1, factory.maximum_k)
        latest_first = factory.prepared.dispatch_window_end_tick - (k - 1) * factory.minimum_gap
        phase = trial.suggest_int("phase", 0, latest_first, step=factory.dispatch_step)
        patterns = [trial.suggest_categorical(f"pattern_{i}", factory.patterns) for i in range(k)]
        dispatches = [phase]
        for i in range(1, k):
            lower = dispatches[-1] + factory.minimum_gap
            upper = factory.prepared.dispatch_window_end_tick - (k - 1 - i) * factory.minimum_gap
            dispatches.append(
                trial.suggest_int(
                    f"dispatch_{i}", lower, upper, step=factory.dispatch_step
                )
            )
        genome = factory.from_dispatches(patterns, dispatches)
        value = _evaluate(evaluator, recorder, genome, "tpe")
        trial.set_user_attr("genome", asdict(genome))
        if value.passengers is not None:
            trial.set_user_attr("feasible", True)
            return passenger_scalar(value.passengers, recorder.objective, journey_upper)
        trial.set_user_attr("feasible", False)
        return demand + len(value.movement.conflicts) + min(0.999, value.movement.total_overlap_ticks / 1e12)

    study.optimize(objective, timeout=max(0.001, deadline - perf_counter()), n_jobs=1, show_progress_bar=False)


def _ga_search(factory, evaluator, recorder, reference, deadline, config):
    from pymoo.algorithms.soo.nonconvex.ga import GA
    from pymoo.algorithms.moo.nsga2 import NSGA2
    from pymoo.core.callback import Callback
    from pymoo.core.crossover import Crossover
    from pymoo.core.duplicate import ElementwiseDuplicateElimination
    from pymoo.core.mutation import Mutation
    from pymoo.core.problem import Problem
    from pymoo.core.selection import Selection
    from pymoo.core.sampling import Sampling
    from pymoo.core.survival import Survival
    from pymoo.optimize import minimize

    multiobjective = config.engine is EvolutionEngine.NSGA2
    initial = _initial(
        factory, reference, config.population_size, np.random.default_rng(config.seed),
        seed_all_stop=config.seed_all_stop,
        pattern_sequences=config.initial_pattern_sequences,
        pattern_search=config.pattern_search,
    )
    demand = sum(g.count for g in evaluator.problem.demand_groups)
    journey_upper = max(
        1, demand * evaluator.problem.resolved_core.passenger_service_end_tick
    )

    class SamplingImpl(Sampling):
        def _do(self, problem, n_samples, *args, random_state=None, **kwargs):
            result = np.empty((n_samples, 1), dtype=object)
            values = initial[:n_samples]
            for i in range(n_samples):
                result[i, 0] = values[i] if i < len(values) else factory.random(rng=random_state)
            return result

    class CrossImpl(Crossover):
        def __init__(self): super().__init__(2, 1, prob=1.0)
        def _do(self, problem, X, *args, random_state=None, **kwargs):
            out = np.empty((1, X.shape[1], 1), dtype=object)
            for i in range(X.shape[1]):
                out[0, i, 0] = factory.variation(X[0, i, 0], X[1, i, 0], config.operator_profile, rng=random_state)
            return out

    class ParentSelection(Selection):
        def _do(self, problem, pop, n_select, n_parents, *, random_state=None, **kwargs):
            rng = random_state
            if config.selection_profile == "grouped":
                values = [problem.results[item.X[0].identity] for item in pop]
                output = np.empty((n_select, n_parents), dtype=int)
                for index in np.ndindex(output.shape):
                    winner, group = parent_index(values, rng, config.objective)
                    output[index] = winner
                    recorder.parent_counts["group_" + group] += 1
                return output
            if config.selection_profile == "pattern_status":
                from .pattern_selection import pattern_parent_index
                values = [problem.results[item.X[0].identity] for item in pop]
                output = np.empty((n_select, n_parents), dtype=int)
                for index in np.ndindex(output.shape):
                    winner, group = pattern_parent_index(values, rng, config.objective)
                    output[index] = winner
                    recorder.parent_counts["pattern_" + group] += 1
                return output
            infeasible = [i for i, item in enumerate(pop) if float(item.CV[0]) > 0]
            output = np.empty((n_select, n_parents), dtype=int)
            for index in np.ndindex(output.shape):
                explore = bool(infeasible) and rng.random() < config.exploration_parent_probability
                pool = infeasible if explore else list(range(len(pop)))
                a, b = (int(i) for i in rng.choice(pool, size=2))
                if explore:
                    def score(i):
                        value = problem.results[pop[i].X[0].identity]
                        return (construction_violation(value), value.movement.total_overlap_ticks)
                    sa, sb = score(a), score(b)
                elif float(pop[a].CV[0]) > 0 or float(pop[b].CV[0]) > 0:
                    sa, sb = float(pop[a].CV[0]), float(pop[b].CV[0])
                else:
                    sa, sb = float(pop[a].F[0]), float(pop[b].F[0])
                winner = a if sa < sb else b if sb < sa else int(rng.choice([a, b]))
                output[index] = winner
                recorder.parent_counts["exploration" if explore else "standard"] += 1
                recorder.parent_counts["infeasible_selected" if float(pop[winner].CV[0]) > 0 else "feasible_selected"] += 1
            return output

    class DuplicateImpl(ElementwiseDuplicateElimination):
        def is_equal(self, a, b):
            return 0.0 if a.X[0].identity == b.X[0].identity else 1.0

    class DiverseSurvival(Survival):
        def __init__(self): super().__init__(filter_infeasible=False)
        def _do(self, problem, pop, *args, n_survive=None, **kwargs):
            entries = list(pop)
            if config.selection_profile == "grouped":
                values = [problem.results[x.X[0].identity] for x in entries]
                selected = [entries[i] for i in survivor_indices(values, n_survive, config.objective)]
                from pymoo.core.population import Population
                recorder.population(selected, problem.results)
                return Population.create(*selected)
            if config.selection_profile == "pattern_status":
                from .pattern_selection import pattern_survivor_indices
                values = [problem.results[x.X[0].identity] for x in entries]
                selected = [entries[i] for i in pattern_survivor_indices(values, n_survive, config.objective)]
                from pymoo.core.population import Population
                recorder.population(selected, problem.results)
                return Population.create(*selected)
            feasible = sorted(
                (x for x in entries if problem.results[x.X[0].identity].passengers is not None),
                key=lambda x: float(x.F[0]),
            )
            selected = feasible[: min(16, n_survive)]
            signatures = {
                (x.X[0].fleet_size, tuple(sorted(Counter(x.X[0].pattern_ids).items())))
                for x in selected
            }
            for candidate in feasible:
                signature = (candidate.X[0].fleet_size,
                             tuple(sorted(Counter(candidate.X[0].pattern_ids).items())))
                if signature not in signatures and len(selected) < min(24, n_survive):
                    selected.append(candidate)
                    signatures.add(signature)
            used = {id(x) for x in selected}
            edges = np.linspace(1, factory.maximum_k + 1, 9, dtype=int)
            for lo, hi in zip(edges[:-1], edges[1:]):
                candidates = [x for x in entries if id(x) not in used and lo <= x.X[0].fleet_size < hi]
                if not candidates:
                    continue
                # Exploration places prefer the least conflicting infeasible
                # proposal.  A valid proposal fills the bin only when no such
                # boundary candidate exists.
                candidates.sort(key=lambda x: (
                    problem.results[x.X[0].identity].passengers is not None,
                    (construction_violation(problem.results[x.X[0].identity])
                     if problem.results[x.X[0].identity].decoder else len(problem.results[x.X[0].identity].movement.conflicts)),
                    problem.results[x.X[0].identity].movement.total_overlap_ticks,
                    -problem.results[x.X[0].identity].movement.optimistic_od_coverage,
                ))
                selected.append(candidates[0]); used.add(id(candidates[0]))
                if len(selected) == n_survive: break
            for x in sorted(entries, key=lambda y: (float(y.CV[0]), float(y.F[0]))):
                if id(x) not in used:
                    selected.append(x); used.add(id(x))
                if len(selected) == n_survive: break
            from pymoo.core.population import Population
            recorder.population(selected, problem.results)
            return Population.create(*selected)

    class ProblemImpl(Problem):
        def __init__(self):
            super().__init__(
                n_var=1,
                n_obj=3 if multiobjective else 1,
                n_ieq_constr=1,
                xl=np.array([0]),
                xu=np.array([1]),
            )
            self.results = {}

        def _origin(self, genome):
            return (
                "reference"
                if reference is not None and genome.identity == reference.identity
                else factory.origin_by_identity.get(genome.identity, "ga")
            )

        def _hint(self, genome):
            parent_identity = getattr(factory, "parent_by_identity", {}).get(
                genome.identity
            )
            parent = self.results.get(parent_identity)
            if parent is None or parent.passengers is None or parent.movement.genome.fleet_size != genome.fleet_size:
                return None
            return tuple(
                trip.switch_ticks[0]
                for trip in sorted(
                    parent.movement.plan.trips, key=lambda trip: trip.cabin_id
                )
            )

        def _record(self, genome, value):
            origin = (
                "reference"
                if reference is not None and genome.identity == reference.identity
                else factory.origin_by_identity.get(genome.identity, "ga")
            )
            recorder.record(genome, value, origin)
            self.results[genome.identity] = value
            if value.passengers is not None and hasattr(factory, "intensify"):
                if not factory.intensified:
                    factory.intensify()
                    recorder._emit({
                        "kind": "search_phase",
                        "elapsed_seconds": perf_counter() - recorder.started,
                        "phase": "feasible_intensification",
                        "trigger_identity": genome.identity,
                    })

        def _score(self, value):
            if multiobjective:
                objectives, violation = nsga_objectives(value, demand)
                return tuple(objectives), (violation,)
            if value.passengers is not None:
                return (
                    passenger_scalar(
                        value.passengers, config.objective, journey_upper
                    ),
                ), (0,)
            objective = demand + (
                construction_violation(value)
                if value.decoder
                else len(value.movement.conflicts)
            ) + min(0.999, value.movement.total_overlap_ticks / 1e12)
            return (objective,), (construction_violation(value),)

        def _evaluate(self, x, out, *args, **kwargs):
            genomes = [row[0] for row in x]
            values = [None] * len(genomes)
            pending = []
            for index, genome in enumerate(genomes):
                previous = self.results.get(genome.identity)
                if previous is not None:
                    values[index] = previous
                else:
                    pending.append((index, genome, self._hint(genome)))

            if process_pool is None:
                for index, genome, hint in pending:
                    value = (
                        evaluator.evaluate(genome, dispatch_hint_ticks=hint)
                        if config.representation == "patterns_only"
                        else evaluator.evaluate(genome)
                    )
                    values[index] = value
                    self._record(genome, value)
            else:
                futures = {
                    process_pool.submit(
                        _evaluate_pattern_process, (genome, hint)
                    ): (index, genome)
                    for index, genome, hint in pending
                }
                for future in as_completed(futures):
                    index, genome = futures[future]
                    value = future.result()
                    values[index] = value
                    self._record(genome, value)

            rows = [self._score(value) for value in values]
            out["F"] = np.asarray([row[0] for row in rows], dtype=float)
            out["G"] = np.asarray([row[1] for row in rows], dtype=float)

    class PopulationCallback(Callback):
        def notify(self, algorithm):
            recorder.population(list(algorithm.pop), algorithm.problem.results)

    shared = dict(
        pop_size=config.population_size,
        n_offsprings=config.offspring_size,
        sampling=SamplingImpl(),
        crossover=CrossImpl(),
        mutation=Mutation(prob=0.0),
        eliminate_duplicates=DuplicateImpl(),
    )
    if multiobjective:
        # Native rank/crowding survival and binary tournament. No custom quota
        # or infeasible-parent injection is used in this branch.
        algorithm = NSGA2(**shared)
    else:
        algorithm = GA(**shared, selection=ParentSelection(), survival=DiverseSurvival())
    process_pool = None
    if config.evaluation_parallelism > 1:
        process_pool = ProcessPoolExecutor(
            max_workers=config.evaluation_parallelism,
            mp_context=mp.get_context("spawn"),
            initializer=_initialize_pattern_process,
            initargs=(evaluator,),
        )
    try:
        minimize(
            ProblemImpl(), algorithm,
            termination=("time", max(0.001, deadline - perf_counter())),
            callback=PopulationCallback(),
            seed=config.seed, verbose=False, copy_algorithm=False,
        )
    finally:
        if process_pool is not None:
            process_pool.shutdown(wait=True, cancel_futures=True)


def nsga_objectives(value: CandidateEvaluation, demand: int):
    """Resource violations are objectives; malformed single trips stay hard constraints.

    Potential is the attained integer assignment, not a physical service claim or
    a bound. On assignment timeout it can underestimate transport potential.
    """
    if value.passengers is not None:
        return (value.passengers.unserved, 0, 0.0), 0
    if value.potential is not None:
        return (value.potential.unassigned, len(value.movement.conflicts),
                value.movement.total_overlap_ticks / 1_000_000), 0
    return (demand, max(1, len(value.movement.conflicts)),
            value.movement.total_overlap_ticks / 1_000_000), 1


def run_search(problem, prepared, config: EvolutionSearchConfig, *, reference_genome=None, event_callback=None, incumbent_callback=None):
    if config.selection_profile not in ("legacy", "grouped", "pattern_status"):
        raise ValueError("unknown selection profile")
    if config.selection_profile in ("grouped", "pattern_status") and config.engine is not EvolutionEngine.GA:
        raise ValueError("custom selection requires engine ga")
    if not 0 <= config.exploration_parent_probability <= 1:
        raise ValueError("exploration parent probability must lie in [0, 1]")
    if config.time_limit_seconds <= 0 or config.passenger_time_limit_seconds <= 0:
        raise ValueError("search and passenger time limits must be positive")
    if config.objective not in ("unserved", "journey_time", "service_then_journey"):
        raise ValueError("unknown evolution objective")
    if config.pattern_search not in ("independent", "line_groups"):
        raise ValueError("unknown pattern search")
    if config.pattern_search == "line_groups" and (
        config.representation not in ("patterns_dispatch", "patterns_only")
        or config.engine is not EvolutionEngine.GA
        or (config.fixed_k is None and config.representation != "patterns_only") or config.operator_profile is not OperatorProfile.MIXED_GLOBAL
    ):
        raise ValueError("line_groups requires fixed K, GA and mixed_global")
    if config.population_size < 2 or config.offspring_size < 1:
        raise ValueError("population must have at least two members and offspring must be positive")
    if not 1 <= config.evaluation_parallelism <= 16:
        raise ValueError("evaluation parallelism must lie in [1, 16]")
    if config.evaluation_parallelism > 1 and config.representation != "patterns_only":
        raise ValueError("parallel evaluation is currently restricted to patterns_only")
    if config.dispatch_decoder not in ('legacy', 'intervals'):
        raise ValueError('unknown dispatch decoder')
    if ((config.waiting_budget_fraction is not None and not 0 <= config.waiting_budget_fraction <= 1)
            or config.waiting_repair_seconds < 0 or not 1 <= config.waiting_workers <= 12):
        raise ValueError('invalid waiting repair budget/workers')
    if config.waiting_construction not in ("no_wait_first", "prefix_first"):
        raise ValueError("unknown waiting construction policy")
    if config.waiting_construction == "prefix_first" and config.dispatch_decoder != "intervals":
        raise ValueError("prefix_first requires the interval decoder")
    if config.waiting_repair_seconds and config.dispatch_decoder != 'intervals':
        raise ValueError('integrated waiting repair requires the interval decoder')
    started = perf_counter()
    deadline = started + config.time_limit_seconds
    if config.representation == "patterns_only":
        if config.waiting_repair_seconds or config.engine is not EvolutionEngine.GA:
            raise ValueError("patterns_only requires GA and zero Waiting repair")
        from .pattern_only import (
            PatternGenomeFactory,
            PatternLineGroupGenomeFactory,
            PatternOnlyEvaluator,
        )
        factory_type = (
            PatternLineGroupGenomeFactory
            if config.pattern_search == "line_groups"
            else PatternGenomeFactory
        )
        factory = factory_type(problem, prepared, seed=config.seed, fixed_k=config.fixed_k)
        evaluator = PatternOnlyEvaluator(problem, prepared,
            subproblem=config.dispatch_subproblem,
            evaluation_seconds=config.evaluation_time_limit_seconds,
            waiting=config.pattern_waiting,
            workers=config.waiting_workers, seed=config.seed, deadline=deadline,
            passenger_objective=config.objective)
    elif config.representation == "patterns_dispatch":
        from .line_groups import LineGroupGenomeFactory
        factory_type = LineGroupGenomeFactory if config.pattern_search == "line_groups" else GenomeFactory
        factory = factory_type(problem, prepared, seed=config.seed, fixed_k=config.fixed_k)
        evaluator = LineEvolutionEvaluator(problem, prepared, config.passenger_time_limit_seconds)
    else:
        raise ValueError("unknown evolution representation")
    if reference_genome is not None and config.fixed_k is not None and reference_genome.fleet_size != config.fixed_k:
        raise ValueError("reference must have exactly fixed_k active cabins")
    if config.engine is not EvolutionEngine.GA and (config.fixed_k is not None or not config.seed_all_stop):
        raise ValueError("fixed_k and custom initialization currently require engine ga")
    if config.representation == "patterns_dispatch":
        evaluator.evaluate_infeasible_potential = config.engine is EvolutionEngine.NSGA2
        evaluator.deadline = deadline
        evaluator.dispatch_decoder = config.dispatch_decoder
        evaluator.waiting_repair_seconds = config.waiting_repair_seconds
        evaluator.waiting_construction = config.waiting_construction
        evaluator.waiting_budget_seconds = (None if config.waiting_budget_fraction is None else
                                           config.waiting_budget_fraction * config.time_limit_seconds)
        evaluator.waiting_workers = config.waiting_workers
        evaluator.seed = config.seed
        evaluator.passenger_objective = config.objective
    recorder = SearchRecorder(
        started, factory.minimum_gap, event_callback, incumbent_callback,
        config.objective, config.stop_on_full_service,
    )
    try:
        if config.engine is EvolutionEngine.RANDOM:
            _random_search(factory, evaluator, recorder, reference_genome, deadline)
        elif config.engine is EvolutionEngine.TPE:
            _tpe_search(factory, evaluator, recorder, reference_genome, deadline, config.seed)
        else:
            _ga_search(factory, evaluator, recorder, reference_genome, deadline, config)
    except (EvaluationDeadline, SearchTargetReached):
        pass
    recorder.finish()
    return {
        "schema": "reservoir_line_evolution_result_v1",
        "config": asdict(config),
        "evaluations": recorder.evaluations,
        "feasible_evaluations": recorder.feasible,
        "cache_size": evaluator.cache_size,
        "phenotype_cache_size": len(evaluator._phenotypes),
        "repair_spent_seconds": evaluator.repair_spent_seconds,
        "selection": "native_nsga2_rank_crowding_tournament" if config.engine is EvolutionEngine.NSGA2 else config.selection_profile,
        "objective_names": (["unassigned_relaxed_or_valid", "conflict_count", "overlap_seconds"]
            if config.engine is EvolutionEngine.NSGA2 else ["validated_unserved"]
            if config.objective == "unserved" else ["validated_journey_time"]
            if config.objective == "journey_time" else ["validated_lexicographic_service_then_journey"]),
        "evaluation_totals": dict(recorder.evaluation_totals),
        "potential_frontier": {str(k): e for k, (_, e) in sorted(recorder.potential_by_k.items())},
        "events": recorder.events,
        "operator_counts": recorder.operator_counts,
        "parent_selection_counts": dict(recorder.parent_counts),
        "fleet_frontier": {
            str(k): event for k, (_, event) in sorted(recorder.best_by_k.items())
        },
        "mixed_fleet_frontier": {str(k): e for k, (_, e) in sorted(recorder.best_mixed_by_k.items())},
        "conflict_frontier": {
            str(k): event for k, (_, event) in sorted(recorder.conflict_frontier_by_k.items())
        },
        "total_wall_seconds": perf_counter() - started,
        "termination_reason": (
            "VALIDATED_FULL_SERVICE" if recorder.target_reached else "TIME_LIMIT"
        ),
        "best": recorder.best,
    }
