"""Sequential single-use bound/repair coordinator with separate certificates."""

from dataclasses import dataclass
import gc
from time import perf_counter

from .arrival_curves import ArrivalIntervalPartition
from .bound_domain import prepare_bound
from .bound_model import (
    ReservoirArrivalBoundBuilder,
    ReservoirArrivalBoundOptimizer,
    analytical_bound,
)
from .certificates import GlobalReservoirBound, ReservoirCertificateLedger
from .repair import ReservoirRepairProblem, ReservoirRepairOptimizer, trim_empty_tails
from ..reservoir_cp_sat_certificate import (
    DddReservoirCpPlan,
    validate_reservoir_cp_plan,
)


@dataclass(frozen=True)
class ReservoirHybridConfig:
    time_limit: float = 600
    workers: int = 12
    seed: int = 0
    repair_time_limit: float = 30
    bound_fraction: float = 0.25
    repair_presolve: bool = False
    normalize_empty_tails: bool = False

    def __post_init__(self):
        from math import isfinite

        if (
            not isfinite(self.time_limit)
            or self.time_limit <= 0
            or not isfinite(self.repair_time_limit)
            or self.repair_time_limit <= 0
        ):
            raise ValueError("positive finite budgets required")
        if not 0 <= self.bound_fraction <= 0.25 or self.workers <= 0:
            raise ValueError("invalid worker count or bound budget fraction")


def select_neighborhood(problem, plan, iteration, seed):
    trips = {t.cabin_id: t for t in plan.trips}
    if not trips:
        return (), 1, "insert"
    ordered = sorted(trips, key=lambda k: (trips[k].switch_ticks[0], k))
    costs = {k: 0.0 for k in trips}
    counts = {k: 0 for k in trips}
    candidates = {r.id: r for r in problem.passenger_build.ride_candidates}
    groups = {g.id: g for g in problem.demand_groups}
    options = {o.id: o for o in problem.resolved_core.route_options}
    for rid, n in plan.ride_counts.items():
        r = candidates[rid]
        t = trips[r.cabin_id]
        arrival = (
            t.switch_ticks[r.alight_visit_index] / 1e6
            + options[
                t.route_option_ids[r.alight_visit_index]
            ].platform_entry_offset_seconds
        )
        costs[r.cabin_id] += n * (
            arrival - groups[r.demand_group_id].release_time_seconds
        )
        counts[r.cabin_id] += n
    family = ("demand", "waiting", "replace")[iteration % 3]
    if family == "demand":
        ranking = sorted(trips, key=lambda k: (-costs[k], k))
    elif family == "waiting":
        ranking = sorted(trips, key=lambda k: (-sum(trips[k].wait_ticks), k))
    else:
        ranking = sorted(trips, key=lambda k: (counts[k], -costs[k], k))
    anchor = ranking[(iteration // 3 + seed) % len(ranking)]
    size = min(len(trips), 3 if (iteration // 3) % 2 == 0 else 6)
    center = ordered.index(anchor)
    ids = tuple(
        sorted(
            {
                ordered[(center + delta) % len(ordered)]
                for delta in range(-size // 2, -size // 2 + size)
            }
        )
    )
    return ids, 1 if size <= 3 else 2, family


class ReservoirHybridOptimizer:
    def __init__(self, config=ReservoirHybridConfig()):
        self.config = config

    def solve(
        self,
        problem,
        *,
        primal_seed=None,
        initial_bound=None,
        on_event=None,
        on_improvement=None,
    ):
        started = perf_counter()
        deadline = started + self.config.time_limit
        ledger = ReservoirCertificateLedger(problem)
        seed_plan = primal_seed or DddReservoirCpPlan((), {})
        if self.config.normalize_empty_tails:
            seed_plan = trim_empty_tails(problem, seed_plan)
        ledger.accept_plan(seed_plan)
        ledger.accept_bound(
            GlobalReservoirBound(
                problem.fingerprint,
                analytical_bound(problem),
                "analytical",
                "analytical_only",
            )
        )
        if initial_bound is not None:
            ledger.accept_bound(initial_bound)
        events = []

        def emit(kind, **data):
            event = {
                "kind": kind,
                "elapsed_seconds": perf_counter() - started,
                "validated_upper_bound": ledger.upper_bound,
                "certified_lower_bound": ledger.lower_bound,
                **data,
            }
            events.append(event)
            if on_event:
                on_event(event)

        emit("initial", seed_adoption_is_improvement=False)
        # A supplied bound was already computed on this immutable domain. Do not
        # spend the same work again: the comparison arms share that initial LB.
        if initial_bound is None and self.config.bound_fraction:
            built = None
            bound_deadline = min(
                deadline, started + self.config.time_limit * self.config.bound_fraction
            )
            try:
                prepared = prepare_bound(
                    problem,
                    ArrivalIntervalPartition.build(problem, 60_000_000),
                    bound_deadline,
                )
                built = ReservoirArrivalBoundBuilder().build(
                    prepared,
                    "movement_capacity",
                    journey_encoding="time_moments",
                    max_variables=None,
                    max_rows=None,
                    deadline=bound_deadline,
                )
                built.project(ledger.plan)
                bound, stats = ReservoirArrivalBoundOptimizer().solve(
                    built,
                    deadline=bound_deadline,
                    threads=self.config.workers,
                    method=2,
                )
                ledger.accept_bound(bound)
                emit("bound", statistics=stats)
            except TimeoutError:
                emit("bound_timeout")
            finally:
                if built is not None:
                    built.model.dispose()
                built = None
                gc.collect()
        iteration = 0
        while (
            deadline - perf_counter() > 0.1
            and ledger.upper_bound - ledger.lower_bound > 1e-5
        ):
            ids, new_slots, family = select_neighborhood(
                problem, ledger.plan, iteration, self.config.seed
            )
            context = ReservoirRepairProblem.prepare(
                problem, ledger.plan, ids, new_slots
            )

            def accept(plan):
                if self.config.normalize_empty_tails:
                    plan = trim_empty_tails(problem, plan)
                previous = ledger.upper_bound
                ledger.accept_plan(plan)
                if ledger.upper_bound < previous - 1e-6:
                    emit("improvement", iteration=iteration)
                    if on_improvement:
                        on_improvement(ledger.plan)

            plan, result = ReservoirRepairOptimizer().solve(
                context,
                time_limit=min(
                    self.config.repair_time_limit, max(0.001, deadline - perf_counter())
                ),
                workers=self.config.workers,
                seed=self.config.seed + iteration,
                presolve=self.config.repair_presolve,
                on_improvement=accept,
            )
            accept(plan)
            emit(
                "repair",
                iteration=iteration,
                family=family,
                open_ids=ids,
                statistics=result,
            )
            iteration += 1
            del context
            gc.collect()
        metrics = validate_reservoir_cp_plan(problem, ledger.plan)
        emit("finished")
        return ledger.plan, {
            "validated_upper_bound": ledger.upper_bound,
            "certified_lower_bound": ledger.lower_bound,
            "gap": (ledger.upper_bound - ledger.lower_bound)
            / max(1, abs(ledger.upper_bound)),
            "actual_total_seconds": perf_counter() - started,
            "events": events,
            "served": metrics.served,
            "unserved": metrics.unserved,
            "problem_fingerprint": problem.fingerprint,
            "original_problem_optimal": False,
            "scope": "single_use_reservoir_global",
            "seed": self.config.seed,
            "bound_reused": initial_bound is not None,
        }
