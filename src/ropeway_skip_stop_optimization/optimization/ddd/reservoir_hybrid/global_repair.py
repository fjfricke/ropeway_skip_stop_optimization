"""Small variable movement core with globally free integer passengers.

Outside movements enter the passenger view as constants; their physical calendar
is the existing repair calendar. Virtual labels are canonicalized only on export.
"""

from dataclasses import asdict, dataclass, replace
from time import perf_counter

from ortools.sat.python import cp_model

from ..cp_hint_completion import complete_cp_hints
from ..cp_sat_certificate import stable_fingerprint
from ..cp_sat_passenger import build_ddd_cp_sat_passenger_assignment
from ..reservoir_cp_sat import _movement_values, _extract, DddReservoirCpModel
from ..reservoir_cp_sat_certificate import (
    DddReservoirCpPlan,
    validate_reservoir_cp_plan,
)
from ..route_topology import unique_stop_route_option
from ..models import DddRouteDecision
from ..time_ticks import ddd_seconds_to_tick as tick
from .repair import ReservoirRepairProblem, build_repair, translate_plan


@dataclass(frozen=True)
class GlobalPassengerRepair:
    context: ReservoirRepairProblem

    def build(self, deadline=None):
        c = self.context
        # Build only the open movement slots and the existing outside calendar.
        empty = replace(c.local, demand_groups=())
        physical = build_repair(replace(c, local=empty), deadline=deadline)
        b = physical.movement
        model = b.model
        times = dict(b.time_by_cabin)
        active = dict(b.active_by_cabin)
        waits = dict(b.wait_steps_by_key)
        selection = dict(b.selection_by_key)
        states = dict(b.states_by_cabin)
        slots = empty.available_fleet_count
        virtual = replace(
            c.original, available_fleet_count=slots + len(c.outside.trips)
        )
        outside_map = {t.cabin_id: slots + j for j, t in enumerate(c.outside.trips)}
        outside = translate_plan(c.original, virtual, c.outside, outside_map)
        opened = translate_plan(
            c.local, virtual, c.local_seed, {k: k for k in range(slots)}
        )
        hint = DddReservoirCpPlan(
            outside.trips + opened.trips, {**outside.ride_counts, **opened.ride_counts}
        )
        options = {o.id: o for o in c.original.resolved_core.route_options}
        outside_trips = {t.cabin_id: t for t in outside.trips}
        for k, t in outside_trips.items():
            n = len(t.route_option_ids)
            states[k] = c.original.visit_states[: n + 1]
            times[k] = [model.new_constant(v) for v in (*t.switch_ticks, t.return_tick)]
            active[k] = [model.new_constant(int(i < n)) for i in range(n + 1)]
            for i, oid in enumerate(t.route_option_ids):
                waits[k, i] = model.new_constant(t.wait_ticks[i] // b.waiting_step_tick)
                for o in c.original.movement.route_options_by_state_id[states[k][i]]:
                    selection[k, i, o.id] = model.new_constant(int(o.id == oid))
        view = replace(
            b,
            time_by_cabin=times,
            active_by_cabin=active,
            wait_steps_by_key=waits,
            selection_by_key=selection,
            states_by_cabin=states,
        )
        groups = {g.id: g for g in virtual.demand_groups}
        keep = []
        for q in virtual.passenger_build.ride_candidates:
            if q.cabin_id in outside_trips:
                t = outside_trips[q.cabin_id]
                i, j = q.board_visit_index, q.alight_visit_index
                if j >= len(t.route_option_ids):
                    continue
                board, alight = (
                    options[t.route_option_ids[i]],
                    options[t.route_option_ids[j]],
                )
                if (
                    board.decision is not DddRouteDecision.STOP
                    or alight.decision is not DddRouteDecision.STOP
                ):
                    continue
                departure = (
                    t.switch_ticks[i]
                    + tick(board.platform_exit_offset_seconds)
                    + t.wait_ticks[i]
                )
                arrival = t.switch_ticks[j] + tick(alight.platform_entry_offset_seconds)
                if (
                    not max(0, tick(groups[q.demand_group_id].release_time_seconds))
                    <= departure
                    <= arrival
                    <= virtual.movement.passenger_service_end_tick
                ):
                    continue
            keep.append(q)
        passengers = build_ddd_cp_sat_passenger_assignment(
            virtual.movement,
            replace(virtual.passenger_build, ride_candidates=tuple(keep)),
            virtual.cabin_capacity,
            view,
            deadline_monotonic=deadline,
        )
        built = DddReservoirCpModel(
            view,
            passengers,
            {},
            stable_fingerprint(
                {
                    "formulation": "global_passenger_repair_v1",
                    "original_domain": c.original.fingerprint,
                    "seed": asdict(c.seed),
                    "open_ids": c.open_ids,
                    "local_slots": c.slots,
                    "retained_candidates": [q.id for q in keep],
                }
            ),
        )
        values = _movement_values(empty, physical, c.local_seed)
        for index, value in values.items():
            model.add_hint(model.get_int_var_from_proto_index(index), value)
            if c.slots == 0:
                model.add(model.get_int_var_from_proto_index(index) == value)
        alight_times = {}
        for k, visit_states in states.items():
            for i, state in enumerate(visit_states[:-1]):
                v = times[k][i]
                base = (
                    values[v.index]
                    if v.index in values
                    else int(list(v.proto.domain)[0])
                )
                alight_times[k, i] = base + tick(
                    unique_stop_route_option(
                        virtual.movement, state, error_context="global repair hint"
                    ).platform_entry_offset_seconds
                )
        passengers.add_hints(virtual, model, hint.ride_counts, alight_times)
        complete_cp_hints(model)
        model.add(
            passengers.objective_expression
            <= validate_reservoir_cp_plan(c.original, c.seed).journey_time_tick
        )
        if model.validate():
            raise ValueError(model.validate())
        return built, virtual, values

    def extract(self, built, virtual, value):
        plan = _extract(virtual, built, value)
        ordered = sorted(plan.trips, key=lambda t: (t.switch_ticks[0], t.cabin_id))
        merged = translate_plan(
            virtual,
            self.context.original,
            plan,
            {t.cabin_id: k for k, t in enumerate(ordered)},
        )
        validate_reservoir_cp_plan(self.context.original, merged)
        return merged

    def solve(
        self,
        *,
        time_limit=30,
        workers=12,
        seed=0,
        presolve=True,
        on_improvement=None,
        log_path=None,
    ):
        started = perf_counter()
        best = self.context.seed
        best_tick = validate_reservoir_cp_plan(
            self.context.original, best
        ).journey_time_tick
        events = []
        try:
            built, virtual, _ = self.build(started + time_limit)
        except TimeoutError:
            return best, dict(
                status="BUILD_TIMEOUT",
                validated_upper_bound=best_tick / 1e6,
                events=[],
                scope="local_repair_only",
            )
        build_seconds = perf_counter() - started
        owner = self

        class Callback(cp_model.CpSolverSolutionCallback):
            def on_solution_callback(self):
                nonlocal best, best_tick
                plan = owner.extract(built, virtual, self.value)
                cost = validate_reservoir_cp_plan(
                    owner.context.original, plan
                ).journey_time_tick
                improved = cost < best_tick
                events.append(
                    dict(
                        elapsed_seconds=perf_counter() - started,
                        validated_upper_bound=cost / 1e6,
                        improvement=improved,
                    )
                )
                if improved:
                    best, best_tick = plan, cost
                    if on_improvement:
                        on_improvement(plan)

        solver = cp_model.CpSolver()
        solver.parameters.num_search_workers = workers
        solver.parameters.random_seed = seed
        solver.parameters.cp_model_presolve = presolve
        solver.parameters.max_time_in_seconds = max(0.001, time_limit - build_seconds)
        solver.parameters.log_search_progress = log_path is not None
        solver.parameters.log_to_stdout = False
        if log_path:
            with log_path.open("w") as log:
                solver.log_callback = lambda line: (log.write(line + "\n"), log.flush())
                status = solver.status_name(
                    solver.solve(built.movement.model, Callback())
                )
        else:
            status = solver.status_name(solver.solve(built.movement.model, Callback()))
        if status in ("INFEASIBLE", "MODEL_INVALID"):
            raise ValueError(f"global repair contradicts checked seed: {status}")
        return best, dict(
            status=status,
            scope="local_repair_only",
            validated_upper_bound=best_tick / 1e6,
            events=events,
            native_solutions=len(events),
            build_seconds=build_seconds,
            actual_total_seconds=perf_counter() - started,
            variables=len(built.movement.model.proto.variables),
            constraints=len(built.movement.model.proto.constraints),
            passenger_candidates=len(built.passengers.ride_count),
            local_movement_slots=self.context.local.available_fleet_count,
            local_raw_bound=solver.best_objective_bound,
            presolve=presolve,
        )
