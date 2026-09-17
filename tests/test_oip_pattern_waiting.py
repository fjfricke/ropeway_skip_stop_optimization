import json
from dataclasses import replace
from datetime import date, datetime, timedelta

import pytest
from ortools.sat.python import cp_model

from ropeway_skip_stop_optimization.benchmarking.oip_pattern_waiting import (
    prepare_oip_pattern_waiting_pilot,
)


def test_frontend_export_preserves_zero_and_absent_incumbent_values(tmp_path):
    from ropeway_skip_stop_optimization.optimization.oip.cp_sat import OipCpSatResult
    from ropeway_skip_stop_optimization.optimization.oip.runner import (
        OipRunConfig,
        _write_frontend_snapshot,
    )

    prepared = prepare_oip_pattern_waiting_pilot(
        maximum_wait_seconds=0, cabin_count=2
    )
    result = OipCpSatResult(
        status="feasible", solver_status="FEASIBLE", objective_value=0,
        best_bound=0, gap=0.0, runtime_seconds=0.1, build_seconds=0.05,
        movement_plan=None, fleet_plan=None, passenger_plan=None,
        served_passengers=sum(d.count for d in prepared.domain.scenario.demands),
        unserved_passengers=0, journey_time_seconds=0.0, model_stats="",
    )
    _write_frontend_snapshot(tmp_path, prepared.domain, OipRunConfig(), result)
    detail = json.loads((tmp_path / "detail.json").read_text())
    assert detail["latest"]["ub"] == 0
    assert detail["latest"]["unserved"] == 0
    assert detail["latest"]["journey_time_seconds"] == 0.0
    assert detail["latest"]["used_fleet"] is None


def test_live_placeholder_reports_waiting_contract(tmp_path):
    from ropeway_skip_stop_optimization.optimization.oip.runner import (
        OipRunConfig,
        _write_live_files,
    )

    _write_live_files(tmp_path, _small_domain(120), OipRunConfig(movement_only=True), [])
    detail = json.loads((tmp_path / "detail.json").read_text())
    assert detail["maximum_wait_seconds"] == 120
    assert "Waiting≤120s" in detail["subtitle"]
from ropeway_skip_stop_optimization.examples.three_station import (
    ThreeStationOptimizedInitialPlacementExample,
)
from ropeway_skip_stop_optimization.models import Demand
from ropeway_skip_stop_optimization.optimization.ean import (
    EanFleetCardinalityMode,
    StationWaitingMode,
    validate_ean_initial_boundary_against_artifact,
    validate_ean_movement_plan_against_artifact,
)
from ropeway_skip_stop_optimization.optimization.oip import (
    OipBackend,
    OipRunConfig,
    prepare_oip_domain,
    run_oip,
)
from ropeway_skip_stop_optimization.optimization.oip.cp_sat import (
    _extract_movement,
    build_oip_cp_sat_model,
)
from ropeway_skip_stop_optimization.optimization.oip.validation import (
    validate_oip_movement_certificate,
)


def _small_domain(maximum_wait_seconds: float, cabin_count: int = 1):
    example = ThreeStationOptimizedInitialPlacementExample()
    scenario = example.build_scenario()
    config = example.build_ean_config(scenario)
    config = replace(
        config,
        station_configs=tuple(
            replace(
                item,
                waiting_mode=(
                    StationWaitingMode.NO_WAITING
                    if maximum_wait_seconds == 0
                    else StationWaitingMode.END_OF_PLATFORM_WAIT
                ),
                max_wait_seconds=(
                    None if maximum_wait_seconds == 0 else maximum_wait_seconds
                ),
            )
            for item in config.station_configs
        ),
    )
    builder = example.build_ean_artifact_builder(scenario, config)
    builder = replace(
        builder,
        fleet_config=replace(
            builder.fleet_config,
            available_fleet_count=cabin_count,
            cardinality_mode=EanFleetCardinalityMode.EXACT,
        ),
    )
    return prepare_oip_domain(
        scenario=scenario,
        artifact=builder.build(scenario, config),
        fixed_k=cabin_count,
    )


