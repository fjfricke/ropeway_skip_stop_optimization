from __future__ import annotations

from ropeway_skip_stop_optimization.benchmarking.ddd_cases import (
    build_three_station_network_combined_probe,
    build_three_station_two_cabin_merge_artifact,
)
from ropeway_skip_stop_optimization.benchmarking.ddd_scaling import (
    build_ddd_scaling_case,
    count_ddd_raw_trajectory_supports,
    evaluate_g9_structural_gate,
)
from ropeway_skip_stop_optimization.optimization.ddd import (
    DddAnonymousFlowMaster,
    DddLayeredTimeNetworkBuilder,
    DddSupportConflictCut,
    DddSupportLiteral,
    EanArtifactToDddMovementProblemAdapter,
    estimate_ddd_prefix_formulation_size,
)


def test_raw_support_count_matches_two_cabin_reference_universe() -> None:
    movement = EanArtifactToDddMovementProblemAdapter().build(
        build_three_station_two_cabin_merge_artifact()
    )

    result = count_ddd_raw_trajectory_supports(movement)

    assert result.per_cabin_counts == (2, 2)
    assert result.trajectory_column_count == 4
    assert result.cartesian_support_count == 4


def test_prefix_size_estimate_matches_built_formulation() -> None:
    problem = build_three_station_network_combined_probe()
    network = DddLayeredTimeNetworkBuilder().build(problem)
    option_by_visit = {
        visit_index: next(
            arc.partial_arc.route_option_id
            for arc in network.arcs
            if arc.partial_arc is not None
            and arc.partial_arc.visit_index == visit_index
        )
        for visit_index in (0, 1)
    }
    cut = DddSupportConflictCut(
        id="scaling_test_cut",
        literals=tuple(
            DddSupportLiteral(cabin_id, visit_index, option_by_visit[visit_index])
            for cabin_id in (0, 1)
            for visit_index in (0, 1)
        ),
        resource_id="scaling_test_resource",
        violation_seconds=1.0,
    )

    result = estimate_ddd_prefix_formulation_size(
        network,
        max_visit_index_by_cabin={0: 1, 1: 1},
    )
    built = DddAnonymousFlowMaster().solve(network, cuts=(cut,))

    assert result.tracked_prefix_cabin_count == 2
    assert result.prefix_variable_count == built.prefix_variable_count == 8
    assert result.movement_prefix_variable_count == 6
    assert result.sink_prefix_variable_count == 2


def test_visit_zero_conflicts_need_no_redundant_prefix_variables() -> None:
    problem = build_three_station_network_combined_probe()
    network = DddLayeredTimeNetworkBuilder().build(problem)

    result = estimate_ddd_prefix_formulation_size(
        network,
        max_visit_index_by_cabin={0: 0, 1: 0},
    )
    first_option_id = next(
        arc.partial_arc.route_option_id
        for arc in network.arcs
        if arc.partial_arc is not None and arc.partial_arc.visit_index == 0
    )
    cut = DddSupportConflictCut(
        id="visit_zero_only",
        literals=tuple(
            DddSupportLiteral(cabin_id, 0, first_option_id)
            for cabin_id in (0, 1)
        ),
        resource_id="visit_zero_resource",
        violation_seconds=1.0,
    )
    built = DddAnonymousFlowMaster().solve(network, cuts=(cut,))

    assert result.tracked_prefix_cabin_count == 0
    assert result.prefix_variable_count == built.prefix_variable_count == 0
    assert result.prefix_conservation_row_count == 0
    assert result.prefix_link_row_count == 0


def test_scaling_case_builds_measured_ddd_and_eager_references() -> None:
    result = build_ddd_scaling_case(
        "three_station_half_no_skip_no_wait_v0"
    )

    assert result["cabin_count"] == 15
    assert result["raw_cartesian_support_count"] == "1"
    assert result["ddd_anonymous_variable_count"] > 0
    assert result["ddd_local_prefix"]["tracked_prefix_cabin_count"] == 2
    assert (
        result["ddd_local_prefix"]["prefix_variable_count"]
        < result["ddd_full_prefix"]["prefix_variable_count"]
    )
    assert result["eager_ean"]["headway_pair_count"] > 0
    assert result["eager_ean"]["variable_count"] > 0


def test_structural_gate_requires_scale_and_nontrivial_supports() -> None:
    cases = [
        {
            "cabin_count": cabin_count,
            "raw_cartesian_support_log10": support_log,
            "ddd_anonymous_variable_count": 100,
            "ddd_local_prefix": {"prefix_variable_count": 10},
            "ddd_full_prefix": {"prefix_variable_count": 1000},
            "eager_ean": {"variable_count": 500},
        }
        for cabin_count, support_log in ((15, 0.0), (19, 20.0), (30, 0.0))
    ]

    result = evaluate_g9_structural_gate(cases)

    assert result["status"] == "achieved"
    assert result["claim_scope"] == "structural_model_size_only"
