from __future__ import annotations

import pytest

from ropeway_skip_stop_optimization.optimization.ean import (
    AllPairsHeadwayPairBuilder,
    EanActivationReference,
    EanTimeReference,
    HeadwayCandidate,
    HeadwayCheckpointDefinition,
    HeadwayCheckpointKind,
    StationWaitingMode,
)


def test_all_pairs_headway_pair_builder_builds_unordered_pairs_per_checkpoint() -> None:
    builder = AllPairsHeadwayPairBuilder()
    checkpoint = _checkpoint("exit_switch::sw_a", headway_seconds=3.5)

    pairs = builder.build(
        candidates=(
            _candidate("c2", checkpoint.id, cabin_id=2, visit_index=0),
            _candidate("c1", checkpoint.id, cabin_id=1, visit_index=0),
            _candidate("c0", checkpoint.id, cabin_id=0, visit_index=0),
        ),
        checkpoints=(checkpoint,),
    )

    assert tuple((pair.first_candidate_id, pair.second_candidate_id) for pair in pairs) == (
        ("c0", "c1"),
        ("c0", "c2"),
        ("c1", "c2"),
    )
    assert tuple(pair.headway_seconds for pair in pairs) == (3.5, 3.5, 3.5)


def test_all_pairs_headway_pair_builder_keeps_checkpoints_separate() -> None:
    builder = AllPairsHeadwayPairBuilder()
    exit_checkpoint = _checkpoint("exit_switch::sw_a", headway_seconds=3.5)
    platform_checkpoint = _checkpoint("platform_entry::sw_a", headway_seconds=2.5)

    pairs = builder.build(
        candidates=(
            _candidate("exit_c0", exit_checkpoint.id, cabin_id=0, visit_index=0),
            _candidate("exit_c1", exit_checkpoint.id, cabin_id=1, visit_index=0),
            _candidate("platform_c0", platform_checkpoint.id, cabin_id=0, visit_index=0),
            _candidate("platform_c1", platform_checkpoint.id, cabin_id=1, visit_index=0),
        ),
        checkpoints=(exit_checkpoint, platform_checkpoint),
    )

    assert tuple(pair.checkpoint_id for pair in pairs) == (
        "exit_switch::sw_a",
        "platform_entry::sw_a",
    )
    assert tuple(pair.headway_seconds for pair in pairs) == (3.5, 2.5)


def test_all_pairs_headway_pair_builder_uses_stable_pair_ids() -> None:
    builder = AllPairsHeadwayPairBuilder()
    checkpoint = _checkpoint("exit_switch::sw_a", headway_seconds=3.5)

    pairs = builder.build(
        candidates=(
            _candidate("candidate_b", checkpoint.id, cabin_id=1, visit_index=0),
            _candidate("candidate_a", checkpoint.id, cabin_id=0, visit_index=0),
        ),
        checkpoints=(checkpoint,),
    )

    assert tuple(pair.id for pair in pairs) == (
        "pair::exit_switch::sw_a::candidate_a::candidate_b",
    )


def test_all_pairs_headway_pair_builder_rejects_duplicate_candidate_ids() -> None:
    builder = AllPairsHeadwayPairBuilder()
    checkpoint = _checkpoint("exit_switch::sw_a", headway_seconds=3.5)

    with pytest.raises(ValueError, match="duplicate headway candidate"):
        builder.build(
            candidates=(
                _candidate("candidate_a", checkpoint.id, cabin_id=0, visit_index=0),
                _candidate("candidate_a", checkpoint.id, cabin_id=1, visit_index=0),
            ),
            checkpoints=(checkpoint,),
        )


def test_all_pairs_headway_pair_builder_rejects_duplicate_checkpoint_ids() -> None:
    builder = AllPairsHeadwayPairBuilder()
    checkpoint = _checkpoint("exit_switch::sw_a", headway_seconds=3.5)

    with pytest.raises(ValueError, match="duplicate headway checkpoint"):
        builder.build(
            candidates=(
                _candidate("candidate_a", checkpoint.id, cabin_id=0, visit_index=0),
            ),
            checkpoints=(checkpoint, checkpoint),
        )


def test_all_pairs_headway_pair_builder_rejects_unknown_checkpoint_reference() -> None:
    builder = AllPairsHeadwayPairBuilder()

    with pytest.raises(ValueError, match="unknown checkpoint_id"):
        builder.build(
            candidates=(
                _candidate("candidate_a", "missing::checkpoint", cabin_id=0, visit_index=0),
            ),
            checkpoints=(_checkpoint("exit_switch::sw_a", headway_seconds=3.5),),
        )


def test_all_pairs_headway_pair_builder_rejects_duplicate_visit_at_checkpoint() -> None:
    builder = AllPairsHeadwayPairBuilder()
    checkpoint = _checkpoint("exit_switch::sw_a", headway_seconds=3.5)

    with pytest.raises(ValueError, match="duplicate candidate visits"):
        builder.build(
            candidates=(
                _candidate("candidate_a", checkpoint.id, cabin_id=0, visit_index=0),
                _candidate("candidate_b", checkpoint.id, cabin_id=0, visit_index=0),
            ),
            checkpoints=(checkpoint,),
        )


def test_all_pairs_headway_pair_builder_requires_inputs() -> None:
    builder = AllPairsHeadwayPairBuilder()

    with pytest.raises(ValueError, match="at least one candidate"):
        builder.build(
            candidates=(),
            checkpoints=(_checkpoint("exit_switch::sw_a", headway_seconds=3.5),),
        )

    with pytest.raises(ValueError, match="at least one checkpoint"):
        builder.build(
            candidates=(
                _candidate("candidate_a", "exit_switch::sw_a", cabin_id=0, visit_index=0),
            ),
            checkpoints=(),
        )


def _checkpoint(checkpoint_id: str, headway_seconds: float) -> HeadwayCheckpointDefinition:
    return HeadwayCheckpointDefinition(
        id=checkpoint_id,
        kind=HeadwayCheckpointKind.EXIT_SWITCH,
        switch_id="sw_a",
        station_id="A",
        headway_seconds=headway_seconds,
        applies_to_serve=True,
        applies_to_skip=True,
        waiting_modes=(StationWaitingMode.NO_WAITING,),
    )


def _candidate(
    candidate_id: str,
    checkpoint_id: str,
    cabin_id: int,
    visit_index: int,
) -> HeadwayCandidate:
    return HeadwayCandidate(
        id=candidate_id,
        checkpoint_id=checkpoint_id,
        cabin_id=cabin_id,
        visit_index=visit_index,
        time_reference=EanTimeReference.EXIT_SWITCH_TIME,
        activation_reference=EanActivationReference.ACTIVE,
    )
