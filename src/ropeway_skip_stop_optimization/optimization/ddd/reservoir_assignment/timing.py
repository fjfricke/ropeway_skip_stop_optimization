"""Exact CP-SAT timing of a fixed demand-led service assignment."""

from dataclasses import asdict, dataclass
from enum import StrEnum
import math
from time import perf_counter

from ortools.sat.python import cp_model

from ..cp_sat_integrated import DddIntegratedCpSatConfig
from ..reservoir_cp_sat import (
    DddReservoirCpObjective,
    _extract,
    build_reservoir_cp_sat,
)
from ..reservoir_cp_sat_certificate import validate_reservoir_cp_plan
from .assignment import canonicalize_reservoir_plan, validate_service_assignment


class ReservoirPassengerFixing(StrEnum):
    EXACT = "exact"
    COMMITMENTS = "commitments"
    REASSIGN = "reassign"


@dataclass(frozen=True)
class ReservoirAssignmentTimingConfig:
    time_limit_seconds: float = 120.0
    workers: int = 12
    seed: int = 0
    log_search_progress: bool = False
    use_witness_hints: bool = True
    fix_routes: bool = True
    fix_witness_waits: bool = False
    fix_witness_resource_order: bool = False
    passenger_fixing: ReservoirPassengerFixing = ReservoirPassengerFixing.EXACT

    def validate(self):
        if not math.isfinite(self.time_limit_seconds) or self.time_limit_seconds <= 0:
            raise ValueError("invalid assignment timing limit")
        if (
            type(self.workers) is not int
            or self.workers <= 0
            or type(self.seed) is not int
            or self.seed < 0
        ):
            raise ValueError("invalid assignment timing workers/seed")
        if self.fix_witness_resource_order and not self.fix_routes:
            raise ValueError("fixing witness resource order requires fixed routes")
        try:
            ReservoirPassengerFixing(self.passenger_fixing)
        except ValueError as error:
            raise ValueError("unknown passenger fixing mode") from error


@dataclass(frozen=True)
class ReservoirTimingAssumption:
    id: str
    kind: str
    key: str
    value: int
    literal_index: int


@dataclass(frozen=True)
class ReservoirAssignmentTimingModel:
    built: object
    trips: dict
    assumptions: tuple[ReservoirTimingAssumption, ...]
    build_seconds: float
    fixed_resource_precedences: int


def _conditional_constraint(model, constraint, *, assumptionize, metadata, registry):
    if not assumptionize:
        return
    literal = model.new_bool_var(f"assignment_assumption[{len(registry)}]")
    constraint.only_enforce_if(literal)
    model.add_assumption(literal)
    registry.append(
        ReservoirTimingAssumption(*metadata, literal_index=literal.index)
    )


def _add_witness_resource_order(problem, movement, trips):
    """Fix each resource's order to the individually valid witness trips.

    This is a diagnostic restriction.  It deliberately keeps the original
    NoOverlap constraints and adds only precedences that the witness satisfies.
    """
    uses_by_resource = {}
    options_by_state = problem.resolved_core.route_options_by_state_id
    resources = problem.resolved_core.resources_by_id
    horizon = problem.resolved_core.operational_end_tick
    step = movement.waiting_step_tick
    for trip in trips.values():
        states = movement.states_by_cabin[trip.cabin_id]
        for i, oid in enumerate(trip.route_option_ids):
            option = next(o for o in options_by_state[states[i]] if o.id == oid)
            witness_time = trip.witness_switch_ticks[i]
            witness_wait = trip.witness_wait_ticks[i]
            wait_steps = movement.wait_steps_by_key[trip.cabin_id, i]
            event_time = movement.time_by_cabin[trip.cabin_id][i]
            for usage_index, usage in enumerate(option.resource_usages):
                resource = resources[usage.resource_id]
                witness_entry = (
                    witness_time
                    + usage.follower_enter_offset_tick
                    + usage.follower_enter_wait_coefficient * witness_wait
                )
                # The shared movement builder omits non-entry resource uses
                # whose entry lies after the operational horizon.
                if (
                    usage.follower_enter_offset_tick != 0
                    or usage.follower_enter_wait_coefficient != 0
                ) and witness_entry > horizon:
                    continue
                witness_end = (
                    witness_time
                    + usage.leader_clear_offset_tick
                    + usage.leader_clear_wait_coefficient * witness_wait
                    + usage.separation_after_tick(resource.minimum_headway_tick)
                )
                entry = (
                    event_time
                    + usage.follower_enter_offset_tick
                    + usage.follower_enter_wait_coefficient * step * wait_steps
                )
                end = (
                    event_time
                    + usage.leader_clear_offset_tick
                    + usage.leader_clear_wait_coefficient * step * wait_steps
                    + usage.separation_after_tick(resource.minimum_headway_tick)
                )
                uses_by_resource.setdefault(usage.resource_id, []).append(
                    (
                        witness_entry,
                        witness_end,
                        trip.cabin_id,
                        i,
                        usage_index,
                        entry,
                        end,
                    )
                )
    count = 0
    for uses in uses_by_resource.values():
        uses.sort(key=lambda item: item[:5])
        for previous, following in zip(uses, uses[1:]):
            movement.model.add(previous[-1] <= following[-2])
            count += 1
    return count


