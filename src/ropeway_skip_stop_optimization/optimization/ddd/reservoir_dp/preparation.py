"""Solver-free, lossless preparation for the native reservoir DP."""

from __future__ import annotations

import json
from dataclasses import dataclass

from ..cp_sat_certificate import stable_fingerprint
from ..models import DddRouteDecision
from ..reservoir_cp_sat_problem import DddReservoirCpSatProblem
from ..time_ticks import ddd_seconds_to_tick as tick

SCHEMA = "reservoir_symbolic_dp_domain_v1"


@dataclass(frozen=True)
class PreparedReservoirDp:
    payload: dict
    fingerprint: str

    @property
    def json(self) -> str:
        return json.dumps(self.payload, sort_keys=True, separators=(",", ":"))


def _checked_tick(value, label):
    result = tick(value)
    if not -(2**63) < result < 2**63:
        raise ValueError(f"{label} exceeds the native i64 range")
    return result


def prepare_reservoir_dp(problem: DddReservoirCpSatProblem) -> PreparedReservoirDp:
    problem.validate()
    step = _checked_tick(problem.waiting_policy.step_seconds or 0.000001, "wait step")
    dispatch_step = _checked_tick(problem.dispatch_step_seconds, "dispatch step")
    if step != 1 or dispatch_step != 1:
        raise ValueError(
            "symbolic reservoir DP v1 requires one-tick dispatch and waiting steps"
        )

    core = problem.resolved_core
    states = tuple(problem.cycle_states)
    state_index = {value: index for index, value in enumerate(states)}
    resources = tuple(sorted(core.resources, key=lambda value: value.id))
    resource_index = {value.id: index for index, value in enumerate(resources)}
    stations = tuple(
        next(
            option.station_id
            for option in core.route_options_by_state_id[state]
            if option.decision is DddRouteDecision.STOP
        )
        for state in states
    )
    if len(set(stations)) != len(stations):
        raise ValueError("symbolic reservoir DP v1 requires unique ring stations")
    station_index = {value: index for index, value in enumerate(stations)}

    options = []
    for option in sorted(core.route_options, key=lambda value: value.id):
        if option.from_state_id not in state_index or option.to_state_id not in state_index:
            raise ValueError("route option lies outside the prepared directed cycle")
        maximum_wait = _checked_tick(
            problem.waiting_policy.maximum_wait_seconds(option.station_id),
            "maximum wait",
        )
        if option.decision is DddRouteDecision.SKIP and maximum_wait:
            maximum_wait = 0
        usages = []
        for usage in option.resource_usages:
            if usage.follower_enter_wait_coefficient not in (0, 1) or (
                usage.leader_clear_wait_coefficient not in (0, 1)
            ):
                raise ValueError("symbolic reservoir DP supports affine 0/1 waits only")
            separation = usage.separation_after_tick(
                core.resources_by_id[usage.resource_id].minimum_headway_tick
            )
            usages.append(
                {
                    "resource": resource_index[usage.resource_id],
                    "enter_offset": usage.follower_enter_offset_tick,
                    "enter_wait": usage.follower_enter_wait_coefficient,
                    "clear_offset": usage.leader_clear_offset_tick + separation,
                    "clear_wait": usage.leader_clear_wait_coefficient,
                }
            )
        options.append(
            {
                "id": option.id,
                "from_state": state_index[option.from_state_id],
                "to_state": state_index[option.to_state_id],
                "station": station_index[option.station_id],
                "stop": option.decision is DddRouteDecision.STOP,
                "duration": option.duration_tick,
                "platform_entry": None
                if option.platform_entry_offset_seconds is None
                else _checked_tick(option.platform_entry_offset_seconds, "platform entry"),
                "platform_exit": None
                if option.platform_exit_offset_seconds is None
                else _checked_tick(option.platform_exit_offset_seconds, "platform exit"),
                "maximum_wait": maximum_wait,
                "usages": usages,
            }
        )

    demands = []
    for group in problem.demand_groups:
        demands.append(
            {
                "id": group.id,
                "origin": station_index[group.origin_station_id],
                "destination": station_index[group.destination_station_id],
                "release": _checked_tick(group.release_time_seconds, "demand release"),
                "count": group.count,
            }
        )

    payload = {
        "schema": SCHEMA,
        "source_fingerprint": problem.fingerprint,
        "capacity": problem.cabin_capacity,
        "available_fleet": problem.available_fleet_count,
        "entry_state": state_index[problem.entry_state_id],
        "dispatch_start": _checked_tick(problem.dispatch_start_seconds, "dispatch start"),
        "dispatch_end": _checked_tick(problem.dispatch_end_seconds, "dispatch end"),
        "return_start": _checked_tick(problem.return_start_seconds, "return start"),
        "service_end": core.passenger_service_end_tick,
        "operational_end": core.operational_end_tick,
        "earliest_positive_wait": _checked_tick(
            problem.waiting_policy.earliest_wait_time_seconds,
            "earliest positive wait",
        ),
        "states": list(states),
        "stations": list(stations),
        "resources": [
            {"id": resource.id, "minimum_headway": resource.minimum_headway_tick}
            for resource in resources
        ],
        "options": options,
        "demands": demands,
        "max_visits": len(problem.visit_states) - 1,
    }
    fingerprint = stable_fingerprint(
        {"schema": SCHEMA, "source": problem.fingerprint, "payload": payload}
    )
    return PreparedReservoirDp(payload, fingerprint)
