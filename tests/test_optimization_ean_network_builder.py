from __future__ import annotations

from dataclasses import replace

import pytest

from ropeway_skip_stop_optimization.examples.registry import EXAMPLES, get_example
from ropeway_skip_stop_optimization.models import StationRoute
from ropeway_skip_stop_optimization.optimization.ean import (
    EanCirculationPatternDefinition,
    EanResourceKind,
    EanResourceConflictIndex,
    EanMovementFeasibilityProblem,
    EanOptimizer,
    EanSolveConfig,
    NetworkEanBuildArtifactBuilder,
    PhysicalMovementNetworkBuilder,
    validate_ean_movement_plan_against_artifact,
)


@pytest.mark.parametrize(
    "example_id",
    (
        "three_station_v0",
        "three_station_full_no_skip_no_wait_v0",
        "three_station_optimized_initial_placement_v0",
        "five_station_circle_cw_half_skip_wait_v0",
    ),
)
def test_network_builder_produces_self_consistent_artifact(example_id: str) -> None:
    example = get_example(example_id)
    scenario = example.build_scenario()
    config = example.build_ean_config(scenario)
    network_builder = example.build_ean_artifact_builder(scenario, config)
    assert isinstance(network_builder, NetworkEanBuildArtifactBuilder)
    network = network_builder.build(scenario, config)

    state_ids = network_builder.pattern_definition.state_node_ids
    assert network.state_ids == state_ids
    assert tuple(timing.switch_id for timing in network.timings) == state_ids
    assert network.movement_network is not None
    assert network.circulation_pattern_ids == (
        network_builder.pattern_definition.id,
    )
    assert network.resource_conflict_index is not None
    assert tuple(
        resource_id
        for resource_id, _ in network.resource_conflict_index.candidate_ids_by_resource_id
    ) == tuple(checkpoint.id for checkpoint in network.headway_checkpoints)
    assert (
        network.resource_conflict_index.complete_headway_pair_count
        == len(network.headway_pairs)
    )


def test_physical_network_builder_preserves_shared_physical_resource_id() -> None:
    example = get_example("three_station_v0")
    scenario = example.build_scenario()
    config = example.build_ean_config(scenario)
    network_builder = example.build_ean_artifact_builder(scenario, config)
    assert isinstance(network_builder, NetworkEanBuildArtifactBuilder)
    first_segment = scenario.track_segments[0]
    second_segment = scenario.track_segments[1]
    shared_resource_id = "shared_test_resource"
    scenario = replace(
        scenario,
        track_segments=tuple(
            replace(segment, resource_id=shared_resource_id)
            if segment.id in {first_segment.id, second_segment.id}
            else segment
            for segment in scenario.track_segments
        ),
    )

    network = PhysicalMovementNetworkBuilder().build(
        scenario,
        EanCirculationPatternDefinition(
            id="test_pattern",
            state_node_ids=network_builder.pattern_definition.state_node_ids,
        ),
    )

    physical_resources = tuple(
        resource
        for resource in network.resources
        if resource.kind is EanResourceKind.PHYSICAL
    )
    assert tuple(resource.physical_resource_id for resource in physical_resources).count(
        shared_resource_id
    ) == 1
    resources = network.resources
    shared = next(
        resource for resource in resources if resource.physical_resource_id == shared_resource_id
    )
    options_using_shared = tuple(
        option.id
        for option in network.route_options
        if shared.id in {usage.resource_id for usage in option.resource_usages}
    )
    assert options_using_shared
    artifact = network_builder.build(scenario, config)
    indexed = dict(
        EanResourceConflictIndex.build(
            network,
            artifact.headway_checkpoints,
            artifact.headway_candidates,
        ).route_option_ids_by_resource_id
    )
    assert indexed[shared.id] == options_using_shared


def test_physical_network_builder_rejects_dynamic_route_choice_clearly() -> None:
    example = get_example("three_station_v0")
    scenario = example.build_scenario()
    config = example.build_ean_config(scenario)
    network_builder = example.build_ean_artifact_builder(scenario, config)
    assert isinstance(network_builder, NetworkEanBuildArtifactBuilder)
    segments_by_id = {segment.id: segment for segment in scenario.track_segments}
    existing = next(
        route
        for route in scenario.station_routes
        if segments_by_id[route.segment_ids[0]].from_node_id
        == network_builder.pattern_definition.state_node_ids[0]
        and route.kind.value == "service"
    )
    additional_route = StationRoute(
        id=f"{existing.id}_alternative",
        station_id=existing.station_id,
        kind=existing.kind,
        segment_ids=existing.segment_ids,
        allows_boarding=existing.allows_boarding,
        allows_alighting=existing.allows_alighting,
    )
    scenario = replace(
        scenario,
        station_routes=scenario.station_routes + (additional_route,),
    )

    with pytest.raises(ValueError, match="dynamic routing not yet supported"):
        PhysicalMovementNetworkBuilder().build(
            scenario,
            EanCirculationPatternDefinition(
                id="test_pattern",
                state_node_ids=network_builder.pattern_definition.state_node_ids,
            ),
        )


