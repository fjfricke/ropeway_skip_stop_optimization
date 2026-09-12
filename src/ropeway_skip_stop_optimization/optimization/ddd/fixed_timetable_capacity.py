"""Integer service-capacity probes with fixed physical trajectories."""

from collections import defaultdict
from dataclasses import dataclass, replace
from math import floor, inf, isfinite, nextafter
from time import perf_counter

from ortools.sat.python import cp_model

from .cp_sat_certificate import validate_ddd_cp_sat_incumbent
from .models import DddRouteDecision
from .time_ticks import ddd_seconds_to_tick
from ..ean.builders.passenger_builder import (
    EanPassengerCandidateBuildResult,
    build_ean_ride_candidates,
)


@dataclass(frozen=True)
class NestedDemand:
    """Deterministic weighted-deficit prefixes; stable IDs and release times."""

    template: tuple

    def groups(self, total: int):
        if type(total) is not int or total < 0:
            raise ValueError("demand total must be a nonnegative integer")
        groups = tuple(sorted(self.template, key=lambda g: g.id))
        if not groups or len({g.id for g in groups}) != len(groups):
            raise ValueError("demand template requires unique groups")
        if any(type(g.count) is not int or g.count < 0 for g in groups):
            raise ValueError("demand template weights must be nonnegative integers")
        weight = sum(g.count for g in groups)
        if weight <= 0:
            raise ValueError("demand template must have positive weight")
        counts = [0] * len(groups)
        for m in range(1, total + 1):
            i = max(
                range(len(groups)),
                key=lambda i: (m * groups[i].count - counts[i] * weight, -i),
            )
            counts[i] += 1
        return tuple(replace(g, count=n) for g, n in zip(groups, counts, strict=True))

    def apply(self, problem, total: int):
        groups = self.groups(total)
        return replace(
            problem,
            passenger_build=EanPassengerCandidateBuildResult(
                groups, build_ean_ride_candidates(groups, problem.artifact)
            ),
        )


def conservative_count_bound(raw):
    return max(0, floor(nextafter(raw, -inf))) if isfinite(raw) else None


