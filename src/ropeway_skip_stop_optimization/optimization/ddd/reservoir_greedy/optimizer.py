"""Native insertion solves and a sequential, monotone greedy construction."""

import math
from dataclasses import asdict, dataclass
from time import perf_counter

from ortools.sat.python import cp_model

from ..reservoir_cp_sat import _extract
from ..reservoir_cp_sat_certificate import DddReservoirCpPlan
from ..reservoir_hybrid.repair import translate_plan
from ..reservoir_lines.evolution.passengers import optimize_waiting_timetable_passengers
from .model import build_insertion, prepare_insertion, validate_lifecycle


@dataclass(frozen=True)
class GreedyConfig:
    backend: str = "cp_sat"
    time_limit: float = 480
    insertion_time_limit: float = 10
    extended_time_limit: float = 60
    workers: int = 12
    seed: int = 0
    objective: str = "unserved"

    def __post_init__(self):
        if self.objective not in ("unserved", "journey_time"):
            raise ValueError("unknown insertion objective")
        if self.backend not in ("cp_sat", "gurobi") or not 1 <= self.workers <= 12:
            raise ValueError("invalid backend/workers")
        if any(
            not math.isfinite(t) or t <= 0
            for t in (
                self.time_limit,
                self.insertion_time_limit,
                self.extended_time_limit,
            )
        ):
            raise ValueError("positive finite time limits required")


def objective_value(metrics, objective):
    return (
        metrics.journey_time_tick if objective == "journey_time" else metrics.unserved
    )


def canonicalize(problem, plan):
    ordered = sorted(plan.trips, key=lambda t: (t.switch_ticks[0], t.cabin_id))
    return translate_plan(
        problem, problem, plan, {t.cabin_id: i for i, t in enumerate(ordered)}
    )