def test_repeated_network_builds_have_identical_movement_model_dimensions() -> None:
    pytest.importorskip("gurobipy")
    example = get_example("three_station_v0")
    scenario = example.build_scenario()
    config = example.build_ean_config(scenario)
    network_builder = example.build_ean_artifact_builder(scenario, config)
    assert isinstance(network_builder, NetworkEanBuildArtifactBuilder)
    first_artifact = network_builder.build(scenario, config)
    network_artifact = network_builder.build(scenario, config)

    optimizer = EanOptimizer(EanSolveConfig(build_only=True))
    first = optimizer.solve(EanMovementFeasibilityProblem(first_artifact))
    network = optimizer.solve(EanMovementFeasibilityProblem(network_artifact))

    assert (
        network.metadata.variable_count,
        network.metadata.constraint_count,
        network.metadata.model_nonzero_count,
    ) == (
        first.metadata.variable_count,
        first.metadata.constraint_count,
        first.metadata.model_nonzero_count,
    )


@pytest.mark.parametrize("example_id", tuple(EXAMPLES))
def test_all_registered_ean_examples_have_a_deterministic_network_pattern(
    example_id: str,
) -> None:
    example = get_example(example_id)
    scenario = example.build_scenario()
    config = example.build_ean_config(scenario)
    builder = example.build_ean_artifact_builder(scenario, config)
    assert isinstance(builder, NetworkEanBuildArtifactBuilder)

    network = builder.network_builder.build(scenario, builder.pattern_definition)
    pattern = network.pattern(builder.pattern_definition.id)
    timings = builder.timing_builder.build(scenario, network, pattern)

    state_ids = builder.pattern_definition.state_node_ids
    assert pattern.state_ids == state_ids
    assert tuple(timing.switch_id for timing in timings) == state_ids

    discovered = builder.network_builder.discover_pattern_definitions(scenario)
    assert len(discovered) == 1
    assert set(discovered[0].state_node_ids) == set(state_ids)
    assert discovered == builder.network_builder.discover_pattern_definitions(scenario)


def test_repeated_network_builds_have_identical_solver_classification() -> None:
    pytest.importorskip("gurobipy")
    example = get_example("three_station_half_no_skip_no_wait_v0")
    scenario = example.build_scenario()
    config = example.build_ean_config(scenario)
    network_builder = example.build_ean_artifact_builder(scenario, config)
    assert isinstance(network_builder, NetworkEanBuildArtifactBuilder)
    artifacts = (
        network_builder.build(scenario, config),
        network_builder.build(scenario, config),
    )

    results = tuple(
        EanOptimizer(EanSolveConfig()).solve(EanMovementFeasibilityProblem(artifact))
        for artifact in artifacts
    )

    assert results[0].metadata.status == results[1].metadata.status == "optimal"
    for artifact, result in zip(artifacts, results, strict=True):
        assert result.movement_plan is not None
        validate_ean_movement_plan_against_artifact(
            artifact, result.movement_plan
        ).raise_for_errors()


def test_network_analysis_finds_minimum_return_cycles_and_corridors() -> None:
    example = get_example("three_station_v0")
    scenario = example.build_scenario()
    config = example.build_ean_config(scenario)
    builder = example.build_ean_artifact_builder(scenario, config)
    assert isinstance(builder, NetworkEanBuildArtifactBuilder)
    network = builder.network_builder.build(scenario, builder.pattern_definition)
    pattern = network.pattern(builder.pattern_definition.id)
    options_by_id = {option.id: option for option in network.route_options}
    expected_minimum_cycle_seconds = sum(
        min(options_by_id[option_id].minimum_seconds for option_id in option_ids)
        for option_ids in pattern.route_option_ids_by_position
    )

    assert network.deterministic_corridors() == (pattern.state_ids,)
    assert network.minimum_return_seconds_by_state() == pytest.approx(
        dict.fromkeys(pattern.state_ids, expected_minimum_cycle_seconds)
    )


def test_network_builder_can_use_a_discovered_pattern_without_legacy_order() -> None:
    example = get_example("three_station_v0")
    scenario = example.build_scenario()
    config = example.build_ean_config(scenario)
    physical_builder = PhysicalMovementNetworkBuilder()
    pattern_definition, = physical_builder.discover_pattern_definitions(scenario)

    artifact = NetworkEanBuildArtifactBuilder(
        pattern_definition=pattern_definition,
        network_builder=physical_builder,
    ).build(scenario, config)

    artifact.validate()
    assert artifact.circulation_state_ids == pattern_definition.state_node_ids
    assert artifact.circulation_pattern_ids == (pattern_definition.id,)
