from __future__ import annotations

from dataclasses import dataclass

from ropeway_skip_stop_optimization.optimization.ean.build_profile import (
    EanArtifactBuildMetrics,
)
from ropeway_skip_stop_optimization.optimization.ean.fleet import (
    EanInitialPlacementParameters,
)
from ropeway_skip_stop_optimization.optimization.ean.models import (
    EanCabinStart,
    EanCabinStartKind,
    EanConfig,
    EanFleetCardinalityMode,
    EanFleetMode,
    EanHeadwayPairScope,
    HeadwayCandidate,
    HeadwayCheckpointDefinition,
    HeadwayPair,
    SkipStopTiming,
    SwitchTransition,
    SwitchVisitDefinition,
)
from ropeway_skip_stop_optimization.optimization.ean.network import (
    EanMovementNetwork,
    EanResourceConflictIndex,
)


@dataclass(frozen=True)
class EanBuildArtifact:
    scenario_id: str
    config: EanConfig
    switch_cycle: tuple[str, ...]
    timings: tuple[SkipStopTiming, ...]
    cabin_starts: tuple[EanCabinStart, ...]
    switch_visits: tuple[SwitchVisitDefinition, ...]
    switch_transitions: tuple[SwitchTransition, ...]
    headway_checkpoints: tuple[HeadwayCheckpointDefinition, ...]
    headway_candidates: tuple[HeadwayCandidate, ...]
    headway_pairs: tuple[HeadwayPair, ...]
    headway_pair_scope: EanHeadwayPairScope = EanHeadwayPairScope.COMPLETE
    fleet_mode: EanFleetMode = EanFleetMode.FIXED_STARTS
    fleet_cardinality_mode: EanFleetCardinalityMode = (
        EanFleetCardinalityMode.UP_TO_AVAILABLE
    )
    initial_placement_parameters: EanInitialPlacementParameters | None = None
    build_metrics: EanArtifactBuildMetrics | None = None
    movement_network: EanMovementNetwork | None = None
    circulation_pattern_ids: tuple[str, ...] = ()
    resource_conflict_index: EanResourceConflictIndex | None = None

    @property
    def circulation_state_ids(self) -> tuple[str, ...]:
        """Canonical state order, with legacy fallback during migration."""

        if self.movement_network is None or not self.circulation_pattern_ids:
            return self.switch_cycle
        return self.movement_network.pattern(self.circulation_pattern_ids[0]).state_ids

    def validate(self) -> None:
        _require_id("EAN build artifact scenario_id", self.scenario_id)
        if not isinstance(self.headway_pair_scope, EanHeadwayPairScope):
            raise ValueError("EAN build artifact needs a valid headway pair scope")
        if self.build_metrics is not None:
            self.build_metrics.validate()
        self.config.validate()
        _validate_switch_cycle(self.switch_cycle)
        self.validate_network_compatibility()

        timing_by_switch_id = _validate_timings(self.timings)
        _require_exact_keys(
            "EAN build artifact timings",
            set(timing_by_switch_id),
            set(self.switch_cycle),
        )

        station_config_ids = {station_config.station_id for station_config in self.config.station_configs}
        timing_station_ids = {timing.station_id for timing in timing_by_switch_id.values()}
        missing_station_configs = timing_station_ids - station_config_ids
        if missing_station_configs:
            raise ValueError(f"EAN build artifact timings reference stations without config: {missing_station_configs}")

        cabin_start_by_cabin_id = _validate_cabin_starts(self.cabin_starts, set(self.switch_cycle))
        _validate_fleet_definition(
            self,
            cabin_start_by_cabin_id,
        )
        visit_keys = _validate_switch_visits(
            self.switch_visits,
            cabin_ids=set(cabin_start_by_cabin_id),
            switch_ids=set(self.switch_cycle),
        )
        _validate_switch_transitions(self.switch_transitions, set(self.switch_cycle))
        checkpoint_ids = _validate_headway_checkpoints(
            self.headway_checkpoints,
            switch_ids=set(self.switch_cycle),
            timing_by_switch_id=timing_by_switch_id,
        )
        candidate_checkpoint_by_id = _validate_headway_candidates(
            self.headway_candidates,
            checkpoint_ids=checkpoint_ids,
            visit_keys=visit_keys,
        )
        _validate_headway_pairs(
            self.headway_pairs,
            checkpoint_ids=checkpoint_ids,
            candidate_checkpoint_by_id=candidate_checkpoint_by_id,
        )

    def validate_network_compatibility(
        self, *, validate_conflict_index: bool = True
    ) -> None:
        """Validate additive network provenance without rescanning all pairs."""
        if self.movement_network is None:
            if self.circulation_pattern_ids:
                raise ValueError("artifact pattern ids require a movement network")
            if self.resource_conflict_index is not None:
                raise ValueError("resource conflict index requires a movement network")
            return
        self.movement_network.validate()
        if not self.circulation_pattern_ids:
            raise ValueError("network artifact needs at least one circulation pattern id")
        network_pattern_ids = {
            pattern.id for pattern in self.movement_network.circulation_patterns
        }
        unknown = set(self.circulation_pattern_ids) - network_pattern_ids
        if unknown:
            raise ValueError(f"artifact references unknown circulation patterns: {unknown}")
        if len(self.circulation_pattern_ids) != 1:
            raise ValueError("stage-one EAN artifacts support exactly one circulation pattern")
        pattern = self.movement_network.pattern(self.circulation_pattern_ids[0])
        if pattern.state_ids != self.switch_cycle:
            raise ValueError("stage-one circulation pattern must reproduce switch_cycle exactly")
        if self.resource_conflict_index is None:
            raise ValueError("network artifact needs a resource conflict index")
        if validate_conflict_index:
            expected_conflict_index = EanResourceConflictIndex.build(
                self.movement_network,
                self.headway_checkpoints,
                self.headway_candidates,
            )
            if self.resource_conflict_index != expected_conflict_index:
                raise ValueError("network artifact resource conflict index is inconsistent")