def solve_insertion(
    problem,
    outside,
    *,
    backend="cp_sat",
    objective="unserved",
    seconds=10,
    workers=12,
    seed=0,
    deadline=None,
    on_event=None,
    on_candidate=None,
    require_new_passengers=False,
    candidate_seed=None,
    log_path=None,
):
    started = perf_counter()
    limit = min(started + seconds, deadline) if deadline else started + seconds
    if backend not in ("cp_sat", "gurobi") or not 1 <= workers <= 12 or seconds <= 0:
        raise ValueError("invalid insertion configuration")
    emit = on_event or (lambda e: None)
    events = []
    best = None
    best_served = -1
    best_value = math.inf
    if objective not in ("unserved", "journey_time"):
        raise ValueError("unknown insertion objective")
    bound_key = (
        "local_journey_time_bound_tick"
        if objective == "journey_time"
        else "local_unserved_bound"
    )
    invalid = []
    outside_metrics = validate_lifecycle(problem, outside)
    outside_value = objective_value(outside_metrics, objective)
    result = {
        "backend": backend,
        "objective": objective,
        "local_journey_time_bound_tick": None,
        "status": "UNKNOWN",
        "scope": "FIXED_OUTSIDE_PLUS_ONE_CABIN",
        "global_bound": None,
        "local_unserved_bound": None,
        "plan": None,
        "events": events,
        "native_solutions": 0,
        "invalid_candidates": invalid,
        "config": {"seconds": seconds, "workers": workers, "seed": seed},
        "preparation_seconds": 0.0,
        "model_build_seconds": 0.0,
        "search_seconds": 0.0,
        "validation_seconds": 0.0,
        "passenger_seconds": 0.0,
    }
    reserve = min(5.0, seconds * 0.3)
    search_deadline = limit - reserve

    def event(e):
        e = {"objective": objective, "insertion_k": len(outside.trips) + 1, **e}
        events.append(e)
        emit(e)

    event(
        {
            "kind": "insertion_started",
            "elapsed_seconds": 0.0,
            "budget_seconds": seconds,
            "outside_value": outside_value,
        }
    )

    try:
        before = perf_counter()
        prepared = prepare_insertion(problem, outside, deadline=search_deadline)
        result["preparation_seconds"] = perf_counter() - before
        before = perf_counter()
        built = build_insertion(prepared, deadline=search_deadline, objective=objective)
        if candidate_seed is not None:
            validate_lifecycle(problem, candidate_seed)
            old_shapes = {
                (
                    t.route_option_ids,
                    t.switch_ticks,
                    t.wait_ticks,
                    t.return_tick,
                ): t.cabin_id
                for t in prepared.outside.trips
            }
            mapping = {}
            for tr in candidate_seed.trips:
                shape = (
                    tr.route_option_ids,
                    tr.switch_ticks,
                    tr.wait_ticks,
                    tr.return_tick,
                )
                mapping[tr.cabin_id] = old_shapes.get(shape, prepared.new_id)
            if (
                len(set(mapping.values())) != len(mapping)
                or len(mapping) != prepared.new_id + 1
            ):
                raise ValueError("candidate hint changed outside movements")
            hint = translate_plan(problem, problem, candidate_seed, mapping)
            tr = next(t for t in hint.trips if t.cabin_id == prepared.new_id)
            b = built.movement
            b.model.clear_hints()
            n = len(tr.route_option_ids)
            for i, v in enumerate(b.time_by_cabin[prepared.new_id]):
                b.model.add_hint(v, tr.switch_ticks[i] if i < n else tr.return_tick)
            for i, v in enumerate(b.active_by_cabin[prepared.new_id]):
                b.model.add_hint(v, int(i < n))
            for (cid, i), v in b.wait_steps_by_key.items():
                if cid == prepared.new_id:
                    b.model.add_hint(
                        v, tr.wait_ticks[i] // b.waiting_step_tick if i < n else 0
                    )
            for (cid, i, oid), v in b.selection_by_key.items():
                if cid == prepared.new_id:
                    b.model.add_hint(v, int(i < n and tr.route_option_ids[i] == oid))
            for rid, v in built.passengers.ride_count.items():
                b.model.add_hint(v, hint.ride_counts.get(rid, 0))
        if require_new_passengers:
            ids = {
                q.id
                for q in problem.passenger_build.ride_candidates
                if q.cabin_id == prepared.new_id
            }
            built.movement.model.add(
                sum(v for rid, v in built.passengers.ride_count.items() if rid in ids)
                >= 1
            )
        result["shared_model_fingerprint"] = built.fingerprint
        result["physical_fingerprint"] = problem.fingerprint
        result["model_build_seconds"] = perf_counter() - before
        result["model_stats"] = {
            "shared_variables": len(built.movement.model.proto.variables),
            "shared_constraints": len(built.movement.model.proto.constraints),
            "variable_cabins": 1,
            "outside_cabins": prepared.new_id,
            "ride_variables": len(built.passengers.ride_count),
            "fixed_reservations": sum(len(v) for _, v in prepared.resources)
            + sum(len(v) for _, v in prepared.states),
        }

        def accept(value, bound):
            nonlocal best, best_served, best_value
            before = perf_counter()
            try:
                candidate = _extract(problem, built, value)
                metrics = validate_lifecycle(problem, candidate)
                candidate = canonicalize(problem, candidate)
                validate_lifecycle(problem, candidate)
            except (ValueError, RuntimeError, StopIteration) as error:
                invalid.append(str(error))
                return
            finally:
                result["validation_seconds"] += perf_counter() - before
            result["native_solutions"] += 1
            elapsed = perf_counter() - started
            value_now = objective_value(metrics, objective)
            improved = value_now < best_value
            if improved:
                best, best_served, best_value = candidate, metrics.served, value_now
                if on_candidate and value_now < outside_value:
                    on_candidate(candidate)
            event(
                {
                    "kind": "native_solution",
                    "elapsed_seconds": elapsed,
                    "served": metrics.served,
                    "unserved": metrics.unserved,
                    "fleet_size": metrics.used_fleet,
                    bound_key: bound,
                    "objective": objective,
                    "improvement_over_previous_native": improved,
                    "improvement_over_outside": value_now < outside_value,
                    "journey_time_tick": metrics.journey_time_tick,
                }
            )

        if backend == "cp_sat":
            solver = cp_model.CpSolver()
            solver.parameters.num_search_workers = workers
            solver.parameters.random_seed = seed
            if log_path:
                solver.parameters.log_search_progress = True
                solver.parameters.log_to_stdout = False

                def log(line):
                    with open(log_path, "a") as stream:
                        stream.write(line + "\n")

                solver.log_callback = log
            solver.best_bound_callback = lambda bound: event(
                {
                    "kind": "local_bound",
                    "elapsed_seconds": perf_counter() - started,
                    bound_key: bound,
                    "objective": objective,
                }
            )
            solver.parameters.max_time_in_seconds = max(
                0.001, search_deadline - perf_counter()
            )

            class Callback(cp_model.CpSolverSolutionCallback):
                def on_solution_callback(self):
                    accept(self.value, self.best_objective_bound)

            if perf_counter() >= search_deadline:
                raise TimeoutError("build consumed search budget")
            before = perf_counter()
            event(
                {"kind": "solve_started", "elapsed_seconds": perf_counter() - started}
            )
            status = solver.solve(built.movement.model, Callback())
            result["search_seconds"] = perf_counter() - before
            result["status"] = solver.status_name(status)
            result["engine_version"] = __import__("ortools").__version__
            result["solver_stats"] = {
                "branches": solver.num_branches,
                "conflicts": solver.num_conflicts,
                "response": solver.response_stats(),
            }
            if status in (cp_model.OPTIMAL, cp_model.FEASIBLE):
                accept(solver.value, solver.best_objective_bound)
            if status != cp_model.MODEL_INVALID:
                result[bound_key] = max(
                    0, math.ceil(solver.best_objective_bound - 1e-6)
                )
        else:
            from gurobipy import GRB, gurobi

            from .gurobi import GurobiInsertion

            before = perf_counter()
            g = GurobiInsertion(built, deadline=search_deadline)
            result["model_build_seconds"] += perf_counter() - before
            model = g.model
            try:
                model.Params.Threads = workers
                model.Params.Seed = seed
                if log_path:
                    model.Params.OutputFlag = 1
                    model.Params.LogToConsole = 0
                    model.Params.LogFile = str(log_path)
                model.Params.MIPFocus = 0
                model.Params.MIPGap = 0
                model.Params.IntFeasTol = 1e-9
                model.Params.FeasibilityTol = 1e-9
                model.Params.TimeLimit = max(0.001, search_deadline - perf_counter())
                result["model_stats"].update(
                    gurobi_variables=model.NumVars,
                    gurobi_rows=model.NumConstrs,
                    gurobi_indicators=model.NumGenConstrs,
                    window_choices=g.window_choices,
                )

                last_reported_bound = None

                def callback(m, where):
                    nonlocal last_reported_bound
                    if where == GRB.Callback.MIP:
                        bound = m.cbGet(GRB.Callback.MIP_OBJBND)
                        if abs(bound) < GRB.INFINITY and (
                            last_reported_bound is None or bound > last_reported_bound
                        ):
                            last_reported_bound = bound
                            event(
                                {
                                    "kind": "local_bound",
                                    "elapsed_seconds": perf_counter() - started,
                                    bound_key: bound,
                                }
                            )
                    if where == GRB.Callback.MIPSOL:
                        values = m.cbGetSolution(g.variables)
                        accept(
                            lambda v: g.value(v, values),
                            m.cbGet(GRB.Callback.MIPSOL_OBJBND),
                        )

                if perf_counter() >= search_deadline:
                    raise TimeoutError("translation consumed search budget")
                before = perf_counter()
                event(
                    {
                        "kind": "solve_started",
                        "elapsed_seconds": perf_counter() - started,
                    }
                )
                model.optimize(callback)
                result["search_seconds"] = perf_counter() - before
                result["status"] = {
                    GRB.OPTIMAL: "OPTIMAL",
                    GRB.INFEASIBLE: "INFEASIBLE",
                    GRB.TIME_LIMIT: "TIME_LIMIT",
                    GRB.INTERRUPTED: "INTERRUPTED",
                }.get(model.Status, str(model.Status))
                result["engine_version"] = ".".join(map(str, gurobi.version()))
                result["solver_stats"] = {
                    "nodes": model.NodeCount,
                    "iterations": model.IterCount,
                }
                if model.SolCount:
                    accept(g.value, model.ObjBound)
                if math.isfinite(model.ObjBound):
                    result[bound_key] = max(0, math.ceil(model.ObjBound - 1e-6))
            finally:
                model.dispose()
    except TimeoutError as error:
        result.update(status="BUILD_TIMEOUT", error=str(error))
    from ..cp_sat_certificate import stable_fingerprint

    if "shared_model_fingerprint" in result:
        result["model_fingerprint"] = stable_fingerprint(
            {
                "shared": result["shared_model_fingerprint"],
                "backend": backend,
                "engine": result.get("engine_version"),
                "encoding": "fixed_window_indicators_v1"
                if backend == "gurobi"
                else "native_intervals_v1",
                "require_new_passengers": require_new_passengers,
            }
        )
    native = best
    if objective == "unserved" and best is not None and limit - perf_counter() > 1:
        before = perf_counter()
        assignment = optimize_waiting_timetable_passengers(
            problem, best, time_limit_seconds=min(3.0, limit - perf_counter() - 1)
        )
        result["passenger_seconds"] = perf_counter() - before
        result["fixed_passenger_optimal"] = assignment.proven_optimal
        if assignment.served > best_served:
            best, best_served = assignment.plan, assignment.served
            event(
                {
                    "kind": "passenger_refinement",
                    "elapsed_seconds": perf_counter() - started,
                    "served": best_served,
                    "unserved": assignment.unserved,
                    "fleet_size": len(best.trips),
                }
            )
    result["native_best_served"] = (
        None if native is None else validate_lifecycle(problem, native).served
    )
    result["plan"] = best
    result["new_cabin_served"] = 0
    if best is not None:
        old_shapes = {
            (t.route_option_ids, t.switch_ticks, t.wait_ticks, t.return_tick)
            for t in outside.trips
        }
        new_ids = {
            t.cabin_id
            for t in best.trips
            if (t.route_option_ids, t.switch_ticks, t.wait_ticks, t.return_tick)
            not in old_shapes
        }
        ride_index = {r.id: r for r in problem.passenger_build.ride_candidates}
        result["new_cabin_served"] = sum(
            n
            for rid, n in best.ride_counts.items()
            if ride_index[rid].cabin_id in new_ids
        )
    result["metrics"] = (
        None if best is None else asdict(validate_lifecycle(problem, best))
    )
    result["total_wall_seconds"] = perf_counter() - started
    result["outside_served"] = validate_lifecycle(problem, outside).served
    event(
        {
            "kind": "insertion_finished",
            "elapsed_seconds": perf_counter() - started,
            bound_key: result[bound_key],
            "summary": {
                k: v
                for k, v in result.items()
                if k not in ("plan", "events", "solver_stats")
            },
        }
    )
    return result