def build_assignment_timing_model(
    problem,
    assignment,
    config=ReservoirAssignmentTimingConfig(),
    *,
    assumptionize=False,
):
    config.validate()
    validate_service_assignment(problem, assignment)
    started = perf_counter()
    cp_config = DddIntegratedCpSatConfig(
        total_time_limit_seconds=config.time_limit_seconds,
        num_workers=config.workers,
        seed=config.seed,
        log_search_progress=config.log_search_progress,
    )
    built = build_reservoir_cp_sat(
        problem,
        config=cp_config,
        objective=DddReservoirCpObjective.UNSERVED,
        dispatch_order_symmetry=False,
    )
    movement = built.movement
    model = movement.model
    trips = {t.cabin_id: t for t in assignment.trips}
    assumptions = []
    options_by_state = problem.resolved_core.route_options_by_state_id
    for k, states in movement.states_by_cabin.items():
        trip = trips.get(k)
        n = 0 if trip is None else len(trip.route_option_ids)
        for i, variable in enumerate(movement.active_by_cabin[k]):
            value = int(i < n)
            constraint = model.add(variable == value)
            _conditional_constraint(
                model,
                constraint,
                assumptionize=assumptionize,
                metadata=(f"active::{k}::{i}", "active", f"{k}:{i}", value),
                registry=assumptions,
            )
        if trip is None:
            continue
        for i, oid in enumerate(trip.route_option_ids):
            if oid not in {o.id for o in options_by_state[states[i]]}:
                raise ValueError("assignment route does not match visit state")
            if config.fix_routes:
                constraint = model.add(movement.selection_by_key[k, i, oid] == 1)
                _conditional_constraint(
                    model,
                    constraint,
                    assumptionize=assumptionize,
                    metadata=(f"route::{k}::{i}::{oid}", "route", f"{k}:{i}:{oid}", 1),
                    registry=assumptions,
                )
            elif config.use_witness_hints:
                for option in options_by_state[states[i]]:
                    model.add_hint(
                        movement.selection_by_key[k, i, option.id],
                        int(option.id == oid),
                    )
        if config.use_witness_hints:
            for i, value in enumerate(trip.witness_switch_ticks):
                model.add_hint(movement.time_by_cabin[k][i], value)
                model.add_hint(
                    movement.wait_steps_by_key[k, i],
                    trip.witness_wait_ticks[i] // movement.waiting_step_tick,
                )
            model.add_hint(movement.time_by_cabin[k][n], trip.witness_return_tick)
        if config.fix_witness_waits:
            for i, value in enumerate(trip.witness_wait_ticks):
                if value % movement.waiting_step_tick:
                    raise ValueError("witness wait is not on the CP-SAT waiting grid")
                constraint = model.add(
                    movement.wait_steps_by_key[k, i]
                    == value // movement.waiting_step_tick
                )
                _conditional_constraint(
                    model,
                    constraint,
                    assumptionize=assumptionize,
                    metadata=(
                        f"wait::{k}::{i}",
                        "wait",
                        f"{k}:{i}",
                        value // movement.waiting_step_tick,
                    ),
                    registry=assumptions,
                )
    missing = {
        rid for rid, count in assignment.ride_counts.items()
        if count and rid not in built.passengers.ride_count
    }
    if missing:
        raise ValueError(f"assignment uses unavailable ride: {min(missing)}")
    passenger_fixing = ReservoirPassengerFixing(config.passenger_fixing)
    if passenger_fixing is ReservoirPassengerFixing.EXACT:
        fixed_rides = (
            (rid, variable, assignment.ride_counts.get(rid, 0), "eq")
            for rid, variable in built.passengers.ride_count.items()
        )
    elif passenger_fixing is ReservoirPassengerFixing.COMMITMENTS:
        fixed_rides = (
            (rid, built.passengers.ride_count[rid], count, "ge")
            for rid, count in assignment.ride_counts.items()
            if count
        )
    else:
        fixed_rides = ()
    for rid, variable, count, relation in fixed_rides:
        constraint = model.add(variable == count if relation == "eq" else variable >= count)
        _conditional_constraint(
            model,
            constraint,
            assumptionize=assumptionize,
            metadata=(f"ride_{relation}::{rid}::{count}", f"ride_{relation}", rid, count),
            registry=assumptions,
        )
    if passenger_fixing is not ReservoirPassengerFixing.EXACT:
        constraint = model.add(
            sum(built.passengers.ride_count.values()) >= assignment.target_served
        )
        _conditional_constraint(
            model,
            constraint,
            assumptionize=assumptionize,
            metadata=(
                f"served_ge::{assignment.target_served}",
                "served_ge",
                "served",
                assignment.target_served,
            ),
            registry=assumptions,
        )
    if config.use_witness_hints:
        for rid, variable in built.passengers.ride_count.items():
            model.add_hint(variable, assignment.ride_counts.get(rid, 0))
    fixed_resource_precedences = (
        _add_witness_resource_order(problem, movement, trips)
        if config.fix_witness_resource_order
        else 0
    )
    model.clear_objective()
    error = model.validate()
    if error:
        raise ValueError(f"invalid fixed-assignment timing model: {error}")
    return ReservoirAssignmentTimingModel(
        built=built,
        trips=trips,
        assumptions=tuple(assumptions),
        build_seconds=perf_counter() - started,
        fixed_resource_precedences=fixed_resource_precedences,
    )


