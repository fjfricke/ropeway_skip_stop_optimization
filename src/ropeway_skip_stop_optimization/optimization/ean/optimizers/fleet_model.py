from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from ropeway_skip_stop_optimization.optimization.ean.artifact import (
    EanBuildArtifact,
)
from ropeway_skip_stop_optimization.optimization.ean.fleet import (
    EanFleetPlan,
    EanInitialPlacementState,
    EanInitialPlacementStateKind,
)
from ropeway_skip_stop_optimization.optimization.ean.models import (
    EanFleetCardinalityMode,
    HeadwayCheckpointKind,
    SkipStopTiming,
    SwitchVisitDefinition,
)
from ropeway_skip_stop_optimization.optimization.ean.plan import EanMovementPlan


VisitKey = tuple[int, int]
BOUNDARY_EPSILON_SECONDS = 1e-5


@dataclass(frozen=True)
class EanFleetVariables:
    cabin_active: dict[int, Any]
    station_selected: dict[VisitKey, Any]
    rope_selected: dict[VisitKey, Any]
    route_active: dict[VisitKey, Any]

    def all_variables(self) -> tuple[Any, ...]:
        return tuple(
            (
                *self.cabin_active.values(),
                *self.station_selected.values(),
                *self.rope_selected.values(),
                *self.route_active.values(),
            )
        )


