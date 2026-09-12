"""Small reservoir CP neighborhoods with an immutable external calendar.

Only open deployments have solver variables. Outside passengers remain assigned;
all output is reassembled and validated in the original physical domain.
"""

from collections import defaultdict
from dataclasses import dataclass, replace
from time import perf_counter

from ortools.sat.python import cp_model

from ..cp_hint_completion import complete_cp_hints
from ..reservoir_cp_sat import build_reservoir_cp_sat, _movement_values, _extract
from ..reservoir_cp_sat_certificate import (
    DddReservoirCpPlan,
    validate_reservoir_cp_plan,
)
from ..route_topology import unique_stop_route_option
from ..time_ticks import ddd_seconds_to_tick as tick


def translate_plan(source, target, plan, mapping):
    """Translate only canonical cabin IDs, never silently discard a positive ride."""
    original = {r.id: r for r in source.passenger_build.ride_candidates}
    target_ids = {
        (r.cabin_id, r.demand_group_id, r.board_visit_index, r.alight_visit_index): r.id
        for r in target.passenger_build.ride_candidates
    }
    rides = {}
    for rid, count in plan.ride_counts.items():
        r = original[rid]
        if r.cabin_id not in mapping:
            raise ValueError("positive ride outside translated deployment set")
        key = (
            mapping[r.cabin_id],
            r.demand_group_id,
            r.board_visit_index,
            r.alight_visit_index,
        )
        if key not in target_ids:
            raise ValueError("positive ride missing from target canonical candidates")
        rides[target_ids[key]] = count
    return DddReservoirCpPlan(
        tuple(replace(t, cabin_id=mapping[t.cabin_id]) for t in plan.trips), rides
    )


def trim_empty_tails(problem, plan):
    """Dominating certificate: remove only unused trips and empty suffixes.

    An earlier return reuses an existing port event and removes future resource
    uses. Retain the entire final alighting STOP, all passenger assignments and
    the original return-start restriction. This changes a seed, not the domain.
    """
    before = validate_reservoir_cp_plan(problem, plan)
    last = defaultdict(lambda: -1)
    candidates = {r.id: r for r in problem.passenger_build.ride_candidates}
    for rid in plan.ride_counts:
        r = candidates[rid]
        last[r.cabin_id] = max(last[r.cabin_id], r.alight_visit_index)
    options = {o.id: o for o in problem.resolved_core.route_options}
    trips = []
    for trip in plan.trips:
        if last[trip.cabin_id] < 0:
            continue
        for n in range(last[trip.cabin_id] + 1, len(trip.route_option_ids) + 1):
            returned = (
                trip.switch_ticks[n]
                if n < len(trip.route_option_ids)
                else trip.return_tick
            )
            if options[
                trip.route_option_ids[n - 1]
            ].to_state_id == problem.entry_state_id and returned >= tick(
                problem.return_start_seconds
            ):
                trips.append(
                    replace(
                        trip,
                        route_option_ids=trip.route_option_ids[:n],
                        switch_ticks=trip.switch_ticks[:n],
                        wait_ticks=trip.wait_ticks[:n],
                        return_tick=returned,
                    )
                )
                break
        else:
            raise ValueError("validated trip has no admissible empty return suffix")
    shortened = DddReservoirCpPlan(tuple(trips), plan.ride_counts)
    ordered = sorted(trips, key=lambda t: (t.switch_ticks[0], t.cabin_id))
    canonical = translate_plan(
        problem, problem, shortened, {t.cabin_id: i for i, t in enumerate(ordered)}
    )
    after = validate_reservoir_cp_plan(problem, canonical)
    if (
        after.journey_time_tick != before.journey_time_tick
        or after.served != before.served
    ):
        raise ValueError("tail normalization changed passenger service or cost")
    return canonical