def test_waiting_cp_sat_can_use_positive_millisecond_and_validates() -> None:
    domain = _small_domain(120.0)
    built = build_oip_cp_sat_model(domain, movement_only=True)
    built.model.add(sum(built.movement.wait_time.values()) >= 1)
    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = 5
    status = solver.solve(built.model)
    assert status in (cp_model.OPTIMAL, cp_model.FEASIBLE)
    movement, fleet = _extract_movement(built, solver)
    assert any(
        visit.wait_seconds >= 0.001
        for trajectory in movement.trajectories
        for visit in trajectory.visits
    )
    validate_ean_movement_plan_against_artifact(
        domain.artifact, movement, tolerance_seconds=0.0011
    ).raise_for_errors()
    validate_ean_initial_boundary_against_artifact(
        domain.artifact, movement, fleet, tolerance_seconds=0.0011
    ).raise_for_errors()


def test_skip_cannot_wait_and_no_wait_has_zero_domains() -> None:
    waiting = _small_domain(120.0)
    built = build_oip_cp_sat_model(waiting, movement_only=True)
    key = next(
        key
        for key in built.movement.stop
        if next(
            timing
            for timing in waiting.artifact.timings
            if timing.switch_id
            == next(
                visit
                for visit in waiting.artifact.switch_visits
                if (visit.cabin_id, visit.visit_index) == key
            ).switch_id
        ).skip_allowed
    )
    built.model.add(built.movement.route_active[key] == 1)
    built.model.add(built.movement.stop[key] == 0)
    built.model.add(built.movement.wait_time[key] >= 1)
    assert cp_model.CpSolver().solve(built.model) == cp_model.INFEASIBLE

    no_wait = build_oip_cp_sat_model(_small_domain(0.0), movement_only=True)
    assert all(
        list(variable.proto.domain) == [0, 0]
        for variable in no_wait.movement.wait_time.values()
    )


def test_waiting_cp_sat_accepts_the_exact_maximum() -> None:
    domain = _small_domain(120.0)
    built = build_oip_cp_sat_model(domain, movement_only=True)
    key = next(iter(built.movement.wait_time))
    built.model.add(built.movement.route_active[key] == 1)
    built.model.add(built.movement.stop[key] == 1)
    built.model.add(built.movement.wait_time[key] == 120_000)
    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = 5
    assert solver.solve(built.model) in (cp_model.OPTIMAL, cp_model.FEASIBLE)


def test_waiting_straddling_zero_exports_platform_wait_state() -> None:
    domain = _small_domain(120.0)
    built = build_oip_cp_sat_model(domain, movement_only=True)
    key = next(iter(built.movement.station_selected))
    visit = next(
        item
        for item in domain.artifact.switch_visits
        if (item.cabin_id, item.visit_index) == key
    )
    timing = next(
        item for item in domain.artifact.timings if item.switch_id == visit.switch_id
    )
    earliest_exit_offset = domain.grid.lower_tick(
        timing.entry_to_platform_entry_seconds
        + timing.min_platform_entry_to_platform_exit_seconds
    )
    built.model.add(built.movement.station_selected[key] == 1)
    built.model.add(built.movement.switch_time[key] == -earliest_exit_offset)
    built.model.add(built.movement.wait_time[key] == 1_000)
    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = 5
    assert solver.solve(built.model) in (cp_model.OPTIMAL, cp_model.FEASIBLE)
    movement, fleet = _extract_movement(built, solver)
    assert fleet.initial_states[0].kind.value == "platform_wait"
    validate_ean_initial_boundary_against_artifact(
        domain.artifact, movement, fleet, tolerance_seconds=0.0011
    ).raise_for_errors()


def test_rope_initial_state_exports_the_pre_boundary_switch() -> None:
    domain = _small_domain(0.0)
    built = build_oip_cp_sat_model(domain, movement_only=True)
    key = next(iter(built.movement.rope_selected))
    built.model.add(built.movement.rope_selected[key] == 1)
    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = 5
    assert solver.solve(built.model) in (cp_model.OPTIMAL, cp_model.FEASIBLE)
    movement, fleet = _extract_movement(built, solver)
    state = fleet.initial_states[0]
    assert state.kind.value == "rope"
    assert state.switch_id == domain.artifact.circulation_state_ids[
        (state.visit_index - 1) % len(domain.artifact.circulation_state_ids)
    ]
    validate_ean_initial_boundary_against_artifact(
        domain.artifact, movement, fleet, tolerance_seconds=0.0011
    ).raise_for_errors()


