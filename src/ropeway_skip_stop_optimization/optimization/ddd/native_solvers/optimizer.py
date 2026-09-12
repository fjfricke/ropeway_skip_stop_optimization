"""Native optimization, hints, and existing independently validated certificates."""

from __future__ import annotations

import math
from dataclasses import asdict, dataclass
from pathlib import Path
from time import perf_counter

from ..cp_sat_certificate import (
    solution_from_cp_sat_payload,
    validate_ddd_cp_sat_domain,
    validate_ddd_cp_sat_incumbent,
    write_ddd_cp_sat_checkpoint,
)
from ..reservoir_cp_sat_certificate import (
    DddReservoirCpPlan,
    DddReservoirCpTrip,
    validate_reservoir_cp_plan,
    write_reservoir_cp_checkpoint,
)
from ..reservoir_cp_sat_problem import DddReservoirCpSatProblem
from ..time_ticks import ddd_seconds_to_tick as tick
from .model import build_native_model, check_deadline, prepare_native_structure


@dataclass(frozen=True)
class NativeSolverConfig:
    backend: str = "z3"
    objective: str = "journey_time"
    time_limit: float = 60
    workers: int = 1
    seed: int = 0
    checkpoint: Path | None = None
    build_only: bool = False

    def validate(self):
        if self.backend not in ("z3", "hexaly") or self.objective not in (
            "journey_time",
            "unserved",
        ):
            raise ValueError("unsupported native engine/objective")
        if not math.isfinite(self.time_limit) or self.time_limit <= 0:
            raise ValueError("time limit must be finite and positive")
        if (
            type(self.workers) is not int
            or self.workers < 1
            or type(self.seed) is not int
            or not 0 <= self.seed < 2**31
        ):
            raise ValueError("invalid workers or seed")


def validate_plan(problem, plan):
    if isinstance(problem, DddReservoirCpSatProblem):
        metrics = validate_reservoir_cp_plan(problem, plan)
        return plan, asdict(metrics)
    checked = validate_ddd_cp_sat_incumbent(
        problem, plan.solution, plan.ride_counts, provenance="native_solver"
    )
    unserved = sum(checked.unserved_counts.values())
    return checked, {
        "journey_time_tick": checked.objective_tick,
        "unserved": unserved,
        "served": sum(g.count for g in problem.passenger_build.demand_groups)
        - unserved,
    }


def save_plan(problem, plan, path):
    if isinstance(problem, DddReservoirCpSatProblem):
        write_reservoir_cp_checkpoint(path, problem, plan)
    else:
        write_ddd_cp_sat_checkpoint(
            path,
            problem=problem,
            manifest=validate_ddd_cp_sat_domain(problem),
            incumbent=plan,
        )


def plan_values(problem, b, plan):
    """Full scalar start values, including artificial terminal tails."""
    plan, _ = validate_plan(problem, plan)
    p, values = b.prepared, {}
    if p.operation == "reservoir":
        supports = {
            t.cabin_id: (
                t.route_option_ids,
                t.switch_ticks,
                t.wait_ticks,
                t.return_tick,
            )
            for t in plan.trips
        }
    else:
        supports = {
            t.cabin_id: (
                tuple(x.route_option_id for x in t.visits),
                tuple(tick(x.switch_time_seconds) for x in t.visits),
                tuple(tick(x.wait_seconds) for x in t.visits),
                tick(t.visits[-1].next_switch_time_seconds),
            )
            for t in plan.solution.trajectories
        }
    for k, states in p.states:
        routes, times, waits, terminal = supports.get(k, ((), (), (), 0))
        for i, state in enumerate(states):
            active = i < len(routes)
            values["time", k, i] = times[i] if active else terminal
            values["active", k, i] = active
            if i < len(states) - 1:
                values["wait", k, i] = waits[i] // p.step if active else 0
                for o in p.movement.route_options_by_state_id[state]:
                    values["route", k, i, o.id] = active and routes[i] == o.id
        if p.operation == "reservoir":
            values["dispatch", k] = (
                (times[0] - tick(problem.dispatch_start_seconds))
                // tick(problem.dispatch_step_seconds)
                if times
                else 0
            )
    by_group, alight = {}, {}
    canonical = {q.id for q in p.rides}
    if any(n and q not in canonical for q, n in plan.ride_counts.items()):
        raise ValueError("positive count on unrepresentable ride")
    for q in p.rides:
        n = plan.ride_counts.get(q.id, 0)
        values["ride", q.id] = n
        by_group[q.demand_group_id] = by_group.get(q.demand_group_id, 0) + n
        e = q.cabin_id, q.alight_visit_index
        alight[e] = alight.get(e, 0) + n
    for g in p.groups:
        values["unserved", g.id] = g.count - by_group.get(g.id, 0)
    for event, count in alight.items():
        values["alight", *event] = count
        for bit in range(p.capacity.bit_length()):
            values["alight_bit", *event, bit] = bool(count & (1 << bit))
    return values


