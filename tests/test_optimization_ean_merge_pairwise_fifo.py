from __future__ import annotations

from dataclasses import replace

import gurobipy as gp
import pytest
from gurobipy import GRB

from ropeway_skip_stop_optimization.examples.registry import get_example
from ropeway_skip_stop_optimization.optimization.ean import (
    EanFormulationConfig,
    EanHeadwayOrderFormulation,
    EanMovementFeasibilityProblem,
    EanOptimizationConfig,
    EanOptimizer,
    EanPairwiseFifoConstraintBuilder,
    EanSolveConfig,
    HeadwayCheckpointKind,
    validate_ean_movement_plan_against_artifact,
)
from ropeway_skip_stop_optimization.optimization.ean.optimizers.movement_model import (
    EanMovementModelBuilder,
)


class _FixedOrderPool:
    def __init__(self, order):
        self.order = order

    def pair_order_expression(self, pair_id: str):
        del pair_id
        return self.order


def _artifact(example_id: str = "three_station_v0"):
    example = get_example(example_id)
    scenario = example.build_scenario()
    config = example.build_ean_config(scenario)
    return example.build_ean_artifact_builder(scenario, config).build(
        scenario,
        config,
    )


def _one_exit_pair_artifact():
    artifact = _artifact("five_station_circle_cw_half_skip_wait_v0")
    checkpoint_by_id = {
        checkpoint.id: checkpoint for checkpoint in artifact.headway_checkpoints
    }
    pair = next(
        pair
        for pair in artifact.headway_pairs
        if checkpoint_by_id[pair.checkpoint_id].kind
        is HeadwayCheckpointKind.EXIT_SWITCH
    )
    return replace(artifact, headway_pairs=(pair,)), pair


@pytest.mark.parametrize(
    ("first_stop", "second_stop", "expected_status"),
    (
        (1, 1, GRB.INFEASIBLE),
        (0, 0, GRB.INFEASIBLE),
        (1, 0, GRB.OPTIMAL),
        (0, 1, GRB.OPTIMAL),
    ),
)
def test_fifo_forbids_same_branch_reorder_but_keeps_cross_branch_merge(
    first_stop: int,
    second_stop: int,
    expected_status: int,
) -> None:
    artifact, pair = _one_exit_pair_artifact()
    candidate_by_id = {
        candidate.id: candidate for candidate in artifact.headway_candidates
    }
    first = candidate_by_id[pair.first_candidate_id]
    second = candidate_by_id[pair.second_candidate_id]
    first_key = (first.cabin_id, first.visit_index)
    second_key = (second.cabin_id, second.visit_index)
    model = gp.Model("fifo_pair_unit")
    model.Params.OutputFlag = 0
    first_time = model.addVar(lb=0.0, ub=100.0)
    second_time = model.addVar(lb=0.0, ub=100.0)
    order = model.addVar(vtype=GRB.BINARY)
    first_route = model.addVar(vtype=GRB.BINARY)
    second_route = model.addVar(vtype=GRB.BINARY)
    first_active = model.addVar(vtype=GRB.BINARY)
    second_active = model.addVar(vtype=GRB.BINARY)
    model.addConstr(first_time == 10.0)
    model.addConstr(second_time == 20.0)
    model.addConstr(order == 0.0)  # second before first at the output
    model.addConstr(first_route == first_stop)
    model.addConstr(second_route == second_stop)
    model.addConstr(first_active == 1.0)
    model.addConstr(second_active == 1.0)

    metrics = EanPairwiseFifoConstraintBuilder().build(
        model=model,
        artifact=artifact,
        headway_pool=_FixedOrderPool(order),
        switch_time={first_key: first_time, second_key: second_time},
        stop={first_key: first_route, second_key: second_route},
        route_active={first_key: first_active, second_key: second_active},
        big_m=1_000.0,
    )
    model.optimize()

    assert model.Status == expected_status
    assert metrics.constrained_pair_count == 1
    assert metrics.service_fifo_row_count == 2
    assert metrics.skip_fifo_row_count == 2


def test_integrated_pairwise_fifo_builds_and_validates() -> None:
    artifact = _artifact()
    optimization = EanOptimizationConfig(
        formulation=EanFormulationConfig(
            headway_order=EanHeadwayOrderFormulation.PAIRWISE_FIFO
        )
    )

    result = EanOptimizer(
        EanSolveConfig(optimization_config=optimization)
    ).solve(
        EanMovementFeasibilityProblem(artifact=artifact)
    )

    assert result.metadata.status == "optimal"
    assert result.movement_plan is not None
    validate_ean_movement_plan_against_artifact(
        artifact,
        result.movement_plan,
    ).raise_for_errors()
    assert (
        result.metadata.build_metrics.fifo_constrained_headway_pair_count
        > 0
    )


def test_legacy_waiting_occupancy_already_rejects_service_reorder() -> None:
    artifact = _artifact("three_station_v0")
    candidate_by_id = {
        candidate.id: candidate for candidate in artifact.headway_candidates
    }
    checkpoint_by_id = {
        checkpoint.id: checkpoint for checkpoint in artifact.headway_checkpoints
    }
    first_key = (0, 0)
    second_key = (28, 0)
    pair = next(
        pair
        for pair in artifact.headway_pairs
        if checkpoint_by_id[pair.checkpoint_id].kind
        is HeadwayCheckpointKind.EXIT_SWITCH
        and {
            (
                candidate_by_id[candidate_id].cabin_id,
                candidate_by_id[candidate_id].visit_index,
            )
            for candidate_id in (
                pair.first_candidate_id,
                pair.second_candidate_id,
            )
        }
        == {first_key, second_key}
    )
    model = gp.Model("legacy_same_branch_reorder_audit")
    model.Params.OutputFlag = 0
    movement = EanMovementModelBuilder().build(
        model=model,
        binary_vtype=GRB.BINARY,
        artifact=artifact,
        optimization_config=EanOptimizationConfig.none(),
    )
    model.addConstr(movement.variables.stop[first_key] == 1)
    model.addConstr(movement.variables.stop[second_key] == 1)
    model.addConstr(
        movement.variables.switch_time[first_key] + 1.0
        <= movement.variables.switch_time[second_key]
    )
    model.addConstr(
        movement.variables.exit_switch_time[second_key] + pair.headway_seconds
        <= movement.variables.exit_switch_time[first_key]
    )

    model.optimize()

    assert model.Status == GRB.INFEASIBLE
