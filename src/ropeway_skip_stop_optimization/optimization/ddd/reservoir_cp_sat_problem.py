"""Finite, single-use reservoir domain; independent of the Fixed-K contract."""

from __future__ import annotations

from dataclasses import asdict, dataclass, replace
from functools import cached_property
import math

from ..ean.builders.passenger_builder import EanPassengerCandidateBuildResult
from ..ean.models import EanDemandGroup, EanRideCandidate
from .cp_sat_certificate import stable_fingerprint
from .models import DddFixedStart, DddMovementCore, DddMovementProblem, DddRouteDecision
from .reservoir_arc_flow_problem import (
    DddReservoirArcFlowProblem,
    DddReservoirOperatingMode,
)
from .route_topology import unique_stop_route_option
from .time_ticks import ddd_seconds_to_tick, ddd_tick_to_seconds
from .trajectory_problem import DddTrajectoryWaitingPolicy


@dataclass(frozen=True)
class DddReservoirCpSatProblem:
    movement_core: DddMovementCore
    demand_groups: tuple[EanDemandGroup, ...]  # absolute release times
    cabin_capacity: int
    available_fleet_count: int
    entry_state_id: str
    dispatch_end_seconds: float
    dispatch_step_seconds: float = 0.000001
    dispatch_start_seconds: float = 0.0
    return_start_seconds: float = 0.0
    waiting_policy: DddTrajectoryWaitingPolicy = DddTrajectoryWaitingPolicy()
    operating_mode: DddReservoirOperatingMode = DddReservoirOperatingMode.SKIP_STOP

    @classmethod
    def from_arc_flow(cls, source: DddReservoirArcFlowProblem):
        """Reuse geometry and ideal port, explicitly enlarge dispatch/return windows."""
        source.validate()
        return cls(
            movement_core=replace(
                source.movement_core,
                passenger_service_end_seconds=source.service_end_seconds,
                operational_end_seconds=source.operational_end_seconds,
            ),
            demand_groups=tuple(
                replace(
                    g,
                    release_time_seconds=g.release_time_seconds + source.warmup_seconds,
                )
                for g in source.demand_groups
            ),
            cabin_capacity=source.cabin_capacity,
            available_fleet_count=source.available_fleet_count,
            entry_state_id=source.entry_state_id,
            dispatch_end_seconds=source.service_end_seconds,
            waiting_policy=source.waiting_policy,
            operating_mode=source.operating_mode,
        )

    @cached_property
    def resolved_core(self):
        return replace(
            self.movement_core,
            route_options=tuple(
                o
                for o in self.movement_core.route_options
                if self.operating_mode is DddReservoirOperatingMode.SKIP_STOP
                or o.decision is DddRouteDecision.STOP
            ),
        )

    @cached_property
    def cycle_states(self) -> tuple[str, ...]:
        states, state = [], self.entry_state_id
        options = self.resolved_core.route_options_by_state_id
        while state not in states:
            states.append(state)
            targets = {o.to_state_id for o in options.get(state, ())}
            if len(targets) != 1:
                raise ValueError("reservoir CP requires deterministic route targets")
            state = next(iter(targets))
        if state != self.entry_state_id or set(states) != {
            s.id for s in self.resolved_core.states
        }:
            raise ValueError("reservoir CP requires one directed circulation")
        return tuple(states)

    @cached_property
    def visit_states(self) -> tuple[str, ...]:
        # Include a terminal slot beyond even the earliest/fastest possible path.
        states = [self.entry_state_id]
        time = ddd_seconds_to_tick(self.dispatch_start_seconds)
        options = self.resolved_core.route_options_by_state_id
        while time <= self.resolved_core.operational_end_tick:
            time += min(o.duration_tick for o in options[states[-1]])
            states.append(options[states[-1]][0].to_state_id)
        return tuple(states)

    @cached_property
    def movement(self) -> DddMovementProblem:
        c = self.resolved_core
        return DddMovementProblem(
            c.scenario_id,
            c.passenger_service_end_seconds,
            c.operational_end_seconds,
            c.states,
            tuple(
                DddFixedStart(
                    k,
                    self.entry_state_id,
                    self.dispatch_start_seconds,
                    len(self.visit_states) - 1,
                )
                for k in range(self.available_fleet_count)
            ),
            c.route_options,
            c.resources,
        )

    @cached_property
    def passenger_build(self):
        states = self.visit_states[:-1]
        stations = [
            unique_stop_route_option(
                self.movement, s, error_context="reservoir CP"
            ).station_id
            for s in states
        ]
        rides = []
        for k in range(self.available_fleet_count):
            for g in self.demand_groups:
                if not g.count:
                    continue
                for board, station in enumerate(stations):
                    if station != g.origin_station_id:
                        continue
                    for alight in range(board + 1, len(stations)):
                        if stations[alight] == g.destination_station_id:
                            rides.append(
                                EanRideCandidate(
                                    f"ride::{g.id}::{k}::{board}::{alight}",
                                    g.id,
                                    k,
                                    board,
                                    alight,
                                )
                            )
                            break  # direct ride to the first destination encounter
        return EanPassengerCandidateBuildResult(self.demand_groups, tuple(rides))

    def validate(self):
        self.movement_core.validate()
        for value in (self.cabin_capacity, self.available_fleet_count):
            if type(value) is not int or value <= 0:
                raise ValueError("reservoir capacity/fleet must be positive integers")
        if not isinstance(self.operating_mode, DddReservoirOperatingMode):
            raise ValueError("invalid reservoir operating mode")
        values = (
            self.dispatch_start_seconds,
            self.dispatch_end_seconds,
            self.dispatch_step_seconds,
            self.return_start_seconds,
            self.waiting_policy.earliest_wait_time_seconds,
            *(v for _, v in self.waiting_policy.maximum_wait_seconds_by_station_id),
        )
        if self.waiting_policy.step_seconds is not None:
            values += (self.waiting_policy.step_seconds,)
        for v in values:
            if (
                not math.isfinite(v)
                or v < 0
                or abs(v - ddd_tick_to_seconds(ddd_seconds_to_tick(v))) > 1e-10
            ):
                raise ValueError("reservoir times must be nonnegative canonical ticks")
        if (
            not 0
            <= self.dispatch_start_seconds
            <= self.dispatch_end_seconds
            <= self.resolved_core.operational_end_seconds
        ):
            raise ValueError("invalid reservoir dispatch window")
        if (
            self.return_start_seconds > self.resolved_core.operational_end_seconds
            or ddd_seconds_to_tick(self.dispatch_step_seconds) < 1
        ):
            raise ValueError("invalid reservoir return window or dispatch step")
        if (
            self.waiting_policy.step_seconds is not None
            and ddd_seconds_to_tick(self.waiting_policy.step_seconds) < 1
        ):
            raise ValueError("invalid reservoir waiting step")
        self.waiting_policy.validate(self.resolved_core)
        stations = []
        for state in self.cycle_states:
            stop = unique_stop_route_option(
                self.movement, state, error_context="reservoir CP"
            )
            if (
                stop.platform_entry_offset_seconds is None
                or stop.platform_exit_offset_seconds is None
            ):
                raise ValueError("reservoir STOP requires platform offsets")
            if (
                not 0
                <= stop.platform_entry_offset_seconds
                <= stop.platform_exit_offset_seconds
                <= stop.duration_seconds
            ):
                raise ValueError("invalid reservoir platform offsets")
            stations.append(stop.station_id)
        if len(set(stations)) != len(stations):
            raise ValueError(
                "reservoir CP v1 requires unique stations on its directed cycle"
            )
        ids = set()
        for g in self.demand_groups:
            g.validate()
            if g.id in ids or type(g.count) is not int or g.count < 0:
                raise ValueError("invalid reservoir integer demand")
            ids.add(g.id)
            if (
                g.origin_station_id not in stations
                or g.destination_station_id not in stations
            ):
                raise ValueError("reservoir demand references an unknown station")
            if (
                abs(
                    g.release_time_seconds
                    - ddd_tick_to_seconds(ddd_seconds_to_tick(g.release_time_seconds))
                )
                > 1e-10
            ):
                raise ValueError("reservoir demand release is off the tick grid")
            if (
                not 0
                <= g.release_time_seconds
                <= self.resolved_core.passenger_service_end_seconds
            ):
                raise ValueError("reservoir demand release outside service horizon")

    @cached_property
    def manifest(self):
        self.validate()
        return {
            "schema": "single_use_reservoir_cp_domain_v1",
            "boundary_contract": "ideal_entry_state_no_depot_resource_unique_state_tick_v1",
            "passenger_contract": "direct_first_destination_empty_return_v1",
            **asdict(self),
            "derived_visit_count": len(self.visit_states) - 1,
        }

    @property
    def fingerprint(self):
        return stable_fingerprint(self.manifest)