def test_fixed_initial_conditions_need_waiting_to_heal_a_merge() -> None:
    no_wait_domain = _small_domain(0.0, cabin_count=2)
    waiting_domain = _small_domain(120.0, cabin_count=2)
    stations = tuple(
        dict.fromkeys(item.station_id for item in waiting_domain.artifact.timings)
    )
    patterns = (stations, tuple(station for station in stations if station != "M"))

    def solve(domain):
        built = build_oip_cp_sat_model(
            domain, movement_only=True, fixed_stop_patterns=patterns
        )
        built.model.add(built.movement.station_selected[0, 0] == 1)
        built.model.add(built.movement.station_selected[1, 0] == 1)
        built.model.add(built.movement.switch_time[0, 0] == -24_181)
        built.model.add(built.movement.switch_time[1, 0] == -3_930)
        solver = cp_model.CpSolver()
        solver.parameters.max_time_in_seconds = 5
        solver.parameters.num_search_workers = 1
        return built, solver, solver.solve(built.model)

    _, _, no_wait_status = solve(no_wait_domain)
    assert no_wait_status == cp_model.INFEASIBLE
    built, solver, waiting_status = solve(waiting_domain)
    assert waiting_status in (cp_model.OPTIMAL, cp_model.FEASIBLE)
    movement, fleet = _extract_movement(built, solver)
    assert any(
        visit.wait_seconds > 0
        for trajectory in movement.trajectories
        for visit in trajectory.visits
    )
    validate_oip_movement_certificate(waiting_domain, movement, fleet)


@pytest.mark.parametrize("encoding", ["od_inventory", "groups"])
def test_release_during_wait_boards_at_actual_platform_exit(encoding) -> None:
    original = _small_domain(120.0)
    anchor = datetime.combine(date(2000, 1, 2), original.scenario.service_start_time)
    scenario = replace(
        original.scenario,
        demands=(
            Demand(
                arrival_time=(anchor + timedelta(milliseconds=500)).time(),
                origin="M",
                destination="R",
                count=1,
            ),
        ),
    )
    domain = prepare_oip_domain(
        scenario=scenario,
        artifact=original.artifact,
        fixed_k=1,
    )
    built = build_oip_cp_sat_model(
        domain, passenger_encoding=encoding, movement_only=False
    )
    key = (0, 0)
    visit = next(
        item
        for item in domain.artifact.switch_visits
        if (item.cabin_id, item.visit_index) == key
    )
    timing = next(
        item for item in domain.artifact.timings if item.switch_id == visit.switch_id
    )
    earliest_exit_offset = domain.grid.lower_tick(
        timing.entry_to_platform_entry_seconds
        + timing.min_platform_entry_to_platform_exit_seconds
    )
    built.model.add(built.movement.station_selected[key] == 1)
    built.model.add(built.movement.switch_time[key] == -earliest_exit_offset)
    built.model.add(built.movement.wait_time[key] == 1_000)
    ride_id = next(
        ride_id
        for ride_id, ride in built.passengers.rides.items()
        if ride.cabin_id == 0 and ride.board_visit_index == 0
    )
    built.model.add(built.passengers.ride_count[ride_id] == 1)
    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = 5
    assert solver.solve(built.model) in (cp_model.OPTIMAL, cp_model.FEASIBLE)
    assert solver.value(built.passengers.board_time[ride_id]) == 1_000


def test_frozen_pilot_contract_and_pattern_counts() -> None:
    prepared = prepare_oip_pattern_waiting_pilot(maximum_wait_seconds=120)
    assert prepared.cycle_seconds == pytest.approx(732)
    assert prepared.demand_window_seconds == pytest.approx(1464)
    assert prepared.passenger_horizon_seconds == pytest.approx(2364)
    assert prepared.operation_seconds == pytest.approx(2664)
    assert sum(item.count for item in prepared.domain.scenario.demands) == 3210
    assert len(prepared.pattern_mixes["all_stop"]) == 62
    mixed = prepared.pattern_mixes["mixed"]
    all_stop = tuple(dict.fromkeys(item.station_id for item in prepared.domain.artifact.timings))
    assert mixed.count(("S1", "S3")) == 16
    assert mixed.count(("S2", "S4")) == 16
    assert mixed.count(all_stop) == 30