@dataclass(frozen=True)
class ReservoirRepairProblem:
    original: object
    seed: DddReservoirCpPlan
    outside: DddReservoirCpPlan
    local: object
    local_seed: DddReservoirCpPlan
    open_ids: tuple[int, ...]
    slots: int

    @classmethod
    def prepare(cls, problem, seed, open_ids, new_slots=0):
        validate_reservoir_cp_plan(problem, seed)
        ids = set(open_ids)
        used = {t.cabin_id for t in seed.trips}
        if (
            len(ids) != len(open_ids)
            or not ids <= used
            or type(new_slots) is not int
            or new_slots < 0
        ):
            raise ValueError("invalid repair deployment selection")
        rides = {r.id: r for r in problem.passenger_build.ride_candidates}
        outside = DddReservoirCpPlan(
            tuple(t for t in seed.trips if t.cabin_id not in ids),
            {
                rid: n
                for rid, n in seed.ride_counts.items()
                if rides[rid].cabin_id not in ids
            },
        )
        assigned = defaultdict(int)
        for rid, n in outside.ride_counts.items():
            assigned[rides[rid].demand_group_id] += n
        count = min(
            len(ids) + new_slots, problem.available_fleet_count - len(outside.trips)
        )
        # Zero-open/no-insert is handled without building any CP model.
        local = replace(
            problem,
            available_fleet_count=max(1, count),
            demand_groups=tuple(
                replace(g, count=g.count - assigned[g.id])
                for g in problem.demand_groups
                if g.count > assigned[g.id]
            ),
        )
        opened = DddReservoirCpPlan(
            tuple(t for t in seed.trips if t.cabin_id in ids),
            {
                rid: n
                for rid, n in seed.ride_counts.items()
                if rides[rid].cabin_id in ids
            },
        )
        ordered = sorted(opened.trips, key=lambda t: (t.switch_ticks[0], t.cabin_id))
        local_seed = translate_plan(
            problem, local, opened, {t.cabin_id: i for i, t in enumerate(ordered)}
        )
        validate_reservoir_cp_plan(local, local_seed)
        return cls(problem, seed, outside, local, local_seed, tuple(sorted(ids)), count)

    def assemble(self, plan):
        # Give both disjoint sets temporary identities, then canonicalize by
        # dispatch globally. Symmetry is local only while the repair is solved.
        labeled = [("outside", t) for t in self.outside.trips] + [
            ("local", t) for t in plan.trips
        ]
        labeled.sort(key=lambda x: (x[1].switch_ticks[0], x[0], x[1].cabin_id))
        mappings = {"outside": {}, "local": {}}
        for k, (label, trip) in enumerate(labeled):
            mappings[label][trip.cabin_id] = k
        outside = translate_plan(
            self.original, self.original, self.outside, mappings["outside"]
        )
        inside = translate_plan(self.local, self.original, plan, mappings["local"])
        merged = DddReservoirCpPlan(
            tuple(sorted(outside.trips + inside.trips, key=lambda t: t.cabin_id)),
            {**outside.ride_counts, **inside.ride_counts},
        )
        validate_reservoir_cp_plan(self.original, merged)
        return merged


def build_repair(context, *, deadline=None):
    built = build_reservoir_cp_sat(context.local, deadline=deadline)
    b = built.movement
    model = b.model
    p = context.original
    options = {o.id: o for o in p.resolved_core.route_options}
    resources, states = defaultdict(list), defaultdict(list)
    for trip in context.outside.trips:
        for i, (oid, t, wait) in enumerate(
            zip(trip.route_option_ids, trip.switch_ticks, trip.wait_ticks)
        ):
            o = options[oid]
            states[o.from_state_id].append(
                model.new_fixed_size_interval_var(
                    t, 1, f"outside_state[{trip.cabin_id},{i}]"
                )
            )
            for j, usage in enumerate(o.resource_usages):
                r = p.resolved_core.resources_by_id[usage.resource_id]
                entry = (
                    t
                    + usage.follower_enter_offset_tick
                    + usage.follower_enter_wait_coefficient * wait
                )
                clear = (
                    t
                    + usage.leader_clear_offset_tick
                    + usage.leader_clear_wait_coefficient * wait
                    + usage.separation_after_tick(r.minimum_headway_tick)
                )
                if entry <= p.resolved_core.operational_end_tick:
                    resources[r.id].append(
                        model.new_fixed_size_interval_var(
                            entry,
                            clear - entry,
                            f"outside_resource[{trip.cabin_id},{i},{j}]",
                        )
                    )
        states[p.entry_state_id].append(
            model.new_fixed_size_interval_var(
                trip.return_tick, 1, f"outside_return[{trip.cabin_id}]"
            )
        )
    for rid, intervals in resources.items():
        model.add_no_overlap(intervals + b.resource_intervals[rid])
    for state, intervals in states.items():
        local_intervals = []
        for k, visit_states in b.states_by_cabin.items():
            for i, s in enumerate(visit_states):
                if s == state:
                    present = b.active_by_cabin[k][max(0, i - 1)]
                    local_intervals.append(
                        model.new_optional_fixed_size_interval_var(
                            b.time_by_cabin[k][i],
                            1,
                            present,
                            f"boundary_state[{k},{i}]",
                        )
                    )
        model.add_no_overlap(intervals + local_intervals)
    return built


