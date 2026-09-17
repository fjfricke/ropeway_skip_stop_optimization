"""Exact dispatch equivalence classes for no-wait line templates."""

from __future__ import annotations

from dataclasses import asdict, dataclass

from ..cp_sat_certificate import stable_fingerprint
from ..reservoir_cp_sat_problem import DddReservoirCpSatProblem
from ..time_ticks import ddd_seconds_to_tick
from .preparation import LineTemplate, PreparedLineProblem


def _ceil_grid(value: int, step: int) -> int:
    return -((-value) // step) * step


def _floor_grid(value: int, step: int) -> int:
    return (value // step) * step


@dataclass(frozen=True, slots=True)
class ServiceClassRide:
    demand_group_id: str
    board_visit_index: int
    alight_visit_index: int
    departure_offset_tick: int
    arrival_offset_tick: int

    @property
    def key(self) -> tuple[str, int, int]:
        return (
            self.demand_group_id,
            self.board_visit_index,
            self.alight_visit_index,
        )


@dataclass(frozen=True, slots=True)
class LineServiceClass:
    id: str
    template_id: str
    pattern_id: str
    minimum_dispatch_tick: int
    maximum_dispatch_tick: int
    rides: tuple[ServiceClassRide, ...]

    @property
    def ride_keys(self) -> frozenset[tuple[str, int, int]]:
        return frozenset(ride.key for ride in self.rides)


@dataclass(frozen=True, slots=True)
class PreparedLineServiceClasses:
    problem_fingerprint: str
    line_model_fingerprint: str
    model_fingerprint: str
    dispatch_step_tick: int
    classes: tuple[LineServiceClass, ...]
    stats: dict

    @property
    def classes_by_id(self) -> dict[str, LineServiceClass]:
        return {item.id: item for item in self.classes}

    @property
    def payload(self) -> dict:
        return asdict(self)


def _canonical_candidates(problem: DddReservoirCpSatProblem):
    """Return cabin-independent candidates and verify fleet symmetry."""
    by_cabin: dict[int, set[tuple[str, int, int]]] = {}
    for ride in problem.passenger_build.ride_candidates:
        by_cabin.setdefault(ride.cabin_id, set()).add(
            (ride.demand_group_id, ride.board_visit_index, ride.alight_visit_index)
        )
    expected = by_cabin.get(0, set())
    for cabin in range(problem.available_fleet_count):
        if by_cabin.get(cabin, set()) != expected:
            raise ValueError(
                "service-class aggregation requires identical passenger supports "
                "for every reservoir cabin"
            )
    return tuple(sorted(expected))


def _template_classes(
    problem: DddReservoirCpSatProblem,
    prepared: PreparedLineProblem,
    template: LineTemplate,
    candidates: tuple[tuple[str, int, int], ...],
) -> tuple[LineServiceClass, ...]:
    step = prepared.dispatch_step_tick
    lower = _ceil_grid(template.minimum_dispatch_tick, step)
    upper = _floor_grid(template.maximum_dispatch_tick, step)
    if lower > upper:
        return ()
    groups = {group.id: group for group in problem.demand_groups}
    horizon = problem.resolved_core.passenger_service_end_tick
    windows: dict[tuple[str, int, int], tuple[int, int, ServiceClassRide]] = {}
    boundaries = {lower, upper + step}
    for group_id, board_index, alight_index in candidates:
        if alight_index >= len(template.visits):
            continue
        board, alight = template.visits[board_index], template.visits[alight_index]
        if board.platform_exit_tick is None or alight.platform_entry_tick is None:
            continue
        group = groups[group_id]
        release = max(
            prepared.service_start_tick,
            ddd_seconds_to_tick(group.release_time_seconds),
        )
        ride_lower = _ceil_grid(
            max(lower, release - board.platform_exit_tick), step
        )
        ride_upper = _floor_grid(
            min(
                upper,
                horizon - board.platform_exit_tick,
                horizon - alight.platform_entry_tick,
            ),
            step,
        )
        if ride_lower > ride_upper:
            continue
        ride = ServiceClassRide(
            group_id,
            board_index,
            alight_index,
            board.platform_exit_tick,
            alight.platform_entry_tick,
        )
        windows[ride.key] = (ride_lower, ride_upper, ride)
        boundaries.update((ride_lower, ride_upper + step))

    points = sorted(value for value in boundaries if lower <= value <= upper + step)
    raw = []
    for left, following in zip(points, points[1:]):
        right = following - step
        if left > right:
            continue
        rides = tuple(
            value[2]
            for _, value in sorted(windows.items())
            if value[0] <= left and right <= value[1]
        )
        if raw and raw[-1][2] == rides and raw[-1][1] + step == left:
            raw[-1] = (raw[-1][0], right, rides)
        else:
            raw.append((left, right, rides))
    return tuple(
        LineServiceClass(
            id=f"service::{template.id}::{left}::{right}",
            template_id=template.id,
            pattern_id=template.pattern_id,
            minimum_dispatch_tick=left,
            maximum_dispatch_tick=right,
            rides=rides,
        )
        for left, right, rides in raw
    )


def prepare_line_service_classes(
    problem: DddReservoirCpSatProblem,
    prepared: PreparedLineProblem,
) -> PreparedLineServiceClasses:
    problem.validate()
    if prepared.problem_fingerprint != problem.fingerprint:
        raise ValueError("prepared line problem has a different physical domain")
    candidates = _canonical_candidates(problem)
    classes = tuple(
        service_class
        for template in prepared.templates
        for service_class in _template_classes(
            problem, prepared, template, candidates
        )
    )
    manifest = {
        "version": "line_service_classes_v1",
        "problem": problem.fingerprint,
        "line": prepared.model_fingerprint,
        "dispatch_step_tick": prepared.dispatch_step_tick,
        "classes": [asdict(item) for item in classes],
    }
    return PreparedLineServiceClasses(
        problem.fingerprint,
        prepared.model_fingerprint,
        stable_fingerprint(manifest),
        prepared.dispatch_step_tick,
        classes,
        {
            "service_classes": len(classes),
            "service_class_rides": sum(len(item.rides) for item in classes),
            "service_classes_without_rides": sum(not item.rides for item in classes),
            "maximum_rides_per_class": max(
                (len(item.rides) for item in classes), default=0
            ),
        },
    )
