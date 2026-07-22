from __future__ import annotations

import argparse
from dataclasses import dataclass
from datetime import time
from pathlib import Path

from ropeway_skip_stop_optimization.examples.base import (
    ScenarioExample,
    ScenarioExampleMetadata,
)
from ropeway_skip_stop_optimization.exports.artifacts import (
    ArtifactSet,
    ArtifactSetBackend,
    EanBuildArtifactArtifactBuilder,
    EanModelBuildProfileArtifactBuilder,
    PhysicalScenarioArtifactBuilder,
)
from ropeway_skip_stop_optimization.exports.runner import (
    export_artifact_set,
    run_artifact_set,
)
from ropeway_skip_stop_optimization.models import (
    Cabin,
    CabinInitialState,
    OperatingParameters,
    PhysicalNode,
    PhysicalNodeKind,
    Scenario,
    SpeedProfile,
    SpeedProfileKind,
    Station,
    StationKind,
    StationRoute,
    StationRouteKind,
    TrackSegment,
    TrackSegmentKind,
)
from ropeway_skip_stop_optimization.optimization.ean import (
    EanArtifactConstructionMode,
    EanConfig,
    EanOptimizationProblemKind,
    RingEanBuildArtifactBuilder,
    StationEanConfig,
    StationWaitingMode,
)
from ropeway_skip_stop_optimization.progress import (
    ProgressReporter,
    configure_progress_logging,
)


BASELINE_EXAMPLE_IDS = {
    "three_station": "three_station_v0",
    "five_station_oip_38": (
        "five_station_optimized_initial_placement_all_stop_skip_wait_v0"
    ),
    "five_station_oip_76": (
        "five_station_optimized_initial_placement_double_all_stop_skip_wait_v0"
    ),
}


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Reproduce exact eager EAN model-construction baselines."
    )
    parser.add_argument(
        "case",
        choices=("all", "one_station", *BASELINE_EXAMPLE_IDS),
    )
    parser.add_argument(
        "--output-root",
        type=Path,
        default=Path("benchmarks/output/ean_build_baselines"),
    )
    parser.add_argument("--progress", action="store_true")
    parser.add_argument(
        "--ean-artifact-construction",
        choices=tuple(mode.value for mode in EanArtifactConstructionMode),
        default=EanArtifactConstructionMode.LEGACY_RING.value,
    )
    args = parser.parse_args()
    if args.progress:
        configure_progress_logging()
    reporter = ProgressReporter(enabled=args.progress)

    cases = (
        ("one_station", *BASELINE_EXAMPLE_IDS)
        if args.case == "all"
        else (args.case,)
    )
    for case in cases:
        if case == "one_station":
            _run_one_station(
                args.output_root,
                reporter,
                EanArtifactConstructionMode(args.ean_artifact_construction),
            )
            continue
        export_artifact_set(
            example_id=BASELINE_EXAMPLE_IDS[case],
            artifact_set_id="ean_passenger_journey_time",
            output_root=args.output_root,
            ean_build_only=True,
            ean_artifact_construction=EanArtifactConstructionMode(
                args.ean_artifact_construction
            ),
            progress=reporter,
        )


def _run_one_station(
    output_root: Path,
    progress: ProgressReporter,
    artifact_construction: EanArtifactConstructionMode,
) -> None:
    run_artifact_set(
        _OneStationBuildBaselineExample(),
        ArtifactSet(
            id="ean_skip_stop_feasibility_build_only",
            label="One-station EAN movement build profile",
            builders=(
                PhysicalScenarioArtifactBuilder(),
                EanBuildArtifactArtifactBuilder(),
                EanModelBuildProfileArtifactBuilder(
                    problem_kind=EanOptimizationProblemKind.MOVEMENT_FEASIBILITY,
                ),
            ),
            backend=ArtifactSetBackend.EAN,
        ),
        output_root=output_root,
        ean_build_only=True,
        ean_artifact_construction=artifact_construction,
        progress=progress,
    )


@dataclass(frozen=True)
class _OneStationBuildBaselineExample(ScenarioExample):
    metadata = ScenarioExampleMetadata(
        id="one_station_ean_build_baseline_v0",
        label="One-station EAN build baseline",
        description="Small deterministic ring for model-construction regression.",
        tags=("ring", "one-station", "build-profile"),
        family_id="ean_build_baseline",
        family_label="EAN build baseline",
        variant_id="one_station",
        variant_label="One station",
    )

    def build_scenario(self) -> Scenario:
        speed = SpeedProfile(
            kind=SpeedProfileKind.CONSTANT,
            speed_m_per_s=1.0,
        )
        segment_specs = (
            (
                "approach",
                TrackSegmentKind.CONNECTOR,
                "entry",
                "platform_entry",
            ),
            (
                "platform",
                TrackSegmentKind.STATION,
                "platform_entry",
                "platform_exit",
            ),
            (
                "departure",
                TrackSegmentKind.CONNECTOR,
                "platform_exit",
                "exit",
            ),
            ("rope", TrackSegmentKind.ROPE, "exit", "entry"),
        )
        scenario = Scenario(
            id=self.metadata.id,
            service_start_time=time(8, 0),
            service_end_time=time(8, 1),
            stations=(
                Station(
                    id="S",
                    kind=StationKind.TERMINAL,
                    route_ids=("service",),
                ),
            ),
            physical_nodes=(
                PhysicalNode("entry", PhysicalNodeKind.ENTRY_SWITCH, "S"),
                PhysicalNode("platform_entry", PhysicalNodeKind.PLATFORM, "S"),
                PhysicalNode("platform_exit", PhysicalNodeKind.PLATFORM, "S"),
                PhysicalNode("exit", PhysicalNodeKind.EXIT_SWITCH, "S"),
            ),
            track_segments=tuple(
                TrackSegment(
                    id=segment_id,
                    kind=kind,
                    from_node_id=from_node_id,
                    to_node_id=to_node_id,
                    length_m=5.0,
                    speed_profile=speed,
                )
                for segment_id, kind, from_node_id, to_node_id in segment_specs
            ),
            station_routes=(
                StationRoute(
                    id="service",
                    station_id="S",
                    kind=StationRouteKind.SERVICE,
                    segment_ids=("approach", "platform", "departure"),
                    allows_boarding=True,
                    allows_alighting=True,
                ),
            ),
            cabins=(Cabin(0),),
            cabin_initial_states=(
                CabinInitialState(
                    cabin_id=0,
                    node_id="entry",
                    available_from=time(8, 0),
                ),
            ),
            demands=(),
            operating=OperatingParameters(
                rope_speed_m_per_s=1.0,
                station_speed_m_per_s=1.0,
                cabin_capacity=1,
                cabin_length_m=5.0,
                min_clearance_m=0.0,
            ),
        )
        scenario.validate()
        return scenario

    def build_ean_config(self, scenario: Scenario) -> EanConfig:
        return EanConfig(
            horizon_seconds=60.0,
            tail_seconds=0.0,
            cabin_capacity=1,
            station_configs=(
                StationEanConfig(
                    station_id="S",
                    waiting_mode=StationWaitingMode.NO_WAITING,
                ),
            ),
        )

    def build_ean_artifact_builder(
        self,
        scenario: Scenario,
        config: EanConfig,
    ) -> RingEanBuildArtifactBuilder:
        return RingEanBuildArtifactBuilder(switch_cycle=("entry",))


if __name__ == "__main__":
    main()
