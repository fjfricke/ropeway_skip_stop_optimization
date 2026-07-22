from __future__ import annotations

from dataclasses import replace

import pytest

from ropeway_skip_stop_optimization.examples.circular_skip_stop import (
    FiveStationOptimizedInitialPlacementAllStopSkipWaitExample,
    FiveStationOptimizedInitialPlacementDoubleAllStopSkipWaitExample,
    FiveStationOptimizedInitialPlacementNoSkipNoWaitExample,
    FiveStationOptimizedInitialPlacementSkipNoWaitExample,
)
from ropeway_skip_stop_optimization.examples.registry import get_example
from ropeway_skip_stop_optimization.examples.three_station import (
    ThreeStationOptimizedInitialPlacementExample,
)
from ropeway_skip_stop_optimization.examples.three_station_ean import (
    build_three_station_ean_config,
    build_three_station_ean_ring_switch_order,
)
from ropeway_skip_stop_optimization.optimization.ean import (
    EanFleetPlan,
    EanFleetConfig,
    EanFleetMode,
    EanFormulationConfig,
    EanHorizonFormulation,
    EanInitialPlacementStateKind,
    EanMipStartStrategy,
    EanPassengerCandidateBuilder,
    EanPassengerObjective,
    EanPassengerServiceProblem,
    EanPhysicalEventKind,
    EanMovementFeasibilityProblem,
    EanOptimizer,
    EanSolveConfig,
    EanTimeBoundFormulation,
    EvenlySpacedAllStopCabinStartBuilder,
    GurobiSolverPolicy,
    NetworkEanBuildArtifactBuilder,
    network_ean_builder_for_cycle,
    StationWaitingMode,
    project_ean_movement_plan_to_physical_replay,
    validate_ean_movement_plan_against_artifact,
)
from ropeway_skip_stop_optimization.optimization.ean.fleet import (
    EanInitialPlacementState,
)
from ropeway_skip_stop_optimization.optimization.ean.optimization_config import (
    EanOptimizationConfig,
    EanOptimizationName,
)
from ropeway_skip_stop_optimization.optimization.ean.optimizers.movement_model import (
    EanMovementModelBuilder,
)
from ropeway_skip_stop_optimization.optimization.ean.optimizers.all_stop_mip_start import (
    EanAllStopMipStartSeedBuilder,
)
from ropeway_skip_stop_optimization.optimization.ean.optimizers.passenger_model import (
    EanPassengerModelBuilder,
    _var_id,
)


def test_five_station_initial_placement_examples_use_explicit_fleet_limits() -> None:
    skip = _artifact(FiveStationOptimizedInitialPlacementSkipNoWaitExample())
    no_skip = _artifact(FiveStationOptimizedInitialPlacementNoSkipNoWaitExample())

    assert skip.fleet_mode is EanFleetMode.OPTIMIZED_INITIAL_PLACEMENT
    assert no_skip.fleet_mode is EanFleetMode.OPTIMIZED_INITIAL_PLACEMENT
    assert skip.initial_placement_parameters is not None
    assert no_skip.initial_placement_parameters is not None
    assert skip.initial_placement_parameters.available_fleet_count == 8
    assert no_skip.initial_placement_parameters.available_fleet_count == 8
    assert isinstance(
        get_example("five_station_optimized_initial_placement_skip_no_wait_v0"),
        FiveStationOptimizedInitialPlacementSkipNoWaitExample,
    )
    double = FiveStationOptimizedInitialPlacementDoubleAllStopSkipWaitExample()
    double_scenario = double.build_scenario()
    double_config = double.build_ean_config(double_scenario)
    double_builder = double.build_ean_artifact_builder(
        double_scenario,
        double_config,
    )
    assert double_builder.fleet_config.available_fleet_count == 76
    all_stop = FiveStationOptimizedInitialPlacementAllStopSkipWaitExample()
    all_stop_scenario = all_stop.build_scenario()
    all_stop_config = all_stop.build_ean_config(all_stop_scenario)
    assert (
        all_stop.build_ean_artifact_builder(
            all_stop_scenario,
            all_stop_config,
        ).fleet_config.available_fleet_count
        == 38
    )
    assert {
        station_config.waiting_mode
        for station_config in double_config.station_configs
    } == {StationWaitingMode.END_OF_PLATFORM_WAIT}
    assert isinstance(
        get_example(
            "five_station_optimized_initial_placement_double_all_stop_skip_wait_v0"
        ),
        FiveStationOptimizedInitialPlacementDoubleAllStopSkipWaitExample,
    )