def test_movement_run_persists_independent_passenger_evaluation(tmp_path) -> None:
    import json

    domain = _small_domain(0.0)
    stations = tuple(dict.fromkeys(item.station_id for item in domain.artifact.timings))
    run_oip(
        domain,
        OipRunConfig(
            backend=OipBackend.CP_SAT,
            movement_only=True,
            fixed_stop_patterns=(stations,),
            time_limit_seconds=5,
            workers=1,
            passenger_evaluation_time_limit_seconds=5,
            output_directory=tmp_path,
        ),
    )
    payload = json.loads((tmp_path / "result.json").read_text())
    evaluation = payload["passenger_evaluation"]
    assert evaluation["passenger_plan"] is not None
    assert (
        evaluation["served_passengers"] + evaluation["unserved_passengers"]
        == sum(item.count for item in domain.scenario.demands)
    )
    assert payload["maximum_used_wait_seconds"] == 0
    assert payload["total_used_wait_seconds"] == 0
    assert (tmp_path / "movement_certificate.json").is_file()


def test_integrated_fixed_pattern_cp_sat_accepts_movement_checkpoint_hint(
    tmp_path,
) -> None:
    domain = _small_domain(0.0)
    stations = tuple(
        dict.fromkeys(item.station_id for item in domain.artifact.timings)
    )
    screening = tmp_path / "screening"
    refinement = tmp_path / "refinement"
    run_oip(
        domain,
        OipRunConfig(
            backend=OipBackend.CP_SAT,
            movement_only=True,
            fixed_stop_patterns=(stations,),
            time_limit_seconds=5,
            workers=1,
            passenger_evaluation_time_limit_seconds=5,
            output_directory=screening,
        ),
    )
    result = run_oip(
        domain,
        OipRunConfig(
            backend=OipBackend.CP_SAT,
            movement_only=False,
            fixed_stop_patterns=(stations,),
            time_limit_seconds=5,
            workers=1,
            start_checkpoint_directory=screening,
            output_directory=refinement,
        ),
    )
    assert result.movement_plan is not None
    assert result.passenger_plan is not None
    assert result.served_passengers is not None
    assert all(
        visit.decision.value == "stop"
        for trajectory in result.movement_plan.trajectories
        for visit in trajectory.visits
    )


def test_integrated_fixed_patterns_reject_gurobi_until_supported() -> None:
    with pytest.raises(ValueError, match="only by CP-SAT"):
        OipRunConfig(
            backend=OipBackend.GUROBI,
            movement_only=False,
            fixed_stop_patterns=(("L", "M", "R"),),
        ).validate()


def test_thesis_od_inventory_checkpoint_exports_chronological_release_matching(
    tmp_path,
) -> None:
    prepared = prepare_oip_pattern_waiting_pilot(
        maximum_wait_seconds=0,
        demand_total=10,
        cabin_count=1,
    )
    patterns = prepared.pattern_mixes["all_stop"]
    screening = tmp_path / "screening"
    run_oip(
        prepared.domain,
        OipRunConfig(
            backend=OipBackend.CP_SAT,
            movement_only=True,
            fixed_stop_patterns=patterns,
            time_limit_seconds=5,
            workers=1,
            passenger_evaluation_time_limit_seconds=5,
            output_directory=screening,
        ),
    )
    refined = run_oip(
        prepared.domain,
        OipRunConfig(
            backend=OipBackend.CP_SAT,
            fixed_stop_patterns=patterns,
            time_limit_seconds=5,
            workers=1,
            start_checkpoint_directory=screening,
        ),
    )
    assert refined.passenger_plan is not None
    assert refined.served_passengers == 10


@pytest.mark.parametrize("backend", [OipBackend.CP_SAT, OipBackend.GUROBI])
def test_waiting_movement_contract_is_shared_by_both_solvers(backend) -> None:
    domain = _small_domain(120.0)
    stations = tuple(dict.fromkeys(item.station_id for item in domain.artifact.timings))
    result = run_oip(
        domain,
        OipRunConfig(
            backend=backend,
            movement_only=True,
            fixed_stop_patterns=(stations,),
            time_limit_seconds=5,
            workers=1,
        ),
    )
    assert result.movement_plan is not None
    assert result.fleet_plan is not None
    validate_oip_movement_certificate(
        domain, result.movement_plan, result.fleet_plan
    )
    assert all(
        0 <= visit.wait_seconds <= 120
        for trajectory in result.movement_plan.trajectories
        for visit in trajectory.visits
    )
