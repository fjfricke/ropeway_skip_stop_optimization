from __future__ import annotations

import pytest

from ropeway_skip_stop_optimization.examples.registry import get_example
from ropeway_skip_stop_optimization.optimization.ean import (
    EanDirectMergeHeadwayRelaxationIndex,
    EanMovementFeasibilityProblem,
    EanOptimizationConfig,
    EanOptimizer,
    EanSolveConfig,
)
from ropeway_skip_stop_optimization.optimization.ean.optimizers.movement_model import (
    EanMovementModelBuilder,
)


def test_direct_merge_relaxation_finds_only_skip_reconvergence_exits() -> None:
    wait_artifact = _artifact(
        "five_station_circle_cw_half_skip_wait_v0"
    )
    no_skip_artifact = _artifact(
        "five_station_circle_cw_half_no_skip_no_wait_v0"
    )

    wait_index = EanDirectMergeHeadwayRelaxationIndex.build(wait_artifact)
    no_skip_index = EanDirectMergeHeadwayRelaxationIndex.build(
        no_skip_artifact
    )

    assert len(wait_index.checkpoint_ids) == 5
    assert len(wait_index.pair_ids) == 46_581
    assert not no_skip_index.checkpoint_ids
    assert not no_skip_index.pair_ids


def test_diagnostic_model_omits_only_indexed_pairs() -> None:
    gp = pytest.importorskip("gurobipy")
    artifact = _artifact("three_station_v0")
    index = EanDirectMergeHeadwayRelaxationIndex.build(artifact)
    eager_model = gp.Model("merge_relaxation_eager")
    eager_model.Params.OutputFlag = 0
    relaxed_model = gp.Model("merge_relaxation_diagnostic")
    relaxed_model.Params.OutputFlag = 0
    eager = EanMovementModelBuilder().build(
        model=eager_model,
        binary_vtype=gp.GRB.BINARY,
        artifact=artifact,
        optimization_config=EanOptimizationConfig.none(),
    )
    relaxed = EanMovementModelBuilder().build(
        model=relaxed_model,
        binary_vtype=gp.GRB.BINARY,
        artifact=artifact,
        optimization_config=EanOptimizationConfig.from_selection(
            "diagnostic_relax_merge_headways"
        ),
    )

    assert (
        relaxed.headway_constraint_pool.diagnostically_omitted_pair_ids
        == index.pair_ids
    )
    assert relaxed.variable_count == eager.variable_count - len(index.pair_ids)
    assert relaxed.constraint_count == (
        eager.constraint_count - 2 * len(index.pair_ids)
    )
    assert (
        relaxed.build_metrics.diagnostically_omitted_headway_pair_count
        == len(index.pair_ids)
    )
    assert (
        relaxed.build_metrics.diagnostically_omitted_headway_checkpoint_count
        == len(index.checkpoint_ids)
    )


def test_diagnostic_solve_reports_complete_full_separation() -> None:
    pytest.importorskip("gurobipy")
    artifact = _artifact("three_station_v0")

    result = EanOptimizer(
        EanSolveConfig(
            log_to_console=False,
            optimization_config=EanOptimizationConfig.from_selection(
                "diagnostic_relax_merge_headways"
            ),
        )
    ).solve(EanMovementFeasibilityProblem(artifact))

    assert result.metadata.status == "optimal"
    assert result.metadata.diagnostic_headway_separation_complete
    assert result.metadata.diagnostic_headway_feasible
    assert result.metadata.diagnostic_headway_violation_count == 0
    assert (
        result.metadata.diagnostically_omitted_headway_pair_count
        == 11_664
    )


def _artifact(example_id: str):
    example = get_example(example_id)
    scenario = example.build_scenario()
    config = example.build_ean_config(scenario)
    return example.build_ean_artifact_builder(scenario, config).build(
        scenario,
        config,
    )
