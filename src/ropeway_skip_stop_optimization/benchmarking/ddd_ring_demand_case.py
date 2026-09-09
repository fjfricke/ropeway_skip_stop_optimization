"""Small controlled demand pilot on the existing immutable directed ring.

This is not the six-station, 60-minute capacity-frontier experiment. These
cases preserve the existing physical snapshot and explicitly replace its
passenger demand and candidate universe.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from enum import StrEnum

from .ddd_fixed_k_arc_flow import DddPreparedFixedKArcFlowRun
from ..optimization.ddd.route_topology import unique_stop_route_option
from ..optimization.ean.builders.passenger_builder import (
    EanPassengerCandidateBuildResult,
    build_ean_ride_candidates,
)
from ..optimization.ean.models import EanDemandGroup


class RingDemandFamily(StrEnum):
    DIFFUSE = "diffuse"
    LOCAL = "local"
    EXPRESS = "express"


class RingDemandTiming(StrEnum):
    BATCH = "batch"
    DISTRIBUTED = "distributed"


@dataclass(frozen=True)
class DddRingDemandCase:
    family: RingDemandFamily
    timing: RingDemandTiming
    total_passengers: int = 1280

    @property
    def case_id(self) -> str:
        return f"{self.family.value}_{self.timing.value}_n{self.total_passengers}"

    def groups(self, station_ids: tuple[str, ...]) -> tuple[EanDemandGroup, ...]:
        if not isinstance(self.family, RingDemandFamily) or not isinstance(
            self.timing, RingDemandTiming
        ):
            raise ValueError("Unknown directed-ring demand family/timing")
        if type(self.total_passengers) is not int or self.total_passengers <= 0:
            raise ValueError("Demand total must be a positive integer")
        if len(station_ids) != 5 or len(set(station_ids)) != 5:
            raise ValueError("This pilot is defined on exactly five distinct stations")
        releases = (
            (0.0,)
            if self.timing is RingDemandTiming.BATCH
            else (0.0, 200.0, 400.0, 600.0)
        )
        distances = {
            RingDemandFamily.DIFFUSE: (1, 2, 3, 4),
            RingDemandFamily.LOCAL: (1,),
            RingDemandFamily.EXPRESS: (3, 4),
        }[self.family]
        cells = sorted(
            (origin, station_ids[(i + distance) % 5], release)
            for i, origin in enumerate(station_ids)
            for distance in distances
            for release in releases
        )
        quotient, remainder = divmod(self.total_passengers, len(cells))
        return tuple(
            EanDemandGroup(
                f"{self.case_id}:{origin}:{destination}:{release:g}",
                origin,
                destination,
                release,
                quotient + (index < remainder),
            )
            for index, (origin, destination, release) in enumerate(cells)
            if quotient + (index < remainder) > 0
        )

    def apply(
        self, prepared: DddPreparedFixedKArcFlowRun
    ) -> DddPreparedFixedKArcFlowRun:
        problem = prepared.problem
        core = problem.trajectory_problem.movement_core
        stations = tuple(
            unique_stop_route_option(
                core, state, error_context="ring demand pilot"
            ).station_id
            for state in problem.artifact.circulation_state_ids
        )
        groups = self.groups(stations)
        if (
            core.passenger_service_end_seconds != 1200.0
            or core.operational_end_seconds != 1200.0
        ):
            raise ValueError("This pilot requires the unchanged 1200-second horizon")
        passenger_build = EanPassengerCandidateBuildResult(
            groups, build_ean_ride_candidates(groups, problem.artifact)
        )
        changed = replace(problem, passenger_build=passenger_build)
        changed.validate()
        return replace(prepared, problem=changed)
