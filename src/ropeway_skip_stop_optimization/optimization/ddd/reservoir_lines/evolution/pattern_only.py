from __future__ import annotations

from dataclasses import dataclass, replace
from enum import StrEnum
from hashlib import sha256
import json
import math
from collections import defaultdict
from time import perf_counter

import numpy as np

from ..config import (
    ReservoirLineCatalogProfile,
    ReservoirLineConfig,
    ReservoirLineFormulation,
    ReservoirLineMode,
    ReservoirLinePreparation,
    ReservoirLineVariant,
)
from ..optimizer import ReservoirLineOptimizer
from ...time_ticks import ddd_tick_to_seconds
from .decoder import minimum_dispatch_gap_tick
from .evaluator import EvaluationDeadline
from .model import CandidateEvaluation, LineGenome, MovementEvaluation, PassengerEvaluation
from .passengers import optimize_fixed_movement_passengers


class DispatchSubproblem(StrEnum):
    TIMING_THEN_PASSENGERS = "timing_then_passengers"
    JOINT_SERVICE = "joint_service"


@dataclass(frozen=True, slots=True)
class PatternSequenceGenome:
    pattern_ids: tuple[str, ...]

    @property
    def fleet_size(self):
        return len(self.pattern_ids)

    @property
    def identity(self):
        return sha256(json.dumps(self.pattern_ids).encode()).hexdigest()


