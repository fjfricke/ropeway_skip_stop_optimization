from __future__ import annotations

from dataclasses import dataclass

from ..reservoir_cp_sat_certificate import (
    DddReservoirCpPlan,
    DddReservoirCpTrip,
    validate_reservoir_cp_plan,
)
from ..reservoir_cp_sat_problem import DddReservoirCpSatProblem
from ..time_ticks import ddd_seconds_to_tick
from .cp_model import BuiltReservoirLineModel
from .preparation import PreparedLineProblem


@dataclass(frozen=True)
class RepresentableLinePlan:
    plan: DddReservoirCpPlan
    template_id_by_cabin: dict[int, str]


def _validate_line_service_start(
    problem: DddReservoirCpSatProblem,
    plan: DddReservoirCpPlan,
    service_start_tick: int,
) -> None:
    trips = {trip.cabin_id: trip for trip in plan.trips}
    candidates = {item.id: item for item in problem.passenger_build.ride_candidates}
    options = {item.id: item for item in problem.resolved_core.route_options}
    for ride_id, count in plan.ride_counts.items():
        if count <= 0:
            continue
        candidate = candidates[ride_id]
        trip = trips[candidate.cabin_id]
        option = options[trip.route_option_ids[candidate.board_visit_index]]
        if option.platform_exit_offset_seconds is None:
            raise ValueError("line passenger boards on a non-STOP movement")
        departure = (
            trip.switch_ticks[candidate.board_visit_index]
            + ddd_seconds_to_tick(option.platform_exit_offset_seconds)
        )
        if departure < service_start_tick:
            raise ValueError("line passenger boards before passenger service starts")


def representable_line_plan(
    problem: DddReservoirCpSatProblem,
    prepared: PreparedLineProblem,
    plan: DddReservoirCpPlan,
) -> RepresentableLinePlan:
    validate_reservoir_cp_plan(problem, plan)
    _validate_line_service_start(problem, plan, prepared.service_start_tick)
    ordered = sorted(plan.trips, key=lambda trip: (trip.switch_ticks[0], trip.cabin_id))
    if [trip.cabin_id for trip in ordered] != list(range(len(ordered))):
        raise ValueError("line reference requires canonical dispatch-ordered cabin IDs")
    if len(ordered) > prepared.maximum_cabins:
        raise ValueError("line reference exceeds the configured fleet limit")
    mapping = {}
    for trip in ordered:
        if any(trip.wait_ticks):
            raise ValueError("line reference contains positive waiting")
        matches = [
            template
            for template in prepared.templates
            if template.route_option_ids == trip.route_option_ids
            and trip.return_tick == trip.switch_ticks[0] + template.duration_tick
            and template.minimum_dispatch_tick
            <= trip.switch_ticks[0]
            <= template.maximum_dispatch_tick
        ]
        if len(matches) != 1:
            raise ValueError("line reference trip has no unique catalog template")
        mapping[trip.cabin_id] = matches[0].id
    return RepresentableLinePlan(plan, mapping)


def add_line_plan_hint(
    problem: DddReservoirCpSatProblem,
    prepared: PreparedLineProblem,
    built: BuiltReservoirLineModel,
    plan: DddReservoirCpPlan,
    *,
    fix_movement: bool = False,
) -> RepresentableLinePlan:
    represented = representable_line_plan(problem, prepared, plan)
    trips = {trip.cabin_id: trip for trip in plan.trips}
    for cabin_id in range(prepared.maximum_cabins):
        trip = trips.get(cabin_id)
        used = int(trip is not None)
        built.model.add_hint(built.used[cabin_id], used)
        if fix_movement:
            built.model.add(built.used[cabin_id] == used)
        dispatch = 0 if trip is None else trip.switch_ticks[0]
        built.model.add_hint(built.dispatch[cabin_id], dispatch)
        if fix_movement:
            built.model.add(built.dispatch[cabin_id] == dispatch)
        built.model.add_hint(
            built.dispatch_index[cabin_id], dispatch // prepared.dispatch_step_tick
        )
        chosen = represented.template_id_by_cabin.get(cabin_id)
        for (k, template_id), variable in built.selection.items():
            if k != cabin_id:
                continue
            built.model.add_hint(
                variable, int(template_id == chosen)
            )
            if fix_movement:
                built.model.add(
                    variable == int(template_id == chosen)
                )
        selected_template = None if chosen is None else prepared.templates_by_id[chosen]
        for (k, pattern_id, lap), variable in built.round_active.items():
            if k != cabin_id:
                continue
            active = int(
                selected_template is not None
                and selected_template.pattern_id == pattern_id
                and selected_template.laps >= lap
            )
            built.model.add_hint(variable, active)
            if fix_movement:
                built.model.add(variable == active)
    supported_rides = set()
    for key, variable in built.passengers.ride_count.items():
        support = built.passengers.supports[key]
        chosen_id = represented.template_id_by_cabin.get(support.cabin_id)
        chosen_template = (
            None if chosen_id is None else prepared.templates_by_id[chosen_id]
        )
        compatible = (
            chosen_template is not None
            and chosen_template.laps >= support.minimum_laps
            and (
                support.template_id == chosen_id
                if support.template_id is not None
                else support.pattern_id in ("*", chosen_template.pattern_id)
            )
        )
        count = plan.ride_counts.get(support.ride_id, 0) if compatible else 0
        built.model.add_hint(variable, count)
        built.model.add_hint(built.passengers.positive[key], int(count > 0))
        if count:
            supported_rides.add(support.ride_id)
    missing = {ride for ride, count in plan.ride_counts.items() if count and ride not in supported_rides}
    if missing:
        raise ValueError(f"positive reference rides are absent from line model: {sorted(missing)[:3]}")
    return represented


def extract_line_plan(
    problem: DddReservoirCpSatProblem,
    prepared: PreparedLineProblem,
    built: BuiltReservoirLineModel,
    value,
    *,
    include_rides: bool = True,
) -> DddReservoirCpPlan:
    trips = []
    for cabin_id in range(prepared.maximum_cabins):
        if not value(built.used[cabin_id]):
            continue
        template = next(
            item
            for (k, template_id), variable in built.selection.items()
            for item in (prepared.templates_by_id[template_id],)
            if k == cabin_id and value(variable)
        )
        dispatch = int(value(built.dispatch[cabin_id]))
        trips.append(
            DddReservoirCpTrip(
                cabin_id,
                template.route_option_ids,
                tuple(dispatch + visit.start_tick for visit in template.visits),
                (0,) * len(template.visits),
                dispatch + template.duration_tick,
            )
        )
    ride_counts: dict[str, int] = {}
    if include_rides:
        for key, variable in built.passengers.ride_count.items():
            count = int(value(variable))
            if count:
                ride = built.passengers.supports[key].ride_id
                ride_counts[ride] = ride_counts.get(ride, 0) + count
    plan = DddReservoirCpPlan(tuple(trips), ride_counts)
    validate_reservoir_cp_plan(problem, plan)
    _validate_line_service_start(problem, plan, prepared.service_start_tick)
    return plan
