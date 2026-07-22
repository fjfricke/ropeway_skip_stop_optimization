from __future__ import annotations

from dataclasses import dataclass, field
from datetime import time

import pytest

from ropeway_skip_stop_optimization.models import Demand, OperatingParameters, Scenario
from ropeway_skip_stop_optimization.optimization.ean import (
    EanCabinStart,
    EanCabinStartKind,
    EanCabinTrajectory,
    EanCabinVisit,
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
    EanBoardTimeFormulation,
    EanTimeReference,
    EanOptimizationConfig,
    EanOptimizer,
    EanFormulationConfig,
    EanFixedMovementPassengerProblem,
    EanHorizonFormulation,
    EanMovementPlan,
    EanMipStartStrategy,
    EanTimeBoundFormulation,
    EanPassengerObjective,
    EanPassengerAssignmentDomain,
    EanPassengerServiceProblem,
    EanRideCandidate,
    EanRouteDecision,
    EanSolveConfig,
    EanSlotActivationFormulation,
    EanStopSkipTimingFormulation,
    GurobiSolverPolicy,
    GurobiCheckpointConfig,
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
from ropeway_skip_stop_optimization.optimization.ean.optimizers.movement_model import (
    StopSkipBigMBounds,
    headway_time_expressions as _headway_time_expressions,
    stop_skip_big_m_bounds as _stop_skip_big_m_bounds,
)
from ropeway_skip_stop_optimization.optimization.ean.optimizers.passenger_model import (
    _add_projected_journey_slot_time_constraints,
    _min_candidate_trip_time_seconds,
    _slot_release_big_m,
)
from ropeway_skip_stop_optimization.optimization.ean.optimizers.solver import (
    _solver_diagnostics,
)


@dataclass(frozen=True)
class _PassengerSolveOptions:
    objective: EanPassengerObjective = EanPassengerObjective.WAITING_TIME
    optimization_config: EanOptimizationConfig = field(
        default_factory=EanOptimizationConfig
    )
    mip_start_strategy: EanMipStartStrategy = (
        EanMipStartStrategy.OPTIMIZED_ALL_STOP
    )


def _solve_passenger(
    scenario: Scenario,
    artifact: EanBuildArtifact,
    options: _PassengerSolveOptions | None = None,
):
    options = options or _PassengerSolveOptions()
    return EanOptimizer(
        EanSolveConfig(optimization_config=options.optimization_config)
    ).solve(
        EanPassengerServiceProblem(
            scenario=scenario,
            artifact=artifact,
            objective=options.objective,
            mip_start_strategy=options.mip_start_strategy,
        )
    )


def test_ean_passenger_service_minimizes_waiting_with_unserved_backlog() -> None:
    pytest.importorskip("gurobipy")
    scenario = _minimal_scenario(
        demands=(Demand(arrival_time=time(8, 0), origin="A", destination="B", count=3),),
    )
    artifact = _minimal_artifact(cabin_capacity=2)

    result = _solve_passenger(scenario, artifact)

    assert result.metadata.status == "optimal"
    assert result.metadata.objective_kind is EanPassengerObjective.WAITING_TIME
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
    assert (
        result.metadata.optimization_config.formulation.stop_skip_timing
        is EanStopSkipTimingFormulation.AFFINE
    )
    assert (
        result.metadata.optimization_config.formulation.slot_activation
        is EanSlotActivationFormulation.FIRST_SLOT_IMPLICATIONS
    )
    assert (
        result.metadata.optimization_config.formulation.board_time
        is EanBoardTimeFormulation.EXPLICIT
    )


def test_ean_passenger_service_journey_time_uses_alighting_time() -> None:
    pytest.importorskip("gurobipy")
    scenario = _minimal_scenario(
        demands=(Demand(arrival_time=time(8, 0), origin="A", destination="B", count=1),),
    )
    artifact = _minimal_artifact(cabin_capacity=2, cycle_count=2)

    result = _solve_passenger(
        scenario,
        artifact,
        _PassengerSolveOptions(objective=EanPassengerObjective.JOURNEY_TIME),
    )

    assert result.metadata.status == "optimal"
    assert result.metadata.objective_kind is EanPassengerObjective.JOURNEY_TIME
    assert result.passenger_plan is not None
    assert len(result.passenger_plan.served_rides) == 1
    ride = result.passenger_plan.served_rides[0]
    assert ride.alight_visit_index == 1
    assert result.metadata.objective_value_seconds == pytest.approx(9.0)
    assert result.metadata.objective_passenger_hours == pytest.approx(9.0 / 3600.0)
    assert (
        result.metadata.optimization_config.formulation.stop_skip_timing
        is EanStopSkipTimingFormulation.AFFINE
    )
    assert (
        result.metadata.optimization_config.formulation.slot_activation
        is EanSlotActivationFormulation.FIRST_SLOT_IMPLICATIONS
    )
    assert (
        result.metadata.optimization_config.formulation.board_time
        is EanBoardTimeFormulation.PROJECTED_JOURNEY_TIME
    )


def test_ean_passenger_service_can_fix_the_canonical_movement_plan() -> None:
    pytest.importorskip("gurobipy")
    scenario = _minimal_scenario(
        demands=(
            Demand(
                arrival_time=time(8, 0),
                origin="A",
                destination="B",
                count=2,
            ),
        )
    )
    artifact = _minimal_artifact(cabin_capacity=2, cycle_count=2)
    objective = EanPassengerObjective.JOURNEY_TIME
    baseline = _solve_passenger(
        scenario,
        artifact,
        _PassengerSolveOptions(objective=objective),
    )
    assert baseline.movement_plan is not None

    fixed = EanOptimizer().solve(
        EanFixedMovementPassengerProblem(
            scenario=scenario,
            artifact=artifact,
            movement_plan=baseline.movement_plan,
            objective=objective,
        )
    )

    assert fixed.metadata.status == "optimal"
    assert fixed.metadata.fixed_movement
    assert (
        fixed.metadata.assignment_domain
        is EanPassengerAssignmentDomain.INTEGER
    )
    assert fixed.metadata.movement_variable_count == 0
    assert fixed.metadata.movement_constraint_count == 0
    assert fixed.metadata.build_metrics.movement_fixing_seconds == 0.0
    assert fixed.metadata.objective_value_seconds == pytest.approx(
        baseline.metadata.objective_value_seconds
    )
    assert fixed.movement_plan == baseline.movement_plan
    assert fixed.passenger_plan == baseline.passenger_plan
    assert fixed.passenger_assignment is not None
    assert fixed.passenger_assignment.fractional_ride_count == 0


def test_fixed_movement_passenger_lp_reports_fractional_odd_cycle() -> None:
    pytest.importorskip("gurobipy")
    scenario, artifact, movement_plan = _odd_cycle_fixed_movement_case()

    integer_result = EanOptimizer().solve(
        EanFixedMovementPassengerProblem(
            scenario=scenario,
            artifact=artifact,
            movement_plan=movement_plan,
            objective=EanPassengerObjective.WAITING_TIME,
        )
    )
    lp_result = EanOptimizer().solve(
        EanFixedMovementPassengerProblem(
            scenario=scenario,
            artifact=artifact,
            movement_plan=movement_plan,
            objective=EanPassengerObjective.WAITING_TIME,
            assignment_domain=(
                EanPassengerAssignmentDomain.LP_RELAXATION
            ),
        )
    )

    assert integer_result.metadata.status == "optimal"
    assert integer_result.metadata.objective_value_seconds == pytest.approx(
        12.5
    )
    assert integer_result.passenger_plan is not None
    assert integer_result.passenger_assignment is not None
    assert integer_result.passenger_assignment.fractional_ride_count == 0

    assert lp_result.metadata.status == "optimal"
    assert lp_result.metadata.objective_value_seconds == pytest.approx(12.25)
    assert lp_result.passenger_plan is None
    assert lp_result.passenger_assignment is not None
    assert lp_result.passenger_assignment.fractional_ride_count == 7
    assert lp_result.passenger_assignment.fractional_distance_sum == pytest.approx(
        3.5
    )
    assert lp_result.passenger_assignment.maximum_fractional_distance == pytest.approx(
        0.5
    )
    assert all(
        value == pytest.approx(0.5)
        for value in (
            lp_result.passenger_assignment.ride_counts_by_candidate_id.values()
        )
    )


def test_fixed_movement_passenger_lp_rejects_checkpoints(tmp_path) -> None:
    scenario = _minimal_scenario(
        demands=(
            Demand(
                arrival_time=time(8, 0),
                origin="A",
                destination="B",
                count=1,
            ),
        )
    )
    artifact = _minimal_artifact(cabin_capacity=2)
    movement = _solve_passenger(scenario, artifact).movement_plan
    assert movement is not None

    with pytest.raises(
        ValueError,
        match="checkpoints are not supported",
    ):
        EanOptimizer(
            EanSolveConfig(
                checkpoint=GurobiCheckpointConfig(
                    final_solution_path=tmp_path / "fixed.sol",
                )
            )
        ).solve(
            EanFixedMovementPassengerProblem(
                scenario=scenario,
                artifact=artifact,
                movement_plan=movement,
                assignment_domain=(
                    EanPassengerAssignmentDomain.LP_RELAXATION
                ),
            )
        )


def test_ean_passenger_service_can_optimize_the_all_stop_mip_start() -> None:
    pytest.importorskip("gurobipy")
    scenario = _minimal_scenario(
        demands=(
            Demand(
                arrival_time=time(8, 0),
                origin="A",
                destination="B",
                count=2,
            ),
        )
    )
    artifact = _minimal_artifact(cabin_capacity=2, cycle_count=2)

    result = _solve_passenger(
        scenario,
        artifact,
        _PassengerSolveOptions(
            objective=EanPassengerObjective.JOURNEY_TIME,
            mip_start_strategy=EanMipStartStrategy.OPTIMIZED_ALL_STOP,
        ),
    )

    assert result.metadata.status == "optimal"
    assert (
        result.metadata.build_metrics.mip_start_objective_value_seconds
        == pytest.approx(result.metadata.objective_value_seconds)
    )
    assert result.metadata.build_metrics.mip_start_seconds > 0.0


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

    strengthened = _solve_passenger(
        scenario,
        artifact,
        _PassengerSolveOptions(objective=EanPassengerObjective.JOURNEY_TIME),
    )
    unstrengthened = _solve_passenger(
        scenario,
        artifact,
        _PassengerSolveOptions(
            objective=EanPassengerObjective.JOURNEY_TIME,
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

    baseline = _solve_passenger(
        scenario,
        artifact,
        _PassengerSolveOptions(objective=EanPassengerObjective.JOURNEY_TIME),
    )
    tightened = _solve_passenger(
        scenario,
        artifact,
        _PassengerSolveOptions(
            objective=EanPassengerObjective.JOURNEY_TIME,
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
        EanPassengerObjective.WAITING_TIME,
        EanPassengerObjective.JOURNEY_TIME,
    ),
)
def test_affine_stop_skip_timing_preserves_minimal_solution(
    objective: EanPassengerObjective,
) -> None:
    pytest.importorskip("gurobipy")
    scenario = _minimal_scenario(
        demands=(Demand(arrival_time=time(8, 0), origin="A", destination="B", count=1),),
    )
    artifact = _minimal_artifact(cabin_capacity=2, cycle_count=2)

    baseline = _solve_passenger(
        scenario,
        artifact,
        _PassengerSolveOptions(
            objective=objective,
            optimization_config=EanOptimizationConfig(
                formulation=EanFormulationConfig(
                    stop_skip_timing=EanStopSkipTimingFormulation.BIG_M,
                )
            ),
        ),
    )
    affine = _solve_passenger(
        scenario,
        artifact,
        _PassengerSolveOptions(
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
    "objective",
    (
        EanPassengerObjective.WAITING_TIME,
        EanPassengerObjective.JOURNEY_TIME,
    ),
)
@pytest.mark.parametrize(
    "waiting_mode",
    (
        StationWaitingMode.NO_WAITING,
        StationWaitingMode.END_OF_PLATFORM_WAIT,
    ),
)
@pytest.mark.parametrize(
    ("arrival_time", "release_seconds"),
    (
        (time(8, 0), 0.0),
        (time(8, 0, 5), 5.0),
    ),
)
@pytest.mark.parametrize(
    ("time_bound_formulation", "enable_strengthening", "enable_tight_big_m_bounds"),
    (
        (EanTimeBoundFormulation.LEGACY_PLUS_10, True, False),
        (EanTimeBoundFormulation.DERIVED_VISIT_BOUNDS, True, False),
        (EanTimeBoundFormulation.LEGACY_PLUS_10, False, False),
        (EanTimeBoundFormulation.DERIVED_VISIT_BOUNDS, False, False),
        (EanTimeBoundFormulation.LEGACY_PLUS_10, True, True),
        (EanTimeBoundFormulation.DERIVED_VISIT_BOUNDS, False, True),
    ),
)
def test_first_slot_activation_preserves_multi_slot_solutions_and_removes_implied_rows(
    objective: EanPassengerObjective,
    waiting_mode: StationWaitingMode,
    arrival_time: time,
    release_seconds: float,
    time_bound_formulation: EanTimeBoundFormulation,
    enable_strengthening: bool,
    enable_tight_big_m_bounds: bool,
) -> None:
    pytest.importorskip("gurobipy")
    scenario = _minimal_scenario(
        demands=(Demand(arrival_time=arrival_time, origin="A", destination="B", count=2),),
    )
    artifact = _minimal_artifact(
        cabin_capacity=2,
        cycle_count=2,
        station_waiting_modes={"A": waiting_mode, "B": waiting_mode},
    )

    baseline = _solve_passenger(
        scenario,
        artifact,
        _PassengerSolveOptions(
            objective=objective,
            optimization_config=EanOptimizationConfig(
                enable_slot_time_relaxation_strengthening=enable_strengthening,
                enable_tight_big_m_bounds=enable_tight_big_m_bounds,
                formulation=EanFormulationConfig(
                    time_bounds=time_bound_formulation,
                    slot_activation=EanSlotActivationFormulation.PER_SLOT_IMPLICATIONS,
                    board_time=EanBoardTimeFormulation.EXPLICIT,
                ),
            ),
        ),
    )
    first_slot = _solve_passenger(
        scenario,
        artifact,
        _PassengerSolveOptions(
            objective=objective,
            optimization_config=EanOptimizationConfig(
                enable_slot_time_relaxation_strengthening=enable_strengthening,
                enable_tight_big_m_bounds=enable_tight_big_m_bounds,
                formulation=EanFormulationConfig(
                    time_bounds=time_bound_formulation,
                    slot_activation=EanSlotActivationFormulation.FIRST_SLOT_IMPLICATIONS,
                    board_time=EanBoardTimeFormulation.EXPLICIT,
                )
            ),
        ),
    )

    assert baseline.metadata.status == "optimal"
    assert first_slot.metadata.status == "optimal"
    assert first_slot.metadata.objective_value_seconds == pytest.approx(
        baseline.metadata.objective_value_seconds
    )
    assert first_slot.metadata.served_passenger_count == baseline.metadata.served_passenger_count
    assert first_slot.metadata.unserved_passenger_count == baseline.metadata.unserved_passenger_count
    assert first_slot.passenger_plan is not None
    assert baseline.passenger_plan is not None
    assert first_slot.passenger_plan.unserved_counts_by_demand_group_id == (
        baseline.passenger_plan.unserved_counts_by_demand_group_id
    )
    assert first_slot.metadata.model_nonzero_count < baseline.metadata.model_nonzero_count
    assert first_slot.metadata.model_setup_runtime_seconds >= 0.0

    slots = baseline.metadata.slot_variable_count
    rides = baseline.metadata.ride_candidate_count
    if release_seconds == 0.0:
        expected_removed_rows = 5 * slots - 4 * rides
        if enable_strengthening:
            expected_removed_rows += slots
            if objective is EanPassengerObjective.JOURNEY_TIME:
                expected_removed_rows += slots
    else:
        expected_removed_rows = 5 * (slots - rides)
        if enable_strengthening and objective is EanPassengerObjective.JOURNEY_TIME:
            expected_removed_rows += slots
    assert baseline.metadata.constraint_count - first_slot.metadata.constraint_count == expected_removed_rows
    assert (
        first_slot.metadata.optimization_config.formulation.slot_activation
        is EanSlotActivationFormulation.FIRST_SLOT_IMPLICATIONS
    )


def test_projected_journey_board_time_matches_explicit_lp_relaxation() -> None:
    gp = pytest.importorskip("gurobipy")
    from gurobipy import GRB

    artifact = _minimal_artifact(cabin_capacity=2, cycle_count=2)
    ride_candidate = EanRideCandidate(
        id="ride::projection",
        demand_group_id="demand::projection",
        cabin_id=0,
        board_visit_index=0,
        alight_visit_index=1,
    )
    group = EanDemandGroup(
        id="demand::projection",
        origin_station_id="A",
        destination_station_id="B",
        release_time_seconds=3.0,
        count=1,
    )
    visits_by_key = {
        (visit.cabin_id, visit.visit_index): visit
        for visit in artifact.switch_visits
    }
    timing_by_switch_id = {timing.switch_id: timing for timing in artifact.timings}
    time_upper_bound = 20.0

    def support_value(*, projected: bool, coefficients: tuple[float, float, float, float]) -> float:
        model = gp.Model()
        model.Params.OutputFlag = 0
        slot_var = model.addVar(lb=0.0, ub=1.0, vtype=GRB.CONTINUOUS, name="slot")
        board_time = model.addVar(lb=0.0, ub=time_upper_bound, vtype=GRB.CONTINUOUS, name="board")
        alight_time = model.addVar(lb=0.0, ub=time_upper_bound, vtype=GRB.CONTINUOUS, name="alight")
        selected_alight_time = model.addVar(
            lb=0.0,
            ub=time_upper_bound,
            vtype=GRB.CONTINUOUS,
            name="selected_alight",
        )
        model.addConstr(selected_alight_time <= time_upper_bound * slot_var)
        model.addConstr(selected_alight_time <= alight_time)
        model.addConstr(selected_alight_time >= alight_time - time_upper_bound * (1 - slot_var))

        if projected:
            _add_projected_journey_slot_time_constraints(
                model=model,
                ride_candidate=ride_candidate,
                group=group,
                slot_index=0,
                slot_var=slot_var,
                board_time=board_time,
                slot_alight_time=selected_alight_time,
                time_upper_bound=time_upper_bound,
                visits_by_key=visits_by_key,
                timing_by_switch_id=timing_by_switch_id,
            )
        else:
            selected_board_time = model.addVar(
                lb=0.0,
                ub=time_upper_bound,
                vtype=GRB.CONTINUOUS,
                name="selected_board",
            )
            model.addConstr(selected_board_time <= time_upper_bound * slot_var)
            model.addConstr(selected_board_time <= board_time)
            model.addConstr(selected_board_time >= board_time - time_upper_bound * (1 - slot_var))
            model.addConstr(selected_board_time >= group.release_time_seconds * slot_var)
            model.addConstr(
                selected_alight_time - selected_board_time
                >= _min_candidate_trip_time_seconds(ride_candidate, visits_by_key, timing_by_switch_id) * slot_var
            )

        model.setObjective(
            coefficients[0] * slot_var
            + coefficients[1] * board_time
            + coefficients[2] * alight_time
            + coefficients[3] * selected_alight_time,
            GRB.MAXIMIZE,
        )
        model.optimize()
        assert model.Status == GRB.OPTIMAL
        return model.ObjVal

    for coefficients in (
        (1.0, 0.0, 0.0, 0.0),
        (0.0, 1.0, 0.0, 0.0),
        (0.0, 0.0, 0.0, 1.0),
        (-5.0, 3.0, -2.0, 7.0),
        (3.0, -4.0, 1.0, -6.0),
    ):
        assert support_value(projected=True, coefficients=coefficients) == pytest.approx(
            support_value(projected=False, coefficients=coefficients)
        )


@pytest.mark.parametrize(
    "waiting_mode",
    (
        StationWaitingMode.NO_WAITING,
        StationWaitingMode.END_OF_PLATFORM_WAIT,
    ),
)
@pytest.mark.parametrize("release_seconds", (0.0, 5.0))
@pytest.mark.parametrize(
    "slot_activation",
    (
        EanSlotActivationFormulation.PER_SLOT_IMPLICATIONS,
        EanSlotActivationFormulation.FIRST_SLOT_IMPLICATIONS,
    ),
)
@pytest.mark.parametrize("enable_strengthening", (False, True))
def test_projected_journey_board_time_preserves_small_instances_and_removes_auxiliaries(
    waiting_mode: StationWaitingMode,
    release_seconds: float,
    slot_activation: EanSlotActivationFormulation,
    enable_strengthening: bool,
) -> None:
    pytest.importorskip("gurobipy")
    scenario = _minimal_scenario(
        demands=(
            Demand(
                arrival_time=time(8, 0, int(release_seconds)),
                origin="A",
                destination="B",
                count=2,
            ),
        ),
    )
    artifact = _minimal_artifact(
        cabin_capacity=2,
        cycle_count=2,
        station_waiting_modes={"A": waiting_mode, "B": waiting_mode},
    )
    baseline_config = EanOptimizationConfig(
        enable_slot_time_relaxation_strengthening=enable_strengthening,
        formulation=EanFormulationConfig(
            slot_activation=slot_activation,
            board_time=EanBoardTimeFormulation.EXPLICIT,
        ),
    )
    projected_config = EanOptimizationConfig(
        enable_slot_time_relaxation_strengthening=enable_strengthening,
        formulation=EanFormulationConfig(
            slot_activation=slot_activation,
            board_time=EanBoardTimeFormulation.PROJECTED_JOURNEY_TIME,
        ),
    )

    baseline = _solve_passenger(
        scenario,
        artifact,
        _PassengerSolveOptions(
            objective=EanPassengerObjective.JOURNEY_TIME,
            optimization_config=baseline_config,
        ),
    )
    projected = _solve_passenger(
        scenario,
        artifact,
        _PassengerSolveOptions(
            objective=EanPassengerObjective.JOURNEY_TIME,
            optimization_config=projected_config,
        ),
    )

    assert baseline.metadata.status == "optimal"
    assert projected.metadata.status == "optimal"
    assert projected.metadata.objective_value_seconds == pytest.approx(
        baseline.metadata.objective_value_seconds
    )
    assert projected.metadata.served_passenger_count == baseline.metadata.served_passenger_count
    assert projected.metadata.unserved_passenger_count == baseline.metadata.unserved_passenger_count
    assert baseline.passenger_plan is not None
    assert projected.passenger_plan is not None
    assert projected.passenger_plan.unserved_counts_by_demand_group_id == (
        baseline.passenger_plan.unserved_counts_by_demand_group_id
    )

    slots = baseline.metadata.slot_variable_count
    assert baseline.metadata.variable_count - projected.metadata.variable_count == slots
    if not enable_strengthening:
        expected_removed_rows = 3 * slots
    elif slot_activation is EanSlotActivationFormulation.FIRST_SLOT_IMPLICATIONS:
        expected_removed_rows = (
            2 * slots
            if release_seconds == 0.0
            else 3 * slots - baseline.metadata.ride_candidate_count
        )
    elif release_seconds == 0.0:
        expected_removed_rows = 4 * slots
    else:
        expected_removed_rows = 3 * slots
    assert baseline.metadata.constraint_count - projected.metadata.constraint_count == expected_removed_rows
    assert (
        projected.metadata.optimization_config.formulation.board_time
        is EanBoardTimeFormulation.PROJECTED_JOURNEY_TIME
    )


def test_projected_journey_board_time_rejects_waiting_time_objective() -> None:
    pytest.importorskip("gurobipy")
    with pytest.raises(ValueError, match="requires journey_time objective"):
        _solve_passenger(
            _minimal_scenario(
                demands=(Demand(arrival_time=time(8, 0), origin="A", destination="B", count=1),),
            ),
            _minimal_artifact(cabin_capacity=2),
            _PassengerSolveOptions(
                objective=EanPassengerObjective.WAITING_TIME,
                optimization_config=EanOptimizationConfig(
                    formulation=EanFormulationConfig(
                        board_time=EanBoardTimeFormulation.PROJECTED_JOURNEY_TIME,
                    )
                ),
            ),
        )


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

    result = _solve_passenger(
        scenario,
        artifact,
        _PassengerSolveOptions(
            objective=EanPassengerObjective.JOURNEY_TIME,
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
        state_ids=("A_entry", "B_entry"),
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


def _odd_cycle_fixed_movement_case() -> tuple[
    Scenario,
    EanBuildArtifact,
    EanMovementPlan,
]:
    demand_specs = (
        ("0", "1", 0),
        ("0", "2", 1),
        ("1", "0", 0),
        ("1", "2", 1),
        ("2", "1", 2),
    )
    scenario = Scenario(
        id="odd_cycle_ean",
        service_start_time=time(8, 0),
        service_end_time=time(8, 1),
        stations=(),
        physical_nodes=(),
        track_segments=(),
        station_routes=(),
        cabins=(),
        cabin_initial_states=(),
        demands=tuple(
            Demand(
                arrival_time=time(8, 0, release),
                origin=origin,
                destination=destination,
                count=1,
            )
            for origin, destination, release in demand_specs
        ),
        operating=OperatingParameters(
            rope_speed_m_per_s=5.0,
            station_speed_m_per_s=0.5,
            cabin_capacity=1,
            cabin_length_m=3.0,
            min_clearance_m=0.5,
        ),
    )
    switch_ids = ("switch_0", "switch_1", "switch_2")
    timings = tuple(
        SkipStopTiming(
            switch_id=switch_id,
            station_id=str(index),
            entry_to_platform_entry_seconds=0.2,
            min_platform_entry_to_platform_exit_seconds=0.3,
            platform_exit_to_exit_switch_seconds=0.2,
            skip_entry_to_exit_switch_seconds=0.7,
            rope_to_next_switch_seconds=0.3,
            skip_allowed=True,
        )
        for index, switch_id in enumerate(switch_ids)
    )
    config = EanConfig(
        horizon_seconds=5.0,
        tail_seconds=0.0,
        cabin_capacity=1,
        station_configs=tuple(
            StationEanConfig(
                station_id=str(index),
                waiting_mode=StationWaitingMode.NO_WAITING,
            )
            for index in range(3)
        ),
    )
    cabin_sequences = {
        0: (0, 1, 2, 0, 1, 2),
        1: (1, 2, 0, 1, 2, 0),
    }
    artifact = EanBuildArtifact(
        scenario_id=scenario.id,
        config=config,
        state_ids=switch_ids,
        timings=timings,
        cabin_starts=(
            EanCabinStart(
                cabin_id=0,
                first_switch_id="switch_0",
                kind=EanCabinStartKind.FIXED,
                time_seconds=0.0,
            ),
            EanCabinStart(
                cabin_id=1,
                first_switch_id="switch_1",
                kind=EanCabinStartKind.FIXED,
                time_seconds=0.0,
            ),
        ),
        switch_visits=tuple(
            SwitchVisitDefinition(
                cabin_id=cabin_id,
                visit_index=visit_index,
                switch_id=switch_ids[station_index],
            )
            for cabin_id, sequence in cabin_sequences.items()
            for visit_index, station_index in enumerate(sequence)
        ),
        switch_transitions=tuple(
            SwitchTransition(
                from_switch_id=switch_ids[index],
                to_switch_id=switch_ids[(index + 1) % 3],
                min_seconds=0.3,
                max_seconds=0.3,
            )
            for index in range(3)
        ),
        headway_checkpoints=(
            HeadwayCheckpointDefinition(
                id="platform_entry::switch_0",
                kind=HeadwayCheckpointKind.PLATFORM_ENTRY,
                switch_id="switch_0",
                station_id="0",
                headway_seconds=0.1,
                applies_to_serve=True,
                applies_to_skip=False,
                waiting_modes=(StationWaitingMode.NO_WAITING,),
            ),
        ),
        headway_candidates=(
            HeadwayCandidate(
                id="candidate::platform_entry::switch_0::cabin_0::visit_0",
                checkpoint_id="platform_entry::switch_0",
                cabin_id=0,
                visit_index=0,
                time_reference=EanTimeReference.PLATFORM_ENTRY_TIME,
                activation_reference=EanActivationReference.SERVE,
            ),
        ),
        headway_pairs=(),
    )
    movement_plan = EanMovementPlan(
        scenario_id=scenario.id,
        horizon_seconds=config.horizon_seconds,
        model_end_seconds=config.model_end_seconds,
        trajectories=tuple(
            EanCabinTrajectory(
                cabin_id=cabin_id,
                visits=tuple(
                    _odd_cycle_visit(
                        cabin_id=cabin_id,
                        visit_index=visit_index,
                        station_index=station_index,
                    )
                    for visit_index, station_index in enumerate(sequence)
                ),
            )
            for cabin_id, sequence in cabin_sequences.items()
        ),
    )
    return scenario, artifact, movement_plan


def _odd_cycle_visit(
    *,
    cabin_id: int,
    visit_index: int,
    station_index: int,
) -> EanCabinVisit:
    decision = (
        EanRouteDecision.SKIP
        if visit_index in {0, 5}
        else EanRouteDecision.STOP
    )
    switch_time = float(visit_index)
    return EanCabinVisit(
        cabin_id=cabin_id,
        visit_index=visit_index,
        switch_id=f"switch_{station_index}",
        station_id=str(station_index),
        decision=decision,
        switch_time_seconds=switch_time,
        platform_entry_time_seconds=(
            switch_time + 0.2
            if decision is EanRouteDecision.STOP
            else None
        ),
        platform_exit_time_seconds=(
            switch_time + 0.5
            if decision is EanRouteDecision.STOP
            else None
        ),
        exit_switch_time_seconds=switch_time + 0.7,
        next_switch_time_seconds=switch_time + 1.0,
        wait_seconds=0.0,
    )


def _artifact_with_earliest_start(
    artifact: EanBuildArtifact,
) -> EanBuildArtifact:
    return EanBuildArtifact(
        scenario_id=artifact.scenario_id,
        config=artifact.config,
        state_ids=artifact.circulation_state_ids,
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
