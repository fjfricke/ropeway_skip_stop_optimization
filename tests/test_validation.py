from __future__ import annotations

from dataclasses import replace
from datetime import time

import pytest

from ropeway_skip_stop_optimization.examples.three_station import build_three_station_scenario
from ropeway_skip_stop_optimization.models import (
    Demand,
    SpeedProfile,
    SpeedProfileKind,
    Station,
    StationKind,
    StationRoute,
    StationRouteKind,
)
from ropeway_skip_stop_optimization.validation import validate_scenario


def test_three_station_scenario_has_no_validation_errors() -> None:
    scenario = build_three_station_scenario()

    report = validate_scenario(scenario)

    assert report.is_valid
    assert report.issues == ()


def test_three_station_scenario_uses_terminal_station_kind() -> None:
    scenario = build_three_station_scenario()

    station_kind_by_id = {station.id: station.kind for station in scenario.stations}

    assert station_kind_by_id == {
        "L": StationKind.TERMINAL,
        "M": StationKind.SERVICE,
        "R": StationKind.TERMINAL,
    }


def test_terminal_station_must_not_have_skip_route() -> None:
    scenario = build_three_station_scenario()
    invalid = replace(
        scenario,
        stations=_append_route_to_station(scenario.stations, station_id="L", route_id="L_bad_skip"),
        station_routes=scenario.station_routes
        + (
            StationRoute(
                id="L_bad_skip",
                station_id="L",
                kind=StationRouteKind.SKIP,
                segment_ids=("L_turnaround_platform",),
                allows_boarding=False,
                allows_alighting=False,
            ),
        ),
    )

    report = validate_scenario(invalid)

    assert "terminal_has_skip_route" in _error_codes(report)


def test_skip_route_must_match_service_route_endpoints() -> None:
    scenario = build_three_station_scenario()
    invalid = replace(
        scenario,
        station_routes=tuple(
            replace(route, segment_ids=("M_lr_approach_fast",))
            if route.id == "M_skip_rl"
            else route
            for route in scenario.station_routes
        ),
    )

    report = validate_scenario(invalid)

    assert "skip_without_matching_service_route" in _error_codes(report)


def test_terminal_station_must_have_exactly_one_service_route() -> None:
    scenario = build_three_station_scenario()
    invalid = replace(
        scenario,
        stations=_remove_route_from_station(scenario.stations, station_id="L", route_id="L_service_turnaround"),
        station_routes=tuple(route for route in scenario.station_routes if route.id != "L_service_turnaround"),
    )

    report = validate_scenario(invalid)

    assert "terminal_service_route_count" in _error_codes(report)


def test_demand_on_storage_station_is_rejected() -> None:
    scenario = build_three_station_scenario()
    invalid = replace(
        scenario,
        stations=scenario.stations + (Station(id="D", kind=StationKind.STORAGE, name="Depot"),),
        demands=scenario.demands + (Demand(arrival_time=time(8, 10), origin="D", destination="M", count=1),),
    )

    report = validate_scenario(invalid)

    assert not report.is_valid
    assert any("non-passenger or unknown origin" in issue.message for issue in report.errors)


def test_sudden_speed_change_at_node_is_rejected() -> None:
    scenario = build_three_station_scenario()
    invalid = replace(
        scenario,
        track_segments=tuple(
            replace(
                segment,
                speed_profile=SpeedProfile(SpeedProfileKind.CONSTANT, speed_m_per_s=1.0),
            )
            if segment.id == "M_lr_approach_fast"
            else segment
            for segment in scenario.track_segments
        ),
    )

    report = validate_scenario(invalid)

    assert "node_speed_discontinuity" in _error_codes(report)
    assert any(issue.entity_id == "M_entry_lr" for issue in report.errors)


def test_raise_for_errors_raises_when_report_has_errors() -> None:
    scenario = build_three_station_scenario()
    invalid = replace(
        scenario,
        stations=_remove_route_from_station(scenario.stations, station_id="L", route_id="L_service_turnaround"),
        station_routes=tuple(route for route in scenario.station_routes if route.id != "L_service_turnaround"),
    )

    report = validate_scenario(invalid)

    with pytest.raises(ValueError, match="terminal_service_route_count"):
        report.raise_for_errors()


def _error_codes(report) -> set[str]:
    return {issue.code for issue in report.errors}


def _append_route_to_station(
    stations: tuple[Station, ...],
    *,
    station_id: str,
    route_id: str,
) -> tuple[Station, ...]:
    return tuple(
        replace(station, route_ids=station.route_ids + (route_id,))
        if station.id == station_id
        else station
        for station in stations
    )


def _remove_route_from_station(
    stations: tuple[Station, ...],
    *,
    station_id: str,
    route_id: str,
) -> tuple[Station, ...]:
    return tuple(
        replace(station, route_ids=tuple(item for item in station.route_ids if item != route_id))
        if station.id == station_id
        else station
        for station in stations
    )
