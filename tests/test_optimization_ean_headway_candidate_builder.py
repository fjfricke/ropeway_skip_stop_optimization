from __future__ import annotations

import pytest

from ropeway_skip_stop_optimization.optimization.ean import (
    EanActivationReference,
    EanTimeReference,
    HeadwayCheckpointDefinition,
    HeadwayCheckpointKind,
    StationWaitingMode,
    SwitchVisitDefinition,
    SwitchVisitHeadwayCandidateBuilder,
    activation_reference_for_checkpoint_kind,
    time_reference_for_checkpoint_kind,
)


def test_switch_visit_headway_candidate_builder_maps_checkpoint_kinds() -> None:
    builder = SwitchVisitHeadwayCandidateBuilder()

    candidates = builder.build(
        visits=(
            SwitchVisitDefinition(cabin_id=0, visit_index=0, switch_id="sw_a"),
            SwitchVisitDefinition(cabin_id=1, visit_index=2, switch_id="sw_b"),
        ),
        checkpoints=(
            _checkpoint("platform_entry::sw_a", HeadwayCheckpointKind.PLATFORM_ENTRY, "sw_a"),
            _checkpoint("platform_exit::sw_a", HeadwayCheckpointKind.PLATFORM_EXIT, "sw_a"),
            _checkpoint("exit_switch::sw_a", HeadwayCheckpointKind.EXIT_SWITCH, "sw_a"),
            _checkpoint("exit_switch::sw_b", HeadwayCheckpointKind.EXIT_SWITCH, "sw_b"),
        ),
    )

    assert tuple(candidate.id for candidate in candidates) == (
        "candidate::platform_entry::sw_a::cabin_0::visit_0",
        "candidate::platform_exit::sw_a::cabin_0::visit_0",
        "candidate::exit_switch::sw_a::cabin_0::visit_0",
        "candidate::exit_switch::sw_b::cabin_1::visit_2",
    )
    assert tuple(candidate.time_reference for candidate in candidates) == (
        EanTimeReference.PLATFORM_ENTRY_TIME,
        EanTimeReference.PLATFORM_EXIT_TIME,
        EanTimeReference.EXIT_SWITCH_TIME,
        EanTimeReference.EXIT_SWITCH_TIME,
    )
    assert tuple(candidate.activation_reference for candidate in candidates) == (
        EanActivationReference.SERVE,
        EanActivationReference.SERVE,
        EanActivationReference.ACTIVE,
        EanActivationReference.ACTIVE,
    )


def test_switch_visit_headway_candidate_builder_filters_by_switch_id() -> None:
    builder = SwitchVisitHeadwayCandidateBuilder()

    candidates = builder.build(
        visits=(SwitchVisitDefinition(cabin_id=0, visit_index=0, switch_id="sw_a"),),
        checkpoints=(
            _checkpoint("exit_switch::sw_b", HeadwayCheckpointKind.EXIT_SWITCH, "sw_b"),
        ),
    )

    assert candidates == ()


def test_checkpoint_kind_helpers_return_expected_references() -> None:
    assert time_reference_for_checkpoint_kind(HeadwayCheckpointKind.ENTRY_SWITCH) is (
        EanTimeReference.ENTRY_TIME
    )
    assert time_reference_for_checkpoint_kind(HeadwayCheckpointKind.PLATFORM_ENTRY) is (
        EanTimeReference.PLATFORM_ENTRY_TIME
    )
    assert time_reference_for_checkpoint_kind(HeadwayCheckpointKind.PLATFORM_EXIT) is EanTimeReference.PLATFORM_EXIT_TIME
    assert time_reference_for_checkpoint_kind(HeadwayCheckpointKind.EXIT_SWITCH) is EanTimeReference.EXIT_SWITCH_TIME
    assert activation_reference_for_checkpoint_kind(HeadwayCheckpointKind.PLATFORM_ENTRY) is EanActivationReference.SERVE
    assert activation_reference_for_checkpoint_kind(HeadwayCheckpointKind.PLATFORM_EXIT) is EanActivationReference.SERVE
    assert activation_reference_for_checkpoint_kind(HeadwayCheckpointKind.EXIT_SWITCH) is EanActivationReference.ACTIVE
    assert activation_reference_for_checkpoint_kind(HeadwayCheckpointKind.ENTRY_SWITCH) is EanActivationReference.ACTIVE


def test_switch_visit_headway_candidate_builder_rejects_duplicate_visits() -> None:
    builder = SwitchVisitHeadwayCandidateBuilder()

    with pytest.raises(ValueError, match="duplicate switch visit"):
        builder.build(
            visits=(
                SwitchVisitDefinition(cabin_id=0, visit_index=0, switch_id="sw_a"),
                SwitchVisitDefinition(cabin_id=0, visit_index=0, switch_id="sw_b"),
            ),
            checkpoints=(
                _checkpoint("exit_switch::sw_a", HeadwayCheckpointKind.EXIT_SWITCH, "sw_a"),
            ),
        )


def test_switch_visit_headway_candidate_builder_rejects_duplicate_checkpoints() -> None:
    builder = SwitchVisitHeadwayCandidateBuilder()

    with pytest.raises(ValueError, match="duplicate headway checkpoint"):
        builder.build(
            visits=(SwitchVisitDefinition(cabin_id=0, visit_index=0, switch_id="sw_a"),),
            checkpoints=(
                _checkpoint("exit_switch::sw_a", HeadwayCheckpointKind.EXIT_SWITCH, "sw_a"),
                _checkpoint("exit_switch::sw_a", HeadwayCheckpointKind.EXIT_SWITCH, "sw_a"),
            ),
        )


def test_switch_visit_headway_candidate_builder_requires_inputs() -> None:
    builder = SwitchVisitHeadwayCandidateBuilder()

    with pytest.raises(ValueError, match="at least one switch visit"):
        builder.build(
            visits=(),
            checkpoints=(
                _checkpoint("exit_switch::sw_a", HeadwayCheckpointKind.EXIT_SWITCH, "sw_a"),
            ),
        )

    with pytest.raises(ValueError, match="at least one checkpoint"):
        builder.build(
            visits=(SwitchVisitDefinition(cabin_id=0, visit_index=0, switch_id="sw_a"),),
            checkpoints=(),
        )


def _checkpoint(
    checkpoint_id: str,
    kind: HeadwayCheckpointKind,
    switch_id: str,
) -> HeadwayCheckpointDefinition:
    return HeadwayCheckpointDefinition(
        id=checkpoint_id,
        kind=kind,
        switch_id=switch_id,
        station_id="A",
        headway_seconds=2.5,
        applies_to_serve=True,
        applies_to_skip=kind is HeadwayCheckpointKind.EXIT_SWITCH,
        waiting_modes=(StationWaitingMode.NO_WAITING,),
    )
