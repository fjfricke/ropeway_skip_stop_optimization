from __future__ import annotations

from dataclasses import replace

import pytest

from ropeway_skip_stop_optimization.examples.registry import get_example
from ropeway_skip_stop_optimization.optimization.ean import (
    EanHeadwayOrderFamilyIndex,
    EanHeadwayPairScope,
    EanMovementFeasibilityProblem,
    EanOptimizationConfig,
    EanOptimizationName,
    EanOptimizer,
    EanSolveConfig,
    HeadwayCheckpointKind,
    validate_ean_movement_plan_against_artifact,
)
from ropeway_skip_stop_optimization.optimization.ean.optimizers.movement_model import (
    EanMovementModelBuilder,
)


@pytest.mark.parametrize(
    ("example_id", "pair_count", "family_count"),
    (
        (
            "five_station_circle_cw_half_skip_no_wait_v0",
            93_162,
            49_138,
        ),
        (
            "five_station_circle_cw_half_skip_wait_v0",
            139_743,
            49_138,
        ),
    ),
)
def test_five_circle_shared_order_family_counts(
    example_id: str,
    pair_count: int,
    family_count: int,
) -> None:
    artifact = _artifact(example_id)

    index = EanHeadwayOrderFamilyIndex.build(artifact)

    assert len(artifact.headway_pairs) == pair_count
    assert index.family_count == family_count
    assert index.family_count < pair_count


def test_skip_exit_starts_new_family_and_propagates_to_next_platform() -> None:
    artifact = _artifact("five_station_circle_cw_half_skip_no_wait_v0")
    index = EanHeadwayOrderFamilyIndex.build(artifact)
    checkpoints = {
        checkpoint.id: checkpoint for checkpoint in artifact.headway_checkpoints
    }
    candidates = {
        candidate.id: candidate for candidate in artifact.headway_candidates
    }
    visits = {
        (visit.cabin_id, visit.visit_index): visit
        for visit in artifact.switch_visits
    }
    exit_pair = next(
        pair
        for pair in artifact.headway_pairs
        if checkpoints[pair.checkpoint_id].kind
        is HeadwayCheckpointKind.EXIT_SWITCH
    )
    exit_events = _pair_events(exit_pair, candidates)
    entry_pair_same_station = _pair_for(
        artifact,
        checkpoint_kind=HeadwayCheckpointKind.PLATFORM_ENTRY,
        switch_id=checkpoints[exit_pair.checkpoint_id].switch_id,
        events=exit_events,
    )
    successor_events = tuple(
        (cabin_id, visit_index + 1) for cabin_id, visit_index in exit_events
    )
    successor_switch_ids = {visits[event].switch_id for event in successor_events}
    assert len(successor_switch_ids) == 1
    entry_pair_next_station = _pair_for(
        artifact,
        checkpoint_kind=HeadwayCheckpointKind.PLATFORM_ENTRY,
        switch_id=successor_switch_ids.pop(),
        events=successor_events,
    )

    exit_reference = index.reference_for_pair(exit_pair.id)
    assert (
        index.reference_for_pair(entry_pair_same_station.id).family_id
        != exit_reference.family_id
    )
    assert (
        index.reference_for_pair(entry_pair_next_station.id).family_id
        == exit_reference.family_id
    )


def test_waiting_platform_entry_and_exit_share_order_family() -> None:
    artifact = _artifact("five_station_circle_cw_half_skip_wait_v0")
    index = EanHeadwayOrderFamilyIndex.build(artifact)
    checkpoints = {
        checkpoint.id: checkpoint for checkpoint in artifact.headway_checkpoints
    }
    candidates = {
        candidate.id: candidate for candidate in artifact.headway_candidates
    }
    entry_pair = next(
        pair
        for pair in artifact.headway_pairs
        if checkpoints[pair.checkpoint_id].kind
        is HeadwayCheckpointKind.PLATFORM_ENTRY
    )
    checkpoint = checkpoints[entry_pair.checkpoint_id]
    exit_pair = _pair_for(
        artifact,
        checkpoint_kind=HeadwayCheckpointKind.PLATFORM_EXIT,
        switch_id=checkpoint.switch_id,
        events=_pair_events(entry_pair, candidates),
    )

    assert (
        index.reference_for_pair(entry_pair.id).family_id
        == index.reference_for_pair(exit_pair.id).family_id
    )


