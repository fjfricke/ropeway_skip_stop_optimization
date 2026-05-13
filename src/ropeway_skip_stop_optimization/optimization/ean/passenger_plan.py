from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class EanServedRideGroup:
    demand_group_id: str
    cabin_id: int
    board_visit_index: int
    alight_visit_index: int
    count: int
    boarding_time_seconds: float
    alighting_time_seconds: float

    def validate(self) -> None:
        _require_id("EAN served ride group demand_group_id", self.demand_group_id)
        _require_nonnegative_int("EAN served ride group cabin_id", self.cabin_id)
        _require_nonnegative_int("EAN served ride group board_visit_index", self.board_visit_index)
        _require_nonnegative_int("EAN served ride group alight_visit_index", self.alight_visit_index)
        if self.board_visit_index >= self.alight_visit_index:
            raise ValueError("EAN served ride group board_visit_index must be before alight_visit_index")
        if self.count <= 0:
            raise ValueError("EAN served ride group count must be positive")
        _require_nonnegative("EAN served ride group boarding_time_seconds", self.boarding_time_seconds)
        _require_nonnegative("EAN served ride group alighting_time_seconds", self.alighting_time_seconds)
        if self.boarding_time_seconds > self.alighting_time_seconds:
            raise ValueError("EAN served ride group boarding time must be before alighting time")


@dataclass(frozen=True)
class EanPassengerServicePlan:
    scenario_id: str
    horizon_seconds: float
    served_rides: tuple[EanServedRideGroup, ...]
    unserved_counts_by_demand_group_id: dict[str, int]

    def validate(self) -> None:
        _require_id("EAN passenger service plan scenario_id", self.scenario_id)
        _require_positive("EAN passenger service plan horizon_seconds", self.horizon_seconds)
        for ride in self.served_rides:
            ride.validate()
        for demand_group_id, count in self.unserved_counts_by_demand_group_id.items():
            _require_id("EAN passenger service plan unserved demand_group_id", demand_group_id)
            _require_nonnegative_int("EAN passenger service plan unserved count", count)


def _require_id(label: str, value: str) -> None:
    if not value:
        raise ValueError(f"{label} must be nonempty")


def _require_positive(label: str, value: float) -> None:
    if value <= 0:
        raise ValueError(f"{label} must be positive")


def _require_nonnegative(label: str, value: float) -> None:
    if value < 0:
        raise ValueError(f"{label} must be nonnegative")


def _require_nonnegative_int(label: str, value: int) -> None:
    if value < 0:
        raise ValueError(f"{label} must be nonnegative")
