from __future__ import annotations

import math
from dataclasses import dataclass
from enum import StrEnum
from typing import Any

from ropeway_skip_stop_optimization.models import Scenario
from ropeway_skip_stop_optimization.optimization.ean.artifact import EanBuildArtifact
from ropeway_skip_stop_optimization.optimization.ean.baselines import (
    EarliestAllStopEanMovementPlanBuilder,
)
from ropeway_skip_stop_optimization.optimization.ean.builders.passenger_builder import (
    EanPassengerCandidateBuildResult,
    EanPassengerCandidateBuilder,
)
from ropeway_skip_stop_optimization.optimization.ean.models import (
    EanDemandGroup,
    EanRideCandidate,
    SkipStopTiming,
    SwitchVisitDefinition,
)
from ropeway_skip_stop_optimization.optimization.ean.formulation_config import (
    EanBoardTimeFormulation,
    EanSlotActivationFormulation,
)
from ropeway_skip_stop_optimization.optimization.ean.optimization_config import EanOptimizationConfig
from ropeway_skip_stop_optimization.optimization.ean.passenger_plan import (
    EanPassengerServicePlan,
    EanServedRideGroup,
)
from ropeway_skip_stop_optimization.optimization.ean.plan import (
    EanCabinVisit,
    EanRouteDecision,
)
from ropeway_skip_stop_optimization.optimization.ean.optimizers.movement_model import (
    EanMovementModel,
    platform_entry_time_expr as _platform_entry_time_expr,
    platform_exit_time_expr as _platform_exit_time_expr,
    service_entry_to_next_switch_seconds as _service_entry_to_next_switch_seconds,
    variable_value as _value,
    visits_by_cabin_id_for as _visits_by_cabin_id,
)


class EanPassengerObjective(StrEnum):
    """Passenger objective for EAN service optimization."""

    WAITING_TIME = "waiting_time"
    JOURNEY_TIME = "journey_time"


@dataclass(frozen=True)
class EanPassengerVariables:
    slot: dict[tuple[str, int], Any]
    slot_board_time: dict[tuple[str, int], Any] | None
    slot_alight_time: dict[tuple[str, int], Any] | None
    unserved: dict[str, Any]


@dataclass(frozen=True)
class EanPassengerModel:
    movement: EanMovementModel
    passenger_build: EanPassengerCandidateBuildResult
    group_by_id: dict[str, EanDemandGroup]
    variables: EanPassengerVariables
    objective: EanPassengerObjective

    def apply_all_stop_mip_start(self) -> None:
        movement_variables = self.movement.variables
        _set_all_stop_mip_start(
            artifact=self.movement.artifact,
            passenger_build=self.passenger_build,
            group_by_id=self.group_by_id,
            switch_time=movement_variables.switch_time,
            exit_switch_time=movement_variables.exit_switch_time,
            wait_time=movement_variables.wait_time,
            stop=movement_variables.stop,
            slot=self.variables.slot,
            slot_board_time=self.variables.slot_board_time,
            slot_alight_time=self.variables.slot_alight_time,
            unserved=self.variables.unserved,
            visit_active=movement_variables.visit_active,
        )

    def extract_passenger_plan(self) -> EanPassengerServicePlan:
        movement_variables = self.movement.variables
        return _extract_passenger_plan(
            artifact=self.movement.artifact,
            passenger_build=self.passenger_build,
            group_by_id=self.group_by_id,
            switch_time=movement_variables.switch_time,
            wait_time=movement_variables.wait_time,
            slot=self.variables.slot,
            unserved=self.variables.unserved,
            visits_by_key=self.movement.visits_by_key,
            timing_by_switch_id=self.movement.timing_by_switch_id,
        )