def test_initial_placement_requires_explicit_positive_k() -> None:
    with pytest.raises(ValueError, match="available_fleet_count"):
        EanFleetConfig(
            mode=EanFleetMode.OPTIMIZED_INITIAL_PLACEMENT,
        ).validate()


@pytest.mark.parametrize(
    ("active_ids", "inactive_ids", "states", "message"),
    (
        ((0, 0), (1,), (), "active cabin ids must be unique"),
        ((0,), (1, 1), (), "inactive cabin ids must be unique"),
        (
            (0,),
            (1,),
            (
                EanInitialPlacementState(
                    cabin_id=0,
                    kind=EanInitialPlacementStateKind.ENTRY_SWITCH,
                    switch_id="entry",
                    visit_index=0,
                    progress=0.0,
                    previous_event_time_seconds=0.0,
                    next_event_time_seconds=0.0,
                ),
            )
            * 2,
            "initial-state cabin ids must be unique",
        ),
    ),
)
def test_fleet_plan_rejects_duplicate_cabin_membership(
    active_ids,
    inactive_ids,
    states,
    message: str,
) -> None:
    with pytest.raises(ValueError, match=message):
        EanFleetPlan(
            mode=EanFleetMode.OPTIMIZED_INITIAL_PLACEMENT,
            available_fleet_count=2,
            active_cabin_ids=active_ids,
            inactive_cabin_ids=inactive_ids,
            initial_states=states,
        ).validate()


def test_explicit_k_changes_only_the_potential_fleet_count() -> None:
    example = FiveStationOptimizedInitialPlacementNoSkipNoWaitExample()
    default = _artifact(example)
    limited = _artifact(example, available_fleet_count=3)

    assert default.initial_placement_parameters is not None
    assert limited.initial_placement_parameters is not None
    assert limited.initial_placement_parameters.available_fleet_count == 3
    assert (
        limited.initial_placement_parameters.initial_phase_visit_count
        == default.initial_placement_parameters.initial_phase_visit_count
    )


def test_initial_placement_accepts_a_certification_tail_and_sizes_visits_to_it() -> (
    None
):
    example = ThreeStationOptimizedInitialPlacementExample()
    without_tail = _artifact(example)
    with_tail = _artifact(example, tail_seconds=300.0)
    assert with_tail.initial_placement_parameters is not None

    assert with_tail.config.horizon_seconds == without_tail.config.horizon_seconds
    assert with_tail.config.model_end_seconds == (
        without_tail.config.model_end_seconds + 300.0
    )
    for cabin_id in range(with_tail.initial_placement_parameters.available_fleet_count):
        without_tail_count = sum(
            visit.cabin_id == cabin_id for visit in without_tail.switch_visits
        )
        with_tail_count = sum(
            visit.cabin_id == cabin_id for visit in with_tail.switch_visits
        )
        assert with_tail_count > without_tail_count


def test_passenger_releases_are_not_shifted_by_a_warm_up() -> None:
    example = FiveStationOptimizedInitialPlacementNoSkipNoWaitExample()
    scenario = example.build_scenario()
    artifact = _artifact(example, available_fleet_count=1)

    passenger_build = EanPassengerCandidateBuilder(
        optimization_config=_initial_placement_optimization_config()
    ).build(scenario, artifact)

    assert passenger_build.demand_groups
    assert (
        min(group.release_time_seconds for group in passenger_build.demand_groups) == 0
    )


def test_initial_placement_keeps_zero_release_bound_for_negative_board_times() -> None:
    gp = pytest.importorskip("gurobipy")
    example = ThreeStationOptimizedInitialPlacementExample()
    scenario = example.build_scenario()
    artifact = _artifact(example, available_fleet_count=1)
    optimization_config = _initial_placement_optimization_config()
    movement, model = _movement_model(
        gp,
        artifact,
        optimization_config,
    )
    passenger_build = EanPassengerCandidateBuilder(
        optimization_config=optimization_config
    ).build(scenario, artifact)
    passenger_model = EanPassengerModelBuilder().build(
        scenario=scenario,
        movement_model=movement,
        objective=EanPassengerObjective.JOURNEY_TIME,
        optimization_config=optimization_config,
        gp=gp,
        grb=gp.GRB,
        passenger_build=passenger_build,
    )
    model.update()
    group_by_id = {group.id: group for group in passenger_build.demand_groups}
    negative_board_candidates = tuple(
        candidate
        for candidate in passenger_build.ride_candidates
        if group_by_id[candidate.demand_group_id].release_time_seconds == 0.0
        and _candidate_board_time_lower_bound(movement, candidate) < 0.0
    )

    assert negative_board_candidates
    constraint_names = {constraint.ConstrName for constraint in model.getConstrs()}
    assert all(
        f"slot_release_{_var_id(candidate.id)}_0" in constraint_names
        for candidate in negative_board_candidates
    )
    assert passenger_model.variables.slot_board_time is None


