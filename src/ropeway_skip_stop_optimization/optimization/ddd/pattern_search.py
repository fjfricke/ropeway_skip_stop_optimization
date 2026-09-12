"""Fixed-pattern timing oracle and a bounded, passenger-guided VNS.

Only route choices are fixed. Conditional visit activation, all times, waits,
resource precedences and integer passenger assignments retain their full domain.
Pattern bounds never become global bounds.
"""

from dataclasses import dataclass, field
from collections import deque
from random import Random
from time import perf_counter
import math

from ortools.sat.python import cp_model

from .cp_sat_certificate import (
    stable_fingerprint,
    validate_ddd_cp_sat_domain,
    validate_ddd_cp_sat_incumbent,
    solution_from_cp_sat_payload,
)
from .cp_sat_integrated import DddIntegratedCpSatModel, _raw_incumbent
from .cp_sat_movement import build_ddd_cp_sat_movement
from .cp_sat_passenger import build_ddd_cp_sat_passenger_assignment
from .fixed_timetable_capacity import conservative_count_bound


def unserved(incumbent):
    return sum(incumbent.unserved_counts.values())


@dataclass(frozen=True)
class StopPattern:
    domain_id: str
    choices: tuple[tuple[int, int, str], ...]

    @property
    def id(self):
        return stable_fingerprint((self.domain_id, self.choices))

    def matches(self, solution):
        selected = {(c, v): o for c, v, o in self.choices}
        return all(
            selected.get((t.cabin_id, v)) == visit.route_option_id
            for t in solution.trajectories
            for v, visit in enumerate(t.visits)
        )


@dataclass(frozen=True)
class PatternEvaluation:
    pattern: StopPattern
    status: str
    incumbent: object = None
    lower_bound: int | None = None
    calls: int = 0
    total_seconds: float = 0.0
    build_seconds: float = 0.0
    solve_seconds: float = 0.0
    validation_seconds: float = 0.0
    call_seconds: float = 0.0

    def record(self):
        return dict(
            pattern_id=self.pattern.id,
            status=self.status,
            pattern_upper_bound=None
            if self.incumbent is None
            else unserved(self.incumbent),
            pattern_lower_bound=self.lower_bound,
            proof_scope="FIXED_PATTERN",
            calls=self.calls,
            total_seconds=self.total_seconds,
            build_seconds=self.build_seconds,
            solve_seconds=self.solve_seconds,
            validation_seconds=self.validation_seconds,
            call_seconds=self.call_seconds,
        )


