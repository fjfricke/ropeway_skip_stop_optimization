"""Native Gurobi optimization on an exact, restricted anonymous phase graph."""

from collections import defaultdict
from bisect import bisect_right
from dataclasses import asdict, dataclass
from time import perf_counter
import math

import gurobipy as gp
from gurobipy import GRB

from ..reservoir_cp_sat_certificate import (
    DddReservoirCpPlan,
    DddReservoirCpTrip,
    validate_reservoir_cp_plan,
    write_reservoir_cp_checkpoint,
)
from ..time_ticks import ddd_seconds_to_tick as tick
from .network import check, replay_paths
from .formulation import ReservoirPhaseFormulationConfig
from .passenger_model import build_passengers
from .resource_structure import prepare_resources
from ..cp_sat_certificate import stable_fingerprint


@dataclass
class PhaseModel:
    network: object
    model: object
    x: dict
    flow: dict
    auxiliary: tuple
    families: dict
    build_seconds: float
    passengers: object
    resources: object
    config: object
    fingerprint: str
    hint_seconds: float = 0.0

    def reference_values(self, plan):
        validate_reservoir_cp_plan(self.network.problem, plan)
        paths = replay_paths(self.network, plan)
        values = {v.index: 0 for v in (*self.x.values(), *self.flow.values())}
        for path in paths.values():
            for a in path:
                values[self.x[a.id].index] = 1
        values.update(self.passengers.reference_values(plan, paths))
        for v, terms in self.auxiliary:
            values[v.index] = sum(values[q.index] for q in terms)
        # Verify every row, not just variable presence.
        for row in self.model.getConstrs():
            if row.ConstrName.startswith("full_service["):
                # A physically valid incomplete reference remains a hint, not
                # a purported feasible witness of the extra U=0 requirement.
                continue
            expr = self.model.getRow(row)
            lhs = sum(
                expr.getCoeff(i) * values[expr.getVar(i).index]
                for i in range(expr.size())
            )
            if (
                (row.Sense == "=" and lhs != row.RHS)
                or (row.Sense == "<" and lhs > row.RHS)
                or (row.Sense == ">" and lhs < row.RHS)
            ):
                raise ValueError(f"reference violates phase row {row.ConstrName}")
        return values


def build_model(
    network,
    *,
    deadline=None,
    reference=None,
    require_full_service=False,
    output=False,
    formulation=None,
):
    started = perf_counter()
    p = network.problem
    config = formulation or ReservoirPhaseFormulationConfig()
    config.validate()
    m = gp.Model("restricted_reservoir_capacity_phases")
    m.Params.OutputFlag = int(output)
    x, flow = {}, {}
    auxiliary = []
    families = defaultdict(int)

    def row(expr, family):
        check(deadline)
        families[family] += 1
        m.addConstr(expr, name=f"{family}[{families[family]}]")

    try:
        inc, out = defaultdict(list), defaultdict(list)
        for a in network.arcs:
            check(deadline)
            x[a.id] = m.addVar(vtype=GRB.BINARY, name=f"x[{a.id}]")
            if a.source is not None:
                out[a.source].append(x[a.id])
            if a.target is not None:
                inc[a.target].append(x[a.id])
        for n in inc.keys() | out.keys():
            row(gp.quicksum(inc[n]) == gp.quicksum(out[n]), "movement")
            row(gp.quicksum(inc[n]) <= 1, "node_occupancy")
        dispatch = [x[a.id] for a in network.arcs if a.kind == "dispatch"]
        returns = [x[a.id] for a in network.arcs if a.kind == "return"]
        row(gp.quicksum(dispatch) == gp.quicksum(returns), "fleet_balance")
        row(gp.quicksum(dispatch) <= p.available_fleet_count, "fleet_max")
        boundary = defaultdict(list)
        for a in network.arcs:
            if a.kind in ("dispatch", "return"):
                boundary[a.target if a.kind == "dispatch" else a.source].append(x[a.id])
        for vs in boundary.values():
            if len(vs) > 1:
                row(gp.quicksum(vs) <= 1, "no_empty_trip")
        resources = prepare_resources(network.arcs, config, deadline)
        for i in resources.retained:
            row(
                gp.quicksum(c * x[aid] for aid, c in resources.rows[i].terms) <= 1,
                "resource",
            )
        for clique, proof in resources.cliques:
            row(gp.quicksum(x[aid] for aid in clique) <= 1, "conflict_clique")
        # The single-occupancy protected waiting resource implies FIFO at this
        # station. Prefix cumulative inequalities bound each FIFO residence.
        by_state = defaultdict(lambda: [[], []])
        for a in network.arcs:
            if a.kind == "ready":
                by_state[a.target[0]][0].append((a.target[2], x[a.id]))
            if a.kind == "exit":
                by_state[a.source[0]][1].append((a.source[2], x[a.id]))
        options = {o.id: o for o in p.resolved_core.route_options}
        for state, (arrivals, departures) in by_state.items():
            o = next(
                o
                for o in options.values()
                if o.from_state_id == state
                and o.platform_exit_offset_seconds is not None
            )
            W = tick(p.waiting_policy.maximum_wait_seconds(o.station_id))

            def prefixes(items, label):
                groups = defaultdict(list)
                for t, v in items:
                    groups[t].append(v)
                result = []
                previous = None
                for t, vs in sorted(groups.items()):
                    terms = tuple(vs) + ((previous,) if previous is not None else ())
                    v = m.addVar(
                        lb=0, ub=len(items), name=f"cumulative_{label}[{state},{t}]"
                    )
                    row(v == gp.quicksum(terms), "cumulative_flow")
                    auxiliary.append((v, terms))
                    result.append((t, v))
                    previous = v
                return result

            A = prefixes(arrivals, "ready")
            E = prefixes(departures, "exit")
            ets = [t for t, v in E]
            for s, v in A:
                index = bisect_right(ets, s + W) - 1
                row(
                    (E[index][1] if index >= 0 else gp.LinExpr()) >= v,
                    "maximum_total_wait",
                )
        passengers = build_passengers(network, m, x, row, config, deadline)
        objective = passengers.objective
        flow = {
            (key[1], key[2]) if key[0] == "g" else key: v
            for key, v in passengers.variables.items()
        }
        if require_full_service:
            row(objective == 0, "full_service")
        m.setObjective(objective, GRB.MINIMIZE)
        m.update()
        built = PhaseModel(
            network,
            m,
            x,
            flow,
            tuple(auxiliary),
            dict(families),
            perf_counter() - started,
            passengers,
            resources,
            config,
            stable_fingerprint(
                dict(
                    graph=network.fingerprint,
                    config=config.as_dict(),
                    passengers=passengers.structure.fingerprint,
                    resources=resources.fingerprint,
                )
            ),
        )
        if reference is not None:
            hint_started = perf_counter()
            values = built.reference_values(reference)
            for v in m.getVars():
                v.Start = values[v.index]
            built.hint_seconds = perf_counter() - hint_started
        return built
    except BaseException:
        m.dispose()
        raise


