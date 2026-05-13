from __future__ import annotations

from datetime import time

import pytest

from ropeway_skip_stop_optimization.models import Demand, OperatingParameters, Scenario
from ropeway_skip_stop_optimization.optimization.ean import (
    EanCabinStart,
    EanCabinStartKind,
    EanConfig,
    HeadwayCandidate,
    HeadwayCheckpointDefinition,
    HeadwayCheckpointKind,
    SkipStopTiming,
    StationEanConfig,
    StationWaitingMode,
    SwitchTransition,
    SwitchVisitDefinition,
    EanActivationReference,
    EanBuildArtifact,
    EanTimeReference,
    EanOptimizationConfig,
    EanPassengerServiceConfig,
    EanPassengerServiceObjective,
    EanRideCandidate,
    GurobiSolverPolicy,
    solve_ean_passenger_service,
)
from ropeway_skip_stop_optimization.optimization.ean.optimizers.passenger_service import (
    _min_candidate_trip_time_seconds,
    _solver_diagnostics,
)


def test_ean_passenger_service_minimizes_waiting_with_unserved_backlog() -> None:
    pytest.importorskip("gurobipy")
    scenario = _minimal_scenario(
        demands=(Demand(arrival_time=time(8, 0), origin="A", destination="B", count=3),),
    )
    artifact = _minimal_artifact(cabin_capacity=2)

    result = solve_ean_passenger_service(scenario, artifact)

    assert result.metadata.status == "optimal"
    assert result.metadata.objective_kind is EanPassengerServiceObjective.WAITING_TIME
    assert result.movement_plan is not None
    assert result.passenger_plan is not None
    assert result.metadata.served_passenger_count == 2
    assert result.metadata.unserved_passenger_count == 1
    assert result.passenger_plan.unserved_counts_by_demand_group_id == {"demand::0": 1}
    assert sum(ride.count for ride in result.passenger_plan.served_rides) == 2
    assert result.metadata.objective_value_seconds == pytest.approx(24.0)
    assert result.metadata.objective_passenger_hours == pytest.approx(24.0 / 3600.0)
    assert result.metadata.solver_status == "OPTIMAL"
    assert result.metadata.solution_count >= 1
    assert result.metadata.runtime_seconds is not None
    assert result.metadata.node_count is not None
    assert result.metadata.best_bound is not None


def test_ean_passenger_service_journey_time_uses_alighting_time() -> None:
    pytest.importorskip("gurobipy")
    scenario = _minimal_scenario(
        demands=(Demand(arrival_time=time(8, 0), origin="A", destination="B", count=1),),
    )
    artifact = _minimal_artifact(cabin_capacity=2, cycle_count=2)

    result = solve_ean_passenger_service(
        scenario,
        artifact,
        EanPassengerServiceConfig(objective=EanPassengerServiceObjective.JOURNEY_TIME),
    )

    assert result.metadata.status == "optimal"
    assert result.metadata.objective_kind is EanPassengerServiceObjective.JOURNEY_TIME
    assert result.passenger_plan is not None
    assert len(result.passenger_plan.served_rides) == 1
    ride = result.passenger_plan.served_rides[0]
    assert ride.alight_visit_index == 1
    assert result.metadata.objective_value_seconds == pytest.approx(9.0)
    assert result.metadata.objective_passenger_hours == pytest.approx(9.0 / 3600.0)


def test_ean_passenger_service_can_disable_slot_time_strengthening() -> None:
    pytest.importorskip("gurobipy")
    scenario = _minimal_scenario(
        demands=(Demand(arrival_time=time(8, 0), origin="A", destination="B", count=1),),
    )
    artifact = _minimal_artifact(cabin_capacity=2, cycle_count=2)

    strengthened = solve_ean_passenger_service(
        scenario,
        artifact,
        EanPassengerServiceConfig(objective=EanPassengerServiceObjective.JOURNEY_TIME),
    )
    unstrengthened = solve_ean_passenger_service(
        scenario,
        artifact,
        EanPassengerServiceConfig(
            objective=EanPassengerServiceObjective.JOURNEY_TIME,
            optimization_config=EanOptimizationConfig(enable_slot_time_relaxation_strengthening=False),
        ),
    )

    assert strengthened.metadata.objective_value_seconds == pytest.approx(unstrengthened.metadata.objective_value_seconds)
    assert strengthened.metadata.constraint_count > unstrengthened.metadata.constraint_count
    assert not unstrengthened.metadata.optimization_config.enable_slot_time_relaxation_strengthening


def test_min_candidate_trip_time_uses_physical_lower_bound_between_platforms() -> None:
    artifact = _minimal_artifact(cabin_capacity=2, cycle_count=2)
    visits_by_key = {
        (visit.cabin_id, visit.visit_index): visit
        for visit in artifact.switch_visits
    }
    timing_by_switch_id = {timing.switch_id: timing for timing in artifact.timings}

    adjacent_candidate = EanRideCandidate(
        id="ride::adjacent",
        demand_group_id="demand::0",
        cabin_id=0,
        board_visit_index=0,
        alight_visit_index=1,
    )
    wrapped_candidate = EanRideCandidate(
        id="ride::wrapped",
        demand_group_id="demand::0",
        cabin_id=0,
        board_visit_index=0,
        alight_visit_index=3,
    )

    assert _min_candidate_trip_time_seconds(
        adjacent_candidate,
        visits_by_key,
        timing_by_switch_id,
    ) == pytest.approx(7.0)
    assert _min_candidate_trip_time_seconds(
        wrapped_candidate,
        visits_by_key,
        timing_by_switch_id,
    ) == pytest.approx(23.0)


