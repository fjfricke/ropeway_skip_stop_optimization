from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import time
from enum import StrEnum

from ropeway_skip_stop_optimization.examples.base import (
    ScenarioExample,
    ScenarioExampleMetadata,
)
from ropeway_skip_stop_optimization.examples.circular_skip_stop import (
    CircularSkipStopSpec,
    FiveStationCircleCwFullSkipNoWaitExample,
    FiveStationCircleCwHalfSkipNoWaitExample,
    build_circular_skip_stop_ean_config,
    build_circular_skip_stop_ean_pattern_definition,
    build_circular_skip_stop_scenario,
)
from ropeway_skip_stop_optimization.examples.linear_skip_stop import (
    LinearSkipStopSpec,
    build_linear_skip_stop_ean_config,
    build_linear_skip_stop_ean_pattern_definition,
    build_linear_skip_stop_scenario,
)
from ropeway_skip_stop_optimization.mapping import DiscretizationConfig
from ropeway_skip_stop_optimization.models import (
    ConventionalQuickSwitchDesign,
    DefaultBypassStopOnFaultDesign,
    FailSafeDiversionDesign,
    HeadwayDesign,
    HeadwayEvidenceKind,
    HeadwayParameterProvenance,
    HeadwayPhysicalParameters,
    GeometricSharedBoundaryDesign,
    MandatoryServiceStationDesign,
    PhysicalNode,
    PhysicalNodeKind,
    Scenario,
    SpeedProfile,
    SpeedProfileKind,
    StationMechanismAssignment,
    StationMechanismDesign,
    TrackSegment,
    TrackSegmentKind,
)
from ropeway_skip_stop_optimization.optimization.ean import (
    EanBuildArtifactBuilder,
    EanConfig,
    EvenlySpacedAllStopCabinStartBuilder,
    StationWaitingMode,
    network_ean_builder_for_pattern,
)


class ArtificialHeadwayArchitecture(StrEnum):
    A = "a"
    B = "b"
    C = "c"


ARTIFICIAL_STATION_IDS = ("S0", "S1", "S2", "S3", "S4", "S5")
ARTIFICIAL_CABIN_COUNT = 12


class FiveStationCircleCwHalfSkipNoWaitHeadwayBExample(
    FiveStationCircleCwHalfSkipNoWaitExample
):
    """Half-demand five-station reference with architecture-B headways."""

    metadata = ScenarioExampleMetadata(
        id="five_station_circle_cw_half_skip_no_wait_headway_b_v0",
        label="Five station circle cw half demand skip+no_wait, headway B",
        description=(
            "Clockwise five-station half-demand reference case with skip enabled, "
            "waiting disabled, and physically derived architecture-B headways."
        ),
        tags=(
            "circle",
            "cw",
            "skip-stop",
            "half-demand",
            "no-waiting",
            "physical-headway",
            "architecture-b",
        ),
        family_id="five_station_circle",
        family_label="Five station circle",
        variant_id="half_skip_no_wait_headway_b",
        variant_label="Half demand skip+no_wait, headway B",
    )

    def build_scenario(self) -> Scenario:
        return _with_architecture_b_headways(
            super().build_scenario(),
            scenario_id=self.metadata.id,
        )


class FiveStationCircleCwFullSkipNoWaitHeadwayBExample(
    FiveStationCircleCwFullSkipNoWaitExample
):
    """Existing five-station scaling case with architecture-B headways."""

    metadata = ScenarioExampleMetadata(
        id="five_station_circle_cw_full_skip_no_wait_headway_b_v0",
        label="Five station circle cw full cabins skip+no_wait, headway B",
        description=(
            "Clockwise five-station full-cabin reference case with skip enabled, "
            "waiting disabled, and physically derived architecture-B headways."
        ),
        tags=(
            "circle",
            "cw",
            "skip-stop",
            "scaling-demo",
            "full-cabins",
            "no-waiting",
            "physical-headway",
            "architecture-b",
        ),
        family_id="five_station_circle",
        family_label="Five station circle",
        variant_id="full_skip_no_wait_headway_b",
        variant_label="Full cabins skip+no_wait, headway B",
    )

    def build_scenario(self) -> Scenario:
        return _with_architecture_b_headways(
            super().build_scenario(),
            scenario_id=self.metadata.id,
        )