def apply_start(problem, b, plan, *, fix_movement=False, fix_passengers=False):
    values = plan_values(problem, b, plan)
    a = b.algebra
    hx = hasattr(a, "hx")
    if hx and (fix_movement or fix_passengers):
        a.m.open()
    for key, variable in b.variables.items():
        if key in b.fixed_values:
            continue
        fixed = (
            fix_passengers
            if key[0] in ("ride", "unserved", "alight", "alight_bit")
            else fix_movement
        )
        if fixed:
            a.add(variable == values[key])
        elif not hx:
            a.engine.set_initial_value(variable, values[key])
    if hx:
        if fix_movement or fix_passengers:
            a.m.close()
        for key, variable in b.variables.items():
            if key not in b.fixed_values:
                variable.value = values[key]
        for (k, i), interval in b.visit_intervals.items():
            interval.value = (
                a.hx.HxInterval(values["time", k, i], values["time", k, i + 1])
                if values["active", k, i]
                else a.hx.HxInterval()
            )
        for resource, order in a.orders.items():
            occurrences = []
            for index, (presence, start, end) in enumerate(b.resources[resource]):
                present = (
                    presence if isinstance(presence, bool) else bool(presence.value)
                )
                if present:
                    occurrences.append(
                        (start if isinstance(start, int) else start.value, index)
                    )
            order.value.clear()
            for _, index in sorted(occurrences):
                order.value.add(index)
    return values


def extract_plan(problem, b, read):
    supports, trips = [], []
    for k, states in b.prepared.states:
        routes, times, waits = [], [], []
        for i, state in enumerate(states[:-1]):
            if not read(b.variables["active", k, i]):
                break
            selected = [
                o.id
                for o in b.prepared.movement.route_options_by_state_id[state]
                if read(b.variables["route", k, i, o.id])
            ]
            if len(selected) != 1:
                raise ValueError("native model has no unique route")
            routes.append(selected[0])
            times.append(read(b.variables["time", k, i]))
            waits.append(b.prepared.step * read(b.variables["wait", k, i]))
        if not routes:
            continue
        terminal = read(b.variables["time", k, len(routes)])
        trips.append(
            DddReservoirCpTrip(k, tuple(routes), tuple(times), tuple(waits), terminal)
        )
        supports.append(
            {
                "cabin_id": k,
                "route_option_ids": routes,
                "switch_times_tick": times,
                "wait_ticks": waits,
            }
        )
    counts = {
        q.id: n for q in b.prepared.rides if (n := read(b.variables["ride", q.id])) > 0
    }
    if b.prepared.operation == "reservoir":
        return DddReservoirCpPlan(tuple(trips), counts)
    solution = solution_from_cp_sat_payload(problem, {"trajectory_supports": supports})
    return validate_ddd_cp_sat_incumbent(
        problem, solution, counts, provenance="native_solver"
    )


