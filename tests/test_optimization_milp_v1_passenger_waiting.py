from __future__ import annotations

import pytest

from ropeway_skip_stop_optimization.models import (
    DiscreteArc,
    DiscreteArcKind,
    DiscreteDemand,
    DiscreteNode,
    DiscreteScenario,
)
from ropeway_skip_stop_optimization.optimization.discrete_time import (
    FixedCabinStart,
    MilpV1PassengerWaitingObjective,
    MilpV1PassengerWaitingConfig,
    solve_milp_v1_passenger_waiting,
    solve_milp_v1_passenger_waiting_feasibility,
)


def test_milp_v1_passenger_waiting_feasibility_solves_reachable_tiny_model() -> None:
    pytest.importorskip("gurobipy")
    discrete = _tiny_one_way_scenario()
    config = MilpV1PassengerWaitingConfig(
        horizon_steps=1,
        fixed_starts=(FixedCabinStart(cabin_id=0, node_id="a_board"),),
    )

    try:
        result = solve_milp_v1_passenger_waiting_feasibility(discrete, config)
    except Exception as error:
        if error.__class__.__name__ == "GurobiError":
            pytest.skip(f"Gurobi is installed but not usable in this environment: {error}")
        raise

    assert result.movement_plan is not None
    assert result.metadata.status in {"optimal", "suboptimal"}
    assert tuple(position.node_id for position in result.movement_plan.trajectories[0].positions) == (
        "a_board",
        "b_alight",
    )
    assert result.metadata.passenger_variable_count == 6
    assert result.metadata.queue_count_by_time_od[0, "A", "B"] in {0, 1}
    assert result.metadata.queue_count_by_time_od[1, "A", "B"] in {0, 1}
    assert result.metadata.total_boarded in {0, 1}
    assert result.metadata.total_alighted == result.metadata.total_boarded
    assert result.metadata.total_onboard_at_horizon == 0


def test_milp_v1_passenger_waiting_omits_boarding_when_destination_is_unreachable() -> None:
    pytest.importorskip("gurobipy")
    discrete = _tiny_unreachable_horizon_scenario()
    config = MilpV1PassengerWaitingConfig(
        horizon_steps=0,
        fixed_starts=(FixedCabinStart(cabin_id=0, node_id="a_board"),),
    )

    try:
        result = solve_milp_v1_passenger_waiting_feasibility(discrete, config)
    except Exception as error:
        if error.__class__.__name__ == "GurobiError":
            pytest.skip(f"Gurobi is installed but not usable in this environment: {error}")
        raise

    assert result.movement_plan is not None
    assert result.metadata.status in {"optimal", "suboptimal"}
    assert result.metadata.total_boarded == 0
    assert result.metadata.total_alighted == 0
    assert result.metadata.total_unserved_at_horizon == 1
    assert result.metadata.total_onboard_at_horizon == 0
    assert result.metadata.boarded_count_by_cabin_time_od == {}


def test_milp_v1_waiting_time_objective_minimizes_queue_time() -> None:
    pytest.importorskip("gurobipy")
    discrete = _tiny_delayed_boarding_scenario()
    config = MilpV1PassengerWaitingConfig(
        horizon_steps=2,
        fixed_starts=(FixedCabinStart(cabin_id=0, node_id="hold"),),
        objective=MilpV1PassengerWaitingObjective.WAITING_TIME,
    )

    try:
        result = solve_milp_v1_passenger_waiting(discrete, config)
    except Exception as error:
        if error.__class__.__name__ == "GurobiError":
            pytest.skip(f"Gurobi is installed but not usable in this environment: {error}")
        raise

    assert result.movement_plan is not None
    assert result.metadata.status == "optimal"
    assert result.metadata.objective_value == pytest.approx(1 / 3600)
    assert result.metadata.objective_passenger_hours == pytest.approx(1 / 3600)
    assert result.metadata.queue_count_by_time_od[0, "A", "B"] == 1
    assert result.metadata.queue_count_by_time_od[1, "A", "B"] == 0
    assert result.metadata.total_boarded == 1
    assert result.metadata.total_alighted == 1
    assert result.metadata.total_unserved_at_horizon == 0


def _tiny_one_way_scenario() -> DiscreteScenario:
    return DiscreteScenario(
        id="tiny_one_way",
        source_scenario_id="tiny",
        delta_seconds=1.0,
        horizon_steps=1,
        nodes=(
            DiscreteNode(id="a_board", station_id="A", allows_boarding=True),
            DiscreteNode(id="b_alight", station_id="B", allows_alighting=True),
        ),
        arcs=(
            DiscreteArc(
                id="move::a_to_b",
                kind=DiscreteArcKind.MOVE,
                from_node_id="a_board",
                to_node_id="b_alight",
            ),
        ),
        routes=(),
        constraints=(),
        stations=(),
        station_routes=(),
        cabins=(),
        cabin_initial_states=(),
        demands=(DiscreteDemand(time_step=0, origin="A", destination="B", count=1),),
        cabin_capacity=1,
        required_cabin_spacing_m=1.0,
    )


def _tiny_unreachable_horizon_scenario() -> DiscreteScenario:
    return DiscreteScenario(
        id="tiny_unreachable",
        source_scenario_id="tiny",
        delta_seconds=1.0,
        horizon_steps=0,
        nodes=(
            DiscreteNode(id="a_board", station_id="A", allows_boarding=True, allows_waiting=True),
            DiscreteNode(id="b_alight", station_id="B", allows_alighting=True),
        ),
        arcs=(
            DiscreteArc(
                id="wait::a_board",
                kind=DiscreteArcKind.WAIT,
                from_node_id="a_board",
                to_node_id="a_board",
            ),
        ),
        routes=(),
        constraints=(),
        stations=(),
        station_routes=(),
        cabins=(),
        cabin_initial_states=(),
        demands=(DiscreteDemand(time_step=0, origin="A", destination="B", count=1),),
        cabin_capacity=1,
        required_cabin_spacing_m=1.0,
    )


def _tiny_delayed_boarding_scenario() -> DiscreteScenario:
    return DiscreteScenario(
        id="tiny_delayed_boarding",
        source_scenario_id="tiny",
        delta_seconds=1.0,
        horizon_steps=2,
        nodes=(
            DiscreteNode(id="hold"),
            DiscreteNode(id="a_board", station_id="A", allows_boarding=True),
            DiscreteNode(id="b_alight", station_id="B", allows_alighting=True),
        ),
        arcs=(
            DiscreteArc(
                id="move::hold_to_a",
                kind=DiscreteArcKind.MOVE,
                from_node_id="hold",
                to_node_id="a_board",
            ),
            DiscreteArc(
                id="move::a_to_b",
                kind=DiscreteArcKind.MOVE,
                from_node_id="a_board",
                to_node_id="b_alight",
            ),
        ),
        routes=(),
        constraints=(),
        stations=(),
        station_routes=(),
        cabins=(),
        cabin_initial_states=(),
        demands=(DiscreteDemand(time_step=0, origin="A", destination="B", count=1),),
        cabin_capacity=1,
        required_cabin_spacing_m=1.0,
    )
