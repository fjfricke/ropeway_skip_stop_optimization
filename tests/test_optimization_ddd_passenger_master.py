from __future__ import annotations

import pytest

from ropeway_skip_stop_optimization.optimization.ddd import (
    DddAnonymousFlowFixing,
    DddAnonymousFlowMaster,
    DddAnonymousFlowStatus,
    DddExactTimedEvent,
    DddFixedStart,
    DddLayeredTimeNetworkBuilder,
    DddLayeredTimeNetwork,
    DddMovementProblem,
    DddMovementState,
    DddNetworkTimeObjective,
    DddNetworkTimeProblem,
    DddPassengerMasterProblem,
    DddRecoveredSchedule,
    DddRecoveredScheduleFlowProjector,
    DddRouteDecision,
    DddRouteOption,
    DddRouteOptionCost,
    DddTimeDiscretization,
    DddTimePartition,
)
from ropeway_skip_stop_optimization.optimization.ean import (
    EanPassengerAssignmentDomain,
    EanPassengerObjective,
)
from ropeway_skip_stop_optimization.optimization.ean.models import EanDemandGroup


def test_anonymous_passenger_master_produces_optimistic_journey_lower_bound() -> None:
    problem = _three_stop_passenger_problem(destination_stops=True)
    network = DddLayeredTimeNetworkBuilder().build(problem)
    passenger = DddPassengerMasterProblem(
        movement_problem=problem.movement_problem,
        demand_groups=(
            EanDemandGroup(
                id="demand",
                origin_station_id="A",
                destination_station_id="C",
                release_time_seconds=0.0,
                count=2,
            ),
        ),
        cabin_capacity=2,
        objective=EanPassengerObjective.JOURNEY_TIME,
        assignment_domain=EanPassengerAssignmentDomain.LP_RELAXATION,
    )

    result = DddAnonymousFlowMaster(include_mandatory_resource_rows=False).solve(
        network, passenger_problem=passenger
    )

    assert result.status is DddAnonymousFlowStatus.OPTIMAL
    assert result.objective_value == pytest.approx(40.0)
    assert result.best_bound == pytest.approx(40.0)
    assert result.passenger_solution is not None
    assert result.passenger_solution.served_passenger_count == pytest.approx(2.0)
    assert result.passenger_solution.unserved_passenger_count == pytest.approx(0.0)
    assert result.passenger_solution.board_values
    assert result.passenger_solution.alight_values
    assert result.termination_reason == "optimal"
    assert result.model_build_seconds >= 0.0
    assert result.optimize_seconds >= 0.0
    assert result.solution_count >= 1
    assert result.time_to_first_incumbent_seconds is not None
    assert result.incumbent_improvements
    assert result.progress_snapshots[-1].requested_elapsed_seconds is None
    assert result.progress_snapshots[-1].best_bound == pytest.approx(40.0)


def test_recovered_schedule_can_fix_every_anonymous_flow_arc() -> None:
    base = _three_stop_passenger_problem(destination_stops=True)
    schedule = DddRecoveredSchedule(
        cabin_id=0,
        route_option_ids=("a_stop", "b_skip", "c_service"),
        events=tuple(
            DddExactTimedEvent(index, state, 10.0 * index)
            for index, state in enumerate("ABCD")
        ),
        objective_value=0.0,
    )
    projector = DddRecoveredScheduleFlowProjector()
    problem = projector.refine_discretization(base, (schedule,))
    network = DddLayeredTimeNetworkBuilder().build(problem)
    fixing = projector.project(problem, network, (schedule,))
    passenger = DddPassengerMasterProblem(
        movement_problem=problem.movement_problem,
        demand_groups=(
            EanDemandGroup(
                id="demand",
                origin_station_id="A",
                destination_station_id="C",
                release_time_seconds=0.0,
                count=2,
            ),
        ),
        cabin_capacity=2,
        objective=EanPassengerObjective.JOURNEY_TIME,
        assignment_domain=EanPassengerAssignmentDomain.LP_RELAXATION,
    )

    result = DddAnonymousFlowMaster(include_mandatory_resource_rows=False).solve(
        network,
        fixed_flow=fixing,
        passenger_problem=passenger,
    )

    assert isinstance(fixing, DddAnonymousFlowFixing)
    assert len(fixing.arc_values) == len(network.arcs)
    assert sum(item.value for item in fixing.arc_values) == 4
    arcs_by_id = network.arcs_by_id
    assert all(
        arcs_by_id[item.arc_id].partial_arc is None
        or (
            arcs_by_id[item.arc_id].partial_arc.target_cell.upper_tick
            == arcs_by_id[item.arc_id].partial_arc.target_cell.lower_tick + 1
        )
        for item in fixing.arc_values
        if item.value
    )
    assert result.status is DddAnonymousFlowStatus.OPTIMAL
    assert result.fixed_flow_constraint_count == len(network.arcs)
    assert result.objective_value == pytest.approx(40.0)
    assert {
        item.arc_id: item.value for item in result.arc_values
    } == {
        item.arc_id: item.value for item in fixing.arc_values if item.value
    }


def test_fixed_flow_projector_rejects_incomplete_schedule_set() -> None:
    problem = _three_stop_passenger_problem(destination_stops=True)
    network = DddLayeredTimeNetworkBuilder().build(problem)

    with pytest.raises(ValueError, match="one schedule per cabin"):
        DddRecoveredScheduleFlowProjector().project(problem, network, ())


