from __future__ import annotations

from dataclasses import replace

from ropeway_skip_stop_optimization.baselines import build_all_stop_cycle_path, greedy_place_max_cabins_on_cycle
from ropeway_skip_stop_optimization.examples.three_station import build_three_station_scenario
from ropeway_skip_stop_optimization.models import DiscreteDemand
from ropeway_skip_stop_optimization.optimization.discrete_time import (
    FixedCabinStart,
    MilpV0Config,
    build_discrete_graph_index,
    build_passenger_milp_index,
    build_sparse_reachability_milp_v0_variable_index,
)
from ropeway_skip_stop_optimization.optimization.discrete_time.movement_model import _allowed_arc_ids
from ropeway_skip_stop_optimization.mapping import discretize_scenario, physical_node_id


def test_passenger_index_aggregates_discrete_demand_by_time_and_od() -> None:
    discrete = replace(
        discretize_scenario(build_three_station_scenario()),
        demands=(
            DiscreteDemand(time_step=3, origin="L", destination="M", count=2),
            DiscreteDemand(time_step=3, origin="L", destination="M", count=5),
            DiscreteDemand(time_step=4, origin="L", destination="R", count=7),
        ),
    )

    passenger_index = _build_passenger_index(discrete, horizon_steps=20)

    assert passenger_index.od_pairs == (("L", "M"), ("L", "R"))
    assert passenger_index.demand_count_by_time_od[3, "L", "M"] == 7
    assert passenger_index.demand_count_by_time_od[4, "L", "R"] == 7
    assert passenger_index.total_demand_by_od["L", "M"] == 7
    assert passenger_index.total_demand_by_od["L", "R"] == 7


def test_passenger_index_uses_only_explicit_boarding_and_alighting_nodes() -> None:
    discrete = discretize_scenario(build_three_station_scenario())

    passenger_index = _build_passenger_index(discrete, horizon_steps=20)

    boarding_node_ids = {
        node_id
        for node_ids in passenger_index.boarding_node_ids_by_station.values()
        for node_id in node_ids
    }
    alighting_node_ids = {
        node_id
        for node_ids in passenger_index.alighting_node_ids_by_station.values()
        for node_id in node_ids
    }

    node_by_id = {node.id: node for node in discrete.nodes}
    assert boarding_node_ids
    assert alighting_node_ids
    assert all(node_by_id[node_id].allows_boarding for node_id in boarding_node_ids)
    assert all(node_by_id[node_id].allows_alighting for node_id in alighting_node_ids)
    assert all("brake" not in node_id and "accelerate" not in node_id for node_id in boarding_node_ids)
    assert all("brake" not in node_id and "accelerate" not in node_id for node_id in alighting_node_ids)


def test_passenger_index_creates_boarding_candidates_only_when_destination_is_reachable() -> None:
    discrete = replace(
        discretize_scenario(build_three_station_scenario()),
        demands=(DiscreteDemand(time_step=0, origin="L", destination="M", count=8),),
    )
    start = FixedCabinStart(cabin_id=0, node_id=physical_node_id("L_platform_exit"))

    passenger_index = _build_passenger_index(discrete, horizon_steps=200, fixed_starts=(start,))

    assert passenger_index.can_reach_destination_by_cabin_time_destination[0, 0, "M"]
    assert passenger_index.boarding_candidates_by_cabin_time_od[0, 0, "L", "M"] == (
        physical_node_id("L_platform_exit"),
    )


def test_passenger_index_omits_boarding_candidates_when_destination_cannot_be_reached_before_horizon() -> None:
    discrete = replace(
        discretize_scenario(build_three_station_scenario()),
        demands=(DiscreteDemand(time_step=0, origin="L", destination="R", count=8),),
    )
    start = FixedCabinStart(cabin_id=0, node_id=physical_node_id("L_platform_exit"))

    passenger_index = _build_passenger_index(discrete, horizon_steps=0, fixed_starts=(start,))

    assert not passenger_index.can_reach_destination_by_cabin_time_destination[0, 0, "R"]
    assert (0, 0, "L", "R") not in passenger_index.boarding_candidates_by_cabin_time_od


def test_passenger_index_lists_alighting_candidates_only_when_reachable_at_time() -> None:
    discrete = replace(
        discretize_scenario(build_three_station_scenario()),
        demands=(DiscreteDemand(time_step=0, origin="L", destination="M", count=8),),
    )
    start = FixedCabinStart(cabin_id=0, node_id=physical_node_id("L_platform_exit"))

    passenger_index = _build_passenger_index(discrete, horizon_steps=200, fixed_starts=(start,))

    alighting_candidate_times = [
        time_step
        for (cabin_id, time_step, destination) in passenger_index.alighting_candidates_by_cabin_time_destination
        if cabin_id == 0 and destination == "M"
    ]

    assert alighting_candidate_times
    assert min(alighting_candidate_times) > 0


def _build_passenger_index(
    discrete,
    *,
    horizon_steps: int,
    fixed_starts: tuple[FixedCabinStart, ...] | None = None,
):
    graph_index = build_discrete_graph_index(discrete)
    if fixed_starts is None:
        path = build_all_stop_cycle_path(discrete)
        start_indices = greedy_place_max_cabins_on_cycle(discrete, path.node_ids)
        fixed_starts = (
            FixedCabinStart(cabin_id=0, node_id=path.node_ids[start_indices[0]]),
        )
    config = MilpV0Config(horizon_steps=horizon_steps, fixed_starts=fixed_starts)
    allowed_arc_ids = _allowed_arc_ids(discrete, config)
    variable_index = build_sparse_reachability_milp_v0_variable_index(
        graph_index,
        fixed_starts,
        allowed_arc_ids,
        horizon_steps,
    )
    return build_passenger_milp_index(
        discrete,
        graph_index,
        variable_index,
        fixed_starts,
        allowed_arc_ids,
        horizon_steps,
    )