class PatternTimingOracle:
    def __init__(
        self, problem, *, workers=12, seed=0, log_callback=None, deadline=None
    ):
        if type(workers) is not int or type(seed) is not int or workers < 1 or seed < 0:
            raise ValueError("invalid workers or seed")
        started = perf_counter()
        self.problem, self.workers, self.seed = problem, workers, seed
        self.log_callback = log_callback
        self.manifest = validate_ddd_cp_sat_domain(problem)
        self.domain_id = stable_fingerprint(self.manifest)
        movement = problem.resolved_trajectory_problem.structural_movement_problem
        b = build_ddd_cp_sat_movement(
            movement,
            waiting_policy=problem.resolved_trajectory_problem.waiting_policy,
            boundary_occurrences=problem.boundary_context.resource_occurrences,
            deadline_monotonic=deadline,
        )
        p = build_ddd_cp_sat_passenger_assignment(
            movement,
            problem.passenger_build,
            problem.artifact.config.cabin_capacity,
            b,
            with_journey_cost=False,
            deadline_monotonic=deadline,
        )
        self.built = DddIntegratedCpSatModel(
            b,
            p,
            self.manifest,
            "FIXED_PATTERN",
            stable_fingerprint(str(b.model.proto)),
            {
                "variables": len(b.model.proto.variables),
                "constraints": len(b.model.proto.constraints),
                "cost_auxiliaries": 0,
                "ride_candidates": len(p.ride_count),
            },
        )
        self.routes = {o.id: o for o in movement.route_options}
        self.options = {}
        for key in b.selection_by_key:
            c, v, option = key
            self.options.setdefault((c, v), {})[self.routes[option].decision.value] = (
                option
            )
        self.cache = {}
        self.build_seconds = perf_counter() - started

    def pattern_from(self, solution):
        actual = {
            (t.cabin_id, v): x.route_option_id
            for t in solution.trajectories
            for v, x in enumerate(t.visits)
        }
        return StopPattern(
            self.domain_id,
            tuple(
                (c, v, actual.get((c, v), opts["stop"]))
                for (c, v), opts in sorted(self.options.items())
            ),
        )

    def validate_pattern(self, pattern):
        if pattern.domain_id != self.domain_id:
            raise ValueError("pattern domain mismatch")
        if tuple(sorted(pattern.choices)) != pattern.choices:
            raise ValueError("pattern must be sorted")
        keys = [(c, v) for c, v, _ in pattern.choices]
        if len(set(keys)) != len(keys) or set(keys) != set(self.options):
            raise ValueError("pattern must cover every structural visit exactly once")
        for c, v, option in pattern.choices:
            if option not in self.options[c, v].values():
                raise ValueError("invalid route in pattern")

    def evaluate(self, pattern, *, budget=5.0, hint=None):
        if not math.isfinite(budget) or budget <= 0:
            raise ValueError("positive finite oracle budget required")
        self.validate_pattern(pattern)
        old = self.cache.get(pattern.id)
        if old and (
            old.status in ("OPTIMAL", "INFEASIBLE")
            or (
                old.incumbent is not None and unserved(old.incumbent) == old.lower_bound
            )
        ):
            return old
        started = perf_counter()
        model = self.built.movement.model.clone()
        var = model.get_int_var_from_proto_index
        for c, v, option in pattern.choices:
            # Do not force the visit active: inactive suffix routes stay zero.
            model.add(
                var(self.built.movement.selection_by_key[c, v, option].index)
                == var(self.built.movement.active_by_cabin[c][v].index)
            )
        incumbent = None if old is None else old.incumbent
        # A different pattern's certificate is never a feasible incumbent.
        if hint is not None and pattern.matches(hint.solution):
            checked = validate_ddd_cp_sat_incumbent(
                self.problem, hint.solution, hint.ride_counts, provenance="pattern_hint"
            )
            if incumbent is None or unserved(checked) < unserved(incumbent):
                incumbent = checked
        # Only times are hinted across patterns. No passenger/route/activation fixings.
        if hint is not None:
            from .cp_sat_integrated import _movement_values

            values, _ = _movement_values(
                self.problem, self.built.movement, hint.solution
            )
            time_indices = {
                x.index
                for seq in self.built.movement.time_by_cabin.values()
                for x in seq
            }
            for index in time_indices:
                model.add_hint(var(index), values[index])
        error = model.validate()
        if error:
            raise ValueError(error)
        build_seconds = perf_counter() - started
        solver = cp_model.CpSolver()
        solver.parameters.num_search_workers = self.workers
        solver.parameters.random_seed = self.seed
        solver.parameters.absolute_gap_limit = 0
        solver.parameters.relative_gap_limit = 0
        if self.log_callback:
            self.log_callback(f"PATTERN {pattern.id} budget={budget}\n")
            solver.parameters.log_search_progress = True
            solver.parameters.log_to_stdout = False
            solver.log_callback = self.log_callback
        remaining = budget - build_seconds
        status = cp_model.UNKNOWN
        solve_seconds = validation_seconds = 0.0
        lower = None if old is None else old.lower_bound
        if remaining > 0:
            solver.parameters.max_time_in_seconds = remaining
            before = perf_counter()
            status = solver.solve(model)
            solve_seconds = perf_counter() - before
            if status == cp_model.MODEL_INVALID:
                raise RuntimeError(solver.response_stats())
            if status == cp_model.INFEASIBLE and incumbent is not None:
                raise RuntimeError(
                    "infeasibility contradicts matching validated pattern hint"
                )
            if status in (cp_model.FEASIBLE, cp_model.OPTIMAL):
                before = perf_counter()
                raw = _raw_incumbent(self.built, solver.value)
                found = validate_ddd_cp_sat_incumbent(
                    self.problem,
                    solution_from_cp_sat_payload(self.problem, raw),
                    raw["ride_counts"],
                    provenance="pattern_timing",
                )
                if (
                    not pattern.matches(found.solution)
                    or unserved(found) != raw["objective_tick"]
                ):
                    raise RuntimeError("pattern/capacity extraction mismatch")
                if incumbent is None or unserved(found) < unserved(incumbent):
                    incumbent = found
                validation_seconds = perf_counter() - before
            if status != cp_model.INFEASIBLE:
                lb = conservative_count_bound(float(solver.best_objective_bound))
                lower = max(lower or 0, lb) if lb is not None else lower
            if status == cp_model.OPTIMAL:
                lower = unserved(incumbent)
        if incumbent is not None and lower is not None and lower > unserved(incumbent):
            raise RuntimeError("invalid pattern bound")
        result = PatternEvaluation(
            pattern,
            solver.status_name(status),
            incumbent,
            lower,
            1 + (old.calls if old else 0),
            perf_counter() - started + (old.total_seconds if old else 0),
            build_seconds,
            solve_seconds,
            validation_seconds,
            perf_counter() - started,
        )
        self.cache[pattern.id] = result
        return result