@dataclass(frozen=True)
class EanPassengerModelBuilder:
    """Extend a canonical movement model with passenger assignment."""

    def build(
        self,
        *,
        scenario: Scenario,
        movement_model: EanMovementModel,
        objective: EanPassengerObjective,
        optimization_config: EanOptimizationConfig,
        gp: Any,
        grb: Any,
        passenger_builder: EanPassengerCandidateBuilder | None = None,
        passenger_build: EanPassengerCandidateBuildResult | None = None,
    ) -> EanPassengerModel:
        artifact = movement_model.artifact
        if scenario.id != artifact.scenario_id:
            raise ValueError(
                "EAN passenger problem scenario does not match the build artifact: "
                f"{scenario.id!r} != {artifact.scenario_id!r}"
            )
        if passenger_build is None:
            passenger_build = (
                passenger_builder
                or EanPassengerCandidateBuilder(optimization_config=optimization_config)
            ).build(scenario, artifact)
        group_by_id = {group.id: group for group in passenger_build.demand_groups}
        model = movement_model.model
        time_upper_bound = movement_model.model_time_bounds.global_upper

        slot: dict[tuple[str, int], Any] = {}
        slot_board_time: dict[tuple[str, int], Any] | None = (
            {}
            if (
                objective is EanPassengerObjective.WAITING_TIME
                or optimization_config.formulation.board_time
                is EanBoardTimeFormulation.EXPLICIT
            )
            else None
        )
        slot_alight_time: dict[tuple[str, int], Any] | None = (
            {} if objective is EanPassengerObjective.JOURNEY_TIME else None
        )
        for ride_candidate in passenger_build.ride_candidates:
            group = group_by_id[ride_candidate.demand_group_id]
            slot_count = min(group.count, artifact.config.cabin_capacity)
            for slot_index in range(slot_count):
                key = (ride_candidate.id, slot_index)
                variable_id = _var_id(ride_candidate.id)
                slot[key] = model.addVar(
                    vtype=grb.BINARY,
                    name=f"slot_{variable_id}_{slot_index}",
                )
                if slot_board_time is not None:
                    slot_board_time[key] = model.addVar(
                        lb=0.0,
                        ub=time_upper_bound,
                        name=f"slot_board_time_{variable_id}_{slot_index}",
                    )
                if slot_alight_time is not None:
                    slot_alight_time[key] = model.addVar(
                        lb=0.0,
                        ub=time_upper_bound,
                        name=f"slot_alight_time_{variable_id}_{slot_index}",
                    )
        unserved = {
            group.id: model.addVar(
                lb=0.0,
                ub=group.count,
                vtype=grb.INTEGER,
                name=f"unserved_{_var_id(group.id)}",
            )
            for group in passenger_build.demand_groups
        }
        model.update()

        movement_variables = movement_model.variables
        _add_passenger_constraints(
            model=model,
            passenger_build=passenger_build,
            group_by_id=group_by_id,
            switch_time=movement_variables.switch_time,
            wait_time=movement_variables.wait_time,
            stop=movement_variables.stop,
            slot=slot,
            slot_board_time=slot_board_time,
            slot_alight_time=slot_alight_time,
            unserved=unserved,
            visits_by_key=movement_model.visits_by_key,
            timing_by_switch_id=movement_model.timing_by_switch_id,
            cabin_capacity=artifact.config.cabin_capacity,
            horizon_seconds=artifact.config.horizon_seconds,
            time_upper_bound=time_upper_bound,
            big_m=movement_model.big_m,
            enable_slot_time_relaxation_strengthening=(
                optimization_config.enable_slot_time_relaxation_strengthening
            ),
            enable_tight_big_m_bounds=optimization_config.enable_tight_big_m_bounds,
            slot_activation_formulation=optimization_config.formulation.slot_activation,
        )
        variables = EanPassengerVariables(
            slot=slot,
            slot_board_time=slot_board_time,
            slot_alight_time=slot_alight_time,
            unserved=unserved,
        )
        objective_expression = _passenger_service_objective(
            objective=objective,
            passenger_build=passenger_build,
            group_by_id=group_by_id,
            slot=slot,
            slot_board_time=slot_board_time,
            slot_alight_time=slot_alight_time,
            unserved=unserved,
            horizon_seconds=artifact.config.horizon_seconds,
            gp=gp,
        )
        model.setObjective(objective_expression, grb.MINIMIZE)
        model.update()
        return EanPassengerModel(
            movement=movement_model,
            passenger_build=passenger_build,
            group_by_id=group_by_id,
            variables=variables,
            objective=objective,
        )