def test_initial_placement_activates_slot_time_upper_bounds_for_negative_times() -> (
    None
):
    gp = pytest.importorskip("gurobipy")
    example = FiveStationOptimizedInitialPlacementSkipNoWaitExample()
    scenario = example.build_scenario()
    artifact = _artifact(example)
    optimization_config = _initial_placement_optimization_config()
    movement, model = _movement_model(
        gp,
        artifact,
        optimization_config,
    )
    passenger_build = EanPassengerCandidateBuilder(
        optimization_config=optimization_config
    ).build(scenario, artifact)
    passenger_model = EanPassengerModelBuilder().build(
        scenario=scenario,
        movement_model=movement,
        objective=EanPassengerObjective.JOURNEY_TIME,
        optimization_config=optimization_config,
        gp=gp,
        grb=gp.GRB,
        passenger_build=passenger_build,
    )
    model.update()
    candidate = next(
        candidate
        for candidate in passenger_build.ride_candidates
        if _candidate_alight_time_lower_bound(movement, candidate) < 0.0
    )
    constraint = model.getConstrByName(f"slot_time_alight_ub_{_var_id(candidate.id)}_0")
    slot_variable = passenger_model.variables.slot[(candidate.id, 0)]
    row = model.getRow(constraint)

    assert any(
        row.getVar(index).sameAs(slot_variable) and row.getCoeff(index) != 0.0
        for index in range(row.size())
    )


@pytest.mark.parametrize(
    "optimization_name",
    (
        EanOptimizationName.CANDIDATE_HORIZON_PRUNING,
        EanOptimizationName.SINGLE_RING_DOMINATED_RIDE_PRUNING,
        EanOptimizationName.TIGHT_BIG_M_BOUNDS,
    ),
)
def test_initial_placement_rejects_unimplemented_fixed_start_optimizations(
    optimization_name: EanOptimizationName,
) -> None:
    config = EanOptimizationConfig.from_enabled_names((optimization_name,))
    with pytest.raises(NotImplementedError):
        config.resolved_for_fleet_mode(EanFleetMode.OPTIMIZED_INITIAL_PLACEMENT)


def test_initial_placement_keeps_shared_slot_time_strengthening() -> None:
    config = EanOptimizationConfig.from_enabled_names(
        (EanOptimizationName.SLOT_TIME_RELAXATION_STRENGTHENING,)
    )

    resolved = config.resolved_for_fleet_mode(EanFleetMode.OPTIMIZED_INITIAL_PLACEMENT)

    assert resolved.enable_slot_time_relaxation_strengthening
    assert not resolved.enable_candidate_horizon_pruning
    assert not resolved.enable_single_ring_dominated_ride_pruning
    assert not resolved.enable_tight_big_m_bounds


def test_initial_placement_rejects_fixed_start_time_bounds() -> None:
    config = EanOptimizationConfig.from_selection(
        EanTimeBoundFormulation.DERIVED_VISIT_BOUNDS.value
    )
    with pytest.raises(NotImplementedError, match="boundary-state time bounds"):
        config.resolved_for_fleet_mode(EanFleetMode.OPTIMIZED_INITIAL_PLACEMENT)


def test_optimizer_auto_resolves_initial_placement_formulations() -> None:
    pytest.importorskip("gurobipy")
    example = FiveStationOptimizedInitialPlacementNoSkipNoWaitExample()
    artifact = _artifact(example, available_fleet_count=1)

    result = EanOptimizer(
        EanSolveConfig(
            optimization_config=EanOptimizationConfig(),
        )
    ).solve(EanMovementFeasibilityProblem(artifact))

    assert result.movement_plan is not None
    assert result.fleet_plan is not None
    assert (
        result.metadata.optimization_config.formulation.horizon
        is EanHorizonFormulation.EXACT_TIME_ACTIVATION
    )
    assert (
        result.metadata.optimization_config.formulation.time_bounds
        is EanTimeBoundFormulation.INITIAL_PLACEMENT_SAFE
    )


