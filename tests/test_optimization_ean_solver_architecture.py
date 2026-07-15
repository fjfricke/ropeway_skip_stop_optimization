from __future__ import annotations

import pytest

from ropeway_skip_stop_optimization.examples.three_station import ThreeStationExample
from ropeway_skip_stop_optimization.optimization.ean import (
    EanOptimizationConfig,
    EanPassengerObjective,
)
from ropeway_skip_stop_optimization.optimization.ean.optimizers.movement_model import (
    EanMovementModel,
    EanMovementModelBuilder,
)
from ropeway_skip_stop_optimization.optimization.ean.optimizers.passenger_model import (
    EanPassengerModelBuilder,
)


def test_passenger_model_composes_the_canonical_movement_layer() -> None:
    gp = pytest.importorskip("gurobipy")
    from gurobipy import GRB

    example = ThreeStationExample()
    scenario = example.build_scenario()
    ean_config = example.build_ean_config(scenario)
    artifact = example.build_ean_artifact_builder(scenario, ean_config).build(
        scenario,
        ean_config,
    )
    optimization_config = EanOptimizationConfig().resolved_for_passenger_objective(
        EanPassengerObjective.JOURNEY_TIME
    )

    movement_only_gurobi = gp.Model("movement_only_test")
    movement_only_gurobi.Params.OutputFlag = 0
    movement_only = EanMovementModelBuilder().build(
        model=movement_only_gurobi,
        binary_vtype=GRB.BINARY,
        artifact=artifact,
        optimization_config=optimization_config,
    )

    passenger_gurobi = gp.Model("passenger_composition_test")
    passenger_gurobi.Params.OutputFlag = 0
    movement_with_passengers = EanMovementModelBuilder().build(
        model=passenger_gurobi,
        binary_vtype=GRB.BINARY,
        artifact=artifact,
        optimization_config=optimization_config,
    )
    passenger_model = EanPassengerModelBuilder().build(
        scenario=scenario,
        movement_model=movement_with_passengers,
        objective=EanPassengerObjective.JOURNEY_TIME,
        optimization_config=optimization_config,
        gp=gp,
        grb=GRB,
    )

    assert passenger_model.movement is movement_with_passengers
    assert movement_only.variable_count == movement_with_passengers.variable_count
    assert movement_only.constraint_count == movement_with_passengers.constraint_count
    assert movement_only.nonzero_count == movement_with_passengers.nonzero_count
    assert _movement_variable_names(movement_only) == _movement_variable_names(
        movement_with_passengers
    )
    assert _constraint_names(movement_only_gurobi) <= _constraint_names(passenger_gurobi)
    assert passenger_gurobi.NumVars > movement_with_passengers.variable_count
    assert passenger_gurobi.NumConstrs > movement_with_passengers.constraint_count


def _movement_variable_names(movement_model: EanMovementModel) -> set[str]:
    return {
        variable.VarName
        for variable in movement_model.model.getVars()[
            : movement_model.variable_count
        ]
    }


def _constraint_names(model: object) -> set[str]:
    return {constraint.ConstrName for constraint in model.getConstrs()}