class PatternGenomeFactory:
    def __init__(self, problem, prepared, *, fixed_k: int | None = None, seed=0):
        if fixed_k is not None and not 1 <= fixed_k <= prepared.maximum_cabins:
            raise ValueError("pattern-only fixed K must fit the prepared fleet")
        self.problem, self.prepared = problem, prepared
        self.fixed_k = fixed_k
        self.maximum_k = fixed_k or prepared.maximum_cabins
        self.minimum_gap = minimum_dispatch_gap_tick(problem)
        self.dispatch_step = prepared.dispatch_step_tick
        self.patterns = tuple(sorted({t.pattern_id for t in prepared.templates}))
        self.pattern_stops = {
            p: next(t.stop_station_ids for t in prepared.templates if t.pattern_id == p)
            for p in self.patterns
        }
        demand_patterns = []
        od_pairs = sorted({
            frozenset((group.origin_station_id, group.destination_station_id))
            for group in problem.demand_groups
        }, key=lambda value: tuple(sorted(value)))
        for od in od_pairs:
            choices = sorted(
                (p for p in self.patterns if od <= self.pattern_stops[p] and p != "all_stop"),
                key=lambda p: (len(self.pattern_stops[p]), p),
            )
            if choices:
                minimum = len(self.pattern_stops[choices[0]])
                demand_patterns.extend(p for p in choices if len(self.pattern_stops[p]) <= minimum + 1)
        self.demand_patterns = tuple(dict.fromkeys(demand_patterns)) or self.patterns
        self.rng = np.random.default_rng(seed)
        self.origin_by_identity = {}
        self.parent_by_identity = {}

    def _tag(self, value, origin):
        if not 1 <= value.fleet_size <= self.maximum_k:
            raise ValueError("pattern fleet must fit [1, maximum_k]")
        if self.fixed_k is not None and value.fleet_size != self.fixed_k:
            raise ValueError("pattern-only operators must preserve fixed K")
        self.origin_by_identity[value.identity] = origin
        return value

    def random(self, *, k=None, patterns=None, arrangement="random", rng=None):
        rng = rng or self.rng
        if self.fixed_k is not None and k is not None and k != self.fixed_k:
            raise ValueError("pattern-only pilot has fixed K")
        k = self.fixed_k or k or (len(patterns) if patterns is not None else int(rng.integers(1, self.maximum_k + 1)))
        values = list(rng.choice(self.patterns, k, replace=True) if patterns is None else patterns)
        if len(values) != k:
            raise ValueError("pattern sequence has the wrong fixed length")
        if arrangement == "grouped":
            values.sort()
        elif arrangement == "alternating":
            groups = {p: values.count(p) for p in sorted(set(values))}
            values = []
            while groups:
                for p in tuple(groups):
                    values.append(p); groups[p] -= 1
                    if not groups[p]: del groups[p]
        elif arrangement != "random":
            raise ValueError("unknown pattern arrangement")
        return self._tag(PatternSequenceGenome(tuple(values)), "initial_sampler")

    def _neighbour(self, pattern, rng):
        stops = self.pattern_stops[pattern]
        choices = [p for p in self.patterns if len(stops.symmetric_difference(self.pattern_stops[p])) == 1]
        return str(rng.choice(choices or self.patterns))

    def resize(self, genome, target_k, *, rng=None):
        """Insert/delete active cabins, preserving the order of retained cabins."""
        rng = self.rng if rng is None else rng
        if not 1 <= target_k <= self.maximum_k:
            raise ValueError("target fleet outside bounds")
        values = list(genome.pattern_ids)
        while len(values) > target_k:
            del values[int(rng.integers(len(values)))]
        while len(values) < target_k:
            values.insert(int(rng.integers(len(values) + 1)), str(rng.choice(self.patterns)))
        result = self._tag(PatternSequenceGenome(tuple(values)), "pattern_fleet_change")
        self.parent_by_identity[result.identity] = genome.identity
        return result

    def variation(self, first, second, profile, *, rng=None):
        rng = rng or self.rng
        if self.fixed_k is None and rng.random() < 0.25:
            if rng.random() < 0.8:
                target = max(1, min(self.maximum_k, first.fleet_size + int(rng.choice((-1, 1)))))
            else:
                target = int(rng.integers(1, self.maximum_k + 1))
            return self.resize(first, target, rng=rng)
        draw = rng.random()
        level = "local" if draw < .5 else "block" if draw < .8 else "global"
        a, b = list(first.pattern_ids), list(second.pattern_ids)
        if level == "local":
            kind = int(rng.integers(3)); i = int(rng.integers(first.fleet_size))
            if kind == 0:
                a[i] = self._neighbour(a[i], rng)
            elif kind == 1:
                a[i] = str(rng.choice(self.patterns))
            elif first.fleet_size > 1:
                j = min(first.fleet_size - 1, i + 1); a[i], a[j] = a[j], a[i]
            return self._tag(PatternSequenceGenome(tuple(a)), "pattern_local")
        if level == "block" and first.fleet_size >= 2:
            length = int(rng.integers(1 if first.fleet_size == 1 else 2, min(10, first.fleet_size) + 1))
            start = int(rng.integers(0, first.fleet_size - length + 1))
            if rng.random() < .5:
                a[start:start+length] = [b[(start+i) % len(b)] for i in range(length)]
            else:
                a[start:start+length] = list(rng.choice(self.patterns, length, replace=True))
            return self._tag(PatternSequenceGenome(tuple(a)), "pattern_block")
        if rng.random() < .5 and first.fleet_size >= 2:
            rng.shuffle(a)
            return self._tag(PatternSequenceGenome(tuple(a)), "pattern_permutation")
        return self._tag(self.random(rng=rng), "pattern_restart")


