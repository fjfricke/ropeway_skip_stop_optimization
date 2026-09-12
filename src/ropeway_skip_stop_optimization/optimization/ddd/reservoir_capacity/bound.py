"""Global All-Stop capacity bounds with exact residual compensation.

The capacity LP uses integer coefficients in ticks. A solver's floating dual
vector is treated as an exact dyadic rational, sign-projected, and evaluated
as a Lagrangian over the finite variable box. This does not require trusting
floating reduced-cost feasibility or rounding a primal LP objective upward.
"""

from time import perf_counter
from dataclasses import asdict
import math

from ..cp_sat_certificate import stable_fingerprint
from ..reservoir_arc_flow_problem import DddReservoirOperatingMode
from ..reservoir_hybrid.arrival_curves import ArrivalIntervalPartition
from ..reservoir_hybrid.bound_domain import prepare_bound
from ..reservoir_hybrid.bound_model import ReservoirArrivalBoundBuilder
from ..time_ticks import ddd_seconds_to_tick as tick
from .network import check


def comparison_fingerprint(problem):
    # Compare physical inputs, not mode-dependent visit/candidate expansions.
    manifest = asdict(problem)
    manifest.pop("operating_mode", None)
    return stable_fingerprint(manifest)


def exact_int(v):
    if not math.isfinite(v) or v != int(v) or abs(v) >= 2**53:
        raise ValueError(
            "capacity dual certificate requires exact finite integer LP data"
        )
    return int(v)


def certify_dual(model, *, deadline=None):
    """A rigorous box-compensated lower bound for this integer-coefficient LP."""
    rows = model.getConstrs()
    variables = model.getVars()
    ratios = []
    for r in rows:
        check(deadline)
        y = r.Pi
        if not math.isfinite(y):
            raise ValueError("nonfinite LP dual")
        if r.Sense == "<":
            y = min(0.0, y)
        elif r.Sense == ">":
            y = max(0.0, y)
        ratios.append(y.as_integer_ratio())
    denominator = max((d for n, d in ratios), default=1)
    residual = [exact_int(v.Obj) * denominator for v in variables]
    numerator = exact_int(model.ObjCon) * denominator
    for r, (n, d) in zip(rows, ratios):
        check(deadline)
        y = n * (denominator // d)
        numerator += exact_int(r.RHS) * y
        expr = model.getRow(r)
        for i in range(expr.size()):
            residual[expr.getVar(i).index] -= exact_int(expr.getCoeff(i)) * y
    compensation = 0
    for v, r in zip(variables, residual):
        compensation += min(r * exact_int(v.LB), r * exact_int(v.UB))
    numerator += compensation
    return dict(
        numerator=str(numerator),
        denominator=str(denominator),
        integer_lower_bound=max(0, -((-numerator) // denominator)),
        residual_compensation=str(compensation),
        method="exact_dyadic_dual_finite_box_v1",
    )


def resource_windows(problem, partition):
    core = problem.resolved_core
    tail = core.operational_end_tick + max(
        (
            u.leader_clear_offset_tick
            + u.separation_after_tick(
                core.resources_by_id[u.resource_id].minimum_headway_tick
            )
            + tick(problem.waiting_policy.maximum_wait_seconds(o.station_id))
            for o in core.route_options
            for u in o.resource_usages
        ),
        default=1,
    )
    bs = sorted(set(partition.points) | {tail})
    return tuple(sorted(set(zip(bs, bs[1:])) | {(0, b) for b in bs if b > 0}))


def build_bound(
    problem, *, interval_tick=60_000_000, parent_interval_tick=None, deadline=None
):
    if problem.operating_mode is not DddReservoirOperatingMode.ALL_STOP:
        raise ValueError("all_stop_bound supports only all_stop")
    part = ArrivalIntervalPartition.build(problem, interval_tick)
    windows = ()
    if parent_interval_tick is not None:
        parent = ArrivalIntervalPartition.build(problem, parent_interval_tick)
        part = part.refine(parent.points[1:-1])
        windows = resource_windows(problem, parent)
    prepared = prepare_bound(problem, part, deadline)
    return ReservoirArrivalBoundBuilder().build(
        prepared,
        "resource_windows",
        deadline=deadline,
        objective="unserved",
        max_variables=None,
        max_rows=None,
        additional_resource_windows=windows,
    )


def solve_bound(built, *, deadline, threads=12):
    if built.objective != "unserved":
        raise ValueError("expected capacity bound")
    started = perf_counter()
    m = built.model
    check(deadline)
    # Leave time for exact dual validation, still inside the caller's deadline.
    remaining = deadline - perf_counter()
    m.Params.TimeLimit = max(0.001, remaining * 0.75)
    m.Params.Threads = threads
    m.Params.Method = -1
    m.Params.SoftMemLimit = 8
    m.optimize()
    certificate = None
    reason = None
    try:
        certificate = certify_dual(m, deadline=deadline)
    except (AttributeError, ValueError, TimeoutError) as exc:
        reason = str(exc)
    return dict(
        objective="unserved",
        status=int(m.Status),
        problem_fingerprint=built.prepared.problem.fingerprint,
        comparison_fingerprint=comparison_fingerprint(built.prepared.problem),
        model_fingerprint=built.fingerprint,
        bound_scope="global_all_stop_single_use_reservoir",
        global_lower_bound=certificate["integer_lower_bound"] if certificate else 0,
        dual_certificate=certificate,
        certificate_unavailable_reason=reason,
        raw_lp_objective=m.ObjVal if m.SolCount else None,
        variables=m.NumVars,
        rows=m.NumConstrs,
        nonzeros=m.NumNZs,
        model_seconds=built.build_seconds,
        search_and_certificate_seconds=perf_counter() - started,
    )