def _add_passenger_constraints(
    model: Any,
    passenger_build: EanPassengerCandidateBuildResult,
    group_by_id: dict[str, EanDemandGroup],
    switch_time: dict[tuple[int, int], Any],
    wait_time: dict[tuple[int, int], Any],
    stop: dict[tuple[int, int], Any],
    slot: dict[tuple[str, int], Any],
    slot_board_time: dict[tuple[str, int], Any] | None,
    slot_alight_time: dict[tuple[str, int], Any] | None,
    unserved: dict[str, Any],
    visits_by_key: dict[tuple[int, int], SwitchVisitDefinition],
    timing_by_switch_id: dict[str, SkipStopTiming],
    cabin_capacity: int,
    horizon_seconds: float,
    time_upper_bound: float,
    big_m: float,
    enable_slot_time_relaxation_strengthening: bool,
    enable_tight_big_m_bounds: bool,
    slot_activation_formulation: EanSlotActivationFormulation,
) -> None:
    ride_by_group_id: dict[str, list[EanRideCandidate]] = {group.id: [] for group in passenger_build.demand_groups}
    for ride_candidate in passenger_build.ride_candidates:
        ride_by_group_id[ride_candidate.demand_group_id].append(ride_candidate)
        _add_ride_slot_constraints(
            model=model,
            ride_candidate=ride_candidate,
            group=group_by_id[ride_candidate.demand_group_id],
            switch_time=switch_time,
            wait_time=wait_time,
            stop=stop,
            slot=slot,
            slot_board_time=slot_board_time,
            slot_alight_time=slot_alight_time,
            visits_by_key=visits_by_key,
            timing_by_switch_id=timing_by_switch_id,
            horizon_seconds=horizon_seconds,
            time_upper_bound=time_upper_bound,
            big_m=big_m,
            cabin_capacity=cabin_capacity,
            enable_slot_time_relaxation_strengthening=enable_slot_time_relaxation_strengthening,
            enable_tight_big_m_bounds=enable_tight_big_m_bounds,
            slot_activation_formulation=slot_activation_formulation,
        )

    for group in passenger_build.demand_groups:
        terms = []
        for ride_candidate in ride_by_group_id[group.id]:
            for slot_index in range(min(group.count, cabin_capacity)):
                terms.append(slot[ride_candidate.id, slot_index])
        model.addConstr(sum(terms) + unserved[group.id] == group.count, name=f"demand_balance_{_var_id(group.id)}")

    visits_by_cabin_id = _visits_by_cabin_id(tuple(visits_by_key.values()))
    ride_candidates_by_cabin_id: dict[int, list[EanRideCandidate]] = {}
    for ride_candidate in passenger_build.ride_candidates:
        ride_candidates_by_cabin_id.setdefault(ride_candidate.cabin_id, []).append(ride_candidate)

    for cabin_id, visits in visits_by_cabin_id.items():
        cabin_ride_candidates = ride_candidates_by_cabin_id.get(cabin_id, [])
        for visit in visits:
            onboard_terms = []
            interval_index = visit.visit_index
            for ride_candidate in cabin_ride_candidates:
                if ride_candidate.board_visit_index <= interval_index < ride_candidate.alight_visit_index:
                    group = group_by_id[ride_candidate.demand_group_id]
                    for slot_index in range(min(group.count, cabin_capacity)):
                        onboard_terms.append(slot[ride_candidate.id, slot_index])
            if onboard_terms:
                model.addConstr(
                    sum(onboard_terms) <= cabin_capacity,
                    name=f"capacity_cabin_{cabin_id}_interval_{interval_index}",
                )


