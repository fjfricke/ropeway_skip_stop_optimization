from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from inspect import signature
from time import perf_counter

from ropeway_skip_stop_optimization.models import Scenario
from ropeway_skip_stop_optimization.optimization.headway_policy import (
    HeadwayPolicyBuilder,
    LegacyHeadwayPolicyAdapterBuilder,
    PhysicalHeadwayPolicyBuilder,
)
from ropeway_skip_stop_optimization.optimization.headway_resource_reduction import (
    HeadwayResourceReduction,
    HeadwayResourceReductionMode,
)
from ropeway_skip_stop_optimization.optimization.ean.artifact import EanBuildArtifact
from ropeway_skip_stop_optimization.optimization.ean.build_profile import (
    EanBuildProgressCallback,
    EanBuildProgressKind,
    EanBuildStage,
    emit_build_progress,
)
from ropeway_skip_stop_optimization.optimization.ean.builders.artifact_assembler import (
    EanCompatibilityArtifactAssembler,
    ResolvedEanArtifactInputs,
)
from ropeway_skip_stop_optimization.optimization.ean.builders.artifact_builder import (
    EanBuildArtifactBuilder,
)
from ropeway_skip_stop_optimization.optimization.ean.builders.fixed_start_builder import (
    DeterministicPhysicalNodeToSwitchStartBuilder,
    EanCabinStartBuilder,
)
from ropeway_skip_stop_optimization.optimization.ean.builders.headway_candidate_builder import (
    HeadwayCandidateBuilder,
    SwitchVisitHeadwayCandidateBuilder,
)
from ropeway_skip_stop_optimization.optimization.ean.builders.headway_duration_builder import (
    HeadwayDurationBuilder,
    OperatingSpeedHeadwayDurationBuilder,
)
from ropeway_skip_stop_optimization.optimization.ean.builders.headway_pair_builder import (
    AllPairsHeadwayPairBuilder,
    HeadwayPairBuilder,
)
from ropeway_skip_stop_optimization.optimization.ean.builders.network_timing_builder import (
    NetworkSkipStopTimingBuilder,
)
from ropeway_skip_stop_optimization.optimization.ean.builders.network_visit_builder import (
    NetworkVisitBuilder,
)
from ropeway_skip_stop_optimization.optimization.ean.builders.physical_network_builder import (
    PhysicalMovementNetworkBuilder,
)
from ropeway_skip_stop_optimization.optimization.ean.models import (
    EanCabinStart,
    EanCabinStartKind,
    EanConfig,
    EanFleetConfig,
    EanFleetMode,
)
from ropeway_skip_stop_optimization.optimization.ean.network import (
    EanCirculationPatternDefinition,
)
from ropeway_skip_stop_optimization.optimization.ean.fleet import (
    build_initial_placement_parameters,
)


class EanArtifactConstructionMode(Enum):
    NETWORK = "network"


def network_ean_builder_for_pattern(
    *,
    pattern_definition: EanCirculationPatternDefinition,
    start_builder: EanCabinStartBuilder | None = None,
    headway_duration_builder: HeadwayDurationBuilder | None = None,
    headway_candidate_builder: HeadwayCandidateBuilder | None = None,
    headway_pair_builder: HeadwayPairBuilder | None = None,
    fleet_config: EanFleetConfig | None = None,
    headway_policy_builder: HeadwayPolicyBuilder | None = None,
    headway_resource_reduction_mode: HeadwayResourceReductionMode = (
        HeadwayResourceReductionMode.EXACT
    ),
) -> NetworkEanBuildArtifactBuilder:
    """Build the stage-one network builder for one deterministic pattern."""

    if headway_duration_builder is not None and headway_policy_builder is not None:
        raise ValueError(
            "legacy headway_duration_builder and headway_policy_builder are "
            "mutually exclusive"
        )
    resolved_policy_builder: HeadwayPolicyBuilder = (
        LegacyHeadwayPolicyAdapterBuilder(headway_duration_builder)
        if headway_duration_builder is not None
        else (headway_policy_builder or PhysicalHeadwayPolicyBuilder())
    )

    return NetworkEanBuildArtifactBuilder(
        pattern_definition=pattern_definition,
        start_builder=(
            start_builder or DeterministicPhysicalNodeToSwitchStartBuilder()
        ),
        headway_duration_builder=(
            headway_duration_builder or OperatingSpeedHeadwayDurationBuilder()
        ),
        headway_candidate_builder=(
            headway_candidate_builder or SwitchVisitHeadwayCandidateBuilder()
        ),
        headway_pair_builder=headway_pair_builder or AllPairsHeadwayPairBuilder(),
        fleet_config=fleet_config or EanFleetConfig(),
        headway_policy_builder=resolved_policy_builder,
        headway_resource_reduction_mode=headway_resource_reduction_mode,
    )


