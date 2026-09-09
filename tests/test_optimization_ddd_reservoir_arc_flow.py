from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import pytest

from ropeway_skip_stop_optimization.optimization.ddd.anonymous_reservoir_network import (
    DddAnonymousReservoirNetworkBuilder,
    _build_resource_cliques_linear_sweep,
)
from ropeway_skip_stop_optimization.optimization.ddd.arc_flow_network import (
    DddArcFlowResourceInterval,
    build_ddd_arc_flow_resource_cliques_from_intervals,
)
from ropeway_skip_stop_optimization.optimization.ddd.models import (
    DddMovementCore,
    DddMovementState,
    DddResource,
    DddResourceUsage,
    DddRouteDecision,
    DddRouteOption,
)
from ropeway_skip_stop_optimization.optimization.ddd.reservoir_arc_flow import (
    DddReservoirAllStopReferenceBuilder,
    DddReservoirArcFlowOptimizer,
    DddReservoirArcFlowSolveConfig,
    DddReservoirArcFlowStatus,
    decompose_ddd_anonymous_reservoir_paths,
    load_ddd_reservoir_incumbent_checkpoint,
    validate_ddd_anonymous_reservoir_selection,
    write_ddd_reservoir_incumbent_checkpoint,
    _DddReservoirMovementMasterBuilder,
    _extract_passenger_metrics,
)
from ropeway_skip_stop_optimization.optimization.ddd.reservoir_arc_flow_problem import (
    DddReservoirArcFlowProblem,
    DddReservoirOperatingMode,
)
from ropeway_skip_stop_optimization.optimization.ddd.reservoir_passenger import (
    DddReservoirPassengerModelBuilder,
)
from ropeway_skip_stop_optimization.optimization.ddd.trajectory_column_generation import (
    DddTrajectoryWaitingDomain,
)
from ropeway_skip_stop_optimization.optimization.ddd.trajectory_problem import (
    DddTrajectoryWaitingPolicy,
)
from ropeway_skip_stop_optimization.optimization.ean.models import EanDemandGroup


def _option(
    station: str,
    target: str,
    decision: DddRouteDecision,
    duration: float,
) -> DddRouteOption:
    stop = decision is DddRouteDecision.STOP
    return DddRouteOption(
        id=f"{station}_{decision.value}",
        from_state_id=station,
        to_state_id=target,
        station_id=station,
        decision=decision,
        duration_seconds=duration,
        platform_entry_offset_seconds=0.0 if stop else None,
        platform_exit_offset_seconds=0.5 if stop else None,
        exit_switch_offset_seconds=0.5 if stop else 0.0,
        resource_usages=(
            DddResourceUsage(
                resource_id=f"rope_{station}",
                leader_clear_offset_seconds=0.0,
                follower_enter_offset_seconds=0.0,
            ),
        ),
    )


def _problem(*, waiting: bool = False, fleet: int = 3) -> DddReservoirArcFlowProblem:
    core = DddMovementCore(
        scenario_id="tiny_reservoir",
        passenger_service_end_seconds=10.0,
        operational_end_seconds=10.0,
        states=(DddMovementState("A"), DddMovementState("B")),
        route_options=(
            _option("A", "B", DddRouteDecision.STOP, 2.0),
            _option("A", "B", DddRouteDecision.SKIP, 1.0),
            _option("B", "A", DddRouteDecision.STOP, 2.0),
            _option("B", "A", DddRouteDecision.SKIP, 1.0),
        ),
        resources=(DddResource("rope_A", 1.0), DddResource("rope_B", 1.0)),
    )
    policy = (
        DddTrajectoryWaitingPolicy(
            domain=DddTrajectoryWaitingDomain.BOUNDED_WAIT,
            step_seconds=1.0,
            maximum_wait_seconds_by_station_id=(("A", 2.0), ("B", 2.0)),
            earliest_wait_time_seconds=5.0,
        )
        if waiting
        else DddTrajectoryWaitingPolicy()
    )
    return DddReservoirArcFlowProblem(
        movement_core=core,
        demand_groups=(EanDemandGroup("g", "A", "B", 0.0, 1),),
        cabin_capacity=1,
        available_fleet_count=fleet,
        entry_state_id="A",
        warmup_seconds=5.0,
        service_seconds=10.0,
        recovery_seconds=5.0,
        dispatch_step_seconds=1.0,
        waiting_policy=policy,
        all_stop_maximum_cabin_count=2,
        all_stop_cycle_seconds=4.0,
        all_stop_headway_seconds=1.0,
    )


def test_linear_interval_sweep_matches_reference_maximal_cliques() -> None:
    intervals = tuple(
        DddArcFlowResourceInterval("r", f"a{i}", 0, start, end)
        for i, (start, end) in enumerate(((0, 3), (1, 5), (2, 4), (5, 7)))
    )
    expected = build_ddd_arc_flow_resource_cliques_from_intervals(intervals)
    actual = _build_resource_cliques_linear_sweep(intervals, deadline_monotonic=None)
    assert tuple(item.coefficients for item in actual) == tuple(
        item.coefficients for item in expected
    )


