from __future__ import annotations

from dataclasses import replace

import pytest

from ropeway_skip_stop_optimization.examples.registry import get_example
from ropeway_skip_stop_optimization.optimization.ean import (
    EanMergeHorizonRole,
    EanMergeSequenceDomainBuilder,
    HeadwayCheckpointKind,
)


def _artifact(example_id: str):
    example = get_example(example_id)
    scenario = example.build_scenario()
    config = example.build_ean_config(scenario)
    return example.build_ean_artifact_builder(scenario, config).build(
        scenario,
        config,
    )


def test_merge_domain_finds_direct_reconvergences_deterministically() -> None:
    artifact = _artifact("five_station_circle_cw_half_skip_no_wait_v0")
    builder = EanMergeSequenceDomainBuilder()

    first = builder.build(artifact)
    second = builder.build(
        replace(
            artifact,
            switch_visits=tuple(reversed(artifact.switch_visits)),
            headway_candidates=tuple(reversed(artifact.headway_candidates)),
        )
    )

    assert len(first.families) == 5
    assert first == second
    assert first.fingerprint == second.fingerprint
    assert not first.eager_fallback_candidate_ids
    assert all(family.proof.complete for family in first.families)
    assert all(len(family.sequence_block_ids) == 1 for family in first.families)


def test_no_skip_exit_candidates_remain_explicit_fallback() -> None:
    artifact = _artifact("three_station_v0")
    domain = EanMergeSequenceDomainBuilder().build(artifact)
    checkpoint_by_id = {
        checkpoint.id: checkpoint for checkpoint in artifact.headway_checkpoints
    }

    assert len(domain.families) == 2
    assert domain.eager_fallback_candidate_ids
    fallback_switch_ids = {
        checkpoint_by_id[candidate.checkpoint_id].switch_id
        for candidate in artifact.headway_candidates
        if candidate.id in domain.eager_fallback_candidate_ids
    }
    merge_state_ids = {family.state_id for family in domain.families}
    assert fallback_switch_ids.isdisjoint(merge_state_ids)
    assert all(
        checkpoint_by_id[candidate.checkpoint_id].kind
        is HeadwayCheckpointKind.EXIT_SWITCH
        for candidate in artifact.headway_candidates
        if candidate.id in domain.eager_fallback_candidate_ids
    )


def test_merge_domain_marks_finite_horizon_boundaries_explicitly() -> None:
    artifact = _artifact("five_station_circle_cw_half_skip_no_wait_v0")
    domain = EanMergeSequenceDomainBuilder().build(artifact)
    roles = {
        role
        for block in domain.sequence_blocks
        for _, role in block.horizon_role_by_candidate_id
    }

    assert EanMergeHorizonRole.INITIAL_BOUNDARY in roles
    assert EanMergeHorizonRole.TERMINAL_BOUNDARY in roles
    assert EanMergeHorizonRole.INTERIOR in roles
    for block in domain.sequence_blocks:
        predecessors = dict(block.predecessor_by_candidate_id)
        successors = dict(block.successor_by_candidate_id)
        for candidate_id, role in block.horizon_role_by_candidate_id:
            assert (candidate_id not in predecessors) == (
                role
                in {
                    EanMergeHorizonRole.INITIAL_BOUNDARY,
                    EanMergeHorizonRole.INITIAL_AND_TERMINAL_BOUNDARY,
                }
            )
            assert (candidate_id not in successors) == (
                role
                in {
                    EanMergeHorizonRole.TERMINAL_BOUNDARY,
                    EanMergeHorizonRole.INITIAL_AND_TERMINAL_BOUNDARY,
                }
            )


def test_merge_domain_rejects_ambiguous_candidate_mapping() -> None:
    artifact = _artifact("three_station_v0")
    duplicate = artifact.headway_candidates[0]

    with pytest.raises(ValueError, match="duplicate candidate visit/checkpoint"):
        EanMergeSequenceDomainBuilder().build(
            replace(
                artifact,
                headway_candidates=artifact.headway_candidates + (duplicate,),
            )
        )


def test_merge_domain_requires_one_pattern() -> None:
    artifact = _artifact("three_station_v0")

    with pytest.raises(NotImplementedError, match="one canonical"):
        EanMergeSequenceDomainBuilder().build(
            replace(artifact, circulation_pattern_ids=())
        )
