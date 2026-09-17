"""Versioned physical scenarios used by the thesis experiment pipeline."""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import time

from .artificial_headway_cases import with_architecture_b_headways
from .base import ScenarioExample, ScenarioExampleMetadata
from .circular_skip_stop import (
    CircularSkipStopSpec,
    build_circular_skip_stop_ean_config,
    build_circular_skip_stop_ean_pattern_definition,
    build_circular_skip_stop_scenario,
)
from ..mapping import DiscretizationConfig
from ..models import Scenario
from ..optimization.ean import (
    EanBuildArtifactBuilder,
    EanConfig,
    EvenlySpacedAllStopCabinStartBuilder,
    StationWaitingMode,
    network_ean_builder_for_pattern,
)


THESIS_STATION_PATH_LENGTH_M = 60.91
THESIS_BRAKE_LENGTH_M = 17.955
THESIS_PLATFORM_LENGTH_M = 15.0
THESIS_FAST_CONNECTOR_LENGTH_M = 5.0

THESIS_GEOMETRIES: dict[str, tuple[float, ...]] = {
    "g300": (300.0,) * 6,
    "g500": (500.0,) * 6,
    "g800": (800.0,) * 6,
    "g1200": (1200.0,) * 6,
    "guneq_v2": (500.0, 1100.0, 900.0, 600.0, 700.0, 1000.0),
}


@dataclass(frozen=True)
class ThesisRingExample(ScenarioExample):
    metadata: ScenarioExampleMetadata
    station_count: int
    geometry_profile: str

    def build_scenario(self) -> Scenario:
        lengths = THESIS_GEOMETRIES[self.geometry_profile]
        if self.geometry_profile == "guneq_v2" and self.station_count != 6:
            raise ValueError("GUNEQ-v2 is defined only for T6R")
        lengths = lengths[: self.station_count]
        scenario = build_circular_skip_stop_scenario(
            CircularSkipStopSpec(
                scenario_id=self.metadata.id,
                station_ids=tuple(f"S{i}" for i in range(self.station_count)),
                label=self.metadata.label,
                description=self.metadata.description,
                include_skip_routes=True,
                service_station_waiting_mode=StationWaitingMode.END_OF_PLATFORM_WAIT,
                service_start_time=time(8, 0),
                service_end_time=time(9, 0),
                rope_speed_m_per_s=6.0,
                platform_speed_m_per_s=0.3,
                rope_segment_length_m=lengths[0],
                rope_segment_lengths_m=lengths,
                approach_fast_length_m=THESIS_FAST_CONNECTOR_LENGTH_M,
                brake_length_m=THESIS_BRAKE_LENGTH_M,
                platform_length_m=THESIS_PLATFORM_LENGTH_M,
                accelerate_length_m=THESIS_BRAKE_LENGTH_M,
                depart_fast_length_m=THESIS_FAST_CONNECTOR_LENGTH_M,
                bypass_length_m=THESIS_STATION_PATH_LENGTH_M,
                cabin_capacity=10,
                cabin_length_m=3.0,
                min_clearance_m=0.5,
                # Physical examples describe infrastructure. Experiment
                # adapters create the requested fixed or reservoir fleet.
                scenario_cabin_count=1,
                demand_count_per_od_pair=1,
            )
        )
        scenario = with_architecture_b_headways(
            scenario,
            scenario_id=self.metadata.id,
            direction="cw",
        )
        return replace(
            scenario,
            experiment_metadata={
                "schema": "thesis_physical_example_v1",
                "topology": f"t{self.station_count}r",
                "geometry": self.geometry_profile,
                "architecture": "B",
                "demand_profile": "physical example only",
            },
        )

    def build_discretization_config(self, scenario: Scenario) -> DiscretizationConfig:
        del scenario
        return DiscretizationConfig()

    def build_ean_config(self, scenario: Scenario) -> EanConfig:
        return build_circular_skip_stop_ean_config(
            scenario,
            waiting_mode=StationWaitingMode.END_OF_PLATFORM_WAIT,
        )

    def build_ean_artifact_builder(
        self,
        scenario: Scenario,
        config: EanConfig,
    ) -> EanBuildArtifactBuilder:
        del config
        return network_ean_builder_for_pattern(
            pattern_definition=build_circular_skip_stop_ean_pattern_definition(
                scenario, direction="cw"
            ),
            start_builder=EvenlySpacedAllStopCabinStartBuilder(1),
        )


def thesis_ring_examples() -> tuple[ThesisRingExample, ...]:
    result = []
    for station_count, topology in ((5, "t5r"), (6, "t6r")):
        geometries = ("g300", "g500", "g800", "g1200")
        if station_count == 6:
            geometries = (*geometries, "guneq_v2")
        for geometry in geometries:
            example_id = f"thesis_{topology}_{geometry}_b_v1"
            length_label = (
                "500/1100/900/600/700/1000 m"
                if geometry == "guneq_v2"
                else f"{int(THESIS_GEOMETRIES[geometry][0])} m"
            )
            result.append(
                ThesisRingExample(
                    metadata=ScenarioExampleMetadata(
                        id=example_id,
                        label=f"{topology.upper()} · {length_label}",
                        description=(
                            f"Versioned thesis {station_count}-station directed ring with "
                            f"architecture B and {geometry.upper()} free rope sections."
                        ),
                        tags=(
                            "thesis-v1",
                            "directed-ring",
                            topology,
                            geometry,
                            "architecture-b",
                        ),
                        family_id=f"thesis_{topology}",
                        family_label=f"{topology.upper()} directed ring",
                        variant_id=geometry,
                        variant_label=length_label,
                    ),
                    station_count=station_count,
                    geometry_profile=geometry,
                )
            )
    return tuple(result)