def _validate_fleet_definition(
    artifact: EanBuildArtifact,
    starts_by_cabin_id: dict[int, EanCabinStart],
) -> None:
    parameters = artifact.initial_placement_parameters
    if artifact.fleet_mode is EanFleetMode.FIXED_STARTS:
        if parameters is not None:
            raise ValueError("fixed-start artifacts must not define initial placement parameters")
        if artifact.fleet_cardinality_mode is not EanFleetCardinalityMode.UP_TO_AVAILABLE:
            raise ValueError("fixed-start artifacts must use up_to_available cardinality")
        return
    if artifact.fleet_mode is not EanFleetMode.OPTIMIZED_INITIAL_PLACEMENT:
        raise ValueError(f"unsupported EAN fleet mode: {artifact.fleet_mode}")
    if parameters is None:
        raise ValueError("optimized initial placement artifact needs fleet parameters")
    parameters.validate()
    if parameters.available_fleet_count != len(starts_by_cabin_id):
        raise ValueError("EAN fleet count does not match potential cabin starts")
    if set(starts_by_cabin_id) != set(range(parameters.available_fleet_count)):
        raise ValueError("initial placement potential cabin ids must be contiguous from zero")
    if parameters.initial_phase_visit_count != len(artifact.circulation_state_ids):
        raise ValueError("initial placement phase count must match switch_cycle")
    for start in starts_by_cabin_id.values():
        if (
            start.kind is not EanCabinStartKind.EARLIEST
            or start.first_switch_id != artifact.circulation_state_ids[0]
            or start.time_seconds != 0.0
        ):
            raise ValueError("initial placement cabin starts must use the canonical ring origin")


def _validate_switch_cycle(switch_cycle: tuple[str, ...]) -> None:
    if not switch_cycle:
        raise ValueError("EAN build artifact switch_cycle must not be empty")
    duplicate_switch_ids = _duplicates(list(switch_cycle))
    if duplicate_switch_ids:
        raise ValueError(f"EAN build artifact switch_cycle has duplicate ids: {duplicate_switch_ids}")
    for switch_id in switch_cycle:
        _require_id("EAN build artifact switch_cycle id", switch_id)