def _add_ride_slot_constraints(
    model: Any,
    ride_candidate: EanRideCandidate,
    group: EanDemandGroup,
    switch_time: dict[tuple[int, int], Any],
    wait_time: dict[tuple[int, int], Any],
    stop: dict[tuple[int, int], Any],
    slot: dict[tuple[str, int], Any],
    slot_board_time: dict[tuple[str, int], Any] | None,
    slot_alight_time: dict[tuple[str, int], Any] | None,
    visits_by_key: dict[tuple[int, int], SwitchVisitDefinition],
    timing_by_switch_id: dict[str, SkipStopTiming],
    horizon_seconds: float,
    time_upper_bound: float,
    big_m: float,
    cabin_capacity: int,
    enable_slot_time_relaxation_strengthening: bool,
    enable_tight_big_m_bounds: bool,
    slot_activation_formulation: EanSlotActivationFormulation,
) -> None:
    board_key = (ride_candidate.cabin_id, ride_candidate.board_visit_index)
    alight_key = (ride_candidate.cabin_id, ride_candidate.alight_visit_index)
    board_time = _platform_exit_time_expr(board_key, switch_time, wait_time, visits_by_key, timing_by_switch_id)
    alight_time = _platform_entry_time_expr(alight_key, switch_time, visits_by_key, timing_by_switch_id)
    slot_count = min(group.count, cabin_capacity)
    release_big_m = _slot_release_big_m(
        group=group,
        global_big_m=big_m,
        enable_tight_big_m_bounds=enable_tight_big_m_bounds,
    )

    compact_activation = (
        slot_activation_formulation is EanSlotActivationFormulation.FIRST_SLOT_IMPLICATIONS
    )
    previous_slot_var = None
    for slot_index in range(slot_count):
        key = (ride_candidate.id, slot_index)
        slot_var = slot[key]
        if not compact_activation or slot_index == 0:
            _add_ride_slot_activation_constraints(
                model=model,
                ride_candidate=ride_candidate,
                group=group,
                slot_index=slot_index,
                slot_var=slot_var,
                board_time=board_time,
                alight_time=alight_time,
                board_stop=stop[board_key],
                alight_stop=stop[alight_key],
                horizon_seconds=horizon_seconds,
                big_m=big_m,
                release_big_m=release_big_m,
                omit_zero_release=compact_activation,
            )
        if slot_board_time is not None:
            slot_time = slot_board_time[key]
            model.addConstr(
                slot_time <= time_upper_bound * slot_var,
                name=f"slot_time_active_{_var_id(ride_candidate.id)}_{slot_index}",
            )
            model.addConstr(
                slot_time <= board_time,
                name=f"slot_time_board_ub_{_var_id(ride_candidate.id)}_{slot_index}",
            )
            model.addConstr(
                slot_time >= board_time - time_upper_bound * (1 - slot_var),
                name=f"slot_time_board_lb_{_var_id(ride_candidate.id)}_{slot_index}",
            )
        if slot_alight_time is not None:
            alight_slot_time = slot_alight_time[key]
            model.addConstr(
                alight_slot_time <= time_upper_bound * slot_var,
                name=f"slot_alight_time_active_{_var_id(ride_candidate.id)}_{slot_index}",
            )
            model.addConstr(
                alight_slot_time <= alight_time,
                name=f"slot_time_alight_ub_{_var_id(ride_candidate.id)}_{slot_index}",
            )
            model.addConstr(
                alight_slot_time >= alight_time - time_upper_bound * (1 - slot_var),
                name=f"slot_time_alight_lb_{_var_id(ride_candidate.id)}_{slot_index}",
            )
        if enable_slot_time_relaxation_strengthening:
            if slot_board_time is not None:
                _add_slot_time_relaxation_strengthening_constraints(
                    model=model,
                    ride_candidate=ride_candidate,
                    group=group,
                    slot_index=slot_index,
                    slot_var=slot_var,
                    slot_board_time=slot_board_time[key],
                    slot_alight_time=slot_alight_time[key] if slot_alight_time is not None else None,
                    visits_by_key=visits_by_key,
                    timing_by_switch_id=timing_by_switch_id,
                    omit_redundant_rows=compact_activation,
                )
            else:
                if slot_alight_time is None:
                    raise ValueError("projected board times require journey-time selected alight variables")
                _add_projected_journey_slot_time_constraints(
                    model=model,
                    ride_candidate=ride_candidate,
                    group=group,
                    slot_index=slot_index,
                    slot_var=slot_var,
                    board_time=board_time,
                    slot_alight_time=slot_alight_time[key],
                    time_upper_bound=time_upper_bound,
                    visits_by_key=visits_by_key,
                    timing_by_switch_id=timing_by_switch_id,
                    omit_release_row=compact_activation and slot_index > 0,
                )
        if previous_slot_var is not None:
            model.addConstr(slot_var <= previous_slot_var, name=f"slot_symmetry_{_var_id(ride_candidate.id)}_{slot_index}")
        previous_slot_var = slot_var


def _add_ride_slot_activation_constraints(
    model: Any,
    ride_candidate: EanRideCandidate,
    group: EanDemandGroup,
    slot_index: int,
    slot_var: Any,
    board_time: Any,
    alight_time: Any,
    board_stop: Any,
    alight_stop: Any,
    horizon_seconds: float,
    big_m: float,
    release_big_m: float,
    omit_zero_release: bool,
) -> None:
    """Add candidate-level conditions activated through one unary slot.

    With unary ordering, the first slot dominates all later slot binaries.
    Attaching these rows only to that first slot therefore preserves the full
    LP relaxation. At zero release, the release implication is redundant
    because platform-departure expressions are nonnegative in every supported
    time-bound formulation.
    """

    variable_id = _var_id(ride_candidate.id)
    model.addConstr(slot_var <= board_stop, name=f"slot_board_stop_{variable_id}_{slot_index}")
    model.addConstr(slot_var <= alight_stop, name=f"slot_alight_stop_{variable_id}_{slot_index}")
    if not (omit_zero_release and group.release_time_seconds == 0.0):
        model.addConstr(
            board_time >= group.release_time_seconds - release_big_m * (1 - slot_var),
            name=f"slot_release_{variable_id}_{slot_index}",
        )
    model.addConstr(
        board_time <= horizon_seconds + big_m * (1 - slot_var),
        name=f"slot_board_horizon_{variable_id}_{slot_index}",
    )
    model.addConstr(
        alight_time <= horizon_seconds + big_m * (1 - slot_var),
        name=f"slot_alight_horizon_{variable_id}_{slot_index}",
    )


def _slot_release_big_m(
    group: EanDemandGroup,
    global_big_m: float,
    enable_tight_big_m_bounds: bool,
) -> float:
    """Return Big-M for the inactive passenger release-time constraint.

    For `slot = 0`, using `M = release_time` relaxes
    `board_time >= release_time - M * (1 - slot)` to `board_time >= 0`.
    That is safe because board-time expressions are built from nonnegative
    switch/wait variables and nonnegative timing constants. Other slot-time
    horizon constraints stay on the conservative global Big-M until we have
    proven expression-specific upper bounds.
    """

    if not enable_tight_big_m_bounds:
        return global_big_m
    return group.release_time_seconds