@dataclass(frozen=True)
class EanFleetModel:
    artifact: EanBuildArtifact
    variables: EanFleetVariables
    switch_time: dict[VisitKey, Any]
    exit_switch_time: dict[VisitKey, Any]
    wait_time: dict[VisitKey, Any]
    stop: dict[VisitKey, Any]
    visits_by_cabin_id: dict[int, tuple[SwitchVisitDefinition, ...]]
    timing_by_switch_id: dict[str, SkipStopTiming]

    def apply_mip_start(
        self,
        fleet_plan: EanFleetPlan,
        movement_plan: EanMovementPlan,
    ) -> None:
        self._apply_mip_start(
            fleet_plan,
            movement_plan,
            cabin_ids=frozenset(self.variables.cabin_active),
        )

    def apply_partial_mip_start(
        self,
        fleet_plan: EanFleetPlan,
        movement_plan: EanMovementPlan,
    ) -> None:
        """Seed only cabins that are active in a partial fleet plan."""

        self._apply_mip_start(
            fleet_plan,
            movement_plan,
            cabin_ids=frozenset(fleet_plan.active_cabin_ids),
        )

    def _apply_mip_start(
        self,
        fleet_plan: EanFleetPlan,
        movement_plan: EanMovementPlan,
        *,
        cabin_ids: frozenset[int],
    ) -> None:
        fleet_plan.validate()
        parameters = self.artifact.initial_placement_parameters
        if parameters is None:
            raise ValueError("fixed-start artifacts do not have fleet variables")
        if fleet_plan.mode is not parameters.mode:
            raise ValueError("fleet MIP start mode does not match the artifact")
        if fleet_plan.available_fleet_count != parameters.available_fleet_count:
            raise ValueError(
                "fleet MIP start available count does not match the artifact"
            )

        state_by_cabin_id = {
            state.cabin_id: state for state in fleet_plan.initial_states
        }
        active_ids = set(fleet_plan.active_cabin_ids)
        movement_keys = {
            (visit.cabin_id, visit.visit_index)
            for trajectory in movement_plan.trajectories
            for visit in trajectory.visits
        }
        for cabin_id, variable in self.variables.cabin_active.items():
            if cabin_id not in cabin_ids:
                continue
            variable.Start = float(cabin_id in active_ids)
        for key, variable in self.variables.station_selected.items():
            if key[0] not in cabin_ids:
                continue
            state = state_by_cabin_id.get(key[0])
            variable.Start = float(
                state is not None
                and state.visit_index == key[1]
                and state.kind is not EanInitialPlacementStateKind.ROPE
            )
        for key, variable in self.variables.rope_selected.items():
            if key[0] not in cabin_ids:
                continue
            state = state_by_cabin_id.get(key[0])
            variable.Start = float(
                state is not None
                and state.visit_index == key[1]
                and state.kind is EanInitialPlacementStateKind.ROPE
            )
        for key, variable in self.variables.route_active.items():
            if key[0] not in cabin_ids:
                continue
            variable.Start = float(key in movement_keys)

    def extract_plan(self) -> EanFleetPlan:
        parameters = self.artifact.initial_placement_parameters
        if parameters is None:
            raise ValueError(
                "fixed-start artifacts do not have an initial placement plan"
            )
        active_ids = tuple(
            cabin_id
            for cabin_id, variable in sorted(self.variables.cabin_active.items())
            if float(variable.X) >= 0.5
        )
        inactive_ids = tuple(
            cabin_id
            for cabin_id in sorted(self.variables.cabin_active)
            if cabin_id not in active_ids
        )
        states = tuple(self._extract_initial_state(cabin_id) for cabin_id in active_ids)
        plan = EanFleetPlan(
            mode=parameters.mode,
            available_fleet_count=parameters.available_fleet_count,
            active_cabin_ids=active_ids,
            inactive_cabin_ids=inactive_ids,
            initial_states=states,
        )
        plan.validate()
        return plan

    def _extract_initial_state(self, cabin_id: int) -> EanInitialPlacementState:
        parameters = self.artifact.initial_placement_parameters
        if parameters is None:
            raise ValueError("initial state extraction needs fleet parameters")
        tolerance = 1e-5
        phase_visits = self.visits_by_cabin_id[cabin_id][
            : parameters.initial_phase_visit_count
        ]
        selected_station = next(
            (
                visit
                for visit in phase_visits
                if float(
                    self.variables.station_selected[(cabin_id, visit.visit_index)].X
                )
                >= 0.5
            ),
            None,
        )
        if selected_station is not None:
            visit = selected_station
            key = (cabin_id, visit.visit_index)
            timing = self.timing_by_switch_id[visit.switch_id]
            switch_seconds = float(self.switch_time[key].X)
            exit_seconds = float(self.exit_switch_time[key].X)
            if abs(switch_seconds) <= tolerance:
                return EanInitialPlacementState(
                    cabin_id=cabin_id,
                    kind=EanInitialPlacementStateKind.ENTRY_SWITCH,
                    switch_id=visit.switch_id,
                    visit_index=visit.visit_index,
                    progress=0.0,
                    previous_event_time_seconds=0.0,
                    next_event_time_seconds=0.0,
                )
            if abs(exit_seconds) <= tolerance:
                return EanInitialPlacementState(
                    cabin_id=cabin_id,
                    kind=EanInitialPlacementStateKind.EXIT_SWITCH,
                    switch_id=visit.switch_id,
                    visit_index=visit.visit_index,
                    progress=0.0,
                    previous_event_time_seconds=0.0,
                    next_event_time_seconds=0.0,
                )
            stopped = float(self.stop[key].X) >= 0.5
            kind = (
                EanInitialPlacementStateKind.SERVICE_ROUTE
                if stopped
                else EanInitialPlacementStateKind.SKIP_ROUTE
            )
            if stopped:
                wait_entry = (
                    switch_seconds
                    + timing.entry_to_platform_entry_seconds
                    + timing.min_platform_entry_to_platform_exit_seconds
                )
                platform_exit = wait_entry + float(self.wait_time[key].X)
                if wait_entry <= tolerance and platform_exit > tolerance:
                    kind = EanInitialPlacementStateKind.PLATFORM_WAIT
            duration = max(exit_seconds - switch_seconds, tolerance)
            return EanInitialPlacementState(
                cabin_id=cabin_id,
                kind=kind,
                switch_id=visit.switch_id,
                visit_index=visit.visit_index,
                progress=min(1.0, max(0.0, -switch_seconds / duration)),
                previous_event_time_seconds=switch_seconds,
                next_event_time_seconds=exit_seconds,
            )

        selected_rope = next(
            (
                visit
                for visit in phase_visits
                if float(self.variables.rope_selected[(cabin_id, visit.visit_index)].X)
                >= 0.5
            ),
            None,
        )
        if selected_rope is not None:
            phase_index = selected_rope.visit_index
            previous_switch_id = self.artifact.switch_cycle[
                (phase_index - 1) % len(self.artifact.switch_cycle)
            ]
            rope_seconds = self.timing_by_switch_id[
                previous_switch_id
            ].rope_to_next_switch_seconds
            next_seconds = float(
                self.switch_time[(cabin_id, selected_rope.visit_index)].X
            )
            previous_seconds = next_seconds - rope_seconds
            return EanInitialPlacementState(
                cabin_id=cabin_id,
                kind=EanInitialPlacementStateKind.ROPE,
                switch_id=previous_switch_id,
                visit_index=selected_rope.visit_index,
                progress=min(
                    1.0,
                    max(0.0, -previous_seconds / rope_seconds),
                ),
                previous_event_time_seconds=previous_seconds,
                next_event_time_seconds=next_seconds,
            )

        raise ValueError(
            f"active cabin {cabin_id} has no physical state at service start"
        )


