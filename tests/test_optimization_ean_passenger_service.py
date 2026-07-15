from __future__ import annotations

from datetime import time

import pytest

from ropeway_skip_stop_optimization.models import Demand, OperatingParameters, Scenario
from ropeway_skip_stop_optimization.optimization.ean import (
    EanCabinStart,
    EanCabinStartKind,
    EanConfig,
    EanDemandGroup,
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
    EanFormulationConfig,
    EanHorizonFormulation,
    EanTimeBoundFormulation,
    EanPassengerServiceConfig,
    EanPassengerServiceObjective,
    EanRideCandidate,
    EanStopSkipTimingFormulation,
    GurobiSolverPolicy,
    solve_ean_passenger_service,
)
from ropeway_skip_stop_optimization.optimization.ean.time_bounds import (
    build_ean_model_time_bounds,
)
from ropeway_skip_stop_optimization.optimization.ean.formulation_config import (
    HORIZON_ACTIVATION_EPSILON_SECONDS,
)
from ropeway_skip_stop_optimization.optimization.ean.horizon import (
    add_visit_horizon_activation,
)
from ropeway_skip_stop_optimization.optimization.ean.optimizers.passenger_service import (
    StopSkipBigMBounds,
    _headway_time_expressions,
    _min_candidate_trip_time_seconds,
    _solver_diagnostics,
    _slot_release_big_m,
    _stop_skip_big_m_bounds,
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


def test_headway_time_expressions_use_wait_occupancy_for_platform_exit_waiting() -> None:
    candidate = HeadwayCandidate(
        id="candidate::platform_exit::A_entry::cabin_0::visit_0",
        checkpoint_id="platform_exit::A_entry",
        cabin_id=0,
        visit_index=0,
        time_reference=EanTimeReference.PLATFORM_EXIT_TIME,
        activation_reference=EanActivationReference.SERVE,
    )
    checkpoint = HeadwayCheckpointDefinition(
        id="platform_exit::A_entry",
        kind=HeadwayCheckpointKind.PLATFORM_EXIT,
        switch_id="A_entry",
        station_id="A",
        headway_seconds=2.0,
        applies_to_serve=True,
        applies_to_skip=False,
        waiting_modes=(StationWaitingMode.END_OF_PLATFORM_WAIT,),
    )
    timing = SkipStopTiming(
        switch_id="A_entry",
        station_id="A",
        entry_to_platform_entry_seconds=1.0,
        min_platform_entry_to_platform_exit_seconds=2.0,
        platform_exit_to_exit_switch_seconds=1.0,
        skip_entry_to_exit_switch_seconds=4.0,
        rope_to_next_switch_seconds=5.0,
        skip_allowed=True,
    )
    key = (0, 0)

    times = _headway_time_expressions(
        candidate=candidate,
        checkpoint=checkpoint,
        station_config=StationEanConfig(station_id="A", waiting_mode=StationWaitingMode.END_OF_PLATFORM_WAIT),
        switch_time={key: 100.0},
        exit_switch_time={key: 109.0},
        wait_time={key: 5.0},
        visits_by_key={key: SwitchVisitDefinition(cabin_id=0, visit_index=0, switch_id="A_entry")},
        timing_by_switch_id={"A_entry": timing},
    )

    assert times.follower_enter_time == pytest.approx(103.0)
    assert times.leader_clear_time == pytest.approx(108.0)
    assert times.semantics_label == "platform_exit_wait_occupancy"


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


def test_ean_passenger_service_tight_big_m_bounds_preserves_minimal_solution() -> None:
    pytest.importorskip("gurobipy")
    scenario = _minimal_scenario(
        demands=(Demand(arrival_time=time(8, 0), origin="A", destination="B", count=1),),
    )
    artifact = _minimal_artifact(cabin_capacity=2, cycle_count=2)

    baseline = solve_ean_passenger_service(
        scenario,
        artifact,
        EanPassengerServiceConfig(objective=EanPassengerServiceObjective.JOURNEY_TIME),
    )
    tightened = solve_ean_passenger_service(
        scenario,
        artifact,
        EanPassengerServiceConfig(
            objective=EanPassengerServiceObjective.JOURNEY_TIME,
            optimization_config=EanOptimizationConfig(enable_tight_big_m_bounds=True),
        ),
    )

    assert tightened.metadata.status == "optimal"
    assert tightened.metadata.objective_value_seconds == pytest.approx(baseline.metadata.objective_value_seconds)
    assert tightened.metadata.served_passenger_count == baseline.metadata.served_passenger_count
    assert tightened.metadata.unserved_passenger_count == baseline.metadata.unserved_passenger_count
    assert tightened.passenger_plan is not None
    assert baseline.passenger_plan is not None
    assert tightened.passenger_plan.unserved_counts_by_demand_group_id == (
        baseline.passenger_plan.unserved_counts_by_demand_group_id
    )
    assert tightened.metadata.optimization_config.enable_tight_big_m_bounds


@pytest.mark.parametrize(
    "objective",
    (
        EanPassengerServiceObjective.WAITING_TIME,
        EanPassengerServiceObjective.JOURNEY_TIME,
    ),
)
def test_affine_stop_skip_timing_preserves_minimal_solution(
    objective: EanPassengerServiceObjective,
) -> None:
    pytest.importorskip("gurobipy")
    scenario = _minimal_scenario(
        demands=(Demand(arrival_time=time(8, 0), origin="A", destination="B", count=1),),
    )
    artifact = _minimal_artifact(cabin_capacity=2, cycle_count=2)

    baseline = solve_ean_passenger_service(
        scenario,
        artifact,
        EanPassengerServiceConfig(objective=objective),
    )
    affine = solve_ean_passenger_service(
        scenario,
        artifact,
        EanPassengerServiceConfig(
            objective=objective,
            optimization_config=EanOptimizationConfig(
                formulation=EanFormulationConfig(
                    stop_skip_timing=EanStopSkipTimingFormulation.AFFINE,
                )
            ),
        ),
    )

    assert affine.metadata.status == "optimal"
    assert affine.metadata.objective_value_seconds == pytest.approx(
        baseline.metadata.objective_value_seconds
    )
    assert affine.metadata.served_passenger_count == baseline.metadata.served_passenger_count
    assert affine.metadata.unserved_passenger_count == baseline.metadata.unserved_passenger_count
    assert affine.metadata.constraint_count < baseline.metadata.constraint_count


@pytest.mark.parametrize(
    "horizon_formulation",
    (
        EanHorizonFormulation.CONSERVATIVE_FREE_SUFFIX,
        EanHorizonFormulation.EXACT_TIME_ACTIVATION,
    ),
)
def test_ean_passenger_service_extracts_only_operational_visit_prefix(
    horizon_formulation: EanHorizonFormulation,
) -> None:
    pytest.importorskip("gurobipy")
    scenario = _minimal_scenario(
        demands=(Demand(arrival_time=time(8, 0), origin="A", destination="B", count=1),),
    )
    artifact = _minimal_artifact(cabin_capacity=2, cycle_count=3)
    config = EanOptimizationConfig(
        formulation=EanFormulationConfig(
            horizon=horizon_formulation,
            time_bounds=EanTimeBoundFormulation.DERIVED_VISIT_BOUNDS,
        )
    )

    result = solve_ean_passenger_service(
        scenario,
        artifact,
        EanPassengerServiceConfig(
            objective=EanPassengerServiceObjective.JOURNEY_TIME,
            optimization_config=config,
        ),
    )

    assert result.metadata.status == "optimal"
    assert result.metadata.objective_value_seconds == pytest.approx(9.0)
    assert result.movement_plan is not None
    assert result.movement_plan.horizon_formulation is horizon_formulation
    assert tuple(
        visit.visit_index
        for visit in result.movement_plan.trajectories[0].visits
    ) == (0, 1, 2)


def test_derived_visit_bounds_allow_waiting_beyond_legacy_ten_second_slack() -> None:
    artifact = _minimal_artifact(
        cabin_capacity=2,
        cycle_count=2,
        station_waiting_modes={"A": StationWaitingMode.END_OF_PLATFORM_WAIT},
    )

    bounds = build_ean_model_time_bounds(
        artifact,
        EanTimeBoundFormulation.DERIVED_VISIT_BOUNDS,
    )

    assert bounds.by_visit[(0, 0)].wait_upper == pytest.approx(
        artifact.config.operational_end_seconds
    )
    assert bounds.by_visit[(0, 0)].wait_upper > 10.0
    assert bounds.by_visit[(0, 1)].switch_upper > bounds.by_visit[(0, 0)].switch_upper


def test_derived_visit_bounds_allow_earliest_start_after_operational_horizon() -> None:
    artifact = _artifact_with_earliest_start(
        _minimal_artifact(cabin_capacity=2)
    )

    bounds = build_ean_model_time_bounds(
        artifact,
        EanTimeBoundFormulation.DERIVED_VISIT_BOUNDS,
    )

    assert bounds.by_visit[(0, 0)].switch_upper > (
        artifact.config.operational_end_seconds
    )


def test_exact_horizon_activation_allows_empty_earliest_start_prefix() -> None:
    gp = pytest.importorskip("gurobipy")
    artifact = _artifact_with_earliest_start(_minimal_artifact(cabin_capacity=2))
    bounds = build_ean_model_time_bounds(
        artifact,
        EanTimeBoundFormulation.DERIVED_VISIT_BOUNDS,
    )
    visits = tuple(
        sorted(artifact.switch_visits, key=lambda visit: visit.visit_index)
    )
    model = gp.Model()
    model.Params.OutputFlag = 0
    switch_time = {
        (visit.cabin_id, visit.visit_index): model.addVar(
            lb=bounds.by_visit[(visit.cabin_id, visit.visit_index)].switch_lower,
            ub=bounds.by_visit[(visit.cabin_id, visit.visit_index)].switch_upper,
        )
        for visit in visits
    }
    active = add_visit_horizon_activation(
        model=model,
        binary_vtype=gp.GRB.BINARY,
        artifact=artifact,
        formulation=EanHorizonFormulation.EXACT_TIME_ACTIVATION,
        switch_time=switch_time,
        visits_by_cabin_id={0: visits},
        selected_time_bounds=bounds,
        big_m=bounds.global_upper + 1.0,
    )
    model.addConstr(
        switch_time[(0, 0)]
        >= artifact.config.operational_end_seconds
        + HORIZON_ACTIVATION_EPSILON_SECONDS
    )

    model.optimize()

    assert model.Status == gp.GRB.OPTIMAL
    assert active[(0, 0)].X == pytest.approx(0.0)
    assert active[(0, 1)].X == pytest.approx(0.0)


def test_slot_release_big_m_can_use_release_time_when_tightened() -> None:
    group = EanDemandGroup(
        id="demand::0",
        origin_station_id="A",
        destination_station_id="B",
        release_time_seconds=15.0,
        count=1,
    )

    assert _slot_release_big_m(
        group=group,
        global_big_m=100.0,
        enable_tight_big_m_bounds=False,
    ) == pytest.approx(100.0)
    assert _slot_release_big_m(
        group=group,
        global_big_m=100.0,
        enable_tight_big_m_bounds=True,
    ) == pytest.approx(15.0)


def test_stop_skip_big_m_bounds_return_global_m_when_disabled() -> None:
    timing = _timing(service_seconds=6.0, skip_seconds=4.0)
    station_config = StationEanConfig(station_id="A", waiting_mode=StationWaitingMode.NO_WAITING)

    assert _stop_skip_big_m_bounds(
        timing=timing,
        station_config=station_config,
        time_upper_bound=20.0,
        global_big_m=100.0,
        enable_tight_big_m_bounds=False,
    ) == StopSkipBigMBounds(
        service_exit_ub=100.0,
        service_exit_lb=100.0,
        skip_exit_ub=100.0,
        skip_exit_lb=100.0,
    )


def test_stop_skip_big_m_bounds_tighten_no_waiting_station() -> None:
    timing = _timing(service_seconds=6.0, skip_seconds=4.0)
    station_config = StationEanConfig(station_id="A", waiting_mode=StationWaitingMode.NO_WAITING)

    assert _stop_skip_big_m_bounds(
        timing=timing,
        station_config=station_config,
        time_upper_bound=20.0,
        global_big_m=100.0,
        enable_tight_big_m_bounds=True,
    ) == StopSkipBigMBounds(
        service_exit_ub=0.0,
        service_exit_lb=2.0,
        skip_exit_ub=2.0,
        skip_exit_lb=0.0,
    )


def test_stop_skip_big_m_bounds_tighten_end_of_platform_wait_station() -> None:
    timing = _timing(service_seconds=6.0, skip_seconds=4.0)
    station_config = StationEanConfig(
        station_id="A",
        waiting_mode=StationWaitingMode.END_OF_PLATFORM_WAIT,
    )

    assert _stop_skip_big_m_bounds(
        timing=timing,
        station_config=station_config,
        time_upper_bound=20.0,
        global_big_m=100.0,
        enable_tight_big_m_bounds=True,
    ) == StopSkipBigMBounds(
        service_exit_ub=0.0,
        service_exit_lb=2.0,
        skip_exit_ub=16.0,
        skip_exit_lb=0.0,
    )


def test_stop_skip_big_m_bounds_allow_zero_values() -> None:
    timing = _timing(service_seconds=4.0, skip_seconds=4.0)
    station_config = StationEanConfig(station_id="A", waiting_mode=StationWaitingMode.NO_WAITING)

    assert _stop_skip_big_m_bounds(
        timing=timing,
        station_config=station_config,
        time_upper_bound=20.0,
        global_big_m=100.0,
        enable_tight_big_m_bounds=True,
    ) == StopSkipBigMBounds(
        service_exit_ub=0.0,
        service_exit_lb=0.0,
        skip_exit_ub=0.0,
        skip_exit_lb=0.0,
    )


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


def _artifact_with_earliest_start(
    artifact: EanBuildArtifact,
) -> EanBuildArtifact:
    return EanBuildArtifact(
        scenario_id=artifact.scenario_id,
        config=artifact.config,
        switch_cycle=artifact.switch_cycle,
        timings=artifact.timings,
        cabin_starts=(
            EanCabinStart(
                cabin_id=0,
                first_switch_id="A_entry",
                kind=EanCabinStartKind.EARLIEST,
                time_seconds=0.0,
            ),
        ),
        switch_visits=artifact.switch_visits,
        switch_transitions=artifact.switch_transitions,
        headway_checkpoints=artifact.headway_checkpoints,
        headway_candidates=artifact.headway_candidates,
        headway_pairs=artifact.headway_pairs,
    )


def _timing(service_seconds: float, skip_seconds: float) -> SkipStopTiming:
    entry_seconds = 1.0
    min_platform_seconds = 1.0
    platform_exit_seconds = service_seconds - entry_seconds - min_platform_seconds
    if platform_exit_seconds <= 0:
        raise ValueError("service_seconds must be greater than 2")
    return SkipStopTiming(
        switch_id="A_entry",
        station_id="A",
        entry_to_platform_entry_seconds=entry_seconds,
        min_platform_entry_to_platform_exit_seconds=min_platform_seconds,
        platform_exit_to_exit_switch_seconds=platform_exit_seconds,
        skip_entry_to_exit_switch_seconds=skip_seconds,
        rope_to_next_switch_seconds=5.0,
        skip_allowed=True,
    )