class FiveStationCircleCwFullSkipWaitHeadwayBExample(
    FiveStationCircleCwFullSkipNoWaitHeadwayBExample
):
    """Architecture-B reference case with bounded end-of-platform waiting."""

    metadata = ScenarioExampleMetadata(
        id="five_station_circle_cw_full_skip_wait_headway_b_v0",
        label="Five station circle cw full cabins skip+wait, headway B",
        description=(
            "Clockwise five-station full-cabin reference case with skip enabled, "
            "one-second waiting steps up to ten seconds, and physically derived "
            "architecture-B headways."
        ),
        tags=(
            "circle",
            "cw",
            "skip-stop",
            "scaling-demo",
            "full-cabins",
            "bounded-waiting",
            "physical-headway",
            "architecture-b",
        ),
        family_id="five_station_circle",
        family_label="Five station circle",
        variant_id="full_skip_wait_headway_b",
        variant_label="Full cabins skip+wait, headway B",
    )

    def build_scenario(self) -> Scenario:
        return replace(super().build_scenario(), id=self.metadata.id)

    def build_ean_config(self, scenario: Scenario) -> EanConfig:
        config = super().build_ean_config(scenario)
        return replace(
            config,
            station_configs=tuple(
                replace(
                    station,
                    waiting_mode=StationWaitingMode.END_OF_PLATFORM_WAIT,
                    max_wait_seconds=10.0,
                )
                for station in config.station_configs
            ),
        )


def with_architecture_b_headways(
    scenario: Scenario,
    *,
    scenario_id: str,
    direction: str = "cw",
) -> Scenario:
    station_ids = tuple(station.id for station in scenario.stations)
    return replace(
        scenario,
        id=scenario_id,
        headway_design=HeadwayDesign(
            physical=_physical_parameters(),
            station_mechanisms=tuple(
                StationMechanismAssignment(
                    exit_switch_id=f"{station}_exit_{direction}",
                    design=DefaultBypassStopOnFaultDesign(
                        **_fault_parameters(),
                        mechanical_service_cycle_seconds=6.0,
                        service_resource_id=(
                            f"service_attachment::{station}::{direction}"
                        ),
                    ),
                )
                for station in station_ids
            ),
            provenance=(
                _architecture_provenance(ArtificialHeadwayArchitecture.B),
            ),
        ),
    )


def with_geometric_headways(
    scenario: Scenario, *, scenario_id: str, direction: str = "cw",
) -> Scenario:
    """Build the thesis geometry directly, without legacy fault inputs."""
    return replace(
        scenario, id=scenario_id,
        headway_design=HeadwayDesign(
            physical=_physical_parameters(),
            station_mechanisms=tuple(
                StationMechanismAssignment(
                    exit_switch_id=f"{station.id}_exit_{direction}",
                    design=GeometricSharedBoundaryDesign(),
                ) for station in scenario.stations
            ),
        ),
    )


# Private compatibility name retained for older imports and historical tests.
_with_architecture_b_headways = with_architecture_b_headways


def build_six_station_ring_headway_scenario(
    architecture: ArtificialHeadwayArchitecture,
    *,
    direction: str,
    scenario_id: str | None = None,
) -> Scenario:
    _require_direction(direction)
    scenario = build_circular_skip_stop_scenario(
        CircularSkipStopSpec(
            scenario_id=(
                scenario_id
                or f"six_station_ring_{direction}_headway_{architecture.value}_v0"
            ),
            station_ids=ARTIFICIAL_STATION_IDS,
            label="Artificial six-station ring",
            description="Artificial A/B/C headway comparison case.",
            include_skip_routes=True,
            service_station_waiting_mode=StationWaitingMode.NO_WAITING,
            direction=direction,
            service_end_time=time(9, 0),
            rope_speed_m_per_s=6.0,
            platform_speed_m_per_s=0.3,
            rope_segment_length_m=300.0,
            platform_length_m=10.0,
            bypass_length_m=20.0,
            cabin_capacity=10,
            cabin_length_m=3.0,
            min_clearance_m=0.5,
            scenario_cabin_count=ARTIFICIAL_CABIN_COUNT,
        )
    )
    safety_path_by_exit: dict[str, tuple[str, ...]] = {}
    if architecture is ArtificialHeadwayArchitecture.C:
        scenario, safety_path_by_exit = _with_ring_safety_paths(
            scenario, direction=direction
        )
    return replace(
        scenario,
        headway_design=HeadwayDesign(
            physical=_physical_parameters(),
            station_mechanisms=tuple(
                StationMechanismAssignment(
                    exit_switch_id=f"{station}_exit_{direction}",
                    design=_bypass_mechanism(
                        architecture,
                        resource_id=f"service_attachment::{station}::{direction}",
                        safety_path_segment_ids=safety_path_by_exit.get(
                            f"{station}_exit_{direction}", ()
                        ),
                    ),
                )
                for station in ARTIFICIAL_STATION_IDS
            ),
            provenance=(_architecture_provenance(architecture),),
        ),
    )


