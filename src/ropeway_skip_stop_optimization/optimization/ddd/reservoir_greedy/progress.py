"""Lossless event archive with a compact, solver-independent dashboard projection."""

import math


def number(value):
    return (
        value
        if isinstance(value, (int, float))
        and math.isfinite(value)
        and abs(value) < 1e90
        else None
    )


def gap_percent(ub, lb):
    if ub is None or lb is None or lb > ub + 1e-6:
        return None
    if ub == 0:
        return 0.0 if lb == 0 else None
    return 100 * (ub - lb) / abs(ub)


class GreedyProgress:
    def __init__(self):
        self.iterations = []
        self.by_id = {}

    def consume(self, event):
        kind = event["kind"]
        if kind == "accepted_insertion":
            for item in reversed(self.iterations):
                if item["k"] == event["fleet_size"]:
                    item["accepted"] = True
                    break
            return
        k = event.get("insertion_k")
        if k is None:
            return
        identifier = str(event.get("iteration_id", f"{k}:{event.get('attempt', 0)}"))
        item = self.by_id.get(identifier)
        if item is None:
            item = {
                "id": identifier,
                "k": k,
                "attempt": event.get("attempt", 0),
                "objective": event.get("objective", "unserved"),
                "status": "building",
                "accepted": False,
                "points": [],
                "elapsed_seconds": 0,
                "ub": None,
                "lb": None,
                "gap_percent": None,
                "first_solution_seconds": None,
                "last_improvement_seconds": None,
                "summary": None,
            }
            self.iterations.append(item)
            self.by_id[identifier] = item
        elapsed = number(event.get("elapsed_seconds")) or 0
        item["elapsed_seconds"] = max(item["elapsed_seconds"], elapsed)
        if event.get("construction_elapsed_seconds") is not None:
            item["construction_start_seconds"] = (
                event["construction_elapsed_seconds"] - elapsed
            )
        if kind == "insertion_started":
            item["budget_seconds"] = event.get("budget_seconds")
            item["outside_value"] = event.get("outside_value")
        if kind == "solve_started":
            item["status"] = "solving"
        if kind in ("local_bound", "native_solution"):
            item["status"] = "solving"
        ub, lb = item["ub"], item["lb"]
        if kind in ("native_solution", "passenger_refinement"):
            value = number(
                event.get(
                    "journey_time_tick"
                    if item["objective"] == "journey_time"
                    else "unserved"
                )
            )
            if value is not None and (ub is None or value < ub):
                ub = value
                item["last_improvement_seconds"] = elapsed
            if value is not None and item["first_solution_seconds"] is None:
                item["first_solution_seconds"] = elapsed
        bound = number(
            event.get(
                "local_journey_time_bound_tick"
                if item["objective"] == "journey_time"
                else "local_unserved_bound"
            )
        )
        if bound is not None and (lb is None or bound > lb):
            lb = bound
        if kind == "insertion_finished":
            item["summary"] = event["summary"]
            item["status"] = event["summary"]["status"]
            metrics = event["summary"].get("metrics")
            if metrics:
                value = number(
                    metrics.get(
                        "journey_time_tick"
                        if item["objective"] == "journey_time"
                        else "unserved"
                    )
                )
                if value is not None and (ub is None or value < ub):
                    ub = value
                    item["last_improvement_seconds"] = elapsed
        if ub != item["ub"] or lb != item["lb"]:
            item["points"].append(
                {
                    "seconds": elapsed,
                    "ub": ub,
                    "lb": lb,
                    "gap_percent": gap_percent(ub, lb),
                }
            )
        item.update(ub=ub, lb=lb, gap_percent=gap_percent(ub, lb))

    def export(self):
        return {
            "schema": "greedy_progress_v1",
            "bound_scope": "fixed_outside_plus_one_cabin",
            "iterations": self.iterations,
        }


def replay_progress(events, steps=()):
    """Recover past traces without inventing missing bounds or event times."""
    progress = GreedyProgress()
    for event in events:
        progress.consume(event)
    # Old logs may omit attempts that ended during model construction. Do not
    # attach a different attempt's final bound by positional alignment.
    if steps and len(progress.iterations) != len(steps):
        return progress
    for item, step in zip(progress.iterations, steps):
        objective = step.get("objective", item["objective"])
        key = (
            "local_journey_time_bound_tick"
            if objective == "journey_time"
            else "local_unserved_bound"
        )
        progress.consume(
            dict(
                kind="insertion_finished",
                iteration_id=item["id"],
                insertion_k=item["k"],
                attempt=item["attempt"],
                objective=objective,
                elapsed_seconds=step["total_wall_seconds"],
                summary={
                    k: v
                    for k, v in step.items()
                    if k not in ("events", "plan", "solver_stats")
                },
                **{key: step.get(key)},
            )
        )
    return progress


def validated_reference(problem, path):
    from dataclasses import asdict

    from ..reservoir_hybrid.domain import load_reference
    from .model import validate_lifecycle

    source, plan = load_reference(path)
    for field in (
        "movement_core",
        "demand_groups",
        "cabin_capacity",
        "dispatch_start_seconds",
        "dispatch_end_seconds",
        "return_start_seconds",
        "boundary_policy",
    ):
        if getattr(source.problem, field) != getattr(problem, field):
            raise ValueError(f"All-Stop reference differs: {field}")
    options = {o.id: o for o in problem.movement_core.route_options}
    if any(
        options[oid].decision.value != "stop"
        for t in plan.trips
        for oid in t.route_option_ids
    ):
        raise ValueError("reference is not All-Stop")
    if any(w for t in plan.trips for w in t.wait_ticks):
        raise ValueError("regular All-Stop reference must be No-Wait")
    metrics = validate_lifecycle(problem, plan)
    return {
        **asdict(metrics),
        "source": str(path.resolve()),
        "scope": "validated_plan",
        "optimality_proven": False,
        "assignment_objective": "recorded_checkpoint_assignment",
    }
