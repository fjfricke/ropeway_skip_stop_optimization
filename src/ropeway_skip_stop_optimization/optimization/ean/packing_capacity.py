from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, ROUND_CEILING
from enum import StrEnum

from ropeway_skip_stop_optimization.models import Scenario
from ropeway_skip_stop_optimization.optimization.ean.builders.physical_network_builder import (
    PhysicalMovementNetworkBuilder,
)
from ropeway_skip_stop_optimization.optimization.ean.models import (
    EanConfig,
    StationWaitingMode,
)
from ropeway_skip_stop_optimization.optimization.ean.network import (
    EanCirculationPatternDefinition,
    EanMovementNetwork,
    EanPassengerBehavior,
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
    network_builder: PhysicalMovementNetworkBuilder = PhysicalMovementNetworkBuilder()

    def build(
        self,
        *,
        scenario: Scenario,
        config: EanConfig,
        pattern_definition: EanCirculationPatternDefinition,
    ) -> EanInitialPlacementPackingBound:
        network = self.network_builder.build(
            scenario,
            pattern_definition,
        )
        return self.build_for_network(
            scenario=scenario,
            config=config,
            network=network,
            pattern_id=pattern_definition.id,
        )

    def build_for_network(
        self,
        *,
        scenario: Scenario,
        config: EanConfig,
        network: EanMovementNetwork,
        pattern_id: str,
    ) -> EanInitialPlacementPackingBound:
        scenario.validate()
        config.validate()
        network.validate()
        pattern = network.pattern(pattern_id)
        options_by_id = {option.id: option for option in network.route_options}
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
        station_id_by_state_id: dict[str, str] = {}
        for state_id, option_ids in zip(
            pattern.state_ids,
            pattern.route_option_ids_by_position,
            strict=True,
        ):
            options = tuple(options_by_id[option_id] for option_id in option_ids)
            service_options = tuple(
                option
                for option in options
                if option.passenger_behavior is EanPassengerBehavior.SERVICE
            )
            skip_options = tuple(
                option
                for option in options
                if option.passenger_behavior is EanPassengerBehavior.SKIP
            )
            if len(service_options) != 1 or len(skip_options) > 1:
                raise ValueError(
                    "packing bound requires one service and at most one skip "
                    f"option at state {state_id!r}"
                )
            service = service_options[0]
            station_id_by_state_id[state_id] = service.station_id
            for segment_id in service.station_segment_ids:
                roles_by_segment_id.setdefault(segment_id, set()).add(
                    f"service::{state_id}"
                )
            for skip in skip_options:
                for segment_id in skip.station_segment_ids:
                    roles_by_segment_id.setdefault(segment_id, set()).add(
                        f"skip::{state_id}"
                    )
            for segment_id in service.continuation_segment_ids:
                roles_by_segment_id.setdefault(segment_id, set()).add(
                    f"rope::{state_id}"
                )

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

        for state_id in pattern.state_ids:
            station_id = station_id_by_state_id[state_id]
            station_config = station_config_by_id.get(station_id)
            if station_config is None:
                raise ValueError(
                    "movement network references station without EAN config: "
                    f"{station_id!r}"
                )
            if (
                station_config.waiting_mode
                is StationWaitingMode.END_OF_PLATFORM_WAIT
            ):
                regions.append(
                    EanFleetPackingRegion(
                        id=f"platform_wait::{state_id}",
                        kind=EanFleetPackingRegionKind.PLATFORM_WAIT,
                        physical_id=f"platform_exit::{state_id}",
                        capacity=1,
                        source_roles=(f"wait::{state_id}",),
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
