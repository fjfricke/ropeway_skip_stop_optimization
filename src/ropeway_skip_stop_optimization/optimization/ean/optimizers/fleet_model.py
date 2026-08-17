from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from ropeway_skip_stop_optimization.models import (
    ConstantHeadwayRule,
    DerivedHeadwayResourceKind,
    LeaderBehaviorHeadwayRule,
)

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
from ropeway_skip_stop_optimization.optimization.ean.optimizers.fleet_symmetry import (
    EanFleetSymmetryBreaker,
)


VisitKey = tuple[int, int]
BOUNDARY_EPSILON_SECONDS = 1e-5


@dataclass(frozen=True)
class EanFleetVariables:
    cabin_active: dict[int, Any]
    station_selected: dict[VisitKey, Any]
    rope_selected: dict[VisitKey, Any]
    route_active: dict[VisitKey, Any]
    initial_previous_service: dict[int, Any]

    def all_variables(self) -> tuple[Any, ...]:
        return tuple(
            (
                *self.cabin_active.values(),
                *self.station_selected.values(),
                *self.rope_selected.values(),
                *self.route_active.values(),
                *self.initial_previous_service.values(),
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
        if self.variables.initial_previous_service:
            missing_previous_behavior = tuple(
                state.cabin_id
                for state in fleet_plan.initial_states
                if state.kind is EanInitialPlacementStateKind.ROPE
                and state.previous_service is None
            )
            if missing_previous_behavior:
                raise ValueError(
                    "leader-dependent rope-start MIP states need previous_service: "
                    f"{missing_previous_behavior}"
                )
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
        for cabin_id, variable in self.variables.initial_previous_service.items():
            if cabin_id not in cabin_ids:
                continue
            state = state_by_cabin_id.get(cabin_id)
            variable.Start = float(
                state is not None
                and state.kind is EanInitialPlacementStateKind.ROPE
                and state.previous_service is True
            )

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
            previous_switch_id = self.artifact.circulation_state_ids[
                (phase_index - 1) % len(self.artifact.circulation_state_ids)
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
                previous_service=(
                    float(
                        self.variables.initial_previous_service[cabin_id].X
                    )
                    >= 0.5
                    if cabin_id in self.variables.initial_previous_service
                    else None
                ),
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
        enable_full_initial_state_symmetry: bool,
        enable_inactive_variable_canonicalization: bool,
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
        initial_previous_service = (
            {
                cabin_id: model.addVar(
                    vtype=binary_vtype,
                    name=f"initial_previous_service_{cabin_id}",
                )
                for cabin_id in visits_by_cabin_id
            }
            if artifact.headway_policy is not None
            and (
                artifact.headway_policy.has_leader_behavior_rules
                or any(
                    resource.kind is DerivedHeadwayResourceKind.SERVICE_MECHANISM
                    for resource in artifact.headway_policy.resource_requirements
                )
            )
            else {}
        )
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
            if cabin_id in initial_previous_service:
                model.addConstr(
                    initial_previous_service[cabin_id]
                    <= sum(
                        rope_selected[(cabin_id, visit.visit_index)]
                        for visit in phase_visits
                    ),
                    name=f"initial_previous_service_requires_rope_{cabin_id}",
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
                previous_switch_id = artifact.circulation_state_ids[
                    (phase_index - 1) % len(artifact.circulation_state_ids)
                ]
                previous_timing = timing_by_switch_id[previous_switch_id]
                if (
                    cabin_id in initial_previous_service
                    and not previous_timing.skip_allowed
                    and artifact.initial_boundary_service_resource(
                        previous_switch_id
                    )
                    is not None
                ):
                    model.addConstr(
                        initial_previous_service[cabin_id] >= rope,
                        name=(
                            "initial_previous_service_mandatory_"
                            f"{cabin_id}_{visit.visit_index}"
                        ),
                    )
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
            stop=stop,
            visits_by_cabin_id=visits_by_cabin_id,
            timing_by_switch_id=timing_by_switch_id,
            big_m=big_m,
            adjacent_only=enable_full_initial_state_symmetry,
            initial_previous_service=initial_previous_service,
        )

        EanFleetSymmetryBreaker(
            enable_full_initial_state_order=enable_full_initial_state_symmetry,
            enable_inactive_variable_canonicalization=(
                enable_inactive_variable_canonicalization
            ),
        ).add_constraints(
            model=model,
            artifact=artifact,
            cabin_active=cabin_active,
            station_selected=station_selected,
            rope_selected=rope_selected,
            switch_time=switch_time,
            exit_switch_time=exit_switch_time,
            wait_time=wait_time,
            stop=stop,
            visits_by_cabin_id=visits_by_cabin_id,
            timing_by_switch_id=timing_by_switch_id,
            big_m=big_m,
        )

        return EanFleetModel(
            artifact=artifact,
            variables=EanFleetVariables(
                cabin_active=cabin_active,
                station_selected=station_selected,
                rope_selected=rope_selected,
                route_active=route_active,
                initial_previous_service=initial_previous_service,
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
    stop: dict[VisitKey, Any],
    visits_by_cabin_id: dict[int, tuple[SwitchVisitDefinition, ...]],
    timing_by_switch_id: dict[str, SkipStopTiming],
    big_m: float,
    adjacent_only: bool,
    initial_previous_service: dict[int, Any],
) -> None:
    parameters = artifact.initial_placement_parameters
    if parameters is None:
        raise ValueError("initial rope headways need fleet parameters")
    exit_checkpoint_by_switch_id = {
        checkpoint.switch_id: checkpoint
        for checkpoint in artifact.headway_checkpoints
        if checkpoint.kind is HeadwayCheckpointKind.EXIT_SWITCH
    }
    cabin_ids = sorted(visits_by_cabin_id)

    for phase_index in range(parameters.initial_phase_visit_count):
        previous_switch_id = artifact.circulation_state_ids[
            (phase_index - 1) % len(artifact.circulation_state_ids)
        ]
        rope_seconds = timing_by_switch_id[
            previous_switch_id
        ].rope_to_next_switch_seconds
        checkpoint = exit_checkpoint_by_switch_id[previous_switch_id]
        rule = artifact.headway_rule_for_checkpoint(checkpoint)
        boundary_service_resource = artifact.initial_boundary_service_resource(
            previous_switch_id
        )
        service_rule = (
            artifact.headway_rule_for_full_resource(boundary_service_resource)
            if boundary_service_resource is not None
            else None
        )

        rope_pairs = (
            tuple(zip(cabin_ids, cabin_ids[1:]))
            if adjacent_only
            else tuple(
                (leader_id, follower_id)
                for leader_position, leader_id in enumerate(cabin_ids)
                for follower_id in cabin_ids[leader_position + 1 :]
            )
        )
        for leader_id, follower_id in rope_pairs:
            leader_key = (leader_id, phase_index)
            leader_exit = switch_time[leader_key] - rope_seconds
            follower_key = (follower_id, phase_index)
            follower_exit = switch_time[follower_key] - rope_seconds
            headway_base, headway_route_term = _initial_headway_terms(
                rule,
                leader_id=leader_id,
                initial_previous_service=initial_previous_service,
            )
            model.addConstr(
                leader_exit + headway_base + headway_route_term
                <= follower_exit
                + big_m
                * (2 - rope_selected[leader_key] - rope_selected[follower_key]),
                name=(
                    f"initial_rope_headway_{previous_switch_id}_"
                    f"{leader_id}_{follower_id}"
                ),
            )

        # Adjacency among all initial rope cabins is sufficient for the main
        # rope, but not for the service-only subsequence: bypassing cabins may
        # lie between two service cabins.  Therefore the service resource must
        # retain every ordered cabin pair even when main-rope symmetry breaking
        # reduces the latter to adjacent pairs.
        if service_rule is not None and initial_previous_service:
            service_headway = service_rule.maximum_seconds
            for leader_position, leader_id in enumerate(cabin_ids):
                leader_key = (leader_id, phase_index)
                leader_exit = switch_time[leader_key] - rope_seconds
                for follower_id in cabin_ids[leader_position + 1 :]:
                    follower_key = (follower_id, phase_index)
                    follower_exit = switch_time[follower_key] - rope_seconds
                    model.addConstr(
                        leader_exit + service_headway
                        <= follower_exit
                        + big_m
                        * (
                            4
                            - rope_selected[leader_key]
                            - rope_selected[follower_key]
                            - initial_previous_service[leader_id]
                            - initial_previous_service[follower_id]
                        ),
                        name=(
                            "initial_service_resource_headway_"
                            f"{previous_switch_id}_{leader_id}_{follower_id}"
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
            headway_base, headway_route_term = _initial_headway_terms(
                rule,
                leader_id=cabin_id,
                initial_previous_service=initial_previous_service,
            )
            for visit in regular_visits:
                regular_key = (visit.cabin_id, visit.visit_index)
                model.addConstr(
                    boundary_exit + headway_base + headway_route_term
                    <= exit_switch_time[regular_key]
                    + big_m
                    * (2 - rope_selected[boundary_key] - route_active[regular_key]),
                    name=(
                        f"initial_rope_to_exit_{previous_switch_id}_"
                        f"{cabin_id}_{visit.cabin_id}_{visit.visit_index}"
                    ),
                )
                if service_rule is not None and initial_previous_service:
                    model.addConstr(
                        boundary_exit + service_rule.maximum_seconds
                        <= exit_switch_time[regular_key]
                        + big_m
                        * (
                            4
                            - rope_selected[boundary_key]
                            - initial_previous_service[cabin_id]
                            - stop[regular_key]
                            - route_active[regular_key]
                        ),
                        name=(
                            f"initial_service_resource_to_exit_"
                            f"{previous_switch_id}_{cabin_id}_"
                            f"{visit.cabin_id}_{visit.visit_index}"
                        ),
                    )


def _initial_headway_terms(
    rule: ConstantHeadwayRule | LeaderBehaviorHeadwayRule,
    *,
    leader_id: int,
    initial_previous_service: dict[int, Any],
) -> tuple[float, Any]:
    if isinstance(rule, ConstantHeadwayRule):
        return rule.seconds, 0.0
    previous_service = initial_previous_service.get(leader_id)
    if previous_service is None:
        raise ValueError(
            "leader-dependent initial rope headway needs previous-service variables"
        )
    return (
        rule.bypass_leader_seconds,
        (rule.service_leader_seconds - rule.bypass_leader_seconds)
        * previous_service,
    )
