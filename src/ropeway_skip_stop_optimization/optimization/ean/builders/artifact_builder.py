from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field

from ropeway_skip_stop_optimization.models import Scenario
from ropeway_skip_stop_optimization.optimization.ean.artifact import EanBuildArtifact
from ropeway_skip_stop_optimization.optimization.ean.builders.fixed_start_builder import (
    DeterministicPhysicalNodeToSwitchStartBuilder,
    EanCabinStartBuilder,
)
from ropeway_skip_stop_optimization.optimization.ean.builders.headway_candidate_builder import (
    HeadwayCandidateBuilder,
    SwitchVisitHeadwayCandidateBuilder,
)
from ropeway_skip_stop_optimization.optimization.ean.builders.headway_checkpoint_builder import (
    SkipStopHeadwayCheckpointBuilder,
)
from ropeway_skip_stop_optimization.optimization.ean.builders.headway_duration_builder import (
    HeadwayDurationBuilder,
    OperatingSpeedHeadwayDurationBuilder,
)
from ropeway_skip_stop_optimization.optimization.ean.builders.headway_pair_builder import (
    AllPairsHeadwayPairBuilder,
    HeadwayPairBuilder,
)
from ropeway_skip_stop_optimization.optimization.ean.builders.ring_switch_visit_builder import (
    RingSwitchVisitBuilder,
)
from ropeway_skip_stop_optimization.optimization.ean.builders.timing_builder import (
    PhysicalSkipStopTimingBuilder,
    SkipStopTimingBuilder,
)
from ropeway_skip_stop_optimization.optimization.ean.models import EanConfig
from ropeway_skip_stop_optimization.optimization.ean.models import (
    EanCabinStart,
    EanCabinStartKind,
    EanFleetConfig,
    EanFleetMode,
)
from ropeway_skip_stop_optimization.optimization.ean.fleet import (
    build_initial_placement_parameters,
)


class EanBuildArtifactBuilder(ABC):
    @abstractmethod
    def build(self, scenario: Scenario, config: EanConfig) -> EanBuildArtifact:
        """Build an EAN artifact from a physical scenario and EAN config."""


@dataclass(frozen=True)
class RingEanBuildArtifactBuilder(EanBuildArtifactBuilder):
    """Build an EAN artifact for a fixed directed ring of skip/stop switches."""

    switch_cycle: tuple[str, ...]
    timing_builder: SkipStopTimingBuilder = field(default_factory=PhysicalSkipStopTimingBuilder)
    start_builder: EanCabinStartBuilder = field(default_factory=DeterministicPhysicalNodeToSwitchStartBuilder)
    headway_duration_builder: HeadwayDurationBuilder = field(default_factory=OperatingSpeedHeadwayDurationBuilder)
    headway_candidate_builder: HeadwayCandidateBuilder = field(default_factory=SwitchVisitHeadwayCandidateBuilder)
    headway_pair_builder: HeadwayPairBuilder = field(default_factory=AllPairsHeadwayPairBuilder)
    fleet_config: EanFleetConfig = field(default_factory=EanFleetConfig)

    def build(self, scenario: Scenario, config: EanConfig) -> EanBuildArtifact:
        scenario.validate()
        config.validate()
        _validate_switch_cycle(self.switch_cycle)

        self.fleet_config.validate()
        timings = self.timing_builder.build(scenario, self.switch_cycle)
        headway_durations = self.headway_duration_builder.build(scenario, timings)
        initial_placement_parameters = None
        selectable_initial_phase_count = 0
        if self.fleet_config.mode is EanFleetMode.OPTIMIZED_INITIAL_PLACEMENT:
            available_fleet_count = self.fleet_config.available_fleet_count
            if available_fleet_count is None:
                raise ValueError("optimized initial placement requires available_fleet_count")
            initial_placement_parameters = build_initial_placement_parameters(
                switch_cycle=self.switch_cycle,
                available_fleet_count=available_fleet_count,
            )
            selectable_initial_phase_count = (
                initial_placement_parameters.initial_phase_visit_count
            )
            cabin_starts = tuple(
                EanCabinStart(
                    cabin_id=cabin_id,
                    first_switch_id=self.switch_cycle[0],
                    kind=EanCabinStartKind.EARLIEST,
                    time_seconds=0.0,
                )
                for cabin_id in range(available_fleet_count)
            )
        else:
            cabin_starts = self.start_builder.build(
                scenario=scenario,
                config=config,
                target_switch_ids=frozenset(self.switch_cycle),
            )
        switch_visit_result = RingSwitchVisitBuilder(
            switch_cycle=self.switch_cycle,
            selectable_initial_phase_count=selectable_initial_phase_count,
        ).build(
            config=config,
            cabin_starts=cabin_starts,
            timings=timings,
        )
        checkpoints = SkipStopHeadwayCheckpointBuilder(
            station_headway_seconds_by_station_id=headway_durations.station_headway_seconds_by_station_id,
            exit_switch_headway_seconds_by_switch_id=headway_durations.exit_switch_headway_seconds_by_switch_id,
        ).build(timings=timings, station_configs=config.station_configs)
        candidates = self.headway_candidate_builder.build(
            visits=switch_visit_result.visits,
            checkpoints=checkpoints,
        )
        pairs = self.headway_pair_builder.build(
            candidates=candidates,
            checkpoints=checkpoints,
        )

        artifact = EanBuildArtifact(
            scenario_id=scenario.id,
            config=config,
            switch_cycle=self.switch_cycle,
            timings=timings,
            cabin_starts=cabin_starts,
            switch_visits=switch_visit_result.visits,
            switch_transitions=switch_visit_result.transitions,
            headway_checkpoints=checkpoints,
            headway_candidates=candidates,
            headway_pairs=pairs,
            headway_pair_scope=self.headway_pair_builder.pair_scope,
            fleet_mode=self.fleet_config.mode,
            fleet_cardinality_mode=self.fleet_config.cardinality_mode,
            initial_placement_parameters=initial_placement_parameters,
        )
        artifact.validate()
        return artifact


def _validate_switch_cycle(switch_cycle: tuple[str, ...]) -> None:
    if not switch_cycle:
        raise ValueError("ring EAN build artifact builder needs a nonempty switch_cycle")
    seen: set[str] = set()
    duplicates: set[str] = set()
    for switch_id in switch_cycle:
        if not switch_id:
            raise ValueError("ring EAN switch ids must be nonempty")
        if switch_id in seen:
            duplicates.add(switch_id)
        seen.add(switch_id)
    if duplicates:
        raise ValueError(f"duplicate ring EAN switch ids: {duplicates}")