def test_family_index_tracks_reversed_pair_orientation() -> None:
    artifact = _artifact("five_station_circle_cw_half_skip_no_wait_v0")
    checkpoints = {
        checkpoint.id: checkpoint for checkpoint in artifact.headway_checkpoints
    }
    candidates = {
        candidate.id: candidate for candidate in artifact.headway_candidates
    }
    exit_pair = next(
        pair
        for pair in artifact.headway_pairs
        if checkpoints[pair.checkpoint_id].kind
        is HeadwayCheckpointKind.EXIT_SWITCH
    )
    exit_events = _pair_events(exit_pair, candidates)
    visits = {
        (visit.cabin_id, visit.visit_index): visit
        for visit in artifact.switch_visits
    }
    successor_events = tuple(
        (cabin_id, visit_index + 1) for cabin_id, visit_index in exit_events
    )
    successor_switch_id = visits[successor_events[0]].switch_id
    target = _pair_for(
        artifact,
        checkpoint_kind=HeadwayCheckpointKind.PLATFORM_ENTRY,
        switch_id=successor_switch_id,
        events=successor_events,
    )
    reversed_target = replace(
        target,
        first_candidate_id=target.second_candidate_id,
        second_candidate_id=target.first_candidate_id,
    )
    modified = replace(
        artifact,
        headway_pairs=tuple(
            reversed_target if pair.id == target.id else pair
            for pair in artifact.headway_pairs
        ),
    )

    index = EanHeadwayOrderFamilyIndex.build(modified)
    source_reference = index.reference_for_pair(exit_pair.id)
    target_reference = index.reference_for_pair(target.id)

    assert source_reference.family_id == target_reference.family_id
    assert (
        source_reference.pair_forward_is_family_forward
        is not target_reference.pair_forward_is_family_forward
    )


def test_family_index_rejects_sparse_pair_artifacts() -> None:
    artifact = replace(
        _artifact("three_station_v0"),
        headway_pairs=(),
        headway_pair_scope=EanHeadwayPairScope.SPARSE,
    )

    with pytest.raises(NotImplementedError, match="complete eager"):
        EanHeadwayOrderFamilyIndex.build(artifact)


def test_shared_eager_reuses_variables_without_removing_pair_rows() -> None:
    gp = pytest.importorskip("gurobipy")
    artifact = _artifact("three_station_v0")
    legacy_model = gp.Model("shared_order_legacy")
    legacy_model.Params.OutputFlag = 0
    shared_model = gp.Model("shared_order_enabled")
    shared_model.Params.OutputFlag = 0
    legacy = EanMovementModelBuilder().build(
        model=legacy_model,
        binary_vtype=gp.GRB.BINARY,
        artifact=artifact,
        optimization_config=EanOptimizationConfig.none(),
    )
    shared = EanMovementModelBuilder().build(
        model=shared_model,
        binary_vtype=gp.GRB.BINARY,
        artifact=artifact,
        optimization_config=EanOptimizationConfig.from_enabled_names(
            [EanOptimizationName.SHARED_MERGE_HEADWAY_ORDER]
        ),
    )

    assert shared.constraint_count == legacy.constraint_count
    assert shared.nonzero_count == legacy.nonzero_count
    assert len(shared.variables.headway_order) < len(
        legacy.variables.headway_order
    )
    assert (
        shared.build_metrics.headway_order_variable_savings
        == len(legacy.variables.headway_order)
        - len(shared.variables.headway_order)
    )
    assert shared.build_metrics.shared_headway_pair_count > 0


def test_shared_eager_and_current_eager_have_equivalent_feasible_models() -> None:
    pytest.importorskip("gurobipy")
    artifact = _artifact("three_station_v0")
    legacy = EanOptimizer(
        EanSolveConfig(
            log_to_console=False,
            optimization_config=EanOptimizationConfig.none(),
        )
    ).solve(EanMovementFeasibilityProblem(artifact))
    shared = EanOptimizer(
        EanSolveConfig(
            log_to_console=False,
            optimization_config=EanOptimizationConfig.from_enabled_names(
                [EanOptimizationName.SHARED_MERGE_HEADWAY_ORDER]
            ),
        )
    ).solve(EanMovementFeasibilityProblem(artifact))

    assert legacy.metadata.status == shared.metadata.status == "optimal"
    assert legacy.movement_plan is not None
    assert shared.movement_plan is not None
    validate_ean_movement_plan_against_artifact(
        artifact, legacy.movement_plan
    ).raise_for_errors()
    validate_ean_movement_plan_against_artifact(
        artifact, shared.movement_plan
    ).raise_for_errors()
    assert (
        shared.metadata.headway_order_variable_count
        < legacy.metadata.headway_order_variable_count
    )


def _artifact(example_id: str):
    example = get_example(example_id)
    scenario = example.build_scenario()
    config = example.build_ean_config(scenario)
    return example.build_ean_artifact_builder(scenario, config).build(
        scenario,
        config,
    )


def _pair_events(pair, candidate_by_id) -> tuple[tuple[int, int], tuple[int, int]]:
    first = candidate_by_id[pair.first_candidate_id]
    second = candidate_by_id[pair.second_candidate_id]
    return (
        (first.cabin_id, first.visit_index),
        (second.cabin_id, second.visit_index),
    )


def _pair_for(
    artifact,
    *,
    checkpoint_kind: HeadwayCheckpointKind,
    switch_id: str,
    events: tuple[tuple[int, int], tuple[int, int]],
):
    checkpoint = next(
        item
        for item in artifact.headway_checkpoints
        if item.kind is checkpoint_kind and item.switch_id == switch_id
    )
    candidates = {
        candidate.id: candidate for candidate in artifact.headway_candidates
    }
    expected = set(events)
    return next(
        pair
        for pair in artifact.headway_pairs
        if pair.checkpoint_id == checkpoint.id
        and set(_pair_events(pair, candidates)) == expected
    )