def test_all_stop_mip_start_projects_even_fixed_phases_into_ring_states() -> None:
    example = ThreeStationOptimizedInitialPlacementExample()
    artifact = _artifact(example, available_fleet_count=31)

    seed = EanAllStopMipStartSeedBuilder().build(
        artifact,
        EanHorizonFormulation.EXACT_TIME_ACTIVATION,
    )

    assert seed.fleet_plan is not None
    assert seed.fleet_plan.active_cabin_ids == tuple(range(30))
    assert seed.fleet_plan.inactive_cabin_ids == (30,)
    assert len(seed.fleet_plan.initial_states) == 30
    phase_indices = tuple(state.visit_index for state in seed.fleet_plan.initial_states)
    assert phase_indices == tuple(sorted(phase_indices))
    phase_zero_rope_states = tuple(
        state
        for state in seed.fleet_plan.initial_states
        if state.visit_index == 0 and state.kind is EanInitialPlacementStateKind.ROPE
    )
    assert tuple(state.cabin_id for state in phase_zero_rope_states) == (4, 5, 6, 7)
    assert tuple(
        state.previous_event_time_seconds for state in phase_zero_rope_states
    ) == tuple(
        sorted(state.previous_event_time_seconds for state in phase_zero_rope_states)
    )
    assert all(
        visit.decision.value == "stop" and visit.wait_seconds == 0.0
        for trajectory in seed.movement_plan.trajectories
        for visit in trajectory.visits
    )
    validate_ean_movement_plan_against_artifact(
        artifact,
        seed.movement_plan,
        tolerance_seconds=1e-5,
    ).raise_for_errors()


def test_initial_placement_mip_start_sets_fleet_and_route_variables() -> None:
    gp = pytest.importorskip("gurobipy")
    example = ThreeStationOptimizedInitialPlacementExample()
    artifact = _artifact(example, available_fleet_count=6)
    movement, model = _movement_model(gp, artifact)
    seed = EanAllStopMipStartSeedBuilder().build(
        artifact,
        EanHorizonFormulation.EXACT_TIME_ACTIVATION,
    )
    assert seed.fleet_plan is not None
    assert movement.fleet_model is not None

    movement.apply_mip_start(seed.movement_plan, seed.fleet_plan)
    model.update()

    fleet_variables = movement.fleet_model.variables
    assert tuple(
        int(round(fleet_variables.cabin_active[cabin_id].Start))
        for cabin_id in range(6)
    ) == (1, 1, 1, 1, 1, 1)
    selected_count = sum(
        int(round(variable.Start))
        for variable in (
            *fleet_variables.station_selected.values(),
            *fleet_variables.rope_selected.values(),
        )
    )
    assert selected_count == 6
    movement_keys = {
        (visit.cabin_id, visit.visit_index)
        for trajectory in seed.movement_plan.trajectories
        for visit in trajectory.visits
    }
    assert all(
        int(round(variable.Start)) == int(key in movement_keys)
        for key, variable in fleet_variables.route_active.items()
    )
    absent_key = next(
        key for key in movement.variables.visit_active if key not in movement_keys
    )
    assert movement.variables.visit_active[absent_key].Start == gp.GRB.UNDEFINED


@pytest.mark.parametrize(
    ("requested_strategy", "resolved_strategy"),
    (
        (
            EanMipStartStrategy.GREEDY_ALL_STOP,
            EanMipStartStrategy.GREEDY_ALL_STOP,
        ),
        (
            EanMipStartStrategy.AUTO,
            EanMipStartStrategy.OPTIMIZED_ALL_STOP,
        ),
    ),
)
def test_initial_placement_supports_shared_all_stop_mip_start_strategies(
    requested_strategy: EanMipStartStrategy,
    resolved_strategy: EanMipStartStrategy,
) -> None:
    pytest.importorskip("gurobipy")
    example = ThreeStationOptimizedInitialPlacementExample()
    base_scenario = example.build_scenario()
    scenario = replace(
        base_scenario,
        demands=(replace(base_scenario.demands[0], count=1),),
    )
    artifact = _artifact(
        example,
        available_fleet_count=2,
        tail_seconds=300.0,
    )

    result = EanOptimizer(
        EanSolveConfig(
            solver_policy=GurobiSolverPolicy(time_limit_seconds=10.0),
        )
    ).solve(
        EanPassengerServiceProblem(
            scenario=scenario,
            artifact=artifact,
            mip_start_strategy=requested_strategy,
        )
    )

    assert result.metadata.solution_count >= 1
    assert result.metadata.resolved_mip_start_strategy is resolved_strategy
    assert result.metadata.mip_start_active_cabin_count == 2
    assert result.metadata.mip_start_unserved_passenger_count == 0
    assert result.metadata.mip_start_passenger_objective_seconds is not None
    assert result.metadata.mip_start_generation_seconds is not None
    assert result.metadata.mip_start_generation_seconds > 0.0


