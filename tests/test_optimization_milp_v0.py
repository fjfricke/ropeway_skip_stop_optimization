from __future__ import annotations

import pytest

from ropeway_skip_stop_optimization.models import DiscreteArc, DiscreteArcKind, DiscreteNode, DiscreteScenario
from ropeway_skip_stop_optimization.optimization import FixedCabinStart, MilpV0Config, solve_milp_v0


def test_milp_v0_solves_tiny_waiting_model_when_gurobi_is_available() -> None:
    pytest.importorskip("gurobipy")
    discrete = _tiny_waiting_scenario()
    config = MilpV0Config(
        horizon_steps=2,
        fixed_starts=(FixedCabinStart(cabin_id=0, node_id="n0"),),
    )

    try:
        result = solve_milp_v0(discrete, config)
    except Exception as error:
        if error.__class__.__name__ == "GurobiError":
            pytest.skip(f"Gurobi is installed but not usable in this environment: {error}")
        raise

    assert result.movement_plan is not None
    assert result.movement_plan.horizon_steps == 2
    assert result.metadata.status in {"optimal", "suboptimal"}
    assert len(result.metadata.selected_arc_ids_by_cabin[0]) == 2
    assert tuple(position.node_id for position in result.movement_plan.trajectories[0].positions) == ("n0", "n0", "n0")


def _tiny_waiting_scenario() -> DiscreteScenario:
    return DiscreteScenario(
        id="tiny_waiting",
        source_scenario_id="tiny",
        delta_seconds=1.0,
        horizon_steps=2,
        nodes=(DiscreteNode(id="n0", allows_waiting=True),),
        arcs=(DiscreteArc(id="wait::n0", kind=DiscreteArcKind.WAIT, from_node_id="n0", to_node_id="n0"),),
        routes=(),
        constraints=(),
        stations=(),
        station_routes=(),
        cabins=(),
        cabin_initial_states=(),
        demands=(),
        cabin_capacity=1,
        required_cabin_spacing_m=1.0,
    )