class PatternLineGroupGenomeFactory(PatternGenomeFactory):
    """Search a few line families while CP-SAT owns every dispatch time.

    The sequence position fixes only the reservoir dispatch order.  Resource
    orders after dispatch remain free in the native timing subproblem.
    """

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.intensified = False
        demand = defaultdict(int)
        for group in self.problem.demand_groups:
            if group.count:
                pair = frozenset((group.origin_station_id, group.destination_station_id))
                demand[pair] += group.count
        self.od_weights = dict(demand)

    def intensify(self):
        """Prefer small changes after this run has found its first valid plan."""
        self.intensified = True

    def _offspring(self, value, parent):
        self.parent_by_identity[value.identity] = parent.identity
        return value

    def _change_position(self, genome, rng):
        patterns = list(genome.pattern_ids)
        index = int(rng.integers(genome.fleet_size))
        patterns[index] = self._neighbour(patterns[index], rng)
        return self._tag(PatternSequenceGenome(tuple(patterns)), "pattern_line_position")

    def random(self, *, k=None, patterns=None, arrangement="random", rng=None):
        rng = self.rng if rng is None else rng
        if patterns is not None:
            return super().random(k=k, patterns=patterns, arrangement=arrangement, rng=rng)
        if self.fixed_k is not None and k is not None and k != self.fixed_k:
            raise ValueError("pattern-only pilot has fixed K")
        k = self.fixed_k or k or int(rng.integers(1, self.maximum_k + 1))
        # All-Stop is already an external reference.  Start the Skip-Stop
        # search with two to four line families, while still allowing All-Stop
        # as one family and through later mutations.
        lower = 2 if len(self.patterns) >= 2 and k >= 2 else 1
        count = int(rng.integers(lower, min(5, k, len(self.patterns)) + 1))
        selected, covered = [], set()
        for _ in range(count):
            remaining = [pattern for pattern in self.patterns if pattern not in selected]
            sizes = sorted({len(self.pattern_stops[pattern]) for pattern in remaining})
            size = int(rng.choice(sizes))
            pool = [pattern for pattern in remaining if len(self.pattern_stops[pattern]) == size]
            weights = [
                sum(
                    amount * (0.1 if pair in covered else 1.0)
                    for pair, amount in self.od_weights.items()
                    if pair <= self.pattern_stops[pattern]
                )
                for pattern in pool
            ]
            total = sum(weights)
            selected_pattern = str(
                rng.choice(pool, p=[weight / total for weight in weights] if total else None)
            )
            selected.append(selected_pattern)
            covered.update(
                pair for pair in self.od_weights if pair <= self.pattern_stops[selected_pattern]
            )
        weights = rng.dirichlet([1.0] * count)
        values = selected + list(
            rng.choice(selected, size=k - count, replace=True, p=weights)
        )
        chosen_arrangement = arrangement
        if arrangement == "random":
            chosen_arrangement = str(rng.choice(("random", "alternating", "grouped")))
        return super().random(
            patterns=values, arrangement=chosen_arrangement, rng=rng
        )

    def demand_cover_initial(self, count, *, rng=None):
        """Create demand-derived line mixes without importing a known plan."""
        rng = self.rng if rng is None else rng
        selected = []
        for pair in sorted(self.od_weights, key=lambda value: tuple(sorted(value))):
            choices = sorted(
                (pattern for pattern in self.patterns if pair <= self.pattern_stops[pattern]),
                key=lambda pattern: (len(self.pattern_stops[pattern]), pattern),
            )
            if choices and choices[0] not in selected:
                selected.append(choices[0])
        if not selected:
            return ()
        weights = [
            sum(amount for pair, amount in self.od_weights.items()
                if pair <= self.pattern_stops[pattern])
            for pattern in selected
        ]
        total = sum(weights)
        results = []
        for index in range(count):
            k = self.fixed_k or max(1, round(self.maximum_k * (index + 1) / count))
            allocations = [k * weight // total for weight in weights]
            for i in sorted(range(len(selected)), key=lambda i: (k * weights[i] % total, -i), reverse=True)[:k - sum(allocations)]:
                allocations[i] += 1
            values = [p for p, amount in zip(selected, allocations, strict=True) for _ in range(amount)]
            arrangement = ("alternating", "grouped", "random")[index % 3]
            if arrangement == "random":
                rng.shuffle(values)
            results.append(self._tag(super().random(patterns=values, arrangement=arrangement, rng=rng), "pattern_demand_" + arrangement))
        return tuple(results)

    def _change_line(self, genome, operation, rng):
        patterns = list(genome.pattern_ids)
        families = sorted(set(patterns))
        if operation == "halt":
            choices = [
                (source, target)
                for source in families
                for target in self.patterns
                if len(self.pattern_stops[source] ^ self.pattern_stops[target]) == 1
            ]
            if not choices:
                return self._tag(genome, "pattern_line_halt_unavailable")
            source, target = choices[int(rng.integers(len(choices)))]
            patterns = [target if pattern == source else pattern for pattern in patterns]
        elif operation == "reallocate":
            if len(families) < 2:
                return self._change_line(genome, "split", rng)
            source, target = (str(value) for value in rng.choice(families, 2, replace=False))
            indices = [i for i, pattern in enumerate(patterns) if pattern == source]
            # Explicit small, medium and large moves keep both local and global
            # changes reachable without making every mutation destructive.
            scales = sorted({1, max(1, len(indices) // 4), max(1, len(indices) // 2)})
            move = min(len(indices), int(rng.choice(scales)))
            for index in rng.choice(indices, size=move, replace=False):
                patterns[int(index)] = target
        elif operation == "split":
            sources = [pattern for pattern in families if patterns.count(pattern) >= 2]
            unused = [pattern for pattern in self.patterns if pattern not in families]
            if not sources or not unused:
                return self._tag(genome, "pattern_line_split_unavailable")
            source = str(rng.choice(sources))
            neighbours = [
                pattern for pattern in unused
                if len(self.pattern_stops[source] ^ self.pattern_stops[pattern]) == 1
            ]
            target = str(rng.choice(neighbours or unused))
            indices = [i for i, pattern in enumerate(patterns) if pattern == source]
            scales = sorted({1, max(1, len(indices) // 4), max(1, len(indices) // 2)})
            move = min(len(indices) - 1, int(rng.choice(scales)))
            for index in rng.choice(indices, size=move, replace=False):
                patterns[int(index)] = target
        else:
            raise ValueError("unknown pattern line operation")
        return self._tag(PatternSequenceGenome(tuple(patterns)), f"pattern_line_{operation}")

    def variation(self, first, second, profile, *, rng=None):
        rng = self.rng if rng is None else rng
        if self.fixed_k is None and rng.random() < 0.25:
            if rng.random() < 0.8:
                target = max(1, min(self.maximum_k, first.fleet_size + int(rng.choice((-1, 1)))))
            else:
                target = int(rng.integers(1, self.maximum_k + 1))
            return self.resize(first, target, rng=rng)
        draw = rng.random()
        if self.intensified:
            if draw < 0.60:
                patterns = list(first.pattern_ids)
                if first.fleet_size > 1:
                    first_index, second_index = rng.choice(
                        first.fleet_size, size=2, replace=False
                    )
                    patterns[int(first_index)], patterns[int(second_index)] = (
                        patterns[int(second_index)], patterns[int(first_index)]
                    )
                value = self._tag(
                    PatternSequenceGenome(tuple(patterns)), "pattern_line_order"
                )
            elif draw < 0.85:
                value = self._change_position(first, rng)
            elif draw < 0.95:
                value = self._change_line(first, "reallocate", rng)
            else:
                value = self._change_line(first, "split", rng)
            return self._offspring(value, first)
        if draw < 0.5:
            operation = str(rng.choice(("reallocate", "split", "order")))
            if operation != "order":
                return self._offspring(self._change_line(first, operation, rng), first)
            patterns = list(first.pattern_ids)
            if first.fleet_size > 1:
                kind = int(rng.integers(3))
                if kind == 0:
                    first_index, second_index = rng.choice(
                        first.fleet_size, size=2, replace=False
                    )
                    patterns[int(first_index)], patterns[int(second_index)] = (
                        patterns[int(second_index)], patterns[int(first_index)]
                    )
                else:
                    length = int(rng.integers(2, min(first.fleet_size, 16) + 1))
                    start = int(rng.integers(0, first.fleet_size - length + 1))
                    block = patterns[start:start + length]
                    if kind == 1:
                        rng.shuffle(block)
                    else:
                        shift = int(rng.integers(1, length))
                        block = block[shift:] + block[:shift]
                    patterns[start:start + length] = block
            return self._offspring(
                self._tag(PatternSequenceGenome(tuple(patterns)), "pattern_line_order"),
                first,
            )
        if draw < 0.8:
            operation = str(rng.choice(("halt", "reallocate", "split", "crossover")))
            if operation != "crossover":
                return self._offspring(self._change_line(first, operation, rng), first)
            length = int(rng.integers(1 if first.fleet_size == 1 else 2, min(10, first.fleet_size) + 1))
            start = int(rng.integers(0, first.fleet_size - length + 1))
            patterns = list(first.pattern_ids)
            patterns[start:start + length] = tuple(second.pattern_ids[(start + i) % second.fleet_size] for i in range(length))
            return self._offspring(
                self._tag(PatternSequenceGenome(tuple(patterns)), "pattern_line_crossover"),
                first,
            )
        if rng.random() < 0.5:
            patterns = list(first.pattern_ids)
            rng.shuffle(patterns)
            return self._offspring(
                self._tag(PatternSequenceGenome(tuple(patterns)), "pattern_line_permutation"),
                first,
            )
        return self._offspring(
            self._tag(self.random(rng=rng), "pattern_line_restart"), first
        )


class PatternOnlyEvaluator:
    def __init__(self, problem, prepared, *, subproblem, evaluation_seconds=8,
                 workers=12, memory_limit_gib=32, seed=0, deadline=None,
                 waiting=False, passenger_objective="unserved"):
        self.problem = problem
        self.subproblem = DispatchSubproblem(subproblem)
        self.evaluation_seconds = evaluation_seconds
        self.workers, self.memory_limit_gib, self.seed = workers, memory_limit_gib, seed
        self.deadline = deadline
        self.waiting = waiting
        self.passenger_objective = passenger_objective
        # A pattern-only model has exactly K slots.  Keeping unused slots from a
        # larger prepared fleet defeats the specialization and introduces pure
        # symmetry.  The physical domain is unchanged; only the model-sized
        # prepared view is narrowed.
        self.prepared = replace(prepared, maximum_cabins=prepared.maximum_cabins)
        self._cache = {}
        self._phenotypes = {}
        self.repair_spent_seconds = 0.0

    @property
    def cache_size(self):
        return len(self._cache)

    def evaluate(
        self,
        genome: PatternSequenceGenome,
        *,
        dispatch_hint_ticks: tuple[int, ...] | None = None,
    ):
        key = (self.problem.fingerprint, self.subproblem.value, self.waiting, genome.identity)
        if key in self._cache:
            value = self._cache[key]
            return replace(value, cached=True, decoder={**value.decoder, "cache_kind": "pattern",
                                                        "decode_seconds_this_call": 0.0})
        started = perf_counter()
        if self.deadline is not None and started >= self.deadline:
            raise EvaluationDeadline
        local_deadline = started + self.evaluation_seconds
        if self.deadline is not None:
            local_deadline = min(local_deadline, self.deadline)
        mode = (ReservoirLineMode.FEASIBILITY if self.subproblem is DispatchSubproblem.TIMING_THEN_PASSENGERS
                else ReservoirLineMode.EXACT_SERVICE)
        screening = self.evaluation_seconds >= 25
        reserve = (2.0 if screening else
                   min(1.0, max(0.02, self.evaluation_seconds * 0.1)))
        solver_cap = ((20.0 if mode is ReservoirLineMode.FEASIBILITY else 28.0)
                      if screening else
                      (5.0 if mode is ReservoirLineMode.FEASIBILITY else 7.0))
        solver_budget = min(solver_cap,
                            max(.001, local_deadline - perf_counter() - reserve))
        local_prepared = replace(self.prepared, maximum_cabins=genome.fleet_size)
        candidate_seed = (self.seed + int(genome.identity[:8], 16)) % (2**31 - 1)
        config = ReservoirLineConfig(
            dispatch_window_end_seconds=ddd_tick_to_seconds(local_prepared.dispatch_window_end_tick),
            passenger_service_start_seconds=ddd_tick_to_seconds(local_prepared.service_start_tick),
            variant=ReservoirLineVariant.DISPATCH_DOMAINS,
            preparation=ReservoirLinePreparation.ENCODING_SPECIFIC,
            formulation=ReservoirLineFormulation.SHARED_ROUNDS,
            mode=mode,
            catalog_profile=ReservoirLineCatalogProfile.RELEVANT,
            maximum_cabins=genome.fleet_size,
            fixed_cabins=genome.fleet_size,
            fixed_pattern_sequence=genome.pattern_ids,
            time_limit_seconds=solver_budget,
            workers=self.workers,
            memory_limit_gib=self.memory_limit_gib,
            seed=candidate_seed,
        )
        if self.waiting:
            from .pattern_waiting import solve_pattern_waiting
            result = solve_pattern_waiting(self.problem, genome.pattern_ids,
                dispatch_end_tick=local_prepared.dispatch_window_end_tick,
                joint=mode is ReservoirLineMode.EXACT_SERVICE,
                seconds=self.evaluation_seconds, deadline=local_deadline,
                workers=self.workers, seed=self.seed)
            plan = result['plan']
        else:
            result, plan = ReservoirLineOptimizer(config).solve(
                self.problem,
                prepared=local_prepared,
                hard_deadline=local_deadline,
                dispatch_hint_ticks=dispatch_hint_ticks,
            )
        status = result["solver_status"]
        diagnostics = {
            "status": "PATTERN_VALID" if plan is not None else
                      "PATTERN_INFEASIBLE" if status == "INFEASIBLE" else "PATTERN_UNKNOWN",
            "subproblem_status": status,
            "subproblem": self.subproblem.value,
            "model_stats": result["model_stats"],
            "preparation_seconds": result["preparation_seconds"],
            "model_build_seconds": result["model_build_seconds"],
            "solve_seconds": result.get("solve_seconds", 0),
            "validation_seconds": result.get("validation_seconds", 0),
            "cache_kind": None,
            "input_pattern_identity": genome.identity,
            "input_pattern_ids": genome.pattern_ids,
            "dispatch_order_scope": "ordered_dispatch_free_resource_order",
            "waiting_enabled": self.waiting,
            "waiting_policy": result.get("waiting_policy"),
            "objective_scope": result.get("objective_scope"),
            "maximum_wait_tick": result.get("maximum_wait_tick"),
            "total_wait_tick": result.get("total_wait_tick"),
            "rounds": result.get("rounds"),
            "model_fingerprint": result.get("model_fingerprint"),
            "solver_branches": result.get("branches"),
            "solver_conflicts": result.get("solver_conflicts"),
            "response_stats": result.get("response_stats"),
            "dispatch_hint_used": result.get("dispatch_hint_used", False),
        }
        if plan is None:
            movement = MovementEvaluation(genome, False, None, (), 0, 0,
                perf_counter()-started, diagnostics["status"])
            diagnostics["decode_seconds_this_call"] = movement.decode_seconds
            value = CandidateEvaluation(movement, None, decoder=diagnostics)
            self._cache[key] = value
            return value
        dispatches = tuple(t.switch_ticks[0] for t in plan.trips)
        minimum_gap = minimum_dispatch_gap_tick(self.problem)
        line_genome = LineGenome(genome.pattern_ids, dispatches[0],
            tuple(b-a-minimum_gap for a,b in zip(dispatches, dispatches[1:])))
        diagnostics["dispatch_ticks_by_cabin"] = {str(t.cabin_id): t.switch_ticks[0] for t in plan.trips}
        diagnostics["dispatch_order"] = [t.cabin_id for t in sorted(plan.trips, key=lambda t: t.switch_ticks[0])]
        movement = MovementEvaluation(line_genome, True, plan, (), 0, 0,
                                      perf_counter()-started)
        diagnostics["decode_seconds_this_call"] = movement.decode_seconds
        if self.waiting:
            passengers = result['passengers']
        elif mode is ReservoirLineMode.FEASIBILITY:
            remaining = min(8.0 if screening else 2.0,
                            max(.001, local_deadline-perf_counter()))
            passengers = optimize_fixed_movement_passengers(
                self.problem,
                plan,
                time_limit_seconds=remaining,
                objective=self.passenger_objective,
            )
        else:
            metrics = result["metrics"]
            passengers = PassengerEvaluation(
                plan, metrics["served"], metrics["unserved"], result["proven_optimal"],
                result.get("native_served_upper_bound"), tuple(sorted(plan.ride_counts.items())),
                result["model_build_seconds"], result["solve_seconds"],
                result["validation_seconds"], status)
        value = CandidateEvaluation(movement, passengers, decoder=diagnostics)
        self._cache[key] = value
        return value
