from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
import math

from ropeway_skip_stop_optimization.optimization.ddd.models import (
    DddFixedStart,
    DddMovementCore,
    DddMovementProblem,
    DddResourceUsage,
)
from ropeway_skip_stop_optimization.optimization.ddd.trajectory_column_generation import (
    DddTrajectoryWaitingDomain,
)


@dataclass(frozen=True)
class DddTrajectoryWaitingPolicy:
    domain: DddTrajectoryWaitingDomain = DddTrajectoryWaitingDomain.NO_WAIT
    step_seconds: float | None = None
    maximum_wait_seconds_by_station_id: tuple[tuple[str, float], ...] = ()
    earliest_wait_time_seconds: float = 0.0

    def validate(self, core: DddMovementCore) -> None:
        core.validate()
        if not isinstance(self.domain, DddTrajectoryWaitingDomain):
            raise ValueError("DDD trajectory waiting domain is invalid")
        if not math.isfinite(self.earliest_wait_time_seconds):
            raise ValueError("DDD earliest waiting time must be finite")
        if self.domain is DddTrajectoryWaitingDomain.NO_WAIT:
            if self.step_seconds is not None or self.maximum_wait_seconds_by_station_id:
                raise ValueError("DDD no-wait policy cannot define waiting values")
            return
        if self.step_seconds is None or not math.isfinite(self.step_seconds) or self.step_seconds <= 0:
            raise ValueError("DDD bounded-wait policy needs a positive finite step")
        if not self.maximum_wait_seconds_by_station_id:
            raise ValueError("DDD bounded-wait policy needs at least one station limit")
        station_ids = {option.station_id for option in core.route_options}
        configured_ids = tuple(
            station_id for station_id, _ in self.maximum_wait_seconds_by_station_id
        )
        if configured_ids != tuple(sorted(set(configured_ids))):
            raise ValueError("DDD waiting station limits must be sorted and unique")
        if set(configured_ids) - station_ids:
            raise ValueError("DDD waiting policy references an unknown station")
        for station_id, maximum in self.maximum_wait_seconds_by_station_id:
            if not station_id or not math.isfinite(maximum) or maximum <= 0:
                raise ValueError("DDD station waiting limit must be positive and finite")
            steps = maximum / self.step_seconds
            if not math.isclose(steps, round(steps), rel_tol=0.0, abs_tol=1e-9):
                raise ValueError("DDD station waiting limit must be a multiple of the step")

    def maximum_wait_seconds(self, station_id: str) -> float:
        return dict(self.maximum_wait_seconds_by_station_id).get(station_id, 0.0)

    def wait_values_seconds(self, station_id: str) -> tuple[float, ...]:
        maximum = self.maximum_wait_seconds(station_id)
        if self.domain is DddTrajectoryWaitingDomain.NO_WAIT or maximum <= 0:
            return (0.0,)
        assert self.step_seconds is not None
        return tuple(
            index * self.step_seconds
            for index in range(int(round(maximum / self.step_seconds)) + 1)
        )


class DddTrajectoryFleetMode(StrEnum):
    FIXED_STARTS = "fixed_starts"
    OPTIMIZED_INITIAL_PLACEMENT = "optimized_initial_placement"
    RESERVOIR_DISPATCH = "reservoir_dispatch"


class DddReservoirDispatchCardinalityMode(StrEnum):
    OPTIONAL = "optional"
    EXACT = "exact"


class DddReservoirTrajectoryKind(StrEnum):
    STORED = "stored"
    DISPATCHED = "dispatched"


class DddReservoirBoundaryMode(StrEnum):
    """Physical meaning of the reservoir-to-network interface."""

    IDEAL_NON_LIMITING = "ideal_non_limiting"
    PHYSICAL_RESOURCE = "physical_resource"