def build_six_station_line_headway_scenario(
    architecture: ArtificialHeadwayArchitecture,
    *,
    scenario_id: str | None = None,
) -> Scenario:
    scenario = build_linear_skip_stop_scenario(
        LinearSkipStopSpec(
            scenario_id=(
                scenario_id or f"six_station_line_headway_{architecture.value}_v0"
            ),
            station_ids=("T0", "S1", "S2", "S3", "S4", "T5"),
            middle_station_ids=("S1", "S2", "S3", "S4"),
            label="Artificial six-station line",
            description="Artificial A/B/C headway comparison case.",
            service_end_time=time(9, 0),
            rope_speed_m_per_s=6.0,
            platform_speed_m_per_s=0.3,
            rope_segment_length_m=300.0,
            terminal_platform_length_m=10.0,
            middle_platform_length_m=10.0,
            middle_bypass_length_m=20.0,
            cabin_capacity=10,
            cabin_length_m=3.0,
            min_clearance_m=0.5,
            scenario_cabin_count=ARTIFICIAL_CABIN_COUNT,
            include_skip_routes=True,
        )
    )
    safety_path_by_exit: dict[str, tuple[str, ...]] = {}
    if architecture is ArtificialHeadwayArchitecture.C:
        scenario, safety_path_by_exit = _with_line_safety_paths(scenario)
    assignments = [
        StationMechanismAssignment(
            exit_switch_id="T0_exit_lr",
            design=MandatoryServiceStationDesign(
                guaranteed_vehicle_interval_seconds=9.0,
                service_resource_id="terminal_turnback::T0",
            ),
        ),
        StationMechanismAssignment(
            exit_switch_id="T5_exit_rl",
            design=MandatoryServiceStationDesign(
                guaranteed_vehicle_interval_seconds=9.0,
                service_resource_id="terminal_turnback::T5",
            ),
        ),
    ]
    for station in ("S1", "S2", "S3", "S4"):
        for direction in ("lr", "rl"):
            exit_switch_id = f"{station}_exit_{direction}"
            assignments.append(
                StationMechanismAssignment(
                    exit_switch_id=exit_switch_id,
                    design=_bypass_mechanism(
                        architecture,
                        resource_id=(f"service_attachment::{station}::{direction}"),
                        safety_path_segment_ids=safety_path_by_exit.get(
                            exit_switch_id, ()
                        ),
                    ),
                )
            )
    return replace(
        scenario,
        headway_design=HeadwayDesign(
            physical=_physical_parameters(),
            station_mechanisms=tuple(assignments),
            provenance=(_architecture_provenance(architecture),),
        ),
    )


@dataclass(frozen=True)
class ArtificialPhysicalHeadwayExample(ScenarioExample):
    metadata: ScenarioExampleMetadata
    architecture: ArtificialHeadwayArchitecture
    topology: str
    direction: str | None = None

    def build_scenario(self) -> Scenario:
        if self.topology == "line":
            return build_six_station_line_headway_scenario(
                self.architecture,
                scenario_id=self.metadata.id,
            )
        if self.topology == "ring" and self.direction is not None:
            return build_six_station_ring_headway_scenario(
                self.architecture,
                direction=self.direction,
                scenario_id=self.metadata.id,
            )
        raise ValueError("artificial headway example has an invalid topology")

    def build_discretization_config(self, scenario: Scenario) -> DiscretizationConfig:
        del scenario
        return DiscretizationConfig()

    def build_ean_config(self, scenario: Scenario) -> EanConfig:
        if self.topology == "line":
            return build_linear_skip_stop_ean_config(
                scenario,
                service_station_waiting_mode=StationWaitingMode.NO_WAITING,
            )
        return build_circular_skip_stop_ean_config(
            scenario,
            waiting_mode=StationWaitingMode.NO_WAITING,
        )

    def build_ean_artifact_builder(
        self,
        scenario: Scenario,
        config: EanConfig,
    ) -> EanBuildArtifactBuilder:
        del config
        pattern = (
            build_linear_skip_stop_ean_pattern_definition(scenario)
            if self.topology == "line"
            else build_circular_skip_stop_ean_pattern_definition(
                scenario,
                direction=self.direction or "cw",
            )
        )
        return network_ean_builder_for_pattern(
            pattern_definition=pattern,
            start_builder=EvenlySpacedAllStopCabinStartBuilder(ARTIFICIAL_CABIN_COUNT),
        )