@dataclass(frozen=True)
class PatternVnsConfig:
    total_seconds: float = 900
    seed: int = 0
    workers: int = 12
    oracle_seconds: float = 5
    retry_seconds: float = 15
    reserve_seconds: float = 10
    retry_unknown: bool = True

    def validate(self):
        values = (
            self.total_seconds,
            self.oracle_seconds,
            self.retry_seconds,
            self.reserve_seconds,
        )
        if (
            any(not math.isfinite(x) or x <= 0 for x in values)
            or self.total_seconds <= self.reserve_seconds
        ):
            raise ValueError("invalid VNS budgets")
        if (
            type(self.seed) is not int
            or type(self.workers) is not int
            or self.seed < 0
            or self.workers < 1
        ):
            raise ValueError("invalid VNS seed/workers")


class PatternNeighborhoods:
    def __init__(self, oracle, rng):
        self.oracle, self.rng = oracle, rng
        self.by_group = {}
        for ride in oracle.problem.passenger_build.ride_candidates:
            self.by_group.setdefault(ride.demand_group_id, []).append(ride)
        for rides in self.by_group.values():
            rides.sort(key=lambda r: r.id)

    def propose(self, pattern, incumbent, neighborhood, width):
        groups = [
            g for g in sorted(self.by_group) if incumbent.unserved_counts.get(g, 0) > 0
        ]
        if not groups:
            return None
        group = self.rng.choices(
            groups, weights=[incumbent.unserved_counts[g] for g in groups]
        )[0]
        ride = self.rng.choice(self.by_group[group])
        selected = {(c, v): o for c, v, o in pattern.choices}
        endpoints = [
            (ride.cabin_id, ride.board_visit_index),
            (ride.cabin_id, ride.alight_visit_index),
        ]
        for key in endpoints:
            selected[key] = self.oracle.options[key]["stop"]
        if neighborhood == 2:
            donors = [
                r
                for r in self.by_group[group]
                if r.cabin_id != ride.cabin_id
                and incumbent.ride_counts.get(r.id, 0) > 0
            ]
            if not donors:
                return None
            donor = self.rng.choice(donors)
            key = (
                donor.cabin_id,
                self.rng.choice([donor.board_visit_index, donor.alight_visit_index]),
            )
            if "skip" not in self.oracle.options[key]:
                return None
            selected[key] = self.oracle.options[key]["skip"]
        elif neighborhood == 3:
            trajectories = {t.cabin_id: t for t in incumbent.solution.trajectories}
            target = trajectories[ride.cabin_id]
            if ride.board_visit_index >= len(target.visits):
                return None
            start = target.visits[ride.board_visit_index].switch_time_seconds
            end = target.visits[
                min(ride.alight_visit_index, len(target.visits) - 1)
            ].next_switch_time_seconds
            resources = {
                u.resource_id
                for visit in target.visits[
                    ride.board_visit_index : ride.alight_visit_index + 1
                ]
                for u in self.oracle.routes[visit.route_option_id].resource_usages
            }

            def rank(t):
                relevant = [
                    v
                    for v in t.visits
                    if resources.intersection(
                        u.resource_id
                        for u in self.oracle.routes[v.route_option_id].resource_usages
                    )
                ]
                return (
                    not bool(relevant),
                    min(
                        (abs(v.switch_time_seconds - start) for v in relevant),
                        default=float("inf"),
                    ),
                    t.cabin_id,
                )

            others = sorted(
                (t for t in trajectories.values() if t.cabin_id != ride.cabin_id),
                key=rank,
            )
            for t in [target, *others[: width - 1]]:
                keys = [
                    (t.cabin_id, i)
                    for i, v in enumerate(t.visits)
                    if v.switch_time_seconds <= end
                    and v.next_switch_time_seconds >= start
                    and (t.cabin_id, i) not in endpoints
                    and "skip" in self.oracle.options[t.cabin_id, i]
                ]
                for key in self.rng.sample(keys, min(2, len(keys))):
                    opts = self.oracle.options[key]
                    selected[key] = (
                        opts["skip"] if selected[key] == opts["stop"] else opts["stop"]
                    )
        changed = {
            (c, v) for c, v, option in pattern.choices if selected[c, v] != option
        }
        active = {
            (t.cabin_id, i)
            for t in incumbent.solution.trajectories
            for i in range(len(t.visits))
        }
        if not changed.intersection(active):
            return None
        return StopPattern(
            pattern.domain_id,
            tuple((c, v, o) for (c, v), o in sorted(selected.items())),
        )


