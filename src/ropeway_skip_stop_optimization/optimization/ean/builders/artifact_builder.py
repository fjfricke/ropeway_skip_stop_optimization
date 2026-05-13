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

    def build(self, scenario: Scenario, config: EanConfig) -> EanBuildArtifact:
        scenario.validate()
        config.validate()
        _validate_switch_cycle(self.switch_cycle)

        timings = self.timing_builder.build(scenario, self.switch_cycle)
        cabin_starts = self.start_builder.build(
            scenario=scenario,
            config=config,
            target_switch_ids=frozenset(self.switch_cycle),
        )
        switch_visit_result = RingSwitchVisitBuilder(switch_cycle=self.switch_cycle).build(
            config=config,
            cabin_starts=cabin_starts,
            timings=timings,
        )
        headway_durations = self.headway_duration_builder.build(scenario, timings)
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