@dataclass(frozen=True)
class EanFleetModelBuilder:
    def build_activation(
        self,
        *,
        model: Any,
        binary_vtype: Any,
        artifact: EanBuildArtifact,
        switch_time: dict[VisitKey, Any],
        exit_switch_time: dict[VisitKey, Any],
        wait_time: dict[VisitKey, Any],
        stop: dict[VisitKey, Any],
        visit_reached: dict[VisitKey, Any],
        visits_by_cabin_id: dict[int, tuple[SwitchVisitDefinition, ...]],
        timing_by_switch_id: dict[str, SkipStopTiming],
        big_m: float,
    ) -> EanFleetModel:
        parameters = artifact.initial_placement_parameters
        if parameters is None:
            raise ValueError("initial placement fleet model needs fleet parameters")

        exact_fleet = artifact.fleet_cardinality_mode is EanFleetCardinalityMode.EXACT
        cabin_active = {
            cabin_id: model.addVar(
                vtype=binary_vtype,
                lb=1.0 if exact_fleet else 0.0,
                ub=1.0,
                name=f"cabin_active_{cabin_id}",
            )
            for cabin_id in visits_by_cabin_id
        }
        phase_keys = tuple(
            (cabin_id, visit.visit_index)
            for cabin_id, visits in visits_by_cabin_id.items()
            for visit in visits[: parameters.initial_phase_visit_count]
        )
        station_selected = {
            key: model.addVar(
                vtype=binary_vtype,
                name=f"initial_station_{key[0]}_{key[1]}",
            )
            for key in phase_keys
        }
        rope_selected = {
            key: model.addVar(
                vtype=binary_vtype,
                name=f"initial_rope_{key[0]}_{key[1]}",
            )
            for key in phase_keys
        }
        route_active = {
            key: model.addVar(
                vtype=binary_vtype,
                name=f"route_active_{key[0]}_{key[1]}",
            )
            for key in visit_reached
        }
        model.update()

        for cabin_id, visits in visits_by_cabin_id.items():
            active = cabin_active[cabin_id]
            phase_visits = visits[: parameters.initial_phase_visit_count]
            model.addConstr(
                sum(
                    (
                        station_selected[(cabin_id, visit.visit_index)]
                        + rope_selected[(cabin_id, visit.visit_index)]
                    )
                    for visit in phase_visits
                )
                == active,
                name=f"select_initial_state_{cabin_id}",
            )

            for visit in visits:
                key = (cabin_id, visit.visit_index)
                reached = visit_reached[key]
                started = sum(
                    (
                        station_selected[(cabin_id, phase_visit.visit_index)]
                        + rope_selected[(cabin_id, phase_visit.visit_index)]
                    )
                    for phase_visit in phase_visits
                    if phase_visit.visit_index <= visit.visit_index
                )
                model.addConstr(
                    route_active[key] <= started,
                    name=f"route_requires_start_{cabin_id}_{visit.visit_index}",
                )
                model.addConstr(
                    route_active[key] <= reached,
                    name=f"route_requires_visit_{cabin_id}_{visit.visit_index}",
                )
                model.addConstr(
                    route_active[key] >= started + reached - 1,
                    name=f"route_active_and_{cabin_id}_{visit.visit_index}",
                )

            for previous, current in zip(visits, visits[1:]):
                current_key = (cabin_id, current.visit_index)
                previous_key = (cabin_id, previous.visit_index)
                start_at_current = (
                    station_selected[current_key] + rope_selected[current_key]
                    if current_key in station_selected
                    else 0
                )
                model.addConstr(
                    route_active[current_key]
                    <= route_active[previous_key] + start_at_current,
                    name=f"route_active_interval_{cabin_id}_{current.visit_index}",
                )

            for phase_index, visit in enumerate(phase_visits):
                key = (cabin_id, visit.visit_index)
                station = station_selected[key]
                rope = rope_selected[key]
                model.addConstr(
                    switch_time[key] <= big_m * (1 - station),
                    name=f"initial_station_entered_{cabin_id}_{visit.visit_index}",
                )
                model.addConstr(
                    exit_switch_time[key] >= -big_m * (1 - station),
                    name=f"initial_station_not_cleared_{cabin_id}_{visit.visit_index}",
                )
                previous_switch_id = artifact.switch_cycle[
                    (phase_index - 1) % len(artifact.switch_cycle)
                ]
                rope_seconds = timing_by_switch_id[
                    previous_switch_id
                ].rope_to_next_switch_seconds
                model.addConstr(
                    switch_time[key] >= BOUNDARY_EPSILON_SECONDS - big_m * (1 - rope),
                    name=f"initial_rope_after_exit_{cabin_id}_{visit.visit_index}",
                )
                model.addConstr(
                    switch_time[key]
                    <= rope_seconds - BOUNDARY_EPSILON_SECONDS + big_m * (1 - rope),
                    name=f"initial_rope_before_entry_{cabin_id}_{visit.visit_index}",
                )

        _add_initial_rope_headways(
            model=model,
            artifact=artifact,
            rope_selected=rope_selected,
            route_active=route_active,
            switch_time=switch_time,
            exit_switch_time=exit_switch_time,
            visits_by_cabin_id=visits_by_cabin_id,
            timing_by_switch_id=timing_by_switch_id,
            big_m=big_m,
        )

        # Cabins are interchangeable at the service boundary.  Sorting their
        # selected ring phases removes label permutations without imposing an
        # order after a later service/skip merge.
        sorted_cabin_ids = sorted(cabin_active)
        initial_phase_expression = {
            cabin_id: sum(
                visit.visit_index
                * (
                    station_selected[(cabin_id, visit.visit_index)]
                    + rope_selected[(cabin_id, visit.visit_index)]
                )
                for visit in visits[: parameters.initial_phase_visit_count]
            )
            for cabin_id, visits in visits_by_cabin_id.items()
        }
        for previous_id, current_id in zip(sorted_cabin_ids, sorted_cabin_ids[1:]):
            model.addConstr(
                initial_phase_expression[previous_id]
                <= (
                    initial_phase_expression[current_id]
                    # In the selectable mode inactive cabins have phase zero
                    # and must not constrain the active prefix.
                    + parameters.initial_phase_visit_count
                    * (2 - cabin_active[previous_id] - cabin_active[current_id])
                ),
                name=f"initial_phase_symmetry_{current_id}",
            )

        if not exact_fleet:
            for previous_id, current_id in zip(sorted_cabin_ids, sorted_cabin_ids[1:]):
                model.addConstr(
                    cabin_active[current_id] <= cabin_active[previous_id],
                    name=f"cabin_activation_symmetry_{current_id}",
                )

        return EanFleetModel(
            artifact=artifact,
            variables=EanFleetVariables(
                cabin_active=cabin_active,
                station_selected=station_selected,
                rope_selected=rope_selected,
                route_active=route_active,
            ),
            switch_time=switch_time,
            exit_switch_time=exit_switch_time,
            wait_time=wait_time,
            stop=stop,
            visits_by_cabin_id=visits_by_cabin_id,
            timing_by_switch_id=timing_by_switch_id,
        )