def test_structural_earliest_times_strengthen_coarse_passenger_lower_bound() -> None:
    base = _three_stop_passenger_problem(destination_stops=True)
    coarse = base.with_discretization(
        DddTimeDiscretization(
            tuple(DddTimePartition(state_id, (0.0, 30.0, 41.0)) for state_id in "BCD")
        )
    )
    passenger = DddPassengerMasterProblem(
        movement_problem=coarse.movement_problem,
        demand_groups=(
            EanDemandGroup(
                id="demand",
                origin_station_id="A",
                destination_station_id="C",
                release_time_seconds=0.0,
                count=2,
            ),
        ),
        cabin_capacity=2,
        objective=EanPassengerObjective.JOURNEY_TIME,
        assignment_domain=EanPassengerAssignmentDomain.LP_RELAXATION,
    )

    legacy = DddAnonymousFlowMaster(include_mandatory_resource_rows=False).solve(
        DddLayeredTimeNetworkBuilder(use_structural_earliest_times=False).build(coarse),
        passenger_problem=passenger,
    )
    strengthened = DddAnonymousFlowMaster(include_mandatory_resource_rows=False).solve(
        DddLayeredTimeNetworkBuilder().build(coarse),
        passenger_problem=passenger,
    )

    assert legacy.objective_value == pytest.approx(0.0)
    assert strengthened.objective_value == pytest.approx(40.0)
    assert strengthened.objective_value > legacy.objective_value


def test_anonymous_passenger_master_cannot_alight_at_skipped_destination() -> None:
    problem = _three_stop_passenger_problem(destination_stops=False)
    network = DddLayeredTimeNetworkBuilder().build(problem)
    passenger = DddPassengerMasterProblem(
        movement_problem=problem.movement_problem,
        demand_groups=(
            EanDemandGroup(
                id="demand",
                origin_station_id="A",
                destination_station_id="C",
                release_time_seconds=0.0,
                count=2,
            ),
        ),
        cabin_capacity=2,
        objective=EanPassengerObjective.JOURNEY_TIME,
    )

    result = DddAnonymousFlowMaster(include_mandatory_resource_rows=False).solve(
        network, passenger_problem=passenger
    )

    assert result.status is DddAnonymousFlowStatus.OPTIMAL
    assert result.objective_value == pytest.approx(60.0)
    assert result.passenger_solution is not None
    assert result.passenger_solution.served_passenger_count == pytest.approx(0.0)
    assert result.passenger_solution.unserved_passenger_count == pytest.approx(2.0)


def test_passenger_master_materializes_the_arc_index_only_once(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    problem = _three_stop_passenger_problem(destination_stops=True)
    network = DddLayeredTimeNetworkBuilder().build(problem)
    original = DddLayeredTimeNetwork.arcs_by_id.fget
    assert original is not None
    access_count = 0

    def counted_arc_index(
        instance: DddLayeredTimeNetwork,
    ) -> dict[str, object]:
        nonlocal access_count
        access_count += 1
        return original(instance)

    monkeypatch.setattr(
        DddLayeredTimeNetwork,
        "arcs_by_id",
        property(counted_arc_index),
    )
    passenger = DddPassengerMasterProblem(
        movement_problem=problem.movement_problem,
        demand_groups=(
            EanDemandGroup(
                id="demand",
                origin_station_id="A",
                destination_station_id="C",
                release_time_seconds=0.0,
                count=2,
            ),
        ),
        cabin_capacity=2,
        objective=EanPassengerObjective.JOURNEY_TIME,
    )

    result = DddAnonymousFlowMaster(include_mandatory_resource_rows=False).solve(
        network, passenger_problem=passenger
    )

    assert result.status is DddAnonymousFlowStatus.OPTIMAL
    assert access_count == 1


def _three_stop_passenger_problem(
    *,
    destination_stops: bool,
) -> DddNetworkTimeProblem:
    options = (
        _route("a_stop", "A", "B", "A", DddRouteDecision.STOP),
        _route("b_skip", "B", "C", "B", DddRouteDecision.SKIP),
        _route(
            "c_service",
            "C",
            "D",
            "C",
            DddRouteDecision.STOP if destination_stops else DddRouteDecision.SKIP,
        ),
    )
    movement = DddMovementProblem(
        scenario_id="ddd_passenger_master",
        passenger_service_end_seconds=30.0,
        operational_end_seconds=30.0,
        states=tuple(DddMovementState(state_id) for state_id in "ABCD"),
        starts=(DddFixedStart(0, "A", 0.0, 3),),
        route_options=options,
        resources=(),
    )
    return DddNetworkTimeProblem(
        movement_problem=movement,
        discretization=DddTimeDiscretization(
            (
                DddTimePartition("B", (0.0, 10.0, 11.0, 30.0, 41.0)),
                DddTimePartition("C", (0.0, 20.0, 21.0, 30.0, 41.0)),
                DddTimePartition("D", (0.0, 30.0, 31.0, 41.0)),
            )
        ),
        objective=DddNetworkTimeObjective(
            route_option_costs=tuple(
                DddRouteOptionCost(option.id, 0.0) for option in options
            )
        ),
    )


def _route(
    route_id: str,
    source: str,
    target: str,
    station: str,
    decision: DddRouteDecision,
) -> DddRouteOption:
    is_stop = decision is DddRouteDecision.STOP
    return DddRouteOption(
        id=route_id,
        from_state_id=source,
        to_state_id=target,
        station_id=station,
        decision=decision,
        duration_seconds=10.0,
        platform_entry_offset_seconds=0.0 if is_stop else None,
        platform_exit_offset_seconds=1.0 if is_stop else None,
        exit_switch_offset_seconds=1.0 if is_stop else 0.0,
        resource_usages=(),
    )
