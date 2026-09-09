from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from hashlib import sha256
import json
import math

from ropeway_skip_stop_optimization.optimization.ddd.models import DddMovementCore
from ropeway_skip_stop_optimization.optimization.ddd.time_ticks import (
    ddd_seconds_to_tick,
)
from ropeway_skip_stop_optimization.optimization.ddd.trajectory_problem import (
    DddTrajectoryWaitingPolicy,
)
from ropeway_skip_stop_optimization.optimization.ean.models import EanDemandGroup


class DddReservoirOperatingMode(StrEnum):
    ALL_STOP = "all_stop"
    SKIP_STOP = "skip_stop"


@dataclass(frozen=True, slots=True)
class DddReservoirArcFlowProblem:
    """One finite-policy anonymous reservoir experiment.

    Times are absolute in the time-expanded graph: warm-up starts at zero,
    passenger demand is released during the service phase, and every dispatched
    unit must reach the boundary reservoir again during recovery.
    """

    movement_core: DddMovementCore
    demand_groups: tuple[EanDemandGroup, ...]
    cabin_capacity: int
    available_fleet_count: int
    entry_state_id: str
    warmup_seconds: float
    service_seconds: float
    recovery_seconds: float
    dispatch_step_seconds: float = 1.0
    operating_mode: DddReservoirOperatingMode = (
        DddReservoirOperatingMode.SKIP_STOP
    )
    waiting_policy: DddTrajectoryWaitingPolicy = DddTrajectoryWaitingPolicy()
    all_stop_maximum_cabin_count: int | None = None
    all_stop_cycle_seconds: float | None = None
    all_stop_headway_seconds: float | None = None

    @property
    def service_start_seconds(self) -> float:
        return self.warmup_seconds

    @property
    def service_end_seconds(self) -> float:
        return self.warmup_seconds + self.service_seconds

    @property
    def operational_end_seconds(self) -> float:
        return self.service_end_seconds + self.recovery_seconds

    @property
    def warmup_tick(self) -> int:
        return ddd_seconds_to_tick(self.warmup_seconds)

    @property
    def service_start_tick(self) -> int:
        return self.warmup_tick

    @property
    def service_end_tick(self) -> int:
        return ddd_seconds_to_tick(self.service_end_seconds)

    @property
    def operational_end_tick(self) -> int:
        return ddd_seconds_to_tick(self.operational_end_seconds)

    @property
    def total_demand(self) -> int:
        return sum(group.count for group in self.demand_groups)

    @property
    def fingerprint(self) -> str:
        payload = {
            "scenario_id": self.movement_core.scenario_id,
            "available_fleet_count": self.available_fleet_count,
            "entry_state_id": self.entry_state_id,
            "warmup_seconds": self.warmup_seconds,
            "service_seconds": self.service_seconds,
            "recovery_seconds": self.recovery_seconds,
            "dispatch_step_seconds": self.dispatch_step_seconds,
            "operating_mode": self.operating_mode.value,
            "cabin_capacity": self.cabin_capacity,
            "waiting": {
                "domain": self.waiting_policy.domain.value,
                "step_seconds": self.waiting_policy.step_seconds,
                "maximum": self.waiting_policy.maximum_wait_seconds_by_station_id,
                "earliest": self.waiting_policy.earliest_wait_time_seconds,
            },
            "route_options": [
                (
                    option.id,
                    option.from_state_id,
                    option.to_state_id,
                    option.decision.value,
                    option.duration_seconds,
                )
                for option in self.movement_core.route_options
            ],
            "resources": [
                (
                    resource.id,
                    resource.minimum_headway_seconds,
                    resource.maximum_headway_seconds,
                )
                for resource in self.movement_core.resources
            ],
            "demands": [
                (
                    group.id,
                    group.origin_station_id,
                    group.destination_station_id,
                    group.release_time_seconds,
                    group.count,
                )
                for group in self.demand_groups
            ],
        }
        return sha256(
            json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()

    def validate(self) -> None:
        self.movement_core.validate()
        if self.available_fleet_count <= 0 or self.cabin_capacity <= 0:
            raise ValueError("reservoir fleet and cabin capacity must be positive")
        state_ids = {state.id for state in self.movement_core.states}
        if self.entry_state_id not in state_ids:
            raise ValueError("reservoir entry state is not in the movement core")
        for label, value in (
            ("warmup", self.warmup_seconds),
            ("service", self.service_seconds),
            ("recovery", self.recovery_seconds),
            ("dispatch step", self.dispatch_step_seconds),
        ):
            if not math.isfinite(value) or value <= 0:
                raise ValueError(f"reservoir {label} must be positive and finite")
        if not isinstance(self.operating_mode, DddReservoirOperatingMode):
            raise ValueError("reservoir operating mode is invalid")
        self.waiting_policy.validate(self.movement_core)
        group_ids: set[str] = set()
        for group in self.demand_groups:
            group.validate()
            if group.id in group_ids:
                raise ValueError("reservoir demand group ids must be unique")
            if group.release_time_seconds > self.service_seconds:
                raise ValueError("reservoir demand is released after service ends")
            group_ids.add(group.id)
        optional_positive = (
            self.all_stop_cycle_seconds,
            self.all_stop_headway_seconds,
        )
        if any(
            value is not None and (not math.isfinite(value) or value <= 0)
            for value in optional_positive
        ):
            raise ValueError("all-stop reference values must be positive and finite")
        if (
            self.all_stop_maximum_cabin_count is not None
            and self.all_stop_maximum_cabin_count <= 0
        ):
            raise ValueError("all-stop maximum cabin count must be positive")