def construct_greedy(
    problem,
    config=None,
    *,
    initial_plan=None,
    on_event=None,
    on_plan=None,
    on_candidate=None,
    log_directory=None,
):
    config = config or GreedyConfig()
    started = perf_counter()
    deadline = started + config.time_limit
    plan = initial_plan or DddReservoirCpPlan((), {})
    validate_lifecycle(problem, plan)
    emit = on_event or (lambda e: None)
    steps = []
    reason = "TIME_LIMIT"
    while perf_counter() < deadline:
        metrics = validate_lifecycle(problem, plan)
        if config.objective == "unserved" and metrics.unserved == 0:
            reason = "FULL_SERVICE"
            break
        if len(plan.trips) >= problem.available_fleet_count:
            reason = "FLEET_LIMIT"
            break
        accepted = False
        steps_before_attempt = len(steps)
        pending = None
        for attempt, budget in enumerate(
            (config.insertion_time_limit, config.extended_time_limit)
        ):
            if deadline - perf_counter() < 2:
                break

            next_k = len(plan.trips) + 1

            iteration_id = len(steps)

            def forward(
                e, insertion_k=next_k, attempt_index=attempt, iteration_id=iteration_id
            ):
                emit(
                    {
                        **e,
                        "construction_elapsed_seconds": perf_counter() - started,
                        "insertion_k": insertion_k,
                        "attempt": attempt_index,
                        "iteration_id": iteration_id,
                    }
                )

            result = solve_insertion(
                problem,
                plan,
                backend=config.backend,
                objective=config.objective,
                seconds=min(budget, deadline - perf_counter()),
                workers=config.workers,
                seed=config.seed + len(steps),
                deadline=deadline,
                on_event=forward,
                on_candidate=on_candidate,
                require_new_passengers=True,
                candidate_seed=pending,
                log_path=None
                if log_directory is None
                else log_directory / f"insertion_{len(steps)}.log",
            )
            candidate = result.pop("plan")
            pending = candidate
            steps.append(result)
            if candidate and objective_value(
                validate_lifecycle(problem, candidate), config.objective
            ) < objective_value(metrics, config.objective):
                # A new cabin must actually carry passengers, not merely reassign old ones.
                old_trips = {
                    (t.route_option_ids, t.switch_ticks, t.wait_ticks, t.return_tick)
                    for t in plan.trips
                }
                rides = {r.id: r for r in problem.passenger_build.ride_candidates}
                new_ids = {
                    t.cabin_id
                    for t in candidate.trips
                    if (t.route_option_ids, t.switch_ticks, t.wait_ticks, t.return_tick)
                    not in old_trips
                }
                if any(rides[rid].cabin_id in new_ids for rid in candidate.ride_counts):
                    plan = candidate
                    accepted = True
                    emit(
                        {
                            "kind": "accepted_insertion",
                            "objective": config.objective,
                            "journey_time_tick": result["metrics"]["journey_time_tick"],
                            "elapsed_seconds": perf_counter() - started,
                            "served": result["metrics"]["served"],
                            "unserved": result["metrics"]["unserved"],
                            "fleet_size": len(plan.trips),
                        }
                    )
                    if on_plan:
                        on_plan(plan)
                    break
            if result["status"] in ("OPTIMAL", "INFEASIBLE"):
                break
        if not accepted:
            reason = (
                steps[-1]["status"]
                if len(steps) > steps_before_attempt
                else "TIME_LIMIT"
            )
            break
    return {
        "plan": plan,
        "metrics": asdict(validate_lifecycle(problem, plan)),
        "steps": steps,
        "termination": reason,
        "total_wall_seconds": perf_counter() - started,
        "global_bound": None,
        "config": asdict(config),
    }