def artificial_physical_headway_examples() -> tuple[
    ArtificialPhysicalHeadwayExample, ...
]:
    result: list[ArtificialPhysicalHeadwayExample] = []
    for architecture in ArtificialHeadwayArchitecture:
        result.append(
            _example(
                architecture=architecture,
                topology="line",
                direction=None,
            )
        )
        for direction in ("cw", "ccw"):
            result.append(
                _example(
                    architecture=architecture,
                    topology="ring",
                    direction=direction,
                )
            )
    return tuple(result)


def _example(
    *,
    architecture: ArtificialHeadwayArchitecture,
    topology: str,
    direction: str | None,
) -> ArtificialPhysicalHeadwayExample:
    direction_part = f"_{direction}" if direction is not None else ""
    example_id = (
        f"six_station_{topology}{direction_part}_headway_{architecture.value}_v0"
    )
    topology_label = "line" if topology == "line" else f"ring {direction}"
    return ArtificialPhysicalHeadwayExample(
        metadata=ScenarioExampleMetadata(
            id=example_id,
            label=(
                f"Six-station {topology_label}, architecture "
                f"{architecture.value.upper()}"
            ),
            description=(
                "Artificial no-wait skip-stop case using physically derived "
                "headways. Opposite ring directions are separate patterns."
            ),
            tags=(
                "artificial",
                "six-station",
                topology,
                "skip-stop",
                "physical-headway",
                f"architecture-{architecture.value}",
                "no-waiting",
            ),
            family_id=f"six_station_{topology}_physical_headway",
            family_label=f"Six-station {topology} physical headway",
            variant_id=(
                f"{direction + '_' if direction else ''}"
                f"architecture_{architecture.value}"
            ),
            variant_label=(
                f"{direction.upper() + ' ' if direction else ''}"
                f"architecture {architecture.value.upper()}"
            ),
        ),
        architecture=architecture,
        topology=topology,
        direction=direction,
    )


def _fault_parameters() -> dict:
    """Inputs used only by the historical stop-on-fault mechanism."""
    return dict(
        merge_clearance_m=0.5,
        emergency_merge_sway_angle_rad=0.34,
        control_delay_seconds=0.5,
        emergency_deceleration_m_per_s2=1.75,
        provenance=(
            _provenance(
                "merge_clearance_m",
                "artificial_case_v0",
                HeadwayEvidenceKind.EXPERIMENTAL,
            ),
            _provenance(
                "emergency_merge_sway_angle_rad",
                "en12929_rm2",
                HeadwayEvidenceKind.EXPERIMENTAL,
            ),
            _provenance(
                "control_delay_seconds",
                "artificial_case_v0",
                HeadwayEvidenceKind.EXPERIMENTAL,
            ),
            _provenance(
                "emergency_deceleration_m_per_s2",
                "en12929_6_3_5",
                HeadwayEvidenceKind.EXPERIMENTAL,
            ),
        ),
    )


def _physical_parameters() -> HeadwayPhysicalParameters:
    return HeadwayPhysicalParameters(
        service_clearance_m=0.5,
        rope_clearance_m=0.5,
        cabin_height_m=2.22,
        attachment_to_cabin_roof_m=2.0,
        rope_sway_angle_rad=0.34,
        provenance=(
            _provenance(
                "service_clearance_m", "tezak2016", HeadwayEvidenceKind.LITERATURE
            ),
            _provenance(
                "rope_clearance_m",
                "artificial_case_v0",
                HeadwayEvidenceKind.EXPERIMENTAL,
            ),
            _provenance(
                "cabin_height_m",
                "doppelmayr_d_line",
                HeadwayEvidenceKind.MANUFACTURER,
            ),
            _provenance(
                "attachment_to_cabin_roof_m",
                "artificial_case_v0",
                HeadwayEvidenceKind.EXPERIMENTAL,
            ),
            _provenance(
                "rope_sway_angle_rad", "en12929_rm2", HeadwayEvidenceKind.EXPERIMENTAL
            ),
        ),
    )