def _validate_timings(timings: tuple[SkipStopTiming, ...]) -> dict[str, SkipStopTiming]:
    if not timings:
        raise ValueError("EAN build artifact needs at least one timing")
    result: dict[str, SkipStopTiming] = {}
    duplicates = set()
    for timing in timings:
        timing.validate()
        if timing.switch_id in result:
            duplicates.add(timing.switch_id)
        result[timing.switch_id] = timing
    if duplicates:
        raise ValueError(f"EAN build artifact has duplicate timing switch ids: {duplicates}")
    return result


def _validate_cabin_starts(
    cabin_starts: tuple[EanCabinStart, ...],
    switch_ids: set[str],
) -> dict[int, EanCabinStart]:
    if not cabin_starts:
        raise ValueError("EAN build artifact needs at least one cabin start")
    result: dict[int, EanCabinStart] = {}
    duplicates = set()
    for cabin_start in cabin_starts:
        cabin_start.validate()
        if cabin_start.first_switch_id not in switch_ids:
            raise ValueError(
                f"EAN build artifact cabin start references unknown switch {cabin_start.first_switch_id!r}"
            )
        if cabin_start.cabin_id in result:
            duplicates.add(cabin_start.cabin_id)
        result[cabin_start.cabin_id] = cabin_start
    if duplicates:
        raise ValueError(f"EAN build artifact has duplicate cabin starts: {duplicates}")
    return result


def _validate_switch_visits(
    switch_visits: tuple[SwitchVisitDefinition, ...],
    cabin_ids: set[int],
    switch_ids: set[str],
) -> set[tuple[int, int]]:
    if not switch_visits:
        raise ValueError("EAN build artifact needs at least one switch visit")
    result: set[tuple[int, int]] = set()
    duplicates = set()
    for visit in switch_visits:
        visit.validate()
        if visit.cabin_id not in cabin_ids:
            raise ValueError(f"EAN build artifact visit references unknown cabin {visit.cabin_id!r}")
        if visit.switch_id not in switch_ids:
            raise ValueError(f"EAN build artifact visit references unknown switch {visit.switch_id!r}")
        key = (visit.cabin_id, visit.visit_index)
        if key in result:
            duplicates.add(key)
        result.add(key)
    if duplicates:
        raise ValueError(f"EAN build artifact has duplicate switch visits: {duplicates}")
    return result


def _validate_switch_transitions(
    switch_transitions: tuple[SwitchTransition, ...],
    switch_ids: set[str],
) -> None:
    if not switch_transitions:
        raise ValueError("EAN build artifact needs at least one switch transition")
    from_switch_ids: set[str] = set()
    duplicates = set()
    for transition in switch_transitions:
        transition.validate()
        if transition.from_switch_id not in switch_ids:
            raise ValueError(
                f"EAN build artifact transition references unknown from_switch_id {transition.from_switch_id!r}"
            )
        if transition.to_switch_id not in switch_ids:
            raise ValueError(
                f"EAN build artifact transition references unknown to_switch_id {transition.to_switch_id!r}"
            )
        if transition.from_switch_id in from_switch_ids:
            duplicates.add(transition.from_switch_id)
        from_switch_ids.add(transition.from_switch_id)
    if duplicates:
        raise ValueError(f"EAN build artifact has duplicate transition from_switch_ids: {duplicates}")
    _require_exact_keys("EAN build artifact transition from_switch_ids", from_switch_ids, switch_ids)


