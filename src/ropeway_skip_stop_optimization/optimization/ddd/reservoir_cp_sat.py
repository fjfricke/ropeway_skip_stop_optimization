"""Integrated reservoir CP-SAT with optional cabins and one deployment per cabin."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field, replace
from enum import StrEnum
import math
from time import perf_counter

from ortools.sat.python import cp_model

from .cp_formulation import formulation_identity, prepare_cp_structure, apply_cp_temporal
from .cp_hint_completion import complete_cp_hints
from .cp_sat_integrated import DddIntegratedCpSatConfig, _ProgressEvents
from .cp_sat_certificate import stable_fingerprint
from .cp_sat_movement import DddCpSatMovementModel
from .cp_sat_passenger import (
    DddCpSatPassengerEncoding,
    DddCpSatPassengerModel,
    build_ddd_cp_sat_passenger_assignment,
)
from .cp_sat_passenger_inventory import (
    DddCpSatInventoryPassengerModel,
    build_ddd_cp_sat_od_inventory_passengers,
)
from .reservoir_cp_sat_problem import DddReservoirCpSatProblem
from .reservoir_cp_sat_movement import build_reservoir_cp_movement
from .models import DddRouteDecision
from .route_topology import unique_stop_route_option
from .reservoir_cp_sat_certificate import (
    DddReservoirCpPlan,
    DddReservoirCpTrip,
    validate_reservoir_cp_plan,
    write_reservoir_cp_checkpoint,
)
from .time_ticks import DDD_TIME_TICKS_PER_SECOND, ddd_seconds_to_tick


class DddReservoirCpObjective(StrEnum):
    JOURNEY_TIME = "journey_time"
    UNSERVED = "unserved"
    SERVICE_THEN_JOURNEY = "service_then_journey"


@dataclass(frozen=True)
class DddReservoirCpModel:
    movement: DddCpSatMovementModel
    passengers: DddCpSatPassengerModel | DddCpSatInventoryPassengerModel
    stats: dict
    fingerprint: str


def build_reservoir_cp_sat(
    problem,
    *,
    config=DddIntegratedCpSatConfig(),
    objective=DddReservoirCpObjective.JOURNEY_TIME,
    deadline=None,
    dispatch_order_symmetry=True,
    lexicographic_unserved_cap=None,
    minimum_active_fleet=0,
):
    if not isinstance(objective, DddReservoirCpObjective):
        raise ValueError("invalid reservoir objective")
    config.validate()
    if (
        type(minimum_active_fleet) is not int
        or not 0 <= minimum_active_fleet <= problem.available_fleet_count
    ):
        raise ValueError("minimum active fleet lies outside available fleet")
    movement = build_reservoir_cp_movement(
        problem,
        deadline=deadline,
        resource_encoding=config.formulation.resource_encoding,
        dispatch_order_symmetry=dispatch_order_symmetry,
    )
    for cabin in range(minimum_active_fleet):
        movement.model.add(movement.active_by_cabin[cabin][0] == 1)
    preprocessing_started = perf_counter()
    prepared = None
    if not config.formulation.legacy:
        prepared = prepare_cp_structure(problem.movement, problem.passenger_build, movement.states_by_cabin, reservoir=problem)
        if config.formulation.enabled("temporal"):
            apply_cp_temporal(movement, prepared, reservoir=True)
    preprocessing_seconds = perf_counter() - preprocessing_started
    passenger_arguments = dict(
        cost_encoding=config.cost_encoding,
        deadline_monotonic=deadline,
        with_journey_cost=objective is not DddReservoirCpObjective.UNSERVED,
    )
    if config.passenger_encoding is DddCpSatPassengerEncoding.OD_INVENTORY:
        passengers = build_ddd_cp_sat_od_inventory_passengers(
            problem.movement,
            problem.passenger_build,
            problem.cabin_capacity,
            movement,
            **passenger_arguments,
        )
    else:
        passengers = build_ddd_cp_sat_passenger_assignment(
            problem.movement,
            problem.passenger_build,
            problem.cabin_capacity,
            movement,
            formulation=config.formulation,
            prepared=prepared,
            **passenger_arguments,
        )
    if config.route_search_priority:
        # Route literals are the only explicit decision strategy.  SKIP comes
        # first so this worker leaves the All-Stop neighbourhood early; STOP,
        # timing, waiting, activation and passenger variables remain free.
        route_literals = []
        for cabin, visit, option_id in sorted(movement.selection_by_key):
            option = next(
                candidate
                for candidate in problem.movement.route_options_by_state_id[
                    movement.states_by_cabin[cabin][visit]
                ]
                if candidate.id == option_id
            )
            route_literals.append(
                (
                    0 if option.decision is DddRouteDecision.SKIP else 1,
                    cabin,
                    visit,
                    option_id,
                    movement.selection_by_key[cabin, visit, option_id],
                )
            )
        movement.model.add_decision_strategy(
            [entry[-1] for entry in sorted(route_literals)],
            cp_model.CHOOSE_FIRST,
            cp_model.SELECT_MAX_VALUE,
        )
    if objective is DddReservoirCpObjective.SERVICE_THEN_JOURNEY:
        enforce_unserved_cap = lexicographic_unserved_cap is not None
        if lexicographic_unserved_cap is None:
            lexicographic_unserved_cap = sum(
                group.count for group in problem.demand_groups
            )
        if type(lexicographic_unserved_cap) is not int or lexicographic_unserved_cap < 0:
            raise ValueError("lexicographic objective requires a validated unserved cap")
        weight = passengers.objective_constant_tick + 1
        maximum_score = weight * lexicographic_unserved_cap + passengers.objective_constant_tick
        if maximum_score >= 2**53:
            raise ValueError("lexicographic CP-SAT objective exceeds exact reporting range")
        if enforce_unserved_cap:
            movement.model.add(
                passengers.unserved_expression <= lexicographic_unserved_cap
            )
        combined = weight * passengers.unserved_expression + passengers.journey_expression
        movement.model.minimize(combined)
        passengers = replace(
            passengers,
            objective_expression=combined,
            lexicographic_weight=weight,
        )
    error = movement.model.validate()
    if error:
        raise ValueError(f"invalid reservoir CP model: {error}")
    stats = dict(
        variables=len(movement.model.proto.variables),
        constraints=len(movement.model.proto.constraints),
        available_cabins=problem.available_fleet_count,
        visits_per_cabin=len(problem.visit_states) - 1,
        ride_candidates=len(passengers.ride_count),
        legacy_ride_candidates=passengers.legacy_ride_candidate_count,
        passenger_encoding=passengers.encoding,
        inventory_intervals=getattr(passengers, "inventory_interval_count", 0),
        resource_intervals=sum(map(len, movement.resource_intervals.values())),
        cost_auxiliaries=passengers.cost_auxiliary_count,
        route_search_priority=config.route_search_priority,
        route_priority_literals=(
            len(movement.selection_by_key) if config.route_search_priority else 0
        ),
    )
    stats["preprocessing_seconds"] = preprocessing_seconds
    if not config.formulation.legacy:
        stats["preprocessing"] = formulation_identity(config.formulation, prepared)
    return DddReservoirCpModel(
        movement,
        passengers,
        stats,
        stable_fingerprint(
            {
                "version": "single_use_reservoir_cp_v1",
                "model": str(movement.model.proto),
                **formulation_identity(config.formulation, prepared),
            }
        ),
    )


def _extract(problem, built, value):
    b = built.movement
    trips = []
    for k, states in b.states_by_cabin.items():
        ids, ticks, waits = [], [], []
        for i in range(len(states) - 1):
            if not value(b.active_by_cabin[k][i]):
                break
            oid = next(
                o.id
                for o in problem.movement.route_options_by_state_id[states[i]]
                if value(b.selection_by_key[k, i, o.id])
            )
            ids.append(oid)
            ticks.append(int(value(b.time_by_cabin[k][i])))
            waits.append(int(value(b.wait_steps_by_key[k, i])) * b.waiting_step_tick)
        if ids:
            trips.append(
                DddReservoirCpTrip(
                    k,
                    tuple(ids),
                    tuple(ticks),
                    tuple(waits),
                    int(value(b.time_by_cabin[k][len(ids)])),
                )
            )
    return DddReservoirCpPlan(
        tuple(trips),
        built.passengers.extract_legacy_counts(value),
    )


def _movement_values(problem, built, plan):
    b = built.movement
    by_cabin = {t.cabin_id: t for t in plan.trips}
    # Labels have no physical meaning; native plans use used-prefix/time symmetry.
    ordered = sorted(plan.trips, key=lambda t: (t.switch_ticks[0], t.cabin_id))
    if [t.cabin_id for t in ordered] != list(range(len(ordered))):
        raise ValueError(
            "reservoir hints require canonical cabin IDs ordered by dispatch"
        )
    values = {}
    for k, states in b.states_by_cabin.items():
        trip = by_cabin.get(k)
        n = 0 if trip is None else len(trip.route_option_ids)
        for i in range(len(states)):
            values[b.active_by_cabin[k][i].index] = int(i < n)
            values[b.time_by_cabin[k][i].index] = (
                0
                if trip is None
                else trip.switch_ticks[i]
                if i < n
                else trip.return_tick
            )
            if i == len(states) - 1:
                continue
            values[b.wait_steps_by_key[k, i].index] = (
                0 if i >= n else trip.wait_ticks[i] // b.waiting_step_tick
            )
            for o in problem.movement.route_options_by_state_id[states[i]]:
                values[b.selection_by_key[k, i, o.id].index] = int(
                    i < n and trip.route_option_ids[i] == o.id
                )
    return values


def _score(problem, metrics, objective):
    if objective is DddReservoirCpObjective.JOURNEY_TIME:
        return metrics.journey_time_tick
    if objective is DddReservoirCpObjective.UNSERVED:
        return metrics.unserved
    horizon = problem.movement.passenger_service_end_tick
    constant = sum(
        group.count * max(0, horizon - ddd_seconds_to_tick(group.release_time_seconds))
        for group in problem.demand_groups
    )
    return (constant + 1) * metrics.unserved + metrics.journey_time_tick


class _ReservoirCallback(cp_model.CpSolverSolutionCallback):
    def __init__(self, problem, built, objective, config, started, events):
        super().__init__()
        self.problem, self.built, self.objective, self.config = (
            problem,
            built,
            objective,
            config,
        )
        self.started, self.events = started, events
        self.last_checkpoint = -math.inf
        self.error = None

    def on_solution_callback(self):
        try:
            elapsed = perf_counter() - self.started
            event = dict(
                kind="incumbent",
                elapsed_seconds=elapsed,
                objective_raw=int(self.value(self.built.passengers.objective_expression)),
                bound_raw=self.best_objective_bound,
            )
            checkpoint_plan = _extract(self.problem, self.built, self.value)
            metrics = validate_reservoir_cp_plan(self.problem, checkpoint_plan)
            event.update(
                served=metrics.served,
                unserved=metrics.unserved,
                journey_time_tick=metrics.journey_time_tick,
                used_fleet=metrics.used_fleet,
            )
            self.events.append(event)
            if (
                self.config.checkpoint_path
                and elapsed - self.last_checkpoint
                >= self.config.checkpoint_interval_seconds
            ):
                write_reservoir_cp_checkpoint(
                    self.config.checkpoint_path, self.problem, checkpoint_plan
                )
                self.last_checkpoint = elapsed
        except Exception as error:
            self.error = error
            self.stop_search()


@dataclass(frozen=True)
class DddReservoirCpSatOptimizer:
    config: DddIntegratedCpSatConfig = field(default_factory=DddIntegratedCpSatConfig)
    objective: DddReservoirCpObjective = DddReservoirCpObjective.JOURNEY_TIME

    def solve(
        self,
        problem: DddReservoirCpSatProblem,
        *,
        primal_seed=None,
        use_primal_hint=True,
        use_primal_cutoff=True,
        use_primal_lexicographic_cap=True,
        minimum_active_fleet=0,
        fixed_plan=None,
        fixed_route_plan=None,
        diagnostic=None,
        event_callback=None,
        log_callback=None,
        require_full_service=False,
    ):
        self.config.validate()
        if not isinstance(use_primal_hint, bool):
            raise ValueError("use_primal_hint must be boolean")
        if not isinstance(use_primal_cutoff, bool):
            raise ValueError("use_primal_cutoff must be boolean")
        if not isinstance(use_primal_lexicographic_cap, bool):
            raise ValueError("use_primal_lexicographic_cap must be boolean")
        if (
            type(minimum_active_fleet) is not int
            or not 0 <= minimum_active_fleet <= problem.available_fleet_count
        ):
            raise ValueError("minimum active fleet lies outside available fleet")
        if diagnostic is not None and (
            fixed_plan is not None or fixed_route_plan is not None or primal_seed is None
        ):
            raise ValueError("diagnostic requires a reference seed and no fixed_plan")
        if fixed_plan is not None and fixed_route_plan is not None:
            raise ValueError("choose either a fixed movement or a fixed route sequence")
        if not isinstance(self.objective, DddReservoirCpObjective):
            raise ValueError("invalid reservoir objective")
        started = perf_counter()
        deadline = started + self.config.total_time_limit_seconds
        problem.validate()
        manifest = problem.manifest
        # Empty reservoir operation is always a valid primal baseline, not proof
        # that any passenger can be served.
        plan = primal_seed or DddReservoirCpPlan((), {})
        metrics = validate_reservoir_cp_plan(problem, plan)
        has_restricted_primal = metrics.used_fleet >= minimum_active_fleet
        if fixed_plan is not None:
            validate_reservoir_cp_plan(problem, fixed_plan)
            if primal_seed is not None and primal_seed.trips != fixed_plan.trips:
                raise ValueError("reservoir seed differs from fixed movement")
            if primal_seed is None:
                plan = DddReservoirCpPlan(fixed_plan.trips, {})
                metrics = validate_reservoir_cp_plan(problem, plan)
                has_restricted_primal = metrics.used_fleet >= minimum_active_fleet
        if fixed_route_plan is not None:
            validate_reservoir_cp_plan(problem, fixed_route_plan)
            if primal_seed is None:
                plan = fixed_route_plan
                metrics = validate_reservoir_cp_plan(problem, plan)
                has_restricted_primal = metrics.used_fleet >= minimum_active_fleet
            elif tuple(
                (trip.cabin_id, trip.route_option_ids) for trip in primal_seed.trips
            ) != tuple(
                (trip.cabin_id, trip.route_option_ids)
                for trip in fixed_route_plan.trips
            ):
                raise ValueError("reservoir seed differs from fixed route sequence")
        built = None
        events = _ProgressEvents(event_callback)
        status, reason, optimal = "UNKNOWN", "BUILD_TIME_LIMIT", False
        raw_bound = bound = cp_value = None
        solve_seconds = validation_seconds = 0.0
        response = None
        try:
            if perf_counter() >= deadline:
                raise TimeoutError()
            built = build_reservoir_cp_sat(
                problem,
                config=self.config,
                objective=self.objective,
                deadline=deadline,
                lexicographic_unserved_cap=(
                    metrics.unserved
                    if (
                        self.objective is DddReservoirCpObjective.SERVICE_THEN_JOURNEY
                        and use_primal_lexicographic_cap
                    )
                    else None
                ),
                minimum_active_fleet=minimum_active_fleet,
            )
        except TimeoutError:
            pass
        hint_started = perf_counter()
        model_build_seconds = hint_started - started
        if built is not None:
            model = built.movement.model
            if require_full_service:
                if self.objective is not DddReservoirCpObjective.UNSERVED:
                    raise ValueError("full-service requirement requires unserved objective")
                model.add(built.passengers.objective_expression == 0)
            if diagnostic is not None:
                info = diagnostic.apply(problem, built, plan)
                built = replace(built, stats={**built.stats, "diagnostic": info})
            values = _movement_values(problem, built, plan)
            for index, value in values.items():
                variable = model.get_int_var_from_proto_index(index)
                if use_primal_hint:
                    model.add_hint(variable, value)
                if fixed_plan is not None:
                    model.add(variable == value)
            if fixed_route_plan is not None:
                route_by_cabin = {
                    trip.cabin_id: trip for trip in fixed_route_plan.trips
                }
                for cabin, states in built.movement.states_by_cabin.items():
                    trip = route_by_cabin.get(cabin)
                    count = 0 if trip is None else len(trip.route_option_ids)
                    for visit_index in range(len(states)):
                        model.add(
                            built.movement.active_by_cabin[cabin][visit_index]
                            == int(visit_index < count)
                        )
                        if visit_index == len(states) - 1:
                            continue
                        for option in problem.movement.route_options_by_state_id[
                            states[visit_index]
                        ]:
                            model.add(
                                built.movement.selection_by_key[
                                    cabin, visit_index, option.id
                                ]
                                == int(
                                    visit_index < count
                                    and trip is not None
                                    and trip.route_option_ids[visit_index] == option.id
                                )
                            )
            if not built.passengers.supports_legacy_counts(plan.ride_counts):
                raise ValueError("positive seed count on pruned ride")
            if use_primal_hint and self.config.formulation.enabled("hints"):
                alight = {
                    (cabin, visit_index): values[
                        built.movement.time_by_cabin[cabin][visit_index].index
                    ]
                    + ddd_seconds_to_tick(
                        unique_stop_route_option(
                            problem.movement,
                            state,
                            error_context="hint",
                        ).platform_entry_offset_seconds
                    )
                    for cabin, states in built.movement.states_by_cabin.items()
                    for visit_index, state in enumerate(states[:-1])
                }
                built.passengers.add_hints(problem, model, plan.ride_counts, alight)
                complete_cp_hints(model)
            elif use_primal_hint and built.passengers.encoding == DddCpSatPassengerEncoding.GROUPS.value:
                for q, v in built.passengers.ride_count.items():
                    model.add_hint(v, plan.ride_counts.get(q, 0))
            elif use_primal_hint:
                built.passengers.add_hints(
                    problem,
                    model,
                    plan.ride_counts,
                    {
                        (cabin, visit_index): values[
                            built.movement.time_by_cabin[cabin][visit_index].index
                        ]
                        + ddd_seconds_to_tick(
                            unique_stop_route_option(
                                problem.movement,
                                state,
                                error_context="inventory hint",
                            ).platform_entry_offset_seconds
                        )
                        for cabin, states in built.movement.states_by_cabin.items()
                        for visit_index, state in enumerate(states[:-1])
                    },
                )
            if use_primal_cutoff and has_restricted_primal:
                # A validated feasible cutoff; does not restrict the true optimum.
                model.add(
                    built.passengers.objective_expression
                    <= _score(problem, metrics, self.objective)
                )
            built = replace(
                built,
                stats={
                    **built.stats,
                    "variables": len(model.proto.variables),
                    "constraints": len(model.proto.constraints),
                },
                fingerprint=stable_fingerprint(
                    {"version": "single_use_reservoir_cp_v1", "model": str(model.proto), **built.stats.get("preprocessing", {})}
                ),
            )
        hint_seconds = perf_counter() - hint_started
        build_seconds = perf_counter() - started
        if built is not None and perf_counter() < deadline:
            solver = cp_model.CpSolver()
            solver.parameters.max_time_in_seconds = deadline - perf_counter()
            solver.parameters.num_search_workers = self.config.num_workers
            solver.parameters.random_seed = self.config.seed
            solver.parameters.relative_gap_limit = (
                solver.parameters.absolute_gap_limit
            ) = 0
            solver.parameters.log_search_progress = self.config.log_search_progress
            if self.config.route_search_priority:
                # Replace CP-SAT's built-in fixed-search worker with a partial
                # fixed-search worker.  The remaining portfolio workers keep
                # their automatic strategies and share incumbents/bounds.
                solver.parameters.merge_text_format(
                    'ignore_subsolvers: "fixed" '
                    'extra_subsolvers: "route_priority" '
                    'subsolver_params { '
                    'name: "route_priority" '
                    'search_branching: PARTIAL_FIXED_SEARCH '
                    '}'
                )
            if log_callback:
                solver.log_callback = log_callback
                solver.parameters.log_to_stdout = False
            last_bound = [-math.inf]

            def progress(value):
                if perf_counter() - last_bound[0] >= 0.5:
                    events.append(
                        dict(
                            kind="bound",
                            elapsed_seconds=perf_counter() - started,
                            bound_raw=value,
                        )
                    )
                    last_bound[0] = perf_counter()

            solver.best_bound_callback = progress
            callback = _ReservoirCallback(
                problem, built, self.objective, self.config, started, events
            )
            before = perf_counter()
            code = solver.solve(built.movement.model, callback)
            solve_seconds = perf_counter() - before
            if callback.error:
                raise RuntimeError(
                    "reservoir CP callback validation failed"
                ) from callback.error
            status, response = solver.status_name(code), solver.response_stats()
            reason = (
                "TIME_LIMIT"
                if code in (cp_model.FEASIBLE, cp_model.UNKNOWN)
                and perf_counter() >= deadline
                else status
            )
            if code == cp_model.MODEL_INVALID or (
                code == cp_model.INFEASIBLE
                and has_restricted_primal
                and (not require_full_service or metrics.unserved == 0)
            ):
                raise RuntimeError(
                    f"reservoir CP {status} contradicts the validated primal: {response}"
                )
            if code in (cp_model.FEASIBLE, cp_model.OPTIMAL):
                before = perf_counter()
                found = _extract(problem, built, solver.value)
                checked = validate_reservoir_cp_plan(problem, found)
                cp_value = int(solver.value(built.passengers.objective_expression))
                if cp_value != _score(problem, checked, self.objective):
                    raise RuntimeError(
                        "reservoir CP cost differs from independent validation"
                    )
                if (
                    not has_restricted_primal
                    or cp_value <= _score(problem, metrics, self.objective)
                ):
                    plan, metrics = found, checked
                    has_restricted_primal = True
                validation_seconds = perf_counter() - before
            raw_bound = float(solver.best_objective_bound)
            if math.isfinite(raw_bound):
                bound = max(0, math.floor(math.nextafter(raw_bound, -math.inf)))
            if require_full_service and code == cp_model.INFEASIBLE:
                # U=0 was excluded, not all original schedules. This proves
                # only U* >= 1; the native infeasibility bound is not a cost LB.
                bound = 1
            if code == cp_model.OPTIMAL:
                if cp_value is None or abs(raw_bound - cp_value) > 0.25:
                    raise RuntimeError("reservoir CP inconsistent optimal bound")
                optimal, bound = True, cp_value
            if (
                has_restricted_primal
                and bound is not None
                and bound > _score(problem, metrics, self.objective)
            ):
                raise RuntimeError(
                    "reservoir CP lower bound exceeds validated upper bound"
                )
        if diagnostic is not None:
            diagnostic.validate(problem, primal_seed, plan)
        if self.config.checkpoint_path and has_restricted_primal:
            before = perf_counter()
            write_reservoir_cp_checkpoint(self.config.checkpoint_path, problem, plan)
            validation_seconds += perf_counter() - before
        scale = (
            DDD_TIME_TICKS_PER_SECOND
            if self.objective is DddReservoirCpObjective.JOURNEY_TIME
            else 1
        )
        upper = (
            _score(problem, metrics, self.objective) / scale
            if has_restricted_primal
            else None
        )
        lower = None if bound is None else bound / scale
        events.append(
            dict(
                kind="final",
                elapsed_seconds=perf_counter() - started,
                objective_raw=(
                    _score(problem, metrics, self.objective)
                    if has_restricted_primal
                    else None
                ),
                bound_raw=bound,
                status=status,
            )
        )
        result = dict(
            primal_hint_enabled=use_primal_hint,
            primal_cutoff_enabled=use_primal_cutoff,
            primal_lexicographic_cap_enabled=use_primal_lexicographic_cap,
            minimum_active_fleet=minimum_active_fleet,
            restricted_primal_available=has_restricted_primal,
            require_full_service=require_full_service,
            full_service_witness=metrics.unserved == 0,
            schema="single_use_reservoir_cp_result_v1",
            problem_fingerprint=problem.fingerprint,
            domain_manifest=manifest,
            proof_scope=(diagnostic.proof_scope if diagnostic is not None else
                         "FIXED_MOVEMENT" if fixed_plan is not None else
                         "FIXED_ROUTE_SEQUENCE" if fixed_route_plan is not None else
                         "RESERVOIR_SINGLE_USE_GLOBAL"),
            objective=self.objective.value,
            cost_encoding=self.config.cost_encoding.value,
            passenger_encoding=self.config.passenger_encoding.value,
            bound_units=(
                "passenger_seconds" if scale > 1 else
                "lexicographic_score_ticks" if self.objective is DddReservoirCpObjective.SERVICE_THEN_JOURNEY else
                "persons"
            ),
            journey_time_seconds=(
                metrics.journey_time_tick / DDD_TIME_TICKS_PER_SECOND
            ),
            lexicographic_weight_tick=(
                None if built is None else built.passengers.lexicographic_weight
            ),
            solver_status=status,
            termination_reason=reason,
            proven_optimal=optimal,
            validated_upper_bound=upper,
            cp_lower_bound=lower,
            relative_gap=None
            if lower is None or upper is None
            else (upper - lower) / max(abs(upper), 1),
            cp_objective_raw=cp_value,
            raw_cp_bound=raw_bound,
            model_fingerprint=None if built is None else built.fingerprint,
            model_stats={} if built is None else built.stats,
            metrics=asdict(metrics),
            plan=asdict(plan),
            build_seconds=build_seconds,
            hint_seconds=hint_seconds, model_build_seconds=model_build_seconds,
            solve_seconds=solve_seconds,
            validation_seconds=validation_seconds,
            total_wall_seconds=perf_counter() - started,
            response_stats=response,
            num_workers=self.config.num_workers,
            seed=self.config.seed,
            events=list(events),
        )
        return result