@dataclass(frozen=True)
class DddReservoirBoundaryConfig:
    """Explicit attachment of an ideal reservoir to one movement state."""

    id: str
    entry_state_id: str
    boundary_mode: DddReservoirBoundaryMode = (
        DddReservoirBoundaryMode.IDEAL_NON_LIMITING
    )
    dispatch_resource_usages: tuple[DddResourceUsage, ...] = ()
    required_entry_resource_ids: tuple[str, ...] = ()
    allowed_first_route_option_ids: tuple[str, ...] = ()

    def validate(self, core: DddMovementCore) -> None:
        core.validate()
        if not self.id or not self.entry_state_id:
            raise ValueError("DDD reservoir boundary ids must be nonempty")
        if not isinstance(self.boundary_mode, DddReservoirBoundaryMode):
            raise ValueError("DDD reservoir boundary mode is invalid")
        if self.entry_state_id not in {state.id for state in core.states}:
            raise ValueError("DDD reservoir boundary references an unknown state")
        dispatch_keys = tuple(
            (
                usage.resource_id,
                usage.leader_clear_offset_seconds,
                usage.follower_enter_offset_seconds,
            )
            for usage in self.dispatch_resource_usages
        )
        if dispatch_keys != tuple(sorted(set(dispatch_keys))):
            raise ValueError(
                "DDD reservoir dispatch resource usages must be sorted and unique"
            )
        if (
            self.boundary_mode is DddReservoirBoundaryMode.IDEAL_NON_LIMITING
            and self.dispatch_resource_usages
        ):
            raise ValueError(
                "ideal non-limiting reservoir boundary cannot consume a physical "
                "dispatch resource"
            )
        if (
            self.boundary_mode is DddReservoirBoundaryMode.PHYSICAL_RESOURCE
            and not self.dispatch_resource_usages
        ):
            raise ValueError(
                "physical reservoir boundary requires a dispatch resource usage"
            )
        resources_by_id = core.resources_by_id
        for usage in self.dispatch_resource_usages:
            usage.validate()
            resource = resources_by_id.get(usage.resource_id)
            if resource is None:
                raise ValueError(
                    "DDD reservoir dispatch references an unknown physical resource"
                )
            separation_tick = usage.separation_after_tick(
                resource.minimum_headway_tick
            )
            if not (
                resource.minimum_headway_tick
                <= separation_tick
                <= resource.maximum_headway_tick
            ):
                raise ValueError(
                    "DDD reservoir dispatch separation lies outside its resource "
                    "headway envelope"
                )
        if tuple(sorted(set(self.required_entry_resource_ids))) != (
            self.required_entry_resource_ids
        ):
            raise ValueError("DDD reservoir entry resources must be sorted and unique")
        if tuple(sorted(set(self.allowed_first_route_option_ids))) != (
            self.allowed_first_route_option_ids
        ):
            raise ValueError("DDD reservoir first-route ids must be sorted and unique")
        outgoing = core.route_options_by_state_id.get(self.entry_state_id, ())
        if not outgoing:
            raise ValueError("DDD reservoir entry state has no outgoing route")
        outgoing_by_id = {option.id: option for option in outgoing}
        allowed = (
            tuple(outgoing_by_id)
            if not self.allowed_first_route_option_ids
            else self.allowed_first_route_option_ids
        )
        if set(allowed) - set(outgoing_by_id):
            raise ValueError("DDD reservoir allows a route from another entry state")
        required = set(self.required_entry_resource_ids)
        if required:
            for option_id in allowed:
                used = {
                    usage.resource_id
                    for usage in outgoing_by_id[option_id].resource_usages
                }
                if not required <= used:
                    raise ValueError(
                        "DDD reservoir first route does not consume every required "
                        f"entry resource: {option_id!r}"
                    )


@dataclass(frozen=True)
class DddReservoirTrajectoryState:
    kind: DddReservoirTrajectoryKind
    interface_id: str
    dispatch_time_seconds: float | None = None

    def validate(self) -> None:
        if not isinstance(self.kind, DddReservoirTrajectoryKind):
            raise ValueError("DDD reservoir trajectory kind is invalid")
        if not self.interface_id:
            raise ValueError("DDD reservoir trajectory interface id is empty")
        if self.kind is DddReservoirTrajectoryKind.STORED:
            if self.dispatch_time_seconds is not None:
                raise ValueError("stored reservoir cabin cannot have a dispatch time")
            return
        if self.dispatch_time_seconds is None or not math.isfinite(
            self.dispatch_time_seconds
        ):
            raise ValueError("dispatched reservoir cabin needs a finite dispatch time")


@dataclass(frozen=True)
class DddReservoirTrajectoryStartDomain:
    cabin_ids: tuple[int, ...]
    boundary: DddReservoirBoundaryConfig
    warmup_seconds: float
    maximum_visit_count: int
    cardinality_mode: DddReservoirDispatchCardinalityMode = (
        DddReservoirDispatchCardinalityMode.OPTIONAL
    )
    mode: DddTrajectoryFleetMode = DddTrajectoryFleetMode.RESERVOIR_DISPATCH

    def validate(self, core: DddMovementCore) -> None:
        core.validate()
        self.boundary.validate(core)
        if not self.cabin_ids or self.cabin_ids != tuple(range(len(self.cabin_ids))):
            raise ValueError("DDD reservoir cabin ids must be the canonical prefix")
        if not math.isfinite(self.warmup_seconds) or self.warmup_seconds <= 0:
            raise ValueError("DDD reservoir warm-up must be finite and positive")
        if self.maximum_visit_count <= 0:
            raise ValueError("DDD reservoir visit bound must be positive")
        if not isinstance(
            self.cardinality_mode, DddReservoirDispatchCardinalityMode
        ):
            raise ValueError("DDD reservoir cardinality mode is invalid")