def test_reservoir_network_obeys_boundary_phases_and_contains_seed() -> None:
    problem = _problem(waiting=True)
    network = DddAnonymousReservoirNetworkBuilder().build(problem)
    assert all(arc.source_tick < problem.warmup_tick for arc in network.dispatch_arcs)
    assert all(
        problem.service_end_tick <= arc.source_tick <= problem.operational_end_tick
        for arc in network.recovery_arcs
    )
    assert set(network.all_stop_seed_dispatch_ticks) <= set(network.dispatch_ticks)
    waited = tuple(arc for arc in network.movement_arcs if arc.wait_tick > 0)
    assert waited
    options = {item.id: item for item in problem.movement_core.route_options}
    assert all(options[arc.option_id].decision is DddRouteDecision.STOP for arc in waited)
    assert all(
        problem.service_start_tick
        <= arc.source_tick
        + options[arc.option_id].exit_switch_offset_tick
        + arc.wait_tick
        <= problem.service_end_tick
        for arc in waited
    )


def test_all_stop_reference_is_a_complete_valid_subset() -> None:
    problem = _problem()
    network = DddAnonymousReservoirNetworkBuilder().build(problem)
    reference = DddReservoirAllStopReferenceBuilder().build(problem, network)
    validate_ddd_anonymous_reservoir_selection(
        problem, network, reference.selected_arc_ids
    )
    assert reference.metrics.unserved_passenger_count == 0
    assert len(reference.paths) == 2
    assert len(decompose_ddd_anonymous_reservoir_paths(network, reference.selected_arc_ids)) == 2


def test_all_stop_network_and_no_wait_network_are_nested_in_richer_domains() -> None:
    no_wait_problem = _problem()
    all_stop_problem = replace(
        no_wait_problem, operating_mode=DddReservoirOperatingMode.ALL_STOP
    )
    waiting_problem = _problem(waiting=True)
    no_wait = DddAnonymousReservoirNetworkBuilder().build(no_wait_problem)
    all_stop = DddAnonymousReservoirNetworkBuilder().build(all_stop_problem)
    waiting = DddAnonymousReservoirNetworkBuilder().build(waiting_problem)
    assert {arc.id for arc in all_stop.arcs} <= {arc.id for arc in no_wait.arcs}
    assert {arc.id for arc in no_wait.arcs} <= {arc.id for arc in waiting.arcs}


def test_tiny_reservoir_optimizer_returns_a_certified_integer_solution(tmp_path: Path) -> None:
    checkpoint = tmp_path / "incumbent.json"
    problem = _problem()
    result = DddReservoirArcFlowOptimizer(
        DddReservoirArcFlowSolveConfig(
            total_time_limit_seconds=20.0,
            threads=1,
            output_flag=False,
            progress_interval_seconds=0.1,
            checkpoint_path=checkpoint,
        )
    ).solve(problem)
    assert result.status is DddReservoirArcFlowStatus.INTEGER_OPTIMAL
    assert result.primary_solver_status == "OPTIMAL"
    assert result.secondary_solver_status == "OPTIMAL"
    assert result.primary_lower_bound == pytest.approx(0.0)
    assert result.primary_upper_bound == pytest.approx(0.0)
    assert result.served_lower_bound == pytest.approx(1.0)
    assert result.served_upper_bound == pytest.approx(1.0)
    assert result.all_stop_seed_accepted
    assert checkpoint.exists()


def test_checkpoint_rejects_an_incompatible_problem(tmp_path: Path) -> None:
    problem = _problem()
    network = DddAnonymousReservoirNetworkBuilder().build(problem)
    reference = DddReservoirAllStopReferenceBuilder().build(problem, network)
    import gurobipy as gp

    model = gp.Model()
    model.Params.OutputFlag = 0
    movement = _DddReservoirMovementMasterBuilder().build(
        model=model, problem=problem, network=network
    )
    passenger = DddReservoirPassengerModelBuilder().build(
        model=model,
        problem=problem,
        network=network,
        route_by_arc_id=movement.route_by_arc_id,
    )
    movement.apply_start(reference.selected_arc_ids)
    model.setObjective(passenger.total_unserved_expression)
    model.optimize()
    metrics = _extract_passenger_metrics(problem, passenger)
    path = tmp_path / "checkpoint.json"
    write_ddd_reservoir_incumbent_checkpoint(
        path,
        problem=problem,
        network=network,
        selected_arc_ids=movement.selected_arc_ids(),
        passenger_model=passenger,
        metrics=metrics,
        provenance="test",
    )
    other = _problem(fleet=4)
    other_network = DddAnonymousReservoirNetworkBuilder().build(other)
    with pytest.raises(ValueError, match="fingerprint"):
        load_ddd_reservoir_incumbent_checkpoint(
            path, problem=other, network=other_network
        )
