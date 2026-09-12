from __future__ import annotations

from dataclasses import dataclass

from ..reservoir_cp_sat_certificate import (
    DddReservoirCpPlan,
    DddReservoirCpTrip,
    validate_reservoir_cp_plan,
)
from ..reservoir_cp_sat_problem import DddReservoirCpSatProblem
from .cp_model import BuiltReservoirLineModel
from .preparation import PreparedLineProblem


@dataclass(frozen=True)
class RepresentableLinePlan:
    plan: DddReservoirCpPlan
    template_id_by_cabin: dict[int, str]


def representable_line_plan(
    problem: DddReservoirCpSatProblem,
    prepared: PreparedLineProblem,
    plan: DddReservoirCpPlan,
) -> RepresentableLinePlan:
    validate_reservoir_cp_plan(problem, plan)
    ordered = sorted(plan.trips, key=lambda trip: (trip.switch_ticks[0], trip.cabin_id))
    if [trip.cabin_id for trip in ordered] != list(range(len(ordered))):
        raise ValueError("line reference requires canonical dispatch-ordered cabin IDs")
    if ordered and ordered[0].switch_ticks[0] != 0:
        raise ValueError("line reference requires first dispatch at zero")
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
        for template in prepared.templates:
            built.model.add_hint(
                built.selection[cabin_id, template.id], int(template.id == chosen)
            )
            if fix_movement:
                built.model.add(
                    built.selection[cabin_id, template.id]
                    == int(template.id == chosen)
                )
    supported_rides = set()
    for key, variable in built.passengers.ride_count.items():
        support = built.passengers.supports[key]
        count = (
            plan.ride_counts.get(support.ride_id, 0)
            if represented.template_id_by_cabin.get(support.cabin_id)
            == support.template_id
            else 0
        )
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
            for item in prepared.templates
            if value(built.selection[cabin_id, item.id])
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
    return plan