@pytest.mark.parametrize("active_count", (0, 1, 2))
def test_empty_partial_and_full_initial_placement_fleets(
    active_count: int,
) -> None:
    gp = pytest.importorskip("gurobipy")
    example = FiveStationOptimizedInitialPlacementNoSkipNoWaitExample()
    artifact = _artifact(example, available_fleet_count=2)

    model = gp.Model("optimized_initial_placement_test")
    model.Params.OutputFlag = 0
    movement = EanMovementModelBuilder().build(
        model=model,
        binary_vtype=gp.GRB.BINARY,
        artifact=artifact,
        optimization_config=_initial_placement_optimization_config(),
    )
    assert movement.fleet_model is not None
    model.addConstr(
        gp.quicksum(movement.fleet_model.variables.cabin_active.values())
        == active_count
    )
    model.setObjective(0.0, gp.GRB.MINIMIZE)
    model.optimize()

    assert model.SolCount >= 1
    fleet_plan = movement.fleet_model.extract_plan()
    assert len(fleet_plan.active_cabin_ids) == active_count
    assert len(fleet_plan.initial_states) == active_count
    if active_count == 1:
        replay = project_ean_movement_plan_to_physical_replay(
            example.build_scenario(),
            artifact,
            movement.extract_plan(),
        )
        assert EanPhysicalEventKind.INITIAL_PLACEMENT in {
            event.event_kind for event in replay.events
        }


@pytest.mark.parametrize(
    "state_kind",
    (
        EanInitialPlacementStateKind.ROPE,
        EanInitialPlacementStateKind.SERVICE_ROUTE,
        EanInitialPlacementStateKind.SKIP_ROUTE,
        EanInitialPlacementStateKind.PLATFORM_WAIT,
        EanInitialPlacementStateKind.ENTRY_SWITCH,
        EanInitialPlacementStateKind.EXIT_SWITCH,
    ),
)
def test_ring_list_supports_forced_initial_states(
    state_kind: EanInitialPlacementStateKind,
) -> None:
    gp = pytest.importorskip("gurobipy")
    example = ThreeStationOptimizedInitialPlacementExample()
    artifact = _artifact(example, available_fleet_count=1)
    movement, model = _movement_model(gp, artifact)
    assert movement.fleet_model is not None

    parameters = artifact.initial_placement_parameters
    assert parameters is not None
    timing_by_switch_id = {timing.switch_id: timing for timing in artifact.timings}
    station_config_by_id = {
        config.station_id: config for config in artifact.config.station_configs
    }
    phase_visits = movement.visits_by_cabin_id[0][
        : parameters.initial_phase_visit_count
    ]
    if state_kind is EanInitialPlacementStateKind.PLATFORM_WAIT:
        phase_visit = next(
            visit
            for visit in phase_visits
            if station_config_by_id[
                timing_by_switch_id[visit.switch_id].station_id
            ].waiting_mode
            is StationWaitingMode.END_OF_PLATFORM_WAIT
        )
    elif state_kind is EanInitialPlacementStateKind.SKIP_ROUTE:
        phase_visit = next(
            visit
            for visit in phase_visits
            if timing_by_switch_id[visit.switch_id].skip_allowed
        )
    else:
        phase_visit = phase_visits[min(1, len(phase_visits) - 1)]

    key = (0, phase_visit.visit_index)
    timing = timing_by_switch_id[phase_visit.switch_id]
    fleet_variables = movement.fleet_model.variables
    if state_kind is EanInitialPlacementStateKind.ROPE:
        model.addConstr(fleet_variables.rope_selected[key] == 1)
        previous_switch_id = artifact.circulation_state_ids[
            (phase_visit.visit_index - 1) % len(artifact.circulation_state_ids)
        ]
        rope_seconds = timing_by_switch_id[
            previous_switch_id
        ].rope_to_next_switch_seconds
        model.addConstr(movement.variables.switch_time[key] == rope_seconds / 2)
    else:
        model.addConstr(fleet_variables.station_selected[key] == 1)
        if state_kind is EanInitialPlacementStateKind.ENTRY_SWITCH:
            model.addConstr(movement.variables.switch_time[key] == 0)
            model.addConstr(movement.variables.stop[key] == 1)
        elif state_kind is EanInitialPlacementStateKind.EXIT_SWITCH:
            model.addConstr(movement.variables.exit_switch_time[key] == 0)
            model.addConstr(movement.variables.stop[key] == 1)
        elif state_kind is EanInitialPlacementStateKind.SERVICE_ROUTE:
            model.addConstr(movement.variables.switch_time[key] == -1)
            model.addConstr(movement.variables.stop[key] == 1)
            model.addConstr(movement.variables.wait_time[key] == 0)
        elif state_kind is EanInitialPlacementStateKind.SKIP_ROUTE:
            model.addConstr(
                movement.variables.switch_time[key]
                == -timing.skip_entry_to_exit_switch_seconds / 2
            )
            model.addConstr(movement.variables.stop[key] == 0)
        else:
            wait_entry_offset = (
                timing.entry_to_platform_entry_seconds
                + timing.min_platform_entry_to_platform_exit_seconds
            )
            model.addConstr(
                movement.variables.switch_time[key] == -(wait_entry_offset + 1)
            )
            model.addConstr(movement.variables.stop[key] == 1)
            model.addConstr(movement.variables.wait_time[key] == 2)

    model.setObjective(0.0, gp.GRB.MINIMIZE)
    model.optimize()

    assert model.SolCount >= 1
    fleet_plan = movement.fleet_model.extract_plan()
    assert fleet_plan.initial_states[0].kind is state_kind
    movement_plan = movement.extract_plan()
    first_visit = movement_plan.trajectories[0].visits[0]
    assert first_visit.visit_index == phase_visit.visit_index
    assert all(
        float(fleet_variables.route_active[(0, visit.visit_index)].X) < 0.5
        for visit in phase_visits
        if visit.visit_index < phase_visit.visit_index
    )
    if state_kind is EanInitialPlacementStateKind.ROPE:
        replay = project_ean_movement_plan_to_physical_replay(
            example.build_scenario(),
            artifact,
            movement_plan,
        )
        initial_event = next(
            event
            for event in replay.events
            if event.event_kind is EanPhysicalEventKind.INITIAL_PLACEMENT
        )
        assert initial_event.switch_id == fleet_plan.initial_states[0].switch_id


