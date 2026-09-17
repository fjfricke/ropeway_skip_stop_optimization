from dataclasses import replace

import pytest

from test_optimization_ddd_reservoir_arc_flow import _problem
from test_optimization_ddd_reservoir_cp_sat import T, trip
from ropeway_skip_stop_optimization.optimization.ddd.cp_sat_integrated import (
    DddIntegratedCpSatConfig,
)
from ropeway_skip_stop_optimization.optimization.ddd.cp_sat_passenger import (
    DddCpSatPassengerEncoding,
)
from ropeway_skip_stop_optimization.optimization.ddd.reservoir_cp_sat import (
    DddReservoirCpObjective,
    DddReservoirCpSatOptimizer,
    build_reservoir_cp_sat,
)
from ropeway_skip_stop_optimization.optimization.ddd.reservoir_cp_sat_certificate import (
    DddReservoirCpPlan,
    reservoir_cp_plan_from_payload,
    validate_reservoir_cp_plan,
)
from ropeway_skip_stop_optimization.optimization.ddd.reservoir_cp_sat_problem import (
    DddReservoirCpSatProblem,
)
from ropeway_skip_stop_optimization.optimization.ean.models import EanDemandGroup


def problem(*, groups, fleet=1, horizon=5):
    source = DddReservoirCpSatProblem.from_arc_flow(_problem(fleet=fleet))
    return replace(
        source,
        dispatch_end_seconds=1,
        dispatch_step_seconds=1,
        movement_core=replace(
            source.movement_core,
            passenger_service_end_seconds=horizon,
            operational_end_seconds=horizon + 1,
        ),
        demand_groups=groups,
    )


def config(encoding):
    return DddIntegratedCpSatConfig(
        total_time_limit_seconds=5,
        num_workers=1,
        passenger_encoding=encoding,
    )


@pytest.mark.parametrize(
    "objective",
    [DddReservoirCpObjective.UNSERVED, DddReservoirCpObjective.JOURNEY_TIME],
)
def test_od_inventory_matches_group_model_and_reconstructs_legacy_certificate(objective):
    p = problem(
        groups=(
            EanDemandGroup("early", "A", "B", 0, 1),
            EanDemandGroup("later", "A", "B", 1, 1),
        )
    )
    results = [
        DddReservoirCpSatOptimizer(config(encoding), objective).solve(p)
        for encoding in DddCpSatPassengerEncoding
    ]
    assert all(result["proven_optimal"] for result in results)
    assert {result["validated_upper_bound"] for result in results} == {
        results[0]["validated_upper_bound"]
    }
    assert {result["metrics"]["served"] for result in results} == {1}
    inventory = results[1]
    plan = reservoir_cp_plan_from_payload(inventory["plan"])
    assert validate_reservoir_cp_plan(p, plan).journey_time_tick == round(
        inventory["journey_time_seconds"] * T
    )


def test_release_at_boarding_tick_is_available_but_later_release_is_not():
    base = problem(groups=(EanDemandGroup("g", "A", "B", 0, 1),))
    movement = DddReservoirCpPlan((trip(dispatch=0),), {})
    stop = next(option for option in base.movement.route_options if option.id == "A_stop")
    departure = stop.platform_exit_offset_seconds
    for release, expected in ((departure, 1), (departure + 0.000001, 0)):
        p = replace(base, demand_groups=(EanDemandGroup("g", "A", "B", release, 1),))
        result = DddReservoirCpSatOptimizer(
            config(DddCpSatPassengerEncoding.OD_INVENTORY),
            DddReservoirCpObjective.UNSERVED,
        ).solve(p, fixed_plan=movement)
        assert result["metrics"]["served"] == expected


def test_inventory_builder_collapses_release_group_cross_product():
    p = problem(
        groups=tuple(
            EanDemandGroup(f"g{i}", "A", "B", i / 10, 1)
            for i in range(10)
        )
    )
    grouped = build_reservoir_cp_sat(p, config=config(DddCpSatPassengerEncoding.GROUPS))
    inventory = build_reservoir_cp_sat(
        p, config=config(DddCpSatPassengerEncoding.OD_INVENTORY)
    )
    assert inventory.stats["passenger_encoding"] == "od_inventory"
    assert inventory.stats["legacy_ride_candidates"] == grouped.stats["ride_candidates"]
    assert inventory.stats["ride_candidates"] < grouped.stats["ride_candidates"]
    assert inventory.stats["variables"] < grouped.stats["variables"]
    assert inventory.stats["constraints"] < grouped.stats["constraints"]


def test_od_inventory_accepts_and_preserves_legacy_seed_counts():
    p = problem(groups=(EanDemandGroup("g", "A", "B", 0, 1),))
    legacy = DddReservoirCpSatOptimizer(
        config(DddCpSatPassengerEncoding.GROUPS)
    ).solve(p)
    seed = reservoir_cp_plan_from_payload(legacy["plan"])
    result = DddReservoirCpSatOptimizer(
        config(DddCpSatPassengerEncoding.OD_INVENTORY)
    ).solve(p, primal_seed=seed)
    assert result["validated_upper_bound"] <= legacy["validated_upper_bound"]
    assert result["metrics"] == legacy["metrics"]


@pytest.mark.parametrize(
    "objective",
    [DddReservoirCpObjective.UNSERVED, DddReservoirCpObjective.JOURNEY_TIME],
)
def test_od_inventory_matches_groups_across_multiple_cabins_and_release_batches(
    objective,
):
    p = problem(
        fleet=2,
        horizon=6,
        groups=(
            EanDemandGroup("g0", "A", "B", 0, 1),
            EanDemandGroup("g1", "A", "B", 0.5, 1),
            EanDemandGroup("g2", "A", "B", 1.5, 1),
        ),
    )
    grouped = DddReservoirCpSatOptimizer(
        config(DddCpSatPassengerEncoding.GROUPS), objective
    ).solve(p)
    inventory = DddReservoirCpSatOptimizer(
        config(DddCpSatPassengerEncoding.OD_INVENTORY), objective
    ).solve(p)
    assert grouped["proven_optimal"] and inventory["proven_optimal"]
    assert inventory["validated_upper_bound"] == grouped["validated_upper_bound"]
    assert inventory["metrics"]["served"] == grouped["metrics"]["served"]
    if objective is DddReservoirCpObjective.JOURNEY_TIME:
        assert (
            inventory["metrics"]["journey_time_tick"]
            == grouped["metrics"]["journey_time_tick"]
        )
    plan = reservoir_cp_plan_from_payload(inventory["plan"])
    assert validate_reservoir_cp_plan(p, plan).served == inventory["metrics"]["served"]
