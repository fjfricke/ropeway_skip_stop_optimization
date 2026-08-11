from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
import math


class EanPassengerObjective(StrEnum):
    """Passenger objective for EAN and DDD service optimization."""

    WAITING_TIME = "waiting_time"
    JOURNEY_TIME = "journey_time"


class EanPassengerObjectiveEvent(StrEnum):
    BOARDING = "boarding"
    ALIGHTING = "alighting"


@dataclass(frozen=True)
class EanPassengerObjectiveDefinition:
    """Canonical exact and optimistic cost semantics for one objective."""

    objective: EanPassengerObjective
    event: EanPassengerObjectiveEvent
    unit: str = "passenger_seconds"

    @property
    def requires_board_time(self) -> bool:
        return self.event is EanPassengerObjectiveEvent.BOARDING

    @property
    def requires_alight_time(self) -> bool:
        return self.event is EanPassengerObjectiveEvent.ALIGHTING

    def event_time_seconds(
        self,
        *,
        boarding_time_seconds: float,
        alighting_time_seconds: float,
    ) -> float:
        if self.event is EanPassengerObjectiveEvent.BOARDING:
            return boarding_time_seconds
        if self.event is EanPassengerObjectiveEvent.ALIGHTING:
            return alighting_time_seconds
        raise ValueError(f"unsupported passenger objective event: {self.event}")

    def served_cost_seconds(
        self,
        *,
        release_time_seconds: float,
        boarding_time_seconds: float,
        alighting_time_seconds: float,
        tolerance_seconds: float = 1e-6,
    ) -> float:
        _validate_time("release_time_seconds", release_time_seconds)
        _validate_time("boarding_time_seconds", boarding_time_seconds)
        _validate_time("alighting_time_seconds", alighting_time_seconds)
        if boarding_time_seconds + tolerance_seconds < release_time_seconds:
            raise ValueError("passenger cannot board before release")
        if alighting_time_seconds + tolerance_seconds < boarding_time_seconds:
            raise ValueError("passenger cannot alight before boarding")
        event_time = self.event_time_seconds(
            boarding_time_seconds=boarding_time_seconds,
            alighting_time_seconds=alighting_time_seconds,
        )
        return max(0.0, event_time - release_time_seconds)

    def optimistic_served_cost_lower_bound_seconds(
        self,
        *,
        release_time_seconds: float,
        earliest_boarding_time_seconds: float,
        earliest_alighting_time_seconds: float,
    ) -> float:
        """Return an admissible nonnegative cost for a partial-time master."""

        _validate_time("release_time_seconds", release_time_seconds)
        _validate_time(
            "earliest_boarding_time_seconds",
            earliest_boarding_time_seconds,
        )
        _validate_time(
            "earliest_alighting_time_seconds",
            earliest_alighting_time_seconds,
        )
        event_time = self.event_time_seconds(
            boarding_time_seconds=earliest_boarding_time_seconds,
            alighting_time_seconds=earliest_alighting_time_seconds,
        )
        return max(0.0, event_time - release_time_seconds)

    def unserved_cost_seconds(
        self,
        *,
        release_time_seconds: float,
        horizon_seconds: float,
    ) -> float:
        _validate_time("release_time_seconds", release_time_seconds)
        _validate_time("horizon_seconds", horizon_seconds)
        return max(0.0, horizon_seconds - release_time_seconds)


_OBJECTIVE_DEFINITIONS = {
    EanPassengerObjective.WAITING_TIME: EanPassengerObjectiveDefinition(
        objective=EanPassengerObjective.WAITING_TIME,
        event=EanPassengerObjectiveEvent.BOARDING,
    ),
    EanPassengerObjective.JOURNEY_TIME: EanPassengerObjectiveDefinition(
        objective=EanPassengerObjective.JOURNEY_TIME,
        event=EanPassengerObjectiveEvent.ALIGHTING,
    ),
}


def ean_passenger_objective_definition(
    objective: EanPassengerObjective | str,
) -> EanPassengerObjectiveDefinition:
    resolved = EanPassengerObjective(objective)
    try:
        return _OBJECTIVE_DEFINITIONS[resolved]
    except KeyError as error:
        raise ValueError(
            f"unsupported EAN passenger objective: {resolved.value}"
        ) from error


def _validate_time(label: str, value: float) -> None:
    if not math.isfinite(value) or value < 0:
        raise ValueError(f"{label} must be finite and nonnegative")