def test_initial_rope_order_uses_one_directed_cabin_id_headway() -> None:
    gp = pytest.importorskip("gurobipy")
    example = ThreeStationOptimizedInitialPlacementExample()
    artifact = _artifact(example, available_fleet_count=2)
    movement, model = _movement_model(gp, artifact)
    assert movement.fleet_model is not None

    phase_index = next(
        index
        for index, switch_id in enumerate(artifact.circulation_state_ids)
        if (
            next(
                timing for timing in artifact.timings if timing.switch_id == switch_id
            ).skip_allowed
            and next(
                config
                for config in artifact.config.station_configs
                if config.station_id
                == next(
                    timing
                    for timing in artifact.timings
                    if timing.switch_id == switch_id
                ).station_id
            ).waiting_mode
            is StationWaitingMode.END_OF_PLATFORM_WAIT
        )
    )
    fleet_variables = movement.fleet_model.variables
    model.addConstr(fleet_variables.rope_selected[(0, phase_index)] == 1)
    model.addConstr(fleet_variables.rope_selected[(1, phase_index)] == 1)
    model.addConstr(movement.variables.stop[(0, phase_index)] == 1)
    model.addConstr(movement.variables.wait_time[(0, phase_index)] == 20)
    model.addConstr(movement.variables.stop[(1, phase_index)] == 0)
    previous_switch_id = artifact.circulation_state_ids[
        (phase_index - 1) % len(artifact.circulation_state_ids)
    ]
    headway_seconds = next(
        checkpoint.headway_seconds
        for checkpoint in artifact.headway_checkpoints
        if checkpoint.id == f"exit_switch::{previous_switch_id}"
    )
    rope_seconds = next(
        timing.rope_to_next_switch_seconds
        for timing in artifact.timings
        if timing.switch_id == previous_switch_id
    )
    model.addConstr(
        movement.variables.switch_time[(0, phase_index)]
        == rope_seconds / 2 - headway_seconds / 2
    )
    model.addConstr(
        movement.variables.switch_time[(1, phase_index)]
        == rope_seconds / 2 + headway_seconds / 2
    )
    model.setObjective(0.0, gp.GRB.MINIMIZE)
    model.optimize()

    assert model.SolCount >= 1
    constraint_names = {constraint.ConstrName for constraint in model.getConstrs()}
    assert f"initial_rope_headway_{previous_switch_id}_0_1" in constraint_names
    assert f"initial_rope_headway_{previous_switch_id}_1_0" not in constraint_names
    regular_visit = next(
        visit
        for visit in movement.visits_by_cabin_id[1]
        if visit.switch_id == previous_switch_id
    )
    assert (
        f"initial_rope_to_exit_{previous_switch_id}_"
        f"0_1_{regular_visit.visit_index}" in constraint_names
    )
    states = movement.fleet_model.extract_plan().initial_states
    assert states[1].previous_event_time_seconds - states[
        0
    ].previous_event_time_seconds == pytest.approx(headway_seconds)