def solve_assignment_timing(
    problem, assignment, config=ReservoirAssignmentTimingConfig()
):
    config.validate()
    assignment_validation = validate_service_assignment(problem, assignment)
    started = perf_counter()
    timing_model = build_assignment_timing_model(problem, assignment, config)
    built = timing_model.built
    movement = built.movement
    model = movement.model
    build_seconds = timing_model.build_seconds
    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = max(
        0.001, config.time_limit_seconds - build_seconds
    )
    solver.parameters.num_search_workers = config.workers
    solver.parameters.random_seed = config.seed
    solver.parameters.stop_after_first_solution = True
    solver.parameters.log_search_progress = config.log_search_progress
    code = solver.solve(model)
    solve_seconds = perf_counter() - started - build_seconds
    plan = metrics = mapping = None
    if code in (cp_model.FEASIBLE, cp_model.OPTIMAL):
        plan = _extract(problem, built, solver.value)
        metrics = validate_reservoir_cp_plan(problem, plan)
        passenger_fixing = ReservoirPassengerFixing(config.passenger_fixing)
        if metrics.served < assignment.target_served:
            raise RuntimeError("timed plan does not meet assignment service target")
        if passenger_fixing is ReservoirPassengerFixing.EXACT:
            if metrics.served != assignment.target_served:
                raise RuntimeError("timed plan changed fixed assignment service")
            if {k: v for k, v in plan.ride_counts.items() if v} != assignment.ride_counts:
                raise RuntimeError("timed plan changed fixed ride counts")
        elif passenger_fixing is ReservoirPassengerFixing.COMMITMENTS:
            if any(plan.ride_counts.get(rid, 0) < count for rid, count in assignment.ride_counts.items()):
                raise RuntimeError("timed plan violated passenger commitments")
        actual = {t.cabin_id: t.route_option_ids for t in plan.trips}
        expected = {t.cabin_id: t.route_option_ids for t in assignment.trips}
        if config.fix_routes and actual != expected:
            raise RuntimeError("timed plan changed fixed routes")
        plan, mapping = canonicalize_reservoir_plan(problem, plan)
        metrics = validate_reservoir_cp_plan(problem, plan)
    return {
        "schema": "reservoir_assignment_timing_result_v1",
        "status": solver.status_name(code),
        "proved_infeasible": code == cp_model.INFEASIBLE,
        "has_valid_plan": plan is not None,
        "assignment_validation": assignment_validation,
        "metrics": None if metrics is None else asdict(metrics),
        "plan": None if plan is None else asdict(plan),
        "model_stats": {
            **built.stats,
            "variables_after_fixing": len(model.proto.variables),
            "constraints_after_fixing": len(model.proto.constraints),
        },
        "build_seconds": build_seconds,
        "solve_seconds": solve_seconds,
        "total_seconds": perf_counter() - started,
        "response_stats": solver.response_stats(),
        "workers": config.workers,
        "seed": config.seed,
        "used_witness_hints": config.use_witness_hints,
        "fixed_routes": config.fix_routes,
        "fixed_witness_waits": config.fix_witness_waits,
        "fixed_witness_resource_order": config.fix_witness_resource_order,
        "fixed_resource_precedences": timing_model.fixed_resource_precedences,
        "passenger_fixing": ReservoirPassengerFixing(config.passenger_fixing).value,
        "cabin_id_mapping": mapping,
    }, plan
