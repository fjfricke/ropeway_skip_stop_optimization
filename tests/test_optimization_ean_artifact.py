from __future__ import annotations

from dataclasses import replace

import pytest

from ropeway_skip_stop_optimization.optimization.ean import (
    EanActivationReference,
    EanBuildArtifact,
    EanCabinStart,
    EanCabinStartKind,
    EanConfig,
    EanTimeReference,
    HeadwayCandidate,
    HeadwayCheckpointDefinition,
    HeadwayCheckpointKind,
    HeadwayPair,
    SkipStopTiming,
    StationEanConfig,
    StationWaitingMode,
    SwitchTransition,
    SwitchVisitDefinition,
)


def test_ean_build_artifact_validates_consistent_bundle() -> None:
    _artifact().validate()


def test_ean_build_artifact_allows_empty_headway_pairs() -> None:
    replace(_artifact(), headway_pairs=()).validate()


def test_ean_build_artifact_requires_timings_for_exact_switch_cycle() -> None:
    with pytest.raises(ValueError, match="timings.*missing"):
        replace(_artifact(), timings=(_timing("sw_a", "A"),)).validate()

    with pytest.raises(ValueError, match="timings.*extra"):
        replace(
            _artifact(),
            timings=(
                _timing("sw_a", "A"),
                _timing("sw_b", "B"),
                _timing("sw_c", "C"),
            ),
        ).validate()


def test_ean_build_artifact_rejects_references_outside_bundle() -> None:
    with pytest.raises(ValueError, match="cabin start references unknown switch"):
        replace(
            _artifact(),
            cabin_starts=(EanCabinStart(0, "sw_x", EanCabinStartKind.FIXED, 0.0),),
        ).validate()

    with pytest.raises(ValueError, match="candidate references unknown visit"):
        replace(
            _artifact(),
            headway_candidates=(
                HeadwayCandidate(
                    id="candidate::platform_entry::sw_a::cabin_0::visit_4",
                    checkpoint_id="platform_entry::sw_a",
                    cabin_id=0,
                    visit_index=4,
                    time_reference=EanTimeReference.PLATFORM_ENTRY_TIME,
                    activation_reference=EanActivationReference.SERVE,
                ),
            ),
        ).validate()

    with pytest.raises(ValueError, match="pair references unknown second_candidate_id"):
        replace(
            _artifact(),
            headway_pairs=(
                HeadwayPair(
                    id="pair::bad",
                    checkpoint_id="platform_entry::sw_a",
                    first_candidate_id="candidate::platform_entry::sw_a::cabin_0::visit_0",
                    second_candidate_id="candidate::missing",
                    headway_seconds=3.0,
                ),
            ),
        ).validate()


def test_ean_build_artifact_rejects_checkpoint_station_mismatch() -> None:
    artifact = _artifact()
    bad_checkpoint = replace(artifact.headway_checkpoints[0], station_id="B")

    with pytest.raises(ValueError, match="station_id does not match"):
        replace(artifact, headway_checkpoints=(bad_checkpoint, *artifact.headway_checkpoints[1:])).validate()


def test_ean_build_artifact_rejects_pair_candidates_from_other_checkpoint() -> None:
    artifact = _artifact()
    wrong_checkpoint_candidate = _candidate(
        "candidate::platform_entry::sw_b::cabin_0::visit_1",
        "platform_entry::sw_b",
        1,
    )

    with pytest.raises(ValueError, match="second candidate belongs to another checkpoint"):
        replace(
            artifact,
            headway_candidates=(artifact.headway_candidates[0], wrong_checkpoint_candidate),
            headway_pairs=(
                HeadwayPair(
                    id="pair::bad_checkpoint",
                    checkpoint_id="platform_entry::sw_a",
                    first_candidate_id=artifact.headway_candidates[0].id,
                    second_candidate_id=wrong_checkpoint_candidate.id,
                    headway_seconds=3.0,
                ),
            ),
        ).validate()


def _artifact() -> EanBuildArtifact:
    return EanBuildArtifact(
        scenario_id="scenario",
        config=EanConfig(
            horizon_seconds=120.0,
            tail_seconds=30.0,
            cabin_capacity=8,
            station_configs=(
                StationEanConfig("A", StationWaitingMode.NO_WAITING),
                StationEanConfig("B", StationWaitingMode.NO_WAITING),
            ),
        ),
        switch_cycle=("sw_a", "sw_b"),
        timings=(_timing("sw_a", "A"), _timing("sw_b", "B")),
        cabin_starts=(EanCabinStart(0, "sw_a", EanCabinStartKind.FIXED, 0.0),),
        switch_visits=(
            SwitchVisitDefinition(cabin_id=0, visit_index=0, switch_id="sw_a"),
            SwitchVisitDefinition(cabin_id=0, visit_index=1, switch_id="sw_b"),
        ),
        switch_transitions=(
            SwitchTransition("sw_a", "sw_b", min_seconds=14.0, max_seconds=20.0),
            SwitchTransition("sw_b", "sw_a", min_seconds=14.0, max_seconds=20.0),
        ),
        headway_checkpoints=(
            _checkpoint("platform_entry::sw_a", "sw_a", "A"),
            _checkpoint("platform_entry::sw_b", "sw_b", "B"),
        ),
        headway_candidates=(
            _candidate("candidate::platform_entry::sw_a::cabin_0::visit_0", "platform_entry::sw_a", 0),
            _candidate("candidate::platform_entry::sw_a::cabin_0::visit_1", "platform_entry::sw_a", 1),
        ),
        headway_pairs=(
            HeadwayPair(
                id="pair::platform_entries",
                checkpoint_id="platform_entry::sw_a",
                first_candidate_id="candidate::platform_entry::sw_a::cabin_0::visit_0",
                second_candidate_id="candidate::platform_entry::sw_a::cabin_0::visit_1",
                headway_seconds=3.0,
            ),
        ),
    )


def _timing(switch_id: str, station_id: str) -> SkipStopTiming:
    return SkipStopTiming(
        switch_id=switch_id,
        station_id=station_id,
        entry_to_platform_entry_seconds=2.0,
        min_platform_entry_to_platform_exit_seconds=5.0,
        platform_exit_to_exit_switch_seconds=3.0,
        skip_entry_to_exit_switch_seconds=4.0,
        rope_to_next_switch_seconds=10.0,
    )


def _checkpoint(checkpoint_id: str, switch_id: str, station_id: str) -> HeadwayCheckpointDefinition:
    return HeadwayCheckpointDefinition(
        id=checkpoint_id,
        kind=HeadwayCheckpointKind.PLATFORM_ENTRY,
        switch_id=switch_id,
        station_id=station_id,
        headway_seconds=3.0,
        applies_to_serve=True,
        applies_to_skip=False,
        waiting_modes=(StationWaitingMode.NO_WAITING,),
    )


def _candidate(candidate_id: str, checkpoint_id: str, visit_index: int) -> HeadwayCandidate:
    return HeadwayCandidate(
        id=candidate_id,
        checkpoint_id=checkpoint_id,
        cabin_id=0,
        visit_index=visit_index,
        time_reference=EanTimeReference.PLATFORM_ENTRY_TIME,
        activation_reference=EanActivationReference.SERVE,
    )