def integer(value):
    n = round(value)
    if abs(value - n) > 1e-5:
        raise ValueError("nonintegral native certificate value")
    return n


def extract(built, value):
    p = built.network.problem
    arcs = {a.id: a for a in built.network.arcs if integer(value(built.x[a.id]))}
    outgoing = {a.source: a for a in arcs.values() if a.source is not None}
    dispatch = sorted(
        (a for a in arcs.values() if a.kind == "dispatch"), key=lambda a: a.target
    )
    trips = []
    visited = set()
    paths = {}
    for k, d in enumerate(dispatch):
        path = [d]
        a = d
        while a.target is not None:
            a = outgoing[a.target]
            if a.id in visited:
                raise ValueError("cycle or merging of selected cabins")
            visited.add(a.id)
            path.append(a)
        ids = []
        times = []
        waits = []
        visit = -1
        for a in path:
            if a.kind in ("arrive", "skip"):
                visit += 1
                ids.append(a.option_id)
                times.append(a.source[2])
                waits.append(0)
            if a.kind == "exit":
                o = next(
                    o for o in p.resolved_core.route_options if o.id == a.option_id
                )
                waits[-1] = (
                    a.source[2] - times[-1] - tick(o.platform_exit_offset_seconds)
                )
        if not ids:
            raise ValueError("empty trip")
        paths[k] = path
        trips.append(
            DddReservoirCpTrip(
                k, tuple(ids), tuple(times), tuple(waits), path[-1].source[2]
            )
        )
    if visited | {a.id for a in dispatch} != set(arcs):
        raise ValueError("unreachable selected movement")
    counts = built.passengers.extract_assignment(value, paths)
    plan = DddReservoirCpPlan(tuple(trips), counts)
    expected = built.passengers.reference_values(plan, paths)
    for v in built.passengers.variables.values():
        if abs(value(v) - expected[v.index]) > 1e-5:
            raise ValueError("native passenger flow does not match lifted certificate")
    metrics = validate_reservoir_cp_plan(p, plan)
    return plan, metrics


