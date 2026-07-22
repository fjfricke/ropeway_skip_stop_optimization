from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, ROUND_CEILING
from enum import StrEnum

from ropeway_skip_stop_optimization.models import Scenario
from ropeway_skip_stop_optimization.optimization.ean.builders.ring_topology_builder import (
    PhysicalRingTopologyBuilder,
)
from ropeway_skip_stop_optimization.optimization.ean.models import (
    EanConfig,
    StationWaitingMode,
)


class EanFleetPackingRegionKind(StrEnum):
    TRACK_SEGMENT = "track_segment"
    PLATFORM_WAIT = "platform_wait"


@dataclass(frozen=True)
class EanFleetPackingRegion:
    id: str
    kind: EanFleetPackingRegionKind
    physical_id: str
    capacity: int
    source_roles: tuple[str, ...]
    length_m: float | None = None
    required_spacing_m: float | None = None
    half_open: bool = False

    def validate(self) -> None:
        if not self.id or not self.physical_id:
            raise ValueError("fleet packing region ids must be nonempty")
        if self.capacity <= 0:
            raise ValueError("fleet packing region capacity must be positive")
        if not self.source_roles:
            raise ValueError("fleet packing region needs at least one source role")
        if self.kind is EanFleetPackingRegionKind.TRACK_SEGMENT:
            if self.length_m is None or self.length_m <= 0:
                raise ValueError("track packing region needs a positive length")
            if (
                self.required_spacing_m is None
                or self.required_spacing_m <= 0
            ):
                raise ValueError(
                    "track packing region needs a positive required spacing"
                )
            if not self.half_open:
                raise ValueError("track packing regions must be half-open")
            return
        if self.length_m is not None or self.required_spacing_m is not None:
            raise ValueError(
                "non-track packing regions must not define length or spacing"
            )
        if self.half_open:
            raise ValueError("non-track packing regions are not half-open")


@dataclass(frozen=True)
class EanInitialPlacementPackingBound:
    regions: tuple[EanFleetPackingRegion, ...]
    packing_upper_bound: int
    required_spacing_m: float
    supported_waiting_modes: tuple[StationWaitingMode, ...]
    assumptions: tuple[str, ...]

    def validate(self) -> None:
        if not self.regions:
            raise ValueError("initial placement packing bound needs regions")
        if self.required_spacing_m <= 0:
            raise ValueError("packing bound spacing must be positive")
        region_ids = [region.id for region in self.regions]
        if len(region_ids) != len(set(region_ids)):
            raise ValueError("packing bound region ids must be unique")
        for region in self.regions:
            region.validate()
        if self.packing_upper_bound != sum(
            region.capacity for region in self.regions
        ):
            raise ValueError(
                "packing upper bound must equal the sum of region capacities"
            )
        if not self.assumptions:
            raise ValueError("packing bound must report its assumptions")


@dataclass(frozen=True)
class EanInitialPlacementPackingBoundBuilder:
    topology_builder: PhysicalRingTopologyBuilder = PhysicalRingTopologyBuilder()

    def build(
        self,
        *,
        scenario: Scenario,
        config: EanConfig,
        switch_cycle: tuple[str, ...],
    ) -> EanInitialPlacementPackingBound:
        scenario.validate()
        config.validate()
        topology = self.topology_builder.build(scenario, switch_cycle)
        station_config_by_id = {
            station_config.station_id: station_config
            for station_config in config.station_configs
        }
        unsupported_modes = {
            station_config.waiting_mode
            for station_config in config.station_configs
            if station_config.waiting_mode
            not in {
                StationWaitingMode.NO_WAITING,
                StationWaitingMode.END_OF_PLATFORM_WAIT,
            }
        }
        if unsupported_modes:
            labels = ", ".join(
                sorted(mode.value for mode in unsupported_modes)
            )
            # FIFO support also needs a certified q_a contribution here once
            # the movement model enforces its physical occupancy capacity.
            raise NotImplementedError(
                "initial placement packing bounds only support no-waiting and "
                f"end-of-platform waiting stations, got: {labels}"
            )

        segment_by_id = {
            segment.id: segment for segment in scenario.track_segments
        }
        roles_by_segment_id: dict[str, set[str]] = {}
        for station in topology.stations:
            for segment_id in station.service_segment_ids:
                roles_by_segment_id.setdefault(segment_id, set()).add(
                    f"service::{station.switch_id}"
                )
            for segment_id in station.skip_segment_ids:
                roles_by_segment_id.setdefault(segment_id, set()).add(
                    f"skip::{station.switch_id}"
                )
            roles_by_segment_id.setdefault(
                station.rope_segment_id,
                set(),
            ).add(f"rope::{station.switch_id}")

        spacing_m = scenario.operating.required_cabin_spacing_m
        regions: list[EanFleetPackingRegion] = []
        for segment_id in sorted(roles_by_segment_id):
            segment = segment_by_id[segment_id]
            regions.append(
                EanFleetPackingRegion(
                    id=f"segment::{segment_id}",
                    kind=EanFleetPackingRegionKind.TRACK_SEGMENT,
                    physical_id=segment_id,
                    capacity=segment_packing_capacity(
                        segment.length_m,
                        spacing_m,
                    ),
                    source_roles=tuple(
                        sorted(roles_by_segment_id[segment_id])
                    ),
                    length_m=segment.length_m,
                    required_spacing_m=spacing_m,
                    half_open=True,
                )
            )

        for station in topology.stations:
            station_config = station_config_by_id.get(station.station_id)
            if station_config is None:
                raise ValueError(
                    "ring topology references station without EAN config: "
                    f"{station.station_id!r}"
                )
            if (
                station_config.waiting_mode
                is StationWaitingMode.END_OF_PLATFORM_WAIT
            ):
                regions.append(
                    EanFleetPackingRegion(
                        id=f"platform_wait::{station.switch_id}",
                        kind=EanFleetPackingRegionKind.PLATFORM_WAIT,
                        physical_id=f"platform_exit::{station.switch_id}",
                        capacity=1,
                        source_roles=(f"wait::{station.switch_id}",),
                    )
                )

        bound = EanInitialPlacementPackingBound(
            regions=tuple(regions),
            packing_upper_bound=sum(region.capacity for region in regions),
            required_spacing_m=spacing_m,
            supported_waiting_modes=(
                StationWaitingMode.NO_WAITING,
                StationWaitingMode.END_OF_PLATFORM_WAIT,
            ),
            assumptions=(
                "The network is one complete directed ring.",
                "Every cabin reference point belongs to exactly one half-open "
                "track segment or one explicit waiting resource.",
                "Track-segment reference points are separated by at least the "
                "required cabin spacing.",
                "An end-of-platform waiting resource holds at most one cabin.",
                "Inactive cabins are outside the physical network.",
            ),
        )
        bound.validate()
        return bound


def segment_packing_capacity(
    length_m: float,
    required_spacing_m: float,
) -> int:
    if length_m <= 0:
        raise ValueError("segment packing length must be positive")
    if required_spacing_m <= 0:
        raise ValueError("segment packing spacing must be positive")
    ratio = Decimal(str(length_m)) / Decimal(str(required_spacing_m))
    return int(ratio.to_integral_value(rounding=ROUND_CEILING))