@dataclass(frozen=True)
class DddFixedTrajectoryStartDomain:
    starts: tuple[DddFixedStart, ...]
    mode: DddTrajectoryFleetMode = DddTrajectoryFleetMode.FIXED_STARTS

    @property
    def cabin_ids(self) -> tuple[int, ...]:
        return tuple(item.cabin_id for item in self.starts)

    def validate(self, core: DddMovementCore) -> None:
        problem = DddMovementProblem(
            scenario_id=core.scenario_id,
            passenger_service_end_seconds=core.passenger_service_end_seconds,
            operational_end_seconds=core.operational_end_seconds,
            states=core.states,
            starts=self.starts,
            route_options=core.route_options,
            resources=core.resources,
        )
        problem.validate()


@dataclass(frozen=True)
class DddOptimizedInitialPlacementDomain:
    """Exact-K continuous initial-placement domain on one deterministic pattern."""

    cabin_ids: tuple[int, ...]
    pattern_id: str
    phase_state_ids: tuple[str, ...]
    maximum_visit_count: int
    mode: DddTrajectoryFleetMode = (
        DddTrajectoryFleetMode.OPTIMIZED_INITIAL_PLACEMENT
    )

    @property
    def cardinality(self) -> int:
        return len(self.cabin_ids)

    def validate(self, core: DddMovementCore) -> None:
        core.validate()
        if not self.pattern_id:
            raise ValueError("DDD OIP pattern id must be nonempty")
        if not self.cabin_ids or self.cabin_ids != tuple(range(len(self.cabin_ids))):
            raise ValueError("DDD OIP cabin ids must be the canonical exact-K prefix")
        if not self.phase_state_ids:
            raise ValueError("DDD OIP needs at least one pattern phase")
        if len(set(self.phase_state_ids)) != len(self.phase_state_ids):
            raise ValueError("DDD OIP pattern phases must be unique")
        state_ids = {state.id for state in core.states}
        if set(self.phase_state_ids) - state_ids:
            raise ValueError("DDD OIP pattern references an unknown movement state")
        if self.maximum_visit_count <= len(self.phase_state_ids):
            raise ValueError("DDD OIP visit bound must cover more than one cycle")


DddTrajectoryStartDomain = (
    DddFixedTrajectoryStartDomain
    | DddOptimizedInitialPlacementDomain
    | DddReservoirTrajectoryStartDomain
)


@dataclass(frozen=True)
class DddTrajectoryProblem:
    movement_core: DddMovementCore
    start_domain: DddTrajectoryStartDomain
    waiting_policy: DddTrajectoryWaitingPolicy = field(
        default_factory=DddTrajectoryWaitingPolicy
    )

    @property
    def cabin_ids(self) -> tuple[int, ...]:
        return self.start_domain.cabin_ids

    @property
    def fleet_mode(self) -> DddTrajectoryFleetMode:
        return self.start_domain.mode

    @property
    def fixed_movement_problem(self) -> DddMovementProblem:
        if not isinstance(self.start_domain, DddFixedTrajectoryStartDomain):
            raise ValueError("optimized initial placement has no fixed-start problem")
        core = self.movement_core
        return DddMovementProblem(
            scenario_id=core.scenario_id,
            passenger_service_end_seconds=core.passenger_service_end_seconds,
            operational_end_seconds=core.operational_end_seconds,
            states=core.states,
            starts=self.start_domain.starts,
            route_options=core.route_options,
            resources=core.resources,
        )

    @property
    def structural_movement_problem(self) -> DddMovementProblem:
        """Compatibility view for resource/index routines that do not use starts."""

        if isinstance(self.start_domain, DddFixedTrajectoryStartDomain):
            return self.fixed_movement_problem
        core = self.movement_core
        domain = self.start_domain
        state_id = (
            domain.phase_state_ids[0]
            if isinstance(domain, DddOptimizedInitialPlacementDomain)
            else domain.boundary.entry_state_id
        )
        maximum_visit_count = domain.maximum_visit_count
        return DddMovementProblem(
            scenario_id=core.scenario_id,
            passenger_service_end_seconds=core.passenger_service_end_seconds,
            operational_end_seconds=core.operational_end_seconds,
            states=core.states,
            starts=tuple(
                DddFixedStart(
                    cabin_id=cabin_id,
                    state_id=state_id,
                    time_seconds=0.0,
                    max_visit_count=maximum_visit_count,
                )
                for cabin_id in domain.cabin_ids
            ),
            route_options=core.route_options,
            resources=core.resources,
        )

    def validate(self) -> None:
        self.start_domain.validate(self.movement_core)
        self.waiting_policy.validate(self.movement_core)
        if (
            isinstance(self.start_domain, DddOptimizedInitialPlacementDomain)
            and self.waiting_policy.domain is DddTrajectoryWaitingDomain.BOUNDED_WAIT
        ):
            raise ValueError("DDD optimized initial placement does not support waiting")