@dataclass(frozen=True)
class FixedTimetableCapacityProbe:
    time_limit_seconds: float = 30.0
    workers: int = 1

    def solve(self, problem, solution):
        if self.time_limit_seconds <= 0 or self.workers <= 0:
            raise ValueError("positive probe budget/workers required")
        started = perf_counter()
        validate_ddd_cp_sat_incumbent(
            problem, solution, {}, provenance="capacity_movement"
        )
        model = cp_model.CpModel()
        visits = {
            (t.cabin_id, i): v
            for t in solution.trajectories
            for i, v in enumerate(t.visits)
        }
        groups = {g.id: g for g in problem.passenger_build.demand_groups}
        horizon = problem.resolved_trajectory_problem.structural_movement_problem.passenger_service_end_tick
        capacity = problem.artifact.config.cabin_capacity
        options = {
            o.id: o
            for o in problem.resolved_trajectory_problem.structural_movement_problem.route_options
        }
        by_group, by_leg, quantities = defaultdict(list), defaultdict(list), {}
        for q in problem.passenger_build.ride_candidates:
            b, a = (
                visits.get((q.cabin_id, q.board_visit_index)),
                visits.get((q.cabin_id, q.alight_visit_index)),
            )
            if (
                b is None
                or a is None
                or b.decision is not DddRouteDecision.STOP
                or a.decision is not DddRouteDecision.STOP
            ):
                continue
            departure = (
                ddd_seconds_to_tick(b.switch_time_seconds)
                + ddd_seconds_to_tick(
                    options[b.route_option_id].platform_exit_offset_seconds
                )
                + ddd_seconds_to_tick(b.wait_seconds)
            )
            arrival = ddd_seconds_to_tick(a.switch_time_seconds) + ddd_seconds_to_tick(
                options[a.route_option_id].platform_entry_offset_seconds
            )
            g = groups[q.demand_group_id]
            if (
                not max(0, ddd_seconds_to_tick(g.release_time_seconds))
                <= departure
                <= arrival
                <= horizon
            ):
                continue
            v = model.new_int_var(0, min(capacity, g.count), q.id)
            quantities[q.id] = v
            by_group[g.id].append(v)
            for leg in range(q.board_visit_index, q.alight_visit_index):
                by_leg[q.cabin_id, leg].append(v)
        unserved = {}
        for g in groups.values():
            u = model.new_int_var(0, g.count, f"u[{g.id}]")
            model.add(sum(by_group[g.id]) + u == g.count)
            unserved[g.id] = u
        for values in by_leg.values():
            model.add(sum(values) <= capacity)
        model.minimize(sum(unserved.values()))
        solver = cp_model.CpSolver()
        remaining = self.time_limit_seconds - (perf_counter() - started)
        status = cp_model.UNKNOWN
        if remaining > 0:
            solver.parameters.max_time_in_seconds = remaining
            solver.parameters.num_search_workers = self.workers
            solver.parameters.absolute_gap_limit = (
                solver.parameters.relative_gap_limit
            ) = 0
            status = solver.solve(model)
        if status in (cp_model.MODEL_INVALID, cp_model.INFEASIBLE):
            raise RuntimeError(
                "fixed passenger model contradicts all-unserved feasible assignment"
            )
        # Fixed movement with no assigned passengers always supplies a valid UB.
        counts = (
            {q: int(solver.value(v)) for q, v in quantities.items() if solver.value(v)}
            if status in (cp_model.OPTIMAL, cp_model.FEASIBLE)
            else {}
        )
        checked = validate_ddd_cp_sat_incumbent(
            problem, solution, counts, provenance="fixed_timetable_capacity"
        )
        upper = sum(checked.unserved_counts.values())
        lower = (
            conservative_count_bound(float(solver.best_objective_bound))
            if remaining > 0
            else 0
        )
        if status == cp_model.OPTIMAL:
            if abs(solver.best_objective_bound - upper) > 0.25:
                raise RuntimeError("capacity bound disagreement")
            lower = upper
        if lower is not None and lower > upper:
            raise RuntimeError("capacity LB exceeds UB")
        return dict(
            objective="unserved",
            bound_units="persons",
            proof_scope="FIXED_MOVEMENT",
            solver_status=solver.status_name(status),
            total_demand=sum(g.count for g in groups.values()),
            unserved_upper_bound=upper,
            unserved_lower_bound=lower,
            capacity_feasible=upper == 0,
            capacity_infeasible_proven=lower is not None and lower > 0,
            variables=len(model.proto.variables),
            constraints=len(model.proto.constraints),
            wall_seconds=perf_counter() - started,
            problem_fingerprint=problem.fingerprint,
            incumbent=checked.to_payload(),
        )


def find_fixed_timetable_capacity(
    probe, problem, solution, demand, *, initial=1280, on_probe=None, max_probes=40
):
    """Bracket and bisect. UNKNOWN never becomes an infeasibility certificate."""
    lower, upper, query = 0, None, initial
    records = []
    for _ in range(max_probes):
        changed = demand.apply(problem, query)
        record = probe.solve(changed, solution)
        records.append(record)
        if on_probe:
            on_probe(query, changed, record)
        if record["capacity_feasible"]:
            lower = max(lower, query)
        elif record["capacity_infeasible_proven"]:
            upper = min(query - 1, upper) if upper is not None else query - 1
        else:
            break
        if upper == lower:
            break
        query = (
            max(lower + 1, (5 * lower + 3) // 4)
            if upper is None
            else (lower + upper + 1) // 2
        )
    return dict(
        kappa_lower=lower,
        kappa_upper=upper,
        exact=lower == upper,
        probe_count=len(records),
        records=records,
    )
