from __future__ import annotations

from dataclasses import dataclass, field, replace
from time import perf_counter

from ropeway_skip_stop_optimization.models import Scenario
from ropeway_skip_stop_optimization.optimization.ean.artifact import EanBuildArtifact
from ropeway_skip_stop_optimization.optimization.ean.build_profile import (
    EanArtifactBuildMetrics,
    EanBuildProgressCallback,
    EanBuildProgressKind,
    EanBuildStage,
    emit_build_progress,
    peak_rss_bytes,
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
from ropeway_skip_stop_optimization.optimization.ean.fleet import (
    EanInitialPlacementParameters,
)
from ropeway_skip_stop_optimization.optimization.ean.models import (
    EanCabinStart,
    EanConfig,
    EanFleetConfig,
    SkipStopTiming,
    SwitchVisitBuildResult,
)
from ropeway_skip_stop_optimization.optimization.ean.network import (
    EanMovementNetwork,
    EanResourceConflictIndex,
)


@dataclass(frozen=True)
class ResolvedEanArtifactInputs:
    state_ids: tuple[str, ...]
    timings: tuple[SkipStopTiming, ...]
    cabin_starts: tuple[EanCabinStart, ...]
    visits: SwitchVisitBuildResult
    fleet_config: EanFleetConfig
    initial_placement_parameters: EanInitialPlacementParameters | None
    timing_seconds: float
    visit_seconds: float
    total_started: float
    movement_network: EanMovementNetwork | None = None
    circulation_pattern_ids: tuple[str, ...] = ()


@dataclass(frozen=True)
class EanCompatibilityArtifactAssembler:
    """Assemble today's deterministic EAN after topology and visits are resolved."""

    headway_duration_builder: HeadwayDurationBuilder = field(
        default_factory=OperatingSpeedHeadwayDurationBuilder
    )
    headway_candidate_builder: HeadwayCandidateBuilder = field(
        default_factory=SwitchVisitHeadwayCandidateBuilder
    )
    headway_pair_builder: HeadwayPairBuilder = field(
        default_factory=AllPairsHeadwayPairBuilder
    )

    def assemble(
        self,
        scenario: Scenario,
        config: EanConfig,
        inputs: ResolvedEanArtifactInputs,
        *,
        progress_callback: EanBuildProgressCallback | None = None,
    ) -> EanBuildArtifact:
        duration_started = perf_counter()
        headway_durations = self.headway_duration_builder.build(
            scenario, inputs.timings
        )
        timing_seconds = inputs.timing_seconds + perf_counter() - duration_started

        checkpoint_started = perf_counter()
        checkpoints = SkipStopHeadwayCheckpointBuilder(
            station_headway_seconds_by_station_id=(
                headway_durations.station_headway_seconds_by_station_id
            ),
            exit_switch_headway_seconds_by_switch_id=(
                headway_durations.exit_switch_headway_seconds_by_switch_id
            ),
        ).build(timings=inputs.timings, station_configs=config.station_configs)
        checkpoint_seconds = perf_counter() - checkpoint_started

        candidate_started = perf_counter()
        emit_build_progress(
            progress_callback,
            stage=EanBuildStage.ARTIFACT_CANDIDATES,
            kind=EanBuildProgressKind.STARTED,
            started=candidate_started,
            checkpoint_count=len(checkpoints),
        )
        candidates = self.headway_candidate_builder.build(
            visits=inputs.visits.visits,
            checkpoints=checkpoints,
        )
        candidate_seconds = perf_counter() - candidate_started
        emit_build_progress(
            progress_callback,
            stage=EanBuildStage.ARTIFACT_CANDIDATES,
            kind=EanBuildProgressKind.FINISHED,
            started=candidate_started,
            checkpoint_count=len(checkpoints),
            candidate_count=len(candidates),
        )

        pair_started = perf_counter()
        emit_build_progress(
            progress_callback,
            stage=EanBuildStage.ARTIFACT_PAIRS,
            kind=EanBuildProgressKind.STARTED,
            started=pair_started,
            checkpoint_count=len(checkpoints),
            candidate_count=len(candidates),
            pair_count=0,
        )

        def pair_progress(processed_checkpoints: int, pair_count: int) -> None:
            emit_build_progress(
                progress_callback,
                stage=EanBuildStage.ARTIFACT_PAIRS,
                kind=EanBuildProgressKind.PROGRESS,
                started=pair_started,
                checkpoint_count=len(checkpoints),
                processed_checkpoint_count=processed_checkpoints,
                candidate_count=len(candidates),
                pair_count=pair_count,
            )

        pairs = self.headway_pair_builder.build(
            candidates=candidates,
            checkpoints=checkpoints,
            progress_callback=(
                pair_progress if progress_callback is not None else None
            ),
        )
        pair_seconds = perf_counter() - pair_started
        emit_build_progress(
            progress_callback,
            stage=EanBuildStage.ARTIFACT_PAIRS,
            kind=EanBuildProgressKind.FINISHED,
            started=pair_started,
            checkpoint_count=len(checkpoints),
            processed_checkpoint_count=len(checkpoints),
            candidate_count=len(candidates),
            pair_count=len(pairs),
        )

        conflict_index = (
            EanResourceConflictIndex.build(
                inputs.movement_network,
                checkpoints,
                candidates,
            )
            if inputs.movement_network is not None
            else None
        )
        artifact = EanBuildArtifact(
            scenario_id=scenario.id,
            config=config,
            switch_cycle=inputs.state_ids,
            timings=inputs.timings,
            cabin_starts=inputs.cabin_starts,
            switch_visits=inputs.visits.visits,
            switch_transitions=inputs.visits.transitions,
            headway_checkpoints=checkpoints,
            headway_candidates=candidates,
            headway_pairs=pairs,
            headway_pair_scope=self.headway_pair_builder.pair_scope,
            fleet_mode=inputs.fleet_config.mode,
            fleet_cardinality_mode=inputs.fleet_config.cardinality_mode,
            initial_placement_parameters=inputs.initial_placement_parameters,
            movement_network=inputs.movement_network,
            circulation_pattern_ids=inputs.circulation_pattern_ids,
            resource_conflict_index=conflict_index,
        )
        validation_started = perf_counter()
        artifact.validate()
        validation_seconds = perf_counter() - validation_started
        return replace(
            artifact,
            build_metrics=EanArtifactBuildMetrics(
                timing_seconds=timing_seconds,
                visit_seconds=inputs.visit_seconds,
                checkpoint_seconds=checkpoint_seconds,
                candidate_seconds=candidate_seconds,
                pair_seconds=pair_seconds,
                validation_seconds=validation_seconds,
                total_seconds=perf_counter() - inputs.total_started,
                checkpoint_count=len(checkpoints),
                candidate_count=len(candidates),
                pair_count=len(pairs),
                peak_rss_bytes=peak_rss_bytes(),
            ),
        )