def _add_slot_time_relaxation_strengthening_constraints(
    model: Any,
    ride_candidate: EanRideCandidate,
    group: EanDemandGroup,
    slot_index: int,
    slot_var: Any,
    slot_board_time: Any,
    slot_alight_time: Any | None,
    visits_by_key: dict[tuple[int, int], SwitchVisitDefinition],
    timing_by_switch_id: dict[str, SkipStopTiming],
    omit_redundant_rows: bool,
) -> None:
    """Add slot-time relaxation strengthening constraints.

    These are valid lower bounds for the existing slot-time linearization:
    active slots cannot board before demand release, and journey-time slots
    cannot alight earlier than the minimum physical trip time. They preserve the
    integer feasible set but make fractional slot assignments less artificially
    cheap in the LP relaxation. In the compact activation formulation, the
    zero-release board lower bound follows from the variable lower bound, and
    the alight-earliest row follows from the board-release and retained
    minimum-trip-duration rows.
    """

    variable_id = _var_id(ride_candidate.id)
    if not (omit_redundant_rows and group.release_time_seconds == 0.0):
        model.addConstr(
            slot_board_time >= group.release_time_seconds * slot_var,
            name=f"slot_board_release_lb_{variable_id}_{slot_index}",
        )

    if slot_alight_time is None:
        return

    min_trip_time = _min_candidate_trip_time_seconds(
        ride_candidate=ride_candidate,
        visits_by_key=visits_by_key,
        timing_by_switch_id=timing_by_switch_id,
    )
    if not omit_redundant_rows:
        model.addConstr(
            slot_alight_time >= (group.release_time_seconds + min_trip_time) * slot_var,
            name=f"slot_alight_earliest_lb_{variable_id}_{slot_index}",
        )
    model.addConstr(
        slot_alight_time - slot_board_time >= min_trip_time * slot_var,
        name=f"slot_trip_duration_lb_{variable_id}_{slot_index}",
    )


def _add_projected_journey_slot_time_constraints(
    model: Any,
    ride_candidate: EanRideCandidate,
    group: EanDemandGroup,
    slot_index: int,
    slot_var: Any,
    board_time: Any,
    slot_alight_time: Any,
    time_upper_bound: float,
    visits_by_key: dict[tuple[int, int], SwitchVisitDefinition],
    timing_by_switch_id: dict[str, SkipStopTiming],
    omit_release_row: bool = False,
) -> None:
    """Add the Fourier--Motzkin projection of selected boarding time.

    For journey time, selected boarding time is auxiliary. Eliminating it from
    its McCormick linearization, release lower bound, and selected minimum-trip
    duration preserves the full LP relaxation in the remaining variables. With
    first-slot activation, the shared board-time release row is needed only for
    the first unary slot because every later slot is bounded by that slot.
    """

    variable_id = _var_id(ride_candidate.id)
    min_trip_time = _min_candidate_trip_time_seconds(
        ride_candidate=ride_candidate,
        visits_by_key=visits_by_key,
        timing_by_switch_id=timing_by_switch_id,
    )
    if group.release_time_seconds > 0.0 and not omit_release_row:
        model.addConstr(
            board_time >= group.release_time_seconds * slot_var,
            name=f"slot_projected_board_release_lb_{variable_id}_{slot_index}",
        )
    model.addConstr(
        slot_alight_time >= (group.release_time_seconds + min_trip_time) * slot_var,
        name=f"slot_projected_alight_earliest_lb_{variable_id}_{slot_index}",
    )
    model.addConstr(
        slot_alight_time
        >= board_time - time_upper_bound * (1 - slot_var) + min_trip_time * slot_var,
        name=f"slot_projected_board_alight_lb_{variable_id}_{slot_index}",
    )


def _passenger_service_objective(
    objective: EanPassengerObjective,
    passenger_build: EanPassengerCandidateBuildResult,
    group_by_id: dict[str, EanDemandGroup],
    slot: dict[tuple[str, int], Any],
    slot_board_time: dict[tuple[str, int], Any] | None,
    slot_alight_time: dict[tuple[str, int], Any] | None,
    unserved: dict[str, Any],
    horizon_seconds: float,
    gp: Any,
) -> Any:
    if objective is EanPassengerObjective.WAITING_TIME:
        if slot_board_time is None:
            raise ValueError("slot_board_time is required for waiting-time objective")
        return _served_time_minus_release_objective(
            passenger_build=passenger_build,
            group_by_id=group_by_id,
            slot=slot,
            slot_time=slot_board_time,
            unserved=unserved,
            horizon_seconds=horizon_seconds,
            gp=gp,
        )
    if objective is EanPassengerObjective.JOURNEY_TIME:
        if slot_alight_time is None:
            raise ValueError("slot_alight_time is required for journey-time objective")
        return _served_time_minus_release_objective(
            passenger_build=passenger_build,
            group_by_id=group_by_id,
            slot=slot,
            slot_time=slot_alight_time,
            unserved=unserved,
            horizon_seconds=horizon_seconds,
            gp=gp,
        )
    raise ValueError(f"unsupported EAN passenger service objective: {objective}")