class ReservoirRepairOptimizer:
    def solve(
        self,
        context,
        *,
        time_limit=10,
        workers=12,
        seed=0,
        on_improvement=None,
        log_path=None,
        verify_fixed_hint=False,
        presolve=True,
    ):
        started = perf_counter()
        deadline = started + time_limit
        original_metrics = validate_reservoir_cp_plan(context.original, context.seed)
        best_plan = context.seed
        best_cost = original_metrics.journey_time_tick / 1e6
        events = []
        if context.slots == 0:
            return best_plan, {
                "status": "fixed",
                "variables": 0,
                "validated_upper_bound": best_cost,
                "native_solutions": 0,
                "events": [],
            }
        try:
            built = build_repair(context, deadline=deadline)
            model = built.movement.model
            values = _movement_values(context.local, built, context.local_seed)
            for index, value in values.items():
                model.add_hint(model.get_int_var_from_proto_index(index), value)
            alight = {
                (k, i): values[built.movement.time_by_cabin[k][i].index]
                + tick(
                    unique_stop_route_option(
                        context.local.movement, s, error_context="repair hint"
                    ).platform_entry_offset_seconds
                )
                for k, visit_states in built.movement.states_by_cabin.items()
                for i, s in enumerate(visit_states[:-1])
            }
            built.passengers.add_hints(
                context.local, model, context.local_seed.ride_counts, alight
            )
            complete_cp_hints(model)
            local_value = validate_reservoir_cp_plan(
                context.local, context.local_seed
            ).journey_time_tick
            model.add(built.passengers.objective_expression <= local_value)
            if model.validate():
                raise ValueError(model.validate())
        except TimeoutError:
            return best_plan, {
                "status": "build_timeout",
                "validated_upper_bound": best_cost,
                "native_solutions": 0,
                "events": [],
                "actual_total_seconds": perf_counter() - started,
            }
        build_seconds = perf_counter() - started

        class Callback(cp_model.CpSolverSolutionCallback):
            def on_solution_callback(callback):
                nonlocal best_plan, best_cost
                local_plan = _extract(context.local, built, callback.value)
                merged = context.assemble(local_plan)
                value = (
                    validate_reservoir_cp_plan(
                        context.original, merged
                    ).journey_time_tick
                    / 1e6
                )
                improved = value < best_cost - 1e-6
                events.append(
                    {
                        "elapsed_seconds": perf_counter() - started,
                        "validated_upper_bound": value,
                        "improvement": improved,
                    }
                )
                if improved:
                    best_plan, best_cost = merged, value
                    if on_improvement:
                        on_improvement(merged)

        solver = cp_model.CpSolver()
        solver.parameters.num_search_workers = workers
        solver.parameters.random_seed = seed
        solver.parameters.cp_model_presolve = presolve
        remaining = deadline - perf_counter()
        status = "BUILD_TIME_LIMIT"
        search_seconds = 0
        if remaining > 0:
            solver.parameters.max_time_in_seconds = remaining
            solver.parameters.fix_variables_to_their_hinted_value = verify_fixed_hint
            solver.parameters.log_search_progress = log_path is not None
            solver.parameters.log_to_stdout = False
            before = perf_counter()
            if log_path is not None:
                with log_path.open("w") as log:
                    solver.log_callback = lambda line: (
                        log.write(line + "\n"),
                        log.flush(),
                    )
                    status = solver.status_name(solver.solve(model, Callback()))
            else:
                status = solver.status_name(solver.solve(model, Callback()))
            search_seconds = perf_counter() - before
            if status == "INFEASIBLE":
                raise ValueError("repair model contradicts the validated feasible seed")
        return best_plan, {
            "status": status,
            "scope": "local_repair_only",
            "validated_upper_bound": best_cost,
            "native_solutions": len(events),
            "events": events,
            "variables": len(model.proto.variables),
            "constraints": len(model.proto.constraints),
            "open_deployments": len(context.open_ids),
            "local_slots": context.local.available_fleet_count,
            "outside_deployments": len(context.outside.trips),
            "build_seconds": build_seconds,
            "search_seconds": search_seconds,
            "actual_total_seconds": perf_counter() - started,
            "hinted_variables": len(model.proto.solution_hint.vars),
            "local_raw_bound": solver.best_objective_bound if remaining > 0 else None,
            "seed_adoption_is_improvement": False,
            "response_stats": solver.response_stats() if remaining > 0 else None,
            "fixed_hint_diagnostic": verify_fixed_hint,
            "presolve": presolve,
        }
