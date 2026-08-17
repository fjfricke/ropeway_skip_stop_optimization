from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from ropeway_skip_stop_optimization.optimization.ean.models import (
    EanFleetMode,
)


class EanInitialPlacementStateKind(StrEnum):
    ENTRY_SWITCH = "entry_switch"
    SERVICE_ROUTE = "service_route"
    SKIP_ROUTE = "skip_route"
    PLATFORM_WAIT = "platform_wait"
    EXIT_SWITCH = "exit_switch"
    ROPE = "rope"


@dataclass(frozen=True)
class EanInitialPlacementParameters:
    mode: EanFleetMode
    available_fleet_count: int
    initial_phase_visit_count: int

    def validate(self) -> None:
        if self.mode is not EanFleetMode.OPTIMIZED_INITIAL_PLACEMENT:
            raise ValueError("initial placement parameters require optimized_initial_placement mode")
        if self.available_fleet_count <= 0:
            raise ValueError("initial placement available fleet count must be positive")
        if self.initial_phase_visit_count <= 0:
            raise ValueError("initial placement phase visit count must be positive")


@dataclass(frozen=True)
class EanInitialPlacementState:
    cabin_id: int
    kind: EanInitialPlacementStateKind
    switch_id: str
    visit_index: int
    progress: float
    previous_event_time_seconds: float
    next_event_time_seconds: float
    previous_service: bool | None = None

    def validate(self) -> None:
        if self.cabin_id < 0:
            raise ValueError("initial placement cabin id must be nonnegative")
        if not self.switch_id:
            raise ValueError("initial placement switch id must be nonempty")
        if self.visit_index < 0:
            raise ValueError("initial placement visit index must be nonnegative")
        if not 0.0 <= self.progress <= 1.0:
            raise ValueError("initial placement progress must lie in [0, 1]")
        if self.previous_event_time_seconds > 0:
            raise ValueError("initial placement previous event must not be after the boundary")
        if self.next_event_time_seconds < 0:
            raise ValueError("initial placement next event must not be before the boundary")
        if self.kind is not EanInitialPlacementStateKind.ROPE and self.previous_service is not None:
            raise ValueError("only rope initial states may define previous_service")


@dataclass(frozen=True)
class EanFleetPlan:
    mode: EanFleetMode
    available_fleet_count: int
    active_cabin_ids: tuple[int, ...]
    inactive_cabin_ids: tuple[int, ...]
    initial_states: tuple[EanInitialPlacementState, ...]

    def validate(self) -> None:
        if self.mode is not EanFleetMode.OPTIMIZED_INITIAL_PLACEMENT:
            raise ValueError("fleet plan requires optimized_initial_placement mode")
        if self.available_fleet_count <= 0:
            raise ValueError("fleet plan available count must be positive")
        active = set(self.active_cabin_ids)
        inactive = set(self.inactive_cabin_ids)
        expected = set(range(self.available_fleet_count))
        if len(active) != len(self.active_cabin_ids):
            raise ValueError("fleet plan active cabin ids must be unique")
        if len(inactive) != len(self.inactive_cabin_ids):
            raise ValueError("fleet plan inactive cabin ids must be unique")
        if active & inactive or active | inactive != expected:
            raise ValueError("fleet plan active and inactive cabins must partition the fleet")
        state_cabin_ids = [state.cabin_id for state in self.initial_states]
        if len(set(state_cabin_ids)) != len(state_cabin_ids):
            raise ValueError("fleet plan initial-state cabin ids must be unique")
        if set(state_cabin_ids) != active:
            raise ValueError("fleet plan needs exactly one initial state per active cabin")
        for state in self.initial_states:
            state.validate()


def build_initial_placement_parameters(
    *,
    state_ids: tuple[str, ...],
    available_fleet_count: int,
) -> EanInitialPlacementParameters:
    if not state_ids:
        raise ValueError("initial placement requires nonempty circulation states")
    if available_fleet_count <= 0:
        raise ValueError("initial placement available fleet count must be positive")

    parameters = EanInitialPlacementParameters(
        mode=EanFleetMode.OPTIMIZED_INITIAL_PLACEMENT,
        available_fleet_count=available_fleet_count,
        initial_phase_visit_count=len(state_ids),
    )
    parameters.validate()
    return parameters
