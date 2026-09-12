"""Bounded refinement of the fast passenger-time-moment relaxation.

Resource-window refinement is deliberately not implicit: replacing an old window
by smaller windows can lose its cut. This pilot refines movement_capacity only.
"""

from collections import defaultdict
from time import perf_counter

from .arrival_curves import ArrivalIntervalPartition
from .bound_domain import prepare_bound
from .bound_model import (
    ReservoirArrivalBoundBuilder,
    ReservoirArrivalBoundOptimizer,
    BoundSizeLimit,
    analytical_bound,
)
from .certificates import ReservoirCertificateLedger, GlobalReservoirBound


def refinement_projection(parent, child):
    if not set(parent.partition.points) <= set(child.partition.points):
        raise ValueError("child partition must retain every parent boundary")
    index = {(a.visit, a.source, a.target, a.option_id): a.id for a in parent.arcs}
    result = {}
    for a in child.arcs:
        key = (
            a.visit,
            parent.partition.cell(child.partition.points[a.source]),
            parent.partition.cell(child.partition.points[a.target]),
            a.option_id,
        )
        if key not in index:
            raise ValueError("refined arc has no parent")
        result[a.id] = index[key]
    return result


def propose_splits(built, maximum=3):
    if built.model.Status != 2:
        return ()
    weights = defaultdict(float)
    arcs = {a.id: a for a in built.prepared.arcs}
    for key, var in built.variables.items():
        if key[0] != "f" or var.X <= 1e-7:
            continue
        a = arcs[key[-1]]
        lo, hi = built.prepared.partition.bounds(a.source)
        if hi > lo:
            weights[a.source] += var.X * (hi - lo)
    selected = sorted(weights, key=lambda cell: (-weights[cell], cell))[:maximum]
    return tuple(
        (sum(built.prepared.partition.bounds(cell)) + 1) // 2 for cell in selected
    )


class ReservoirBoundRefiner:
    def solve(
        self,
        problem,
        plan,
        *,
        time_limit=300,
        max_rounds=5,
        method=2,
        workers=12,
        on_round=None,
    ):
        started = perf_counter()
        deadline = started + time_limit
        partition = ArrivalIntervalPartition.build(problem, 60_000_000)
        ledger = ReservoirCertificateLedger(problem)
        ledger.accept_plan(plan)
        ledger.accept_bound(
            GlobalReservoirBound(
                problem.fingerprint,
                analytical_bound(problem),
                "analytical",
                "analytical_only",
            )
        )
        best_source = {
            "source": "analytical_only",
            "model_fingerprint": None,
            "round": None,
        }
        rounds = []
        parent = None
        size_limit = None
        stagnant = 0
        reason = "round_limit"
        for i in range(max_rounds):
            built = None
            try:
                prepared = prepare_bound(problem, partition, deadline)
                mapping = (
                    {} if parent is None else refinement_projection(parent, prepared)
                )
                built = ReservoirArrivalBoundBuilder().build(
                    prepared,
                    "movement_capacity",
                    journey_encoding="time_moments",
                    max_variables=size_limit,
                    max_rows=None,
                    deadline=deadline,
                )
                witness = built.project(plan)
                bound, result = ReservoirArrivalBoundOptimizer().solve(
                    built, deadline=deadline, threads=workers, method=method
                )
                previous = ledger.lower_bound
                ledger.accept_bound(bound)
                if bound.value > previous + 1e-5:
                    best_source = {
                        "source": bound.source,
                        "model_fingerprint": bound.model_fingerprint,
                        "round": i,
                    }
                if i == 0:
                    size_limit = 2 * built.model.NumVars
                result.update(
                    round=i,
                    partition=list(partition.points),
                    projection=witness,
                    mapped_child_arcs=len(mapping),
                    cumulative_seconds=perf_counter() - started,
                    ledger_lower_bound=ledger.lower_bound,
                )
                points = propose_splits(built)
                result["proposed_splits"] = list(points)
                rounds.append(result)
                if on_round:
                    on_round(result)
                if result["status"] != 2:
                    reason = f"lp_status_{result['status']}"
                    break
                stagnant = stagnant + 1 if ledger.lower_bound <= previous + 1e-5 else 0
                if not points or stagnant >= 3:
                    reason = "no_splits" if not points else "three_stagnant_rounds"
                    break
                parent = prepared
                partition = partition.refine(points)
            except (BoundSizeLimit, TimeoutError) as error:
                reason = str(error)
                break
            finally:
                if built is not None:
                    built.model.dispose()
        start_bound = rounds[0]["certified_lower_bound"] if rounds else 0
        target_gain = 0.01 * (ledger.upper_bound - start_bound)
        return {
            "rounds": rounds,
            "certified_lower_bound": ledger.lower_bound,
            "validated_upper_bound": ledger.upper_bound,
            "termination_reason": reason,
            "G3_passed": bool(rounds)
            and ledger.lower_bound - start_bound >= target_gain,
            "required_gain": target_gain,
            "actual_total_seconds": perf_counter() - started,
            "refined_profile": "movement_capacity",
            "journey_encoding": "time_moments",
            "best_bound_source": best_source,
            "original_problem_optimal": False,
        }