def solve_native(
    problem,
    config=None,
    *,
    primal_seed=None,
    fixed_plan=None,
    fix_passengers=False,
    event_callback=None,
):
    config = NativeSolverConfig() if config is None else config
    config.validate()
    started = perf_counter()
    deadline = started + config.time_limit
    events, best, best_score, reference_score, native_score = [], None, None, None, None
    validation_seconds = 0.0
    timers = {
        "preparation_seconds": 0.0,
        "build_seconds": 0.0,
        "hint_seconds": 0.0,
        "solve_seconds": 0.0,
    }
    built, status, lower, error, raw_lower = None, "UNKNOWN", None, None, None

    def score(metrics):
        return metrics[
            "journey_time_tick" if config.objective == "journey_time" else "unserved"
        ]

    def emit(kind, **data):
        item = dict(kind=kind, elapsed_seconds=perf_counter() - started, **data)
        events.append(item)
        if event_callback:
            event_callback(item)

    reference = primal_seed or fixed_plan
    if primal_seed is not None and fixed_plan is not None:
        first = (
            primal_seed.trips
            if isinstance(problem, DddReservoirCpSatProblem)
            else primal_seed.solution
        )
        second = (
            fixed_plan.trips
            if isinstance(problem, DddReservoirCpSatProblem)
            else fixed_plan.solution
        )
        if first != second:
            raise ValueError("seed differs from fixed movement")
    if reference is not None:
        t = perf_counter()
        best, metrics = validate_plan(problem, reference)
        validation_seconds += perf_counter() - t
        reference_score = best_score = score(metrics)
        emit("reference", objective=reference_score)
        if config.checkpoint:
            save_plan(problem, best, config.checkpoint)

    callback_errors = []

    def accept(read):
        nonlocal best, best_score, native_score, validation_seconds
        raw_score = read(built.objective)
        if native_score is not None and raw_score >= native_score:
            return
        t = perf_counter()
        try:
            plan, metrics = validate_plan(problem, extract_plan(problem, built, read))
            value = score(metrics)
            if value != raw_score:
                raise ValueError(
                    "native objective differs from independent certificate"
                )
            native_score = value
            better = reference_score is not None and value < reference_score
            emit(
                "native_solution",
                objective=value,
                improves_reference=better,
                reference_reproduced=reference_score == value,
                metrics=metrics,
            )
            if best_score is None or value < best_score:
                best, best_score = plan, value
                if config.checkpoint:
                    save_plan(problem, best, config.checkpoint)
        except Exception as exc:  # noqa: BLE001 - preserve diagnostics across optional native engine failures
            callback_errors.append(f"{type(exc).__name__}: {exc}")
        finally:
            validation_seconds += perf_counter() - t

    try:
        t = perf_counter()
        p = prepare_native_structure(problem)
        timers["preparation_seconds"] = perf_counter() - t
        emit(
            "prepared",
            domain_fingerprint=p.domain_fingerprint,
            structure_fingerprint=p.fingerprint,
        )
        check_deadline(deadline)
        t = perf_counter()
        try:
            built = build_native_model(
                problem,
                backend=config.backend,
                objective=config.objective,
                prepared=p,
                deadline=deadline,
                fixed_plan=fixed_plan,
                fix_passengers=fix_passengers,
                progress=lambda **data: emit("build_progress", **data),
            )
        finally:
            timers["build_seconds"] = perf_counter() - t
        emit("built", stats=built.stats, model_fingerprint=built.fingerprint)
        if reference is not None:
            t = perf_counter()
            apply_start(
                problem,
                built,
                reference,
                fix_movement=fixed_plan is not None,
                fix_passengers=fix_passengers,
            )
            timers["hint_seconds"] = perf_counter() - t
        if config.build_only:
            status = "BUILT"
        else:
            check_deadline(deadline)
            a = built.algebra
            t = perf_counter()
            if config.backend == "z3":
                z = a.z

                def reader(model):
                    def read(expr):
                        value = model.eval(expr, model_completion=True)
                        if z.is_bool(value):
                            return z.is_true(value)
                        return value.as_long()

                    return read

                a.engine.set(timeout=max(1, int((deadline - perf_counter()) * 1000)))
                # Values are extracted and validated inside the callback, before
                # Z3 invalidates its callback model. No Python objective loop.
                a.engine.set_on_model(lambda model: accept(reader(model)))
                result = a.engine.check()
                status = str(result).upper()
                if result != z.unsat:
                    try:
                        accept(reader(a.engine.model()))
                    except z.Z3Exception:
                        pass
                raw_lower = str(a.engine.lower(built.handle))
                bound = a.engine.lower(built.handle)
                if z.is_int_value(bound):
                    lower = bound.as_long()
                if result == z.unknown:
                    error = a.engine.reason_unknown()
                built.stats["solver_statistics"] = str(a.engine.statistics())
            else:
                a.engine.param.time_limit = max(
                    1, math.floor(deadline - perf_counter())
                )
                a.engine.param.nb_threads = config.workers
                a.engine.param.seed = config.seed

                def progress(*_):
                    if a.engine.solution.status in (
                        a.hx.HxSolutionStatus.FEASIBLE,
                        a.hx.HxSolutionStatus.OPTIMAL,
                    ):
                        accept(lambda x: x.value)
                    bound = a.engine.solution.get_objective_bound(0)
                    if math.isfinite(bound):
                        emit("bound", lower_bound=math.floor(bound))
                    if perf_counter() >= deadline or callback_errors:
                        a.engine.stop()

                a.engine.add_callback(a.hx.HxCallbackType.TIME_TICKED, progress)
                a.engine.solve()
                progress()
                status = a.engine.solution.status.name
                raw_lower = a.engine.solution.get_objective_bound(0)
                if math.isfinite(raw_lower):
                    lower = math.floor(raw_lower)
                built.stats["solver_statistics"] = str(a.engine.statistics)
            timers["solve_seconds"] = perf_counter() - t
            if callback_errors:
                raise ValueError("invalid native certificate: " + callback_errors[0])
            if status in ("UNSAT", "INCONSISTENT") and reference is not None:
                raise ValueError(
                    "native infeasibility contradicts independently validated reference"
                )
            if lower is not None and best_score is not None and lower > best_score:
                raise ValueError("native lower bound exceeds validated upper bound")
            if lower is not None:
                emit("bound", lower_bound=lower)
    except TimeoutError as exc:
        status, error = "TIMEOUT", str(exc)
    except Exception as exc:  # noqa: BLE001 - preserve diagnostics across optional native engine failures
        status, error = "ERROR", f"{type(exc).__name__}: {exc}"
        lower = None
    finally:
        if built is not None and config.backend == "hexaly":
            built.algebra.engine.delete()
    proven = (
        status not in ("ERROR", "BUILT")
        and native_score is not None
        and lower == native_score
    )
    result = {
        "schema": "native_solver_result_v1",
        "backend": config.backend,
        "engine_version": None if built is None else built.algebra.version,
        "engine_path": None if built is None else built.algebra.engine_path,
        "objective": config.objective,
        "status": status,
        "error": error,
        "reference_objective": reference_score,
        "native_objective": native_score,
        "validated_upper_bound": best_score,
        "lower_bound": lower,
        "raw_lower_bound": raw_lower,
        "proven_optimal": proven,
        "proof_scope": "FIXED_MOVEMENT" if fixed_plan is not None else "FULL_DOMAIN",
        "units": "person_ticks" if config.objective == "journey_time" else "persons",
        "events": events,
        "timings": {
            **timers,
            "validation_seconds": validation_seconds,
            "total_seconds": perf_counter() - started,
        },
        "stats": built.stats if built else None,
        "model_fingerprint": built.fingerprint if built else None,
        "actual_worker_configuration": 1 if config.backend == "z3" else config.workers,
        "repetition_is_seed": config.backend == "hexaly",
    }
    return result, best