@dataclass(frozen=True)
class NetworkEanBuildArtifactBuilder(EanBuildArtifactBuilder):
    """Parallel stage-one builder backed by the canonical movement network.

    The compatibility artifact assembly still reuses the stable pair pipeline;
    network timing and visits are independently derived and checked before they
    replace the compatibility values. This makes migration failures explicit
    while keeping all current solver inputs byte-stable.
    """

    pattern_definition: EanCirculationPatternDefinition
    network_builder: PhysicalMovementNetworkBuilder = field(default_factory=PhysicalMovementNetworkBuilder)
    timing_builder: NetworkSkipStopTimingBuilder = field(default_factory=NetworkSkipStopTimingBuilder)
    start_builder: EanCabinStartBuilder = field(default_factory=DeterministicPhysicalNodeToSwitchStartBuilder)
    headway_duration_builder: HeadwayDurationBuilder = field(default_factory=OperatingSpeedHeadwayDurationBuilder)
    headway_candidate_builder: HeadwayCandidateBuilder = field(default_factory=SwitchVisitHeadwayCandidateBuilder)
    headway_pair_builder: HeadwayPairBuilder = field(default_factory=AllPairsHeadwayPairBuilder)
    fleet_config: EanFleetConfig = field(default_factory=EanFleetConfig)
    headway_policy_builder: HeadwayPolicyBuilder = field(
        default_factory=PhysicalHeadwayPolicyBuilder
    )
    headway_resource_reduction: HeadwayResourceReduction = field(
        default_factory=HeadwayResourceReduction
    )
    headway_resource_reduction_mode: HeadwayResourceReductionMode = (
        HeadwayResourceReductionMode.EXACT
    )

    def build(
        self,
        scenario: Scenario,
        config: EanConfig,
        *,
        progress_callback: EanBuildProgressCallback | None = None,
    ) -> EanBuildArtifact:
        total_started = perf_counter()
        scenario.validate()
        config.validate()
        self.fleet_config.validate()

        timing_started = perf_counter()
        emit_build_progress(
            progress_callback,
            stage=EanBuildStage.ARTIFACT_TIMINGS,
            kind=EanBuildProgressKind.STARTED,
            started=timing_started,
        )
        network = self.network_builder.build(scenario, self.pattern_definition)
        pattern = network.pattern(self.pattern_definition.id)
        timings = self.timing_builder.build(scenario, network, pattern)
        headway_policy = self.headway_policy_builder.build(
            scenario,
            network,
            timings,
            pattern,
        )
        effective_headway_policy = (
            None
            if headway_policy.legacy
            else self.headway_resource_reduction.reduce(
                policy=headway_policy,
                network=network,
                timings=timings,
                station_configs=config.station_configs,
                mode=self.headway_resource_reduction_mode,
            )
        )
        timing_seconds = perf_counter() - timing_started
        emit_build_progress(
            progress_callback,
            stage=EanBuildStage.ARTIFACT_TIMINGS,
            kind=EanBuildProgressKind.FINISHED,
            started=timing_started,
        )

        visit_started = perf_counter()
        emit_build_progress(
            progress_callback,
            stage=EanBuildStage.ARTIFACT_VISITS,
            kind=EanBuildProgressKind.STARTED,
            started=visit_started,
        )
        initial_placement_parameters = None
        selectable_initial_phase_count = 0
        if self.fleet_config.mode is EanFleetMode.OPTIMIZED_INITIAL_PLACEMENT:
            available_fleet_count = self.fleet_config.available_fleet_count
            if available_fleet_count is None:
                raise ValueError("optimized initial placement requires available_fleet_count")
            initial_placement_parameters = build_initial_placement_parameters(
                state_ids=pattern.state_ids,
                available_fleet_count=available_fleet_count,
            )
            selectable_initial_phase_count = initial_placement_parameters.initial_phase_visit_count
            cabin_starts = tuple(
                EanCabinStart(
                    cabin_id=cabin_id,
                    first_switch_id=pattern.state_ids[0],
                    kind=EanCabinStartKind.EARLIEST,
                    time_seconds=0.0,
                )
                for cabin_id in range(available_fleet_count)
            )
        else:
            if "headway_policy" in signature(
                self.start_builder.build
            ).parameters:
                cabin_starts = self.start_builder.build(
                    scenario=scenario,
                    config=config,
                    network=network,
                    pattern=pattern,
                    headway_policy=headway_policy,
                )
            else:
                cabin_starts = self.start_builder.build(
                    scenario=scenario,
                    config=config,
                    network=network,
                    pattern=pattern,
                )
        visit_result = NetworkVisitBuilder(
            pattern=pattern,
            selectable_initial_phase_count=selectable_initial_phase_count,
        ).build(config=config, cabin_starts=cabin_starts, timings=timings)
        visit_seconds = perf_counter() - visit_started
        emit_build_progress(
            progress_callback,
            stage=EanBuildStage.ARTIFACT_VISITS,
            kind=EanBuildProgressKind.FINISHED,
            started=visit_started,
            visit_count=len(visit_result.visits),
        )

        return EanCompatibilityArtifactAssembler(
            headway_duration_builder=self.headway_duration_builder,
            headway_candidate_builder=self.headway_candidate_builder,
            headway_pair_builder=self.headway_pair_builder,
        ).assemble(
            scenario,
            config,
            ResolvedEanArtifactInputs(
                state_ids=pattern.state_ids,
                timings=timings,
                cabin_starts=cabin_starts,
                visits=visit_result,
                fleet_config=self.fleet_config,
                initial_placement_parameters=initial_placement_parameters,
                timing_seconds=timing_seconds,
                visit_seconds=visit_seconds,
                total_started=total_started,
                movement_network=network,
                circulation_pattern_ids=(pattern.id,),
                headway_policy=headway_policy,
                effective_headway_policy=effective_headway_policy,
            ),
            progress_callback=progress_callback,
        )