def test_initial_placement_tail_keeps_tail_routes_and_headways_valid() -> None:
    gp = pytest.importorskip("gurobipy")
    example = ThreeStationOptimizedInitialPlacementExample()
    scenario = example.build_scenario()
    artifact = _artifact(example, tail_seconds=300.0)
    movement, model = _movement_model(gp, artifact)
    assert movement.fleet_model is not None

    fleet_variables = movement.fleet_model.variables
    model.addConstr(fleet_variables.station_selected[(0, 0)] == 1)
    model.addConstr(movement.variables.switch_time[(0, 0)] == 0.0)
    model.addConstr(movement.variables.stop[(0, 0)] == 1)
    for cabin_id in range(1, len(artifact.cabin_starts)):
        model.addConstr(fleet_variables.cabin_active[cabin_id] == 0)

    tail_visit_index = 8
    assert tail_visit_index < len(movement.visits_by_cabin_id[0])
    model.addConstr(fleet_variables.route_active[(0, tail_visit_index)] == 1)
    model.setObjective(0.0, gp.GRB.MINIMIZE)
    model.optimize()

    assert model.SolCount >= 1
    plan = movement.extract_plan()
    validate_ean_movement_plan_against_artifact(artifact, plan).raise_for_errors()
    assert any(
        artifact.config.horizon_seconds
        < visit.switch_time_seconds
        <= artifact.config.model_end_seconds
        for visit in plan.trajectories[0].visits
    )

    replay = project_ean_movement_plan_to_physical_replay(
        scenario,
        artifact,
        plan,
    )
    assert replay.model_end_seconds == artifact.config.model_end_seconds
    assert any(
        artifact.config.horizon_seconds
        < event.time_seconds
        <= artifact.config.model_end_seconds
        for event in replay.events
        if event.cabin_id == 0
    )


def test_three_station_ring_list_serves_passengers_end_to_end() -> None:
    pytest.importorskip("gurobipy")
    example = ThreeStationOptimizedInitialPlacementExample()
    base_scenario = example.build_scenario()
    scenario = replace(
        base_scenario,
        demands=(replace(base_scenario.demands[0], count=1),),
    )
    artifact = _artifact(
        example,
        available_fleet_count=2,
        tail_seconds=300.0,
    )

    result = EanOptimizer(
        EanSolveConfig(
            solver_policy=GurobiSolverPolicy(time_limit_seconds=10.0),
        )
    ).solve(
        EanPassengerServiceProblem(
            scenario=scenario,
            artifact=artifact,
            mip_start_strategy=EanMipStartStrategy.NONE,
        )
    )

    assert result.metadata.solution_count >= 1
    assert result.metadata.unserved_passenger_count == 0
    assert result.fleet_plan is not None
    assert len(result.fleet_plan.active_cabin_ids) == 1
    assert result.movement_plan is not None
    assert result.passenger_plan is not None
    validate_ean_movement_plan_against_artifact(
        artifact,
        result.movement_plan,
    ).raise_for_errors()
    assert all(
        0.0 <= ride.boarding_time_seconds <= artifact.config.horizon_seconds
        and ride.alighting_time_seconds <= artifact.config.horizon_seconds
        for ride in result.passenger_plan.served_rides
    )