def _add_initial_rope_headways(
    *,
    model: Any,
    artifact: EanBuildArtifact,
    rope_selected: dict[VisitKey, Any],
    route_active: dict[VisitKey, Any],
    switch_time: dict[VisitKey, Any],
    exit_switch_time: dict[VisitKey, Any],
    visits_by_cabin_id: dict[int, tuple[SwitchVisitDefinition, ...]],
    timing_by_switch_id: dict[str, SkipStopTiming],
    big_m: float,
) -> None:
    parameters = artifact.initial_placement_parameters
    if parameters is None:
        raise ValueError("initial rope headways need fleet parameters")
    exit_headway_by_switch_id = {
        checkpoint.switch_id: checkpoint.headway_seconds
        for checkpoint in artifact.headway_checkpoints
        if checkpoint.kind is HeadwayCheckpointKind.EXIT_SWITCH
    }
    cabin_ids = sorted(visits_by_cabin_id)

    for phase_index in range(parameters.initial_phase_visit_count):
        previous_switch_id = artifact.switch_cycle[
            (phase_index - 1) % len(artifact.switch_cycle)
        ]
        rope_seconds = timing_by_switch_id[
            previous_switch_id
        ].rope_to_next_switch_seconds
        headway_seconds = exit_headway_by_switch_id[previous_switch_id]

        for leader_position, leader_id in enumerate(cabin_ids):
            leader_key = (leader_id, phase_index)
            leader_exit = switch_time[leader_key] - rope_seconds
            for follower_id in cabin_ids[leader_position + 1 :]:
                follower_key = (follower_id, phase_index)
                follower_exit = switch_time[follower_key] - rope_seconds
                model.addConstr(
                    leader_exit + headway_seconds
                    <= follower_exit
                    + big_m
                    * (2 - rope_selected[leader_key] - rope_selected[follower_key]),
                    name=(
                        f"initial_rope_headway_{previous_switch_id}_"
                        f"{leader_id}_{follower_id}"
                    ),
                )

        regular_visits = tuple(
            visit
            for visits in visits_by_cabin_id.values()
            for visit in visits
            if visit.switch_id == previous_switch_id
        )
        for cabin_id in cabin_ids:
            boundary_key = (cabin_id, phase_index)
            boundary_exit = switch_time[boundary_key] - rope_seconds
            for visit in regular_visits:
                regular_key = (visit.cabin_id, visit.visit_index)
                model.addConstr(
                    boundary_exit + headway_seconds
                    <= exit_switch_time[regular_key]
                    + big_m
                    * (2 - rope_selected[boundary_key] - route_active[regular_key]),
                    name=(
                        f"initial_rope_to_exit_{previous_switch_id}_"
                        f"{cabin_id}_{visit.cabin_id}_{visit.visit_index}"
                    ),
                )