def test_solver_diagnostics_collects_model_and_policy_metadata() -> None:
    model = _FakeSolvedModel()
    policy = GurobiSolverPolicy(mip_gap=0.1, time_limit_seconds=60.0)

    diagnostics = _solver_diagnostics(model, _FakeGRB, policy)

    assert diagnostics == {
        "status": "optimal",
        "solver_status": "OPTIMAL",
        "best_bound": 90.0,
        "mip_gap": 0.05,
        "runtime_seconds": 12.5,
        "node_count": 42.0,
        "solution_count": 3,
        "mip_gap_target": 0.1,
        "time_limit_seconds": 60.0,
    }


def test_solver_diagnostics_omits_gap_when_no_solution_exists() -> None:
    model = _FakeSolvedModel()
    model.Status = _FakeGRB.TIME_LIMIT
    model.SolCount = 0
    model.MIPGap = float("inf")

    diagnostics = _solver_diagnostics(model, _FakeGRB, GurobiSolverPolicy())

    assert diagnostics["status"] == "time_limit"
    assert diagnostics["solver_status"] == "TIME_LIMIT"
    assert diagnostics["solution_count"] == 0
    assert diagnostics["mip_gap"] is None


class _FakeGRB:
    OPTIMAL = 2
    INFEASIBLE = 3
    INF_OR_UNBD = 4
    UNBOUNDED = 5
    TIME_LIMIT = 9
    INTERRUPTED = 11


class _FakeSolvedModel:
    Status = _FakeGRB.OPTIMAL
    SolCount = 3
    ObjBound = 90.0
    MIPGap = 0.05
    Runtime = 12.5
    NodeCount = 42.0


def _minimal_scenario(demands: tuple[Demand, ...]) -> Scenario:
    return Scenario(
        id="minimal_ean",
        service_start_time=time(8, 0),
        service_end_time=time(8, 1),
        stations=(),
        physical_nodes=(),
        track_segments=(),
        station_routes=(),
        cabins=(),
        cabin_initial_states=(),
        demands=demands,
        operating=OperatingParameters(
            rope_speed_m_per_s=5.0,
            station_speed_m_per_s=0.5,
            cabin_capacity=2,
            cabin_length_m=3.0,
            min_clearance_m=0.5,
        ),
    )


def _minimal_artifact(
    cabin_capacity: int,
    cycle_count: int = 1,
    station_waiting_modes: dict[str, StationWaitingMode] | None = None,
) -> EanBuildArtifact:
    station_waiting_modes = station_waiting_modes or {}
    station_a_waiting_mode = station_waiting_modes.get("A", StationWaitingMode.NO_WAITING)
    station_b_waiting_mode = station_waiting_modes.get("B", StationWaitingMode.NO_WAITING)
    config = EanConfig(
        horizon_seconds=20.0,
        tail_seconds=0.0,
        cabin_capacity=cabin_capacity,
        station_configs=(
            StationEanConfig(station_id="A", waiting_mode=station_a_waiting_mode),
            StationEanConfig(station_id="B", waiting_mode=station_b_waiting_mode),
        ),
    )
    return EanBuildArtifact(
        scenario_id="minimal_ean",
        config=config,
        switch_cycle=("A_entry", "B_entry"),
        timings=(
            SkipStopTiming(
                switch_id="A_entry",
                station_id="A",
                entry_to_platform_entry_seconds=1.0,
                min_platform_entry_to_platform_exit_seconds=1.0,
                platform_exit_to_exit_switch_seconds=1.0,
                skip_entry_to_exit_switch_seconds=3.0,
                rope_to_next_switch_seconds=5.0,
                skip_allowed=False,
            ),
            SkipStopTiming(
                switch_id="B_entry",
                station_id="B",
                entry_to_platform_entry_seconds=1.0,
                min_platform_entry_to_platform_exit_seconds=1.0,
                platform_exit_to_exit_switch_seconds=1.0,
                skip_entry_to_exit_switch_seconds=3.0,
                rope_to_next_switch_seconds=5.0,
                skip_allowed=False,
            ),
        ),
        cabin_starts=(
            EanCabinStart(
                cabin_id=0,
                first_switch_id="A_entry",
                kind=EanCabinStartKind.FIXED,
                time_seconds=0.0,
            ),
        ),
        switch_visits=tuple(
            SwitchVisitDefinition(
                cabin_id=0,
                visit_index=visit_index,
                switch_id=("A_entry", "B_entry")[visit_index % 2],
            )
            for visit_index in range(cycle_count * 2)
        ),
        switch_transitions=(
            SwitchTransition(from_switch_id="A_entry", to_switch_id="B_entry", min_seconds=5.0, max_seconds=5.0),
            SwitchTransition(from_switch_id="B_entry", to_switch_id="A_entry", min_seconds=5.0, max_seconds=5.0),
        ),
        headway_checkpoints=(
            HeadwayCheckpointDefinition(
                id="platform_entry::A_entry",
                kind=HeadwayCheckpointKind.PLATFORM_ENTRY,
                switch_id="A_entry",
                station_id="A",
                headway_seconds=1.0,
                applies_to_serve=True,
                applies_to_skip=False,
                waiting_modes=(station_a_waiting_mode,),
            ),
        ),
        headway_candidates=(
            HeadwayCandidate(
                id="candidate::platform_entry::A_entry::cabin_0::visit_0",
                checkpoint_id="platform_entry::A_entry",
                cabin_id=0,
                visit_index=0,
                time_reference=EanTimeReference.PLATFORM_ENTRY_TIME,
                activation_reference=EanActivationReference.SERVE,
            ),
        ),
        headway_pairs=(),
    )