def _validate_headway_checkpoints(
    headway_checkpoints: tuple[HeadwayCheckpointDefinition, ...],
    switch_ids: set[str],
    timing_by_switch_id: dict[str, SkipStopTiming],
) -> set[str]:
    if not headway_checkpoints:
        raise ValueError("EAN build artifact needs at least one headway checkpoint")
    checkpoint_ids: set[str] = set()
    duplicates = set()
    for checkpoint in headway_checkpoints:
        checkpoint.validate()
        if checkpoint.switch_id not in switch_ids:
            raise ValueError(
                f"EAN build artifact checkpoint references unknown switch {checkpoint.switch_id!r}"
            )
        expected_station_id = timing_by_switch_id[checkpoint.switch_id].station_id
        if checkpoint.station_id != expected_station_id:
            raise ValueError(
                "EAN build artifact checkpoint station_id does not match timing station_id for "
                f"switch {checkpoint.switch_id!r}"
            )
        if checkpoint.id in checkpoint_ids:
            duplicates.add(checkpoint.id)
        checkpoint_ids.add(checkpoint.id)
    if duplicates:
        raise ValueError(f"EAN build artifact has duplicate checkpoint ids: {duplicates}")
    return checkpoint_ids


def _validate_headway_candidates(
    headway_candidates: tuple[HeadwayCandidate, ...],
    checkpoint_ids: set[str],
    visit_keys: set[tuple[int, int]],
) -> dict[str, str]:
    if not headway_candidates:
        raise ValueError("EAN build artifact needs at least one headway candidate")
    candidate_checkpoint_by_id: dict[str, str] = {}
    duplicates = set()
    for candidate in headway_candidates:
        candidate.validate()
        if candidate.checkpoint_id not in checkpoint_ids:
            raise ValueError(
                f"EAN build artifact candidate references unknown checkpoint {candidate.checkpoint_id!r}"
            )
        if (candidate.cabin_id, candidate.visit_index) not in visit_keys:
            raise ValueError(
                "EAN build artifact candidate references unknown visit "
                f"{(candidate.cabin_id, candidate.visit_index)!r}"
            )
        if candidate.id in candidate_checkpoint_by_id:
            duplicates.add(candidate.id)
        candidate_checkpoint_by_id[candidate.id] = candidate.checkpoint_id
    if duplicates:
        raise ValueError(f"EAN build artifact has duplicate candidate ids: {duplicates}")
    return candidate_checkpoint_by_id


def _validate_headway_pairs(
    headway_pairs: tuple[HeadwayPair, ...],
    checkpoint_ids: set[str],
    candidate_checkpoint_by_id: dict[str, str],
) -> None:
    pair_ids: set[str] = set()
    duplicates = set()
    for pair in headway_pairs:
        pair.validate()
        if pair.checkpoint_id not in checkpoint_ids:
            raise ValueError(f"EAN build artifact pair references unknown checkpoint {pair.checkpoint_id!r}")
        if pair.first_candidate_id not in candidate_checkpoint_by_id:
            raise ValueError(
                f"EAN build artifact pair references unknown first_candidate_id {pair.first_candidate_id!r}"
            )
        if pair.second_candidate_id not in candidate_checkpoint_by_id:
            raise ValueError(
                f"EAN build artifact pair references unknown second_candidate_id {pair.second_candidate_id!r}"
            )
        if candidate_checkpoint_by_id[pair.first_candidate_id] != pair.checkpoint_id:
            raise ValueError("EAN build artifact pair first candidate belongs to another checkpoint")
        if candidate_checkpoint_by_id[pair.second_candidate_id] != pair.checkpoint_id:
            raise ValueError("EAN build artifact pair second candidate belongs to another checkpoint")
        if pair.id in pair_ids:
            duplicates.add(pair.id)
        pair_ids.add(pair.id)
    if duplicates:
        raise ValueError(f"EAN build artifact has duplicate pair ids: {duplicates}")


def _require_exact_keys(label: str, actual: set, expected: set) -> None:
    missing = expected - actual
    extra = actual - expected
    if missing or extra:
        raise ValueError(f"{label} mismatch: missing={missing}, extra={extra}")


def _require_id(label: str, value: str) -> None:
    if not value:
        raise ValueError(f"{label} must be nonempty")


def _duplicates(values: list[str]) -> set[str]:
    seen = set()
    duplicates = set()
    for value in values:
        if value in seen:
            duplicates.add(value)
        seen.add(value)
    return duplicates