def test_fixed_starts_and_initial_placement_use_same_k_with_comparable_tail_models() -> (
    None
):
    gp = pytest.importorskip("gurobipy")
    example = ThreeStationOptimizedInitialPlacementExample()
    scenario = example.build_scenario()
    config = build_three_station_ean_config(scenario, tail_seconds=300.0)
    switch_cycle = build_three_station_ean_ring_switch_order(scenario)
    fixed_artifact = network_ean_builder_for_cycle(
        state_ids=switch_cycle,
        start_builder=EvenlySpacedAllStopCabinStartBuilder(
            cabin_count=len(scenario.cabins),
        ),
    ).build(scenario, config)
    initial_placement_artifact = network_ean_builder_for_cycle(
        state_ids=switch_cycle,
        fleet_config=EanFleetConfig(
            mode=EanFleetMode.OPTIMIZED_INITIAL_PLACEMENT,
            available_fleet_count=len(fixed_artifact.cabin_starts),
        ),
    ).build(scenario, config)

    assert len(fixed_artifact.cabin_starts) == 4
    assert initial_placement_artifact.initial_placement_parameters is not None
    assert (
        initial_placement_artifact.initial_placement_parameters.available_fleet_count
        == len(fixed_artifact.cabin_starts)
    )
    assert (
        fixed_artifact.config.model_end_seconds
        == initial_placement_artifact.config.model_end_seconds
    )

    fixed_movement, _ = _movement_model(
        gp,
        fixed_artifact,
        _fixed_start_optimization_config(),
    )
    initial_placement_movement, _ = _movement_model(
        gp,
        initial_placement_artifact,
    )
    assert fixed_movement.variables.headway_order
    assert initial_placement_movement.variables.headway_order
    assert len(fixed_movement.variables.headway_order) == len(
        fixed_artifact.headway_pairs
    )
    assert len(initial_placement_movement.variables.headway_order) == len(
        initial_placement_artifact.headway_pairs
    )
    assert fixed_movement.variable_count > 0
    assert initial_placement_movement.variable_count > 0
    assert fixed_movement.constraint_count > 0
    assert initial_placement_movement.constraint_count > 0


def _candidate_board_time_lower_bound(movement, candidate) -> float:
    key = (candidate.cabin_id, candidate.board_visit_index)
    timing = movement.timing_by_switch_id[movement.visits_by_key[key].switch_id]
    return (
        movement.model_time_bounds.by_visit[key].switch_lower
        + timing.entry_to_platform_entry_seconds
        + timing.min_platform_entry_to_platform_exit_seconds
    )


def _candidate_alight_time_lower_bound(movement, candidate) -> float:
    key = (candidate.cabin_id, candidate.alight_visit_index)
    timing = movement.timing_by_switch_id[movement.visits_by_key[key].switch_id]
    return (
        movement.model_time_bounds.by_visit[key].switch_lower
        + timing.entry_to_platform_entry_seconds
    )


def _initial_placement_optimization_config() -> EanOptimizationConfig:
    return EanOptimizationConfig(
        enable_candidate_horizon_pruning=False,
        enable_single_ring_dominated_ride_pruning=False,
        enable_tight_big_m_bounds=False,
        formulation=EanFormulationConfig(
            horizon=EanHorizonFormulation.EXACT_TIME_ACTIVATION,
            time_bounds=EanTimeBoundFormulation.INITIAL_PLACEMENT_SAFE,
        ),
    )


def _fixed_start_optimization_config() -> EanOptimizationConfig:
    return EanOptimizationConfig(
        enable_candidate_horizon_pruning=False,
        enable_single_ring_dominated_ride_pruning=False,
        enable_tight_big_m_bounds=False,
        formulation=EanFormulationConfig(
            horizon=EanHorizonFormulation.EXACT_TIME_ACTIVATION,
            time_bounds=EanTimeBoundFormulation.DERIVED_VISIT_BOUNDS,
        ),
    )


def _movement_model(
    gp,
    artifact,
    optimization_config: EanOptimizationConfig | None = None,
):
    model = gp.Model("optimized_initial_ring_list_test")
    model.Params.OutputFlag = 0
    movement = EanMovementModelBuilder().build(
        model=model,
        binary_vtype=gp.GRB.BINARY,
        artifact=artifact,
        optimization_config=(
            optimization_config or _initial_placement_optimization_config()
        ),
    )
    return movement, model


def _artifact(
    example: FiveStationOptimizedInitialPlacementNoSkipNoWaitExample
    | FiveStationOptimizedInitialPlacementSkipNoWaitExample
    | ThreeStationOptimizedInitialPlacementExample,
    *,
    available_fleet_count: int | None = None,
    tail_seconds: float | None = None,
):
    scenario = example.build_scenario()
    config = example.build_ean_config(scenario)
    if tail_seconds is not None:
        config = replace(config, tail_seconds=tail_seconds)
    builder = example.build_ean_artifact_builder(scenario, config)
    if available_fleet_count is not None:
        assert isinstance(builder, NetworkEanBuildArtifactBuilder)
        builder = replace(
            builder,
            fleet_config=replace(
                builder.fleet_config,
                available_fleet_count=available_fleet_count,
            ),
        )
    return builder.build(scenario, config)