def _set_all_stop_mip_start(
    artifact: EanBuildArtifact,
    passenger_build: EanPassengerCandidateBuildResult,
    group_by_id: dict[str, EanDemandGroup],
    switch_time: dict[tuple[int, int], Any],
    exit_switch_time: dict[tuple[int, int], Any],
    wait_time: dict[tuple[int, int], Any],
    stop: dict[tuple[int, int], Any],
    slot: dict[tuple[str, int], Any],
    slot_board_time: dict[tuple[str, int], Any] | None,
    slot_alight_time: dict[tuple[str, int], Any] | None,
    unserved: dict[str, Any],
    visit_active: dict[tuple[int, int], Any],
) -> None:
    all_stop_plan = EarliestAllStopEanMovementPlanBuilder().build(artifact)
    visit_start_by_key = {
        (visit.cabin_id, visit.visit_index): visit
        for trajectory in all_stop_plan.trajectories
        for visit in trajectory.visits
    }

    for key, variable in switch_time.items():
        visit = visit_start_by_key[key]
        active_start = float(
            visit.switch_time_seconds <= artifact.config.operational_end_seconds
        )
        if not isinstance(visit_active[key], int | float):
            visit_active[key].Start = active_start
            route_active_start = active_start
        else:
            route_active_start = float(visit_active[key])
        variable.Start = visit.switch_time_seconds
        exit_switch_time[key].Start = visit.exit_switch_time_seconds
        wait_time[key].Start = 0.0
        stop[key].Start = route_active_start

    for key, variable in slot.items():
        variable.Start = 0.0
        if slot_board_time is not None:
            slot_board_time[key].Start = 0.0
        if slot_alight_time is not None:
            slot_alight_time[key].Start = 0.0
    for variable in unserved.values():
        variable.Start = 0.0

    remaining_by_group_id = {
        group.id: group.count
        for group in passenger_build.demand_groups
    }
    load_by_interval: dict[tuple[int, int], int] = {}
    served_slot_keys: set[tuple[str, int]] = set()

    for ride_candidate in _all_stop_mip_start_candidate_order(
        passenger_build.ride_candidates,
        group_by_id,
        visit_start_by_key,
        artifact.config.horizon_seconds,
    ):
        group = group_by_id[ride_candidate.demand_group_id]
        remaining = remaining_by_group_id[group.id]
        if remaining <= 0:
            continue

        interval_keys = tuple(
            (ride_candidate.cabin_id, interval_index)
            for interval_index in range(ride_candidate.board_visit_index, ride_candidate.alight_visit_index)
        )
        free_capacity = min(
            artifact.config.cabin_capacity - load_by_interval.get(interval_key, 0)
            for interval_key in interval_keys
        )
        if free_capacity <= 0:
            continue

        slot_count = min(group.count, artifact.config.cabin_capacity)
        assign_count = min(remaining, free_capacity, slot_count)
        board_time = _all_stop_platform_exit_time(
            ride_candidate.cabin_id,
            ride_candidate.board_visit_index,
            visit_start_by_key,
        )
        alight_time = _all_stop_platform_entry_time(
            ride_candidate.cabin_id,
            ride_candidate.alight_visit_index,
            visit_start_by_key,
        )
        for slot_index in range(assign_count):
            slot_key = (ride_candidate.id, slot_index)
            slot[slot_key].Start = 1.0
            if slot_board_time is not None:
                slot_board_time[slot_key].Start = board_time
            if slot_alight_time is not None:
                slot_alight_time[slot_key].Start = alight_time
            served_slot_keys.add(slot_key)

        for interval_key in interval_keys:
            load_by_interval[interval_key] = load_by_interval.get(interval_key, 0) + assign_count
        remaining_by_group_id[group.id] -= assign_count

    for group_id, remaining in remaining_by_group_id.items():
        unserved[group_id].Start = remaining

    for key, variable in slot.items():
        if key in served_slot_keys:
            continue
        variable.Start = 0.0
        if slot_board_time is not None:
            slot_board_time[key].Start = 0.0
        if slot_alight_time is not None:
            slot_alight_time[key].Start = 0.0