def solve(
    built,
    *,
    deadline,
    threads=12,
    seed=0,
    reference=None,
    checkpoint=None,
    emit=None,
    soft_memory_gb=8,
):
    started = perf_counter()
    p = built.network.problem
    m = built.model
    reference_metrics = (
        validate_reservoir_cp_plan(p, reference) if reference is not None else None
    )
    best = reference
    metrics = reference_metrics
    events = []
    error = []
    root_complete = None
    validation_seconds = 0.0
    last_progress = -1.0
    certificate_variables = m.getVars()

    def callback(model, where):
        nonlocal best, metrics, root_complete, last_progress, validation_seconds
        elapsed = perf_counter() - started
        if where == GRB.Callback.MIPNODE and root_complete is None:
            if (
                model.cbGet(GRB.Callback.MIPNODE_NODCNT) == 0
                and model.cbGet(GRB.Callback.MIPNODE_STATUS) == GRB.OPTIMAL
            ):
                root_complete = elapsed
        if where == GRB.Callback.MIP and elapsed - last_progress >= 1:
            last_progress = elapsed
            event = dict(
                event="restricted_bound",
                seconds=elapsed,
                lower=model.cbGet(GRB.Callback.MIP_OBJBND),
                nodes=model.cbGet(GRB.Callback.MIP_NODCNT),
            )
            events.append(event)
            if emit:
                emit(event)
        if where != GRB.Callback.MIPSOL:
            return
        try:
            validation_started = perf_counter()
            native_values = model.cbGetSolution(certificate_variables)
            plan, checked = extract(built, lambda v: native_values[v.index])
            validation_seconds += perf_counter() - validation_started
            raw = model.cbGet(GRB.Callback.MIPSOL_OBJ)
            if abs(raw - checked.unserved) > 1e-5:
                raise ValueError("native objective/certificate mismatch")
            event = dict(
                event="native_solution",
                seconds=perf_counter() - started,
                unserved=checked.unserved,
                used_fleet=checked.used_fleet,
                improvement=metrics is not None and checked.unserved < metrics.unserved,
            )
            events.append(event)
            if emit:
                emit(event)
            if metrics is None or checked.unserved < metrics.unserved:
                best, metrics = plan, checked
                if checkpoint:
                    write_reservoir_cp_checkpoint(checkpoint, p, plan)
        except BaseException as exc:
            error.append(exc)
            model.terminate()

    check(deadline)
    m.Params.TimeLimit = max(0.001, deadline - perf_counter())
    m.Params.Threads = threads
    m.Params.Seed = seed
    m.Params.MIPFocus = 0
    m.Params.Method = -1
    m.Params.SoftMemLimit = soft_memory_gb
    m.optimize(callback)
    if error:
        raise error[0]
    if m.SolCount:
        validation_started = perf_counter()
        native_values = m.getAttr("X", certificate_variables)
        plan, checked = extract(built, lambda v: native_values[v.index])
        validation_seconds += perf_counter() - validation_started
        if metrics is None or checked.unserved < metrics.unserved:
            best, metrics = plan, checked
    if best is not None and checkpoint:
        write_reservoir_cp_checkpoint(checkpoint, p, best)
    lower = m.ObjBound if math.isfinite(m.ObjBound) else None
    return best, dict(
        status=int(m.Status),
        objective="unserved",
        problem_fingerprint=p.fingerprint,
        model_fingerprint=built.fingerprint,
        network_fingerprint=built.network.fingerprint,
        formulation=built.config.as_dict(),
        passenger_preparation_seconds=built.passengers.structure.seconds,
        passenger_variables=len(built.passengers.variables),
        contracted_equalities=built.passengers.structure.removed_equalities,
        removed_resource_rows=len(built.resources.implied_by),
        additional_cliques=len(built.resources.cliques),
        bound_scope="restricted_phase_network",
        global_lower_bound=None,
        restricted_lower_bound=lower,
        validated_upper_bound=metrics.unserved if metrics else None,
        validated_metrics=asdict(metrics) if metrics else None,
        reference_unserved=reference_metrics.unserved if reference_metrics else None,
        native_events=events,
        variables=m.NumVars,
        rows=m.NumConstrs,
        nonzeros=m.NumNZs,
        variable_types={
            "binary": m.NumBinVars,
            "integer": m.NumIntVars - m.NumBinVars,
            "continuous": m.NumVars - m.NumIntVars,
        },
        row_families=built.families,
        search_seconds=perf_counter() - started,
        network_seconds=built.network.build_seconds,
        model_seconds=max(
            0.0,
            built.build_seconds
            - built.passengers.structure.seconds
            - built.resources.seconds,
        ),
        total_build_seconds=built.build_seconds,
        resource_preparation_seconds=built.resources.seconds,
        hint_seconds=built.hint_seconds,
        validation_seconds=validation_seconds,
        nodes=m.NodeCount,
        root_lp_complete_seconds=root_complete,
        root_lp_measurement_note="first optimal root MIPNODE; null if unavailable/presolve solved",
        global_optimal=False,
    )