def _bypass_mechanism(
    architecture: ArtificialHeadwayArchitecture,
    *,
    resource_id: str,
    safety_path_segment_ids: tuple[str, ...],
) -> StationMechanismDesign:
    if architecture is ArtificialHeadwayArchitecture.A:
        return ConventionalQuickSwitchDesign(manufacturer_vehicle_interval_seconds=9.0)
    if architecture is ArtificialHeadwayArchitecture.B:
        return DefaultBypassStopOnFaultDesign(
            **_fault_parameters(),
            mechanical_service_cycle_seconds=6.0,
            service_resource_id=resource_id,
        )
    if not safety_path_segment_ids:
        raise ValueError("architecture C needs an explicit physical safety path")
    return FailSafeDiversionDesign(
        mechanical_service_cycle_seconds=6.0,
        detection_seconds=0.2,
        diversion_seconds=0.3,
        safety_path_segment_ids=safety_path_segment_ids,
        service_resource_id=resource_id,
    )


def _with_ring_safety_paths(
    scenario: Scenario,
    *,
    direction: str,
) -> tuple[Scenario, dict[str, tuple[str, ...]]]:
    sources = tuple(
        (station, direction, f"{station}_service_accelerate_{direction}")
        for station in ARTIFICIAL_STATION_IDS
    )
    return _with_safety_paths(scenario, sources)


def _with_line_safety_paths(
    scenario: Scenario,
) -> tuple[Scenario, dict[str, tuple[str, ...]]]:
    sources = tuple(
        (station, direction, f"{station}_service_accelerate_{direction}")
        for station in ("S1", "S2", "S3", "S4")
        for direction in ("lr", "rl")
    )
    return _with_safety_paths(scenario, sources)


def _with_safety_paths(
    scenario: Scenario,
    sources: tuple[tuple[str, str, str], ...],
) -> tuple[Scenario, dict[str, tuple[str, ...]]]:
    profile = SpeedProfile(
        SpeedProfileKind.CONSTANT,
        speed_m_per_s=scenario.operating.rope_speed_m_per_s,
    )
    nodes = list(scenario.physical_nodes)
    segments = list(scenario.track_segments)
    result: dict[str, tuple[str, ...]] = {}
    for station, direction, source_node_id in sources:
        target_node_id = f"{station}_safety_clear_{direction}"
        segment_id = f"{station}_{direction}_safety_clear"
        nodes.append(
            PhysicalNode(
                id=target_node_id,
                kind=PhysicalNodeKind.CONNECTOR,
                station_id=station,
            )
        )
        segments.append(
            TrackSegment(
                id=segment_id,
                kind=TrackSegmentKind.CONNECTOR,
                from_node_id=source_node_id,
                to_node_id=target_node_id,
                length_m=5.0,
                speed_profile=profile,
                resource_id=f"safety_path::{station}::{direction}",
            )
        )
        result[f"{station}_exit_{direction}"] = (segment_id,)
    return replace(
        scenario,
        physical_nodes=tuple(nodes),
        track_segments=tuple(segments),
    ), result


def _architecture_provenance(
    architecture: ArtificialHeadwayArchitecture,
) -> HeadwayParameterProvenance:
    source = (
        "leitner_quick_switch"
        if architecture is ArtificialHeadwayArchitecture.A
        else "artificial_case_v0"
    )
    evidence = (
        HeadwayEvidenceKind.MANUFACTURER
        if architecture is ArtificialHeadwayArchitecture.A
        else HeadwayEvidenceKind.ENGINEERING_INPUT
    )
    return _provenance(f"architecture_{architecture.value}", source, evidence)


def _provenance(
    parameter_name: str,
    source_id: str,
    evidence_kind: HeadwayEvidenceKind,
) -> HeadwayParameterProvenance:
    return HeadwayParameterProvenance(
        parameter_name=parameter_name,
        source_id=source_id,
        evidence_kind=evidence_kind,
    )


def _require_direction(direction: str) -> None:
    if direction not in {"cw", "ccw"}:
        raise ValueError("artificial ring direction must be 'cw' or 'ccw'")