def _all_stop_mip_start_candidate_order(
    ride_candidates: tuple[EanRideCandidate, ...],
    group_by_id: dict[str, EanDemandGroup],
    visit_start_by_key: dict[tuple[int, int], EanCabinVisit],
    horizon_seconds: float,
) -> tuple[EanRideCandidate, ...]:
    candidates_with_times: list[tuple[float, float, int, int, str, EanRideCandidate]] = []
    for ride_candidate in ride_candidates:
        group = group_by_id[ride_candidate.demand_group_id]
        board_key = (ride_candidate.cabin_id, ride_candidate.board_visit_index)
        alight_key = (ride_candidate.cabin_id, ride_candidate.alight_visit_index)
        if board_key not in visit_start_by_key or alight_key not in visit_start_by_key:
            continue
        if not _all_stop_visit_is_stop_at_station(board_key, group.origin_station_id, visit_start_by_key):
            continue
        if not _all_stop_visit_is_stop_at_station(alight_key, group.destination_station_id, visit_start_by_key):
            continue
        board_time = _all_stop_platform_exit_time(ride_candidate.cabin_id, ride_candidate.board_visit_index, visit_start_by_key)
        alight_time = _all_stop_platform_entry_time(ride_candidate.cabin_id, ride_candidate.alight_visit_index, visit_start_by_key)
        if board_time < group.release_time_seconds or board_time > horizon_seconds or alight_time > horizon_seconds:
            continue
        candidates_with_times.append(
            (
                group.release_time_seconds,
                board_time,
                ride_candidate.cabin_id,
                ride_candidate.board_visit_index,
                ride_candidate.id,
                ride_candidate,
            )
        )
    return tuple(item[-1] for item in sorted(candidates_with_times))


def _all_stop_visit_is_stop_at_station(
    key: tuple[int, int],
    station_id: str,
    visit_start_by_key: dict[tuple[int, int], EanCabinVisit],
) -> bool:
    visit = visit_start_by_key[key]
    return visit.decision is EanRouteDecision.STOP and visit.station_id == station_id


def _all_stop_platform_entry_time(
    cabin_id: int,
    visit_index: int,
    visit_start_by_key: dict[tuple[int, int], EanCabinVisit],
) -> float:
    time_seconds = visit_start_by_key[cabin_id, visit_index].platform_entry_time_seconds
    if time_seconds is None:
        raise ValueError("all-stop MIP start needs platform entry times")
    return time_seconds


def _all_stop_platform_exit_time(
    cabin_id: int,
    visit_index: int,
    visit_start_by_key: dict[tuple[int, int], EanCabinVisit],
) -> float:
    time_seconds = visit_start_by_key[cabin_id, visit_index].platform_exit_time_seconds
    if time_seconds is None:
        raise ValueError("all-stop MIP start needs platform exit times")
    return time_seconds


def _waiting_time_objective(
    passenger_build: EanPassengerCandidateBuildResult,
    group_by_id: dict[str, EanDemandGroup],
    slot: dict[tuple[str, int], Any],
    slot_board_time: dict[tuple[str, int], Any],
    unserved: dict[str, Any],
    horizon_seconds: float,
    gp: Any,
) -> Any:
    return _served_time_minus_release_objective(
        passenger_build=passenger_build,
        group_by_id=group_by_id,
        slot=slot,
        slot_time=slot_board_time,
        unserved=unserved,
        horizon_seconds=horizon_seconds,
        gp=gp,
    )


def _served_time_minus_release_objective(
    passenger_build: EanPassengerCandidateBuildResult,
    group_by_id: dict[str, EanDemandGroup],
    slot: dict[tuple[str, int], Any],
    slot_time: dict[tuple[str, int], Any],
    unserved: dict[str, Any],
    horizon_seconds: float,
    gp: Any,
) -> Any:
    candidate_by_id = {candidate.id: candidate for candidate in passenger_build.ride_candidates}
    served_terms = []
    for key, slot_var in slot.items():
        ride_candidate = candidate_by_id[key[0]]
        group = group_by_id[ride_candidate.demand_group_id]
        served_terms.append(slot_time[key] - group.release_time_seconds * slot_var)

    unserved_terms = [
        max(0.0, horizon_seconds - group.release_time_seconds) * unserved[group.id]
        for group in passenger_build.demand_groups
    ]
    return gp.quicksum(served_terms + unserved_terms)