@dataclass
class PatternVnsOptimizer:
    config: PatternVnsConfig = field(default_factory=PatternVnsConfig)

    def solve(
        self,
        problem,
        *,
        primal_seed,
        event_callback=None,
        log_callback=None,
        checkpoint_callback=None,
        pattern_checkpoint_callback=None,
        oracle_factory=PatternTimingOracle,
    ):
        self.config.validate()
        started = perf_counter()
        deadline = started + self.config.total_seconds - self.config.reserve_seconds
        best = validate_ddd_cp_sat_incumbent(
            problem,
            primal_seed.solution,
            primal_seed.ride_counts,
            provenance="vns_seed",
        )
        initial = best
        oracle = oracle_factory(
            problem,
            workers=self.config.workers,
            seed=self.config.seed,
            log_callback=log_callback,
            deadline=deadline,
        )
        rng = Random(self.config.seed)
        neighborhoods = PatternNeighborhoods(oracle, rng)
        current_pattern = oracle.pattern_from(best.solution)
        initial_pattern_id = current_pattern.id
        current = best
        pool = {current_pattern.id: (current_pattern, current)}
        events, attempted, retry = [], set(), deque()
        refined, changed_valid = set(), set()
        n, failures, duplicate_count, fresh, cycle = 1, 0, 0, 0, 0
        status = "TIME_LIMIT"

        def emit(kind, **data):
            row = dict(kind=kind, elapsed_seconds=perf_counter() - started, **data)
            events.append(row)
            if event_callback:
                event_callback(row)

        def evaluate(pattern, budget, kind):
            nonlocal best
            allowance = min(budget, deadline - perf_counter())
            if allowance <= 0:
                return None
            cached = oracle.cache.get(pattern.id)
            hint = (
                cached.incumbent if cached and cached.incumbent is not None else current
            )
            r = oracle.evaluate(pattern, budget=allowance, hint=hint)
            emit(
                "pattern_evaluated",
                evaluation_kind=kind,
                neighborhood=n,
                width=(2, 4, 8)[cycle % 3],
                **r.record(),
            )
            if r.incumbent is not None:
                if pattern_checkpoint_callback:
                    pattern_checkpoint_callback(pattern, r.incumbent)
                if (
                    pattern.id != initial_pattern_id
                    and r.incumbent.solution != initial.solution
                ):
                    changed_valid.add(pattern.id)
                pool[pattern.id] = (pattern, r.incumbent)
                keep = sorted(pool.values(), key=lambda x: (unserved(x[1]), x[0].id))[
                    :5
                ]
                pool.clear()
                pool.update({p.id: (p, inc) for p, inc in keep})
                if unserved(r.incumbent) < unserved(best):
                    best = r.incumbent
                    emit("incumbent", unserved=unserved(best), pattern_id=pattern.id)
                    if checkpoint_callback:
                        checkpoint_callback(best)
            return r

        emit(
            "model_built",
            model_stats=oracle.built.stats,
            build_seconds=oracle.build_seconds,
        )
        emit(
            "incumbent",
            unserved=unserved(best),
            pattern_id=current_pattern.id,
            initial=True,
        )
        if unserved(best) > 0:
            r = evaluate(current_pattern, self.config.oracle_seconds, "initial")
            if r and r.incumbent is not None:
                current = r.incumbent
        while perf_counter() < deadline and unserved(best) > 0:
            pattern = neighborhoods.propose(
                current_pattern, current, n, (2, 4, 8)[cycle % 3]
            )
            if pattern is None or pattern.id in attempted or pattern.id in oracle.cache:
                duplicate_count += 1
                if duplicate_count in (15, 30):
                    n = min(3, n + 1)
                    failures = 0
                    emit("neighborhood_exhausted", next_neighborhood=n)
                if duplicate_count >= 50:
                    status = "SEARCH_STALLED"
                    break
                continue
            duplicate_count = 0
            attempted.add(pattern.id)
            old_best = unserved(best)
            r = evaluate(pattern, self.config.oracle_seconds, "new")
            if r is None:
                break
            fresh += 1
            if r.status == "UNKNOWN" and self.config.retry_unknown:
                retry.append(pattern)
            if (
                unserved(best) < old_best
                and r.status == "FEASIBLE"
                and pattern.id not in refined
            ):
                refined.add(pattern.id)
                r = evaluate(pattern, self.config.retry_seconds, "refine") or r
            if r.incumbent is not None and unserved(r.incumbent) <= unserved(current):
                current_pattern, current = pattern, r.incumbent
            if unserved(best) < old_best:
                current_pattern, current = pattern, best
                n, failures = 1, 0
            else:
                failures += 1
            if fresh % 5 == 0 and retry:
                p = retry.popleft()
                rr = evaluate(p, self.config.retry_seconds, "retry")
                if (
                    rr
                    and rr.incumbent is not None
                    and unserved(rr.incumbent) < unserved(current)
                ):
                    current_pattern, current = p, rr.incumbent
                    n, failures = 1, 0
            if failures >= 5:
                failures = 0
                if n < 3:
                    n += 1
                else:
                    alternatives = [
                        x for p, x in pool.items() if p != current_pattern.id
                    ]
                    if alternatives:
                        current_pattern, current = rng.choice(alternatives)
                    elif r.incumbent is not None:
                        current_pattern, current = pattern, r.incumbent
                    n = 1
                    cycle += 1
        if unserved(best) == 0:
            status = "OPTIMAL"
        if checkpoint_callback:
            checkpoint_callback(best)
        emit(
            "final",
            status=status,
            unserved=unserved(best),
            distinct_patterns=len(oracle.cache),
            changed_valid_patterns=len(changed_valid),
        )
        return dict(
            schema="pattern_search_v1",
            objective="unserved",
            bound_units="persons",
            proof_scope="HEURISTIC_FIXED_K",
            status=status,
            problem_fingerprint=problem.fingerprint,
            domain_manifest=oracle.manifest,
            unserved_upper_bound=unserved(best),
            unserved_lower_bound=0,
            proven_optimal=unserved(best) == 0,
            served=sum(g.count for g in problem.passenger_build.demand_groups)
            - unserved(best),
            total_seconds=perf_counter() - started,
            model_stats=oracle.built.stats,
            distinct_patterns=len(oracle.cache),
            changed_valid_patterns=len(changed_valid),
            incumbent=best.to_payload(),
            events=events,
            evaluations=[r.record() for r in oracle.cache.values()],
            patterns={i: r.pattern.choices for i, r in oracle.cache.items()},
        )