def _extract_passenger_plan(
    artifact: EanBuildArtifact,
    passenger_build: EanPassengerCandidateBuildResult,
    group_by_id: dict[str, EanDemandGroup],
    switch_time: dict[tuple[int, int], Any],
    wait_time: dict[tuple[int, int], Any],
    slot: dict[tuple[str, int], Any],
    unserved: dict[str, Any],
    visits_by_key: dict[tuple[int, int], SwitchVisitDefinition],
    timing_by_switch_id: dict[str, SkipStopTiming],
) -> EanPassengerServicePlan:
    served_rides: list[EanServedRideGroup] = []
    served_count_by_candidate_id: dict[str, int] = {}
    for key, variable in slot.items():
        if _value(variable) >= 0.5:
            served_count_by_candidate_id[key[0]] = served_count_by_candidate_id.get(key[0], 0) + 1

    for ride_candidate in passenger_build.ride_candidates:
        count = served_count_by_candidate_id.get(ride_candidate.id, 0)
        if count == 0:
            continue
        board_key = (ride_candidate.cabin_id, ride_candidate.board_visit_index)
        alight_key = (ride_candidate.cabin_id, ride_candidate.alight_visit_index)
        served_rides.append(
            EanServedRideGroup(
                demand_group_id=ride_candidate.demand_group_id,
                cabin_id=ride_candidate.cabin_id,
                board_visit_index=ride_candidate.board_visit_index,
                alight_visit_index=ride_candidate.alight_visit_index,
                count=count,
                boarding_time_seconds=_expr_value(
                    _platform_exit_time_expr(board_key, switch_time, wait_time, visits_by_key, timing_by_switch_id)
                ),
                alighting_time_seconds=_expr_value(
                    _platform_entry_time_expr(alight_key, switch_time, visits_by_key, timing_by_switch_id)
                ),
            )
        )

    unserved_counts = {
        group_id: int(round(_value(variable)))
        for group_id, variable in unserved.items()
    }
    plan = EanPassengerServicePlan(
        scenario_id=artifact.scenario_id,
        horizon_seconds=artifact.config.horizon_seconds,
        served_rides=tuple(served_rides),
        unserved_counts_by_demand_group_id=unserved_counts,
    )
    plan.validate()
    _validate_passenger_accounting(group_by_id, plan)
    return plan


def _validate_passenger_accounting(
    group_by_id: dict[str, EanDemandGroup],
    plan: EanPassengerServicePlan,
) -> None:
    served_by_group_id: dict[str, int] = {group_id: 0 for group_id in group_by_id}
    for ride in plan.served_rides:
        served_by_group_id[ride.demand_group_id] = served_by_group_id.get(ride.demand_group_id, 0) + ride.count
    for group_id, group in group_by_id.items():
        if served_by_group_id[group_id] + plan.unserved_counts_by_demand_group_id[group_id] != group.count:
            raise ValueError(f"EAN passenger accounting mismatch for demand group {group_id!r}")


def _min_candidate_trip_time_seconds(
    ride_candidate: EanRideCandidate,
    visits_by_key: dict[tuple[int, int], SwitchVisitDefinition],
    timing_by_switch_id: dict[str, SkipStopTiming],
) -> float:
    if ride_candidate.alight_visit_index <= ride_candidate.board_visit_index:
        raise ValueError("ride candidate alight visit must be after board visit")

    board_key = (ride_candidate.cabin_id, ride_candidate.board_visit_index)
    alight_key = (ride_candidate.cabin_id, ride_candidate.alight_visit_index)
    if board_key not in visits_by_key:
        raise ValueError(f"ride candidate board visit is not in EAN visits: {board_key!r}")
    if alight_key not in visits_by_key:
        raise ValueError(f"ride candidate alight visit is not in EAN visits: {alight_key!r}")

    board_timing = timing_by_switch_id[visits_by_key[board_key].switch_id]
    alight_timing = timing_by_switch_id[visits_by_key[alight_key].switch_id]
    elapsed = board_timing.platform_exit_to_exit_switch_seconds + board_timing.rope_to_next_switch_seconds

    for visit_index in range(ride_candidate.board_visit_index + 1, ride_candidate.alight_visit_index):
        key = (ride_candidate.cabin_id, visit_index)
        if key not in visits_by_key:
            raise ValueError(f"ride candidate intermediate visit is not in EAN visits: {key!r}")
        timing = timing_by_switch_id[visits_by_key[key].switch_id]
        elapsed += _min_entry_to_next_switch_seconds(timing)

    return elapsed + alight_timing.entry_to_platform_entry_seconds


def _min_entry_to_next_switch_seconds(timing: SkipStopTiming) -> float:
    service_seconds = _service_entry_to_next_switch_seconds(timing)
    if not timing.skip_allowed:
        return service_seconds
    return min(service_seconds, timing.skip_entry_to_exit_switch_seconds + timing.rope_to_next_switch_seconds)


def _expr_value(expression: Any) -> float:
    if hasattr(expression, "getValue"):
        value = float(expression.getValue())
    else:
        value = float(expression.X)
    if math.isclose(value, round(value), abs_tol=1e-8):
        return float(round(value))
    return value


def _var_id(value: str) -> str:
    return value.replace("::", "_").replace(":", "_").replace("-", "_")
