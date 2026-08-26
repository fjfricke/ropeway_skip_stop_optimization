from __future__ import annotations

from dataclasses import dataclass, replace
from enum import StrEnum
from hashlib import sha256
import json
import math

from ropeway_skip_stop_optimization.optimization.ddd.models import DddRouteDecision
from ropeway_skip_stop_optimization.optimization.ddd.reference import (
    DddReferenceResourceOccurrence,
    find_ddd_reference_conflicts,
)
from ropeway_skip_stop_optimization.optimization.ddd.trajectory_column_generation import (
    DddTrajectoryWaitingDomain,
)
from ropeway_skip_stop_optimization.optimization.ddd.trajectory_problem import (
    DddFixedTrajectoryStartDomain,
    DddTrajectoryProblem,
)
from ropeway_skip_stop_optimization.optimization.ean.artifact import EanBuildArtifact
from ropeway_skip_stop_optimization.optimization.ean.fleet import (
    EanInitialPlacementState,
)
from ropeway_skip_stop_optimization.optimization.ean.builders.passenger_builder import (
    EanPassengerCandidateBuildResult,
)
from ropeway_skip_stop_optimization.optimization.ean.passenger_objective import (
    EanPassengerObjective,
)


class DddFixedKOperatingMode(StrEnum):
    ALL_STOP = "all_stop"
    SKIP_STOP = "skip_stop"


class DddFixedKStartPolicy(StrEnum):
    LEGACY = "legacy"
    CANONICAL_ROPE = "canonical_rope"
    BALANCED_REFERENCE = "balanced_reference"


@dataclass(frozen=True)
class DddFixedKBoundaryContext:
    """Physical resource provenance that crosses the fixed boundary t=0."""

    initial_states: tuple[EanInitialPlacementState, ...] = ()
    resource_occurrences: tuple[DddReferenceResourceOccurrence, ...] = ()
    source: str = "none"

    def validate(self, problem: DddTrajectoryProblem) -> None:
        problem.validate()
        if not self.source:
            raise ValueError("Fixed-K boundary context source must not be empty")
        cabin_ids = set(problem.cabin_ids)
        if {state.cabin_id for state in self.initial_states} - cabin_ids:
            raise ValueError("Fixed-K boundary state references an unknown cabin")
        if len({state.cabin_id for state in self.initial_states}) != len(
            self.initial_states
        ):
            raise ValueError("Fixed-K boundary states must be unique per cabin")
        for state in self.initial_states:
            state.validate()
        resources = problem.movement_core.resources_by_id
        for occurrence in self.resource_occurrences:
            if occurrence.cabin_id not in cabin_ids:
                raise ValueError(
                    "Fixed-K boundary occurrence references an unknown cabin"
                )
            resource = resources.get(occurrence.resource_id)
            if resource is None:
                raise ValueError(
                    "Fixed-K boundary occurrence references an unknown resource"
                )
            if (
                occurrence.leader_clear_time_seconds
                + (
                    occurrence.separation_after_seconds
                    if occurrence.separation_after_seconds is not None
                    else resource.minimum_headway_seconds
                )
                <= 0
            ):
                raise ValueError(
                    "Fixed-K boundary occurrence does not reach the model horizon"
                )
        movement = problem.structural_movement_problem
        conflicts = find_ddd_reference_conflicts(
            self.resource_occurrences,
            movement,
        )
        if conflicts:
            raise ValueError(
                f"Fixed-K boundary context contains a conflict: {conflicts[0]}"
            )


class DddFixedKExperimentProfile(StrEnum):
    SCREENING = "screening"
    REGULAR = "regular"
    HEADLINE = "headline"


@dataclass(frozen=True)
class DddFixedKProfileConfig:
    total_time_limit_seconds: float
    max_iterations: int
    pricing_time_limit_tiers_seconds: tuple[float, ...]
    restricted_mip_interval: int
    restricted_mip_time_limit_seconds: float
    final_mip_time_limit_seconds: float
    cp_seed_time_limit_seconds: float

    @classmethod
    def for_profile(
        cls, profile: DddFixedKExperimentProfile
    ) -> DddFixedKProfileConfig:
        if profile is DddFixedKExperimentProfile.SCREENING:
            return cls(600.0, 30, (5.0, 15.0), 3, 15.0, 60.0, 30.0)
        if profile is DddFixedKExperimentProfile.REGULAR:
            return cls(3600.0, 60, (5.0, 15.0, 60.0), 3, 30.0, 300.0, 120.0)
        if profile is DddFixedKExperimentProfile.HEADLINE:
            return cls(
                14_400.0,
                100,
                (5.0, 15.0, 60.0, 120.0),
                3,
                60.0,
                1_800.0,
                600.0,
            )
        raise ValueError(f"unsupported Fixed-K profile: {profile}")

    def validate(self) -> None:
        values = (
            self.total_time_limit_seconds,
            self.restricted_mip_time_limit_seconds,
            self.final_mip_time_limit_seconds,
            self.cp_seed_time_limit_seconds,
            *self.pricing_time_limit_tiers_seconds,
        )
        if any(not math.isfinite(value) or value <= 0 for value in values):
            raise ValueError("Fixed-K profile time limits must be positive and finite")
        if self.max_iterations <= 0 or self.restricted_mip_interval <= 0:
            raise ValueError("Fixed-K profile iteration values must be positive")
        if tuple(sorted(set(self.pricing_time_limit_tiers_seconds))) != (
            self.pricing_time_limit_tiers_seconds
        ):
            raise ValueError("Fixed-K pricing tiers must be increasing and unique")


@dataclass(frozen=True)
class DddFixedKTrajectoryProblem:
    """Certificate identity for one exact-active fixed-start experiment."""

    trajectory_problem: DddTrajectoryProblem
    artifact: EanBuildArtifact
    passenger_build: EanPassengerCandidateBuildResult
    objective: EanPassengerObjective
    operating_mode: DddFixedKOperatingMode
    start_policy: DddFixedKStartPolicy
    boundary_context: DddFixedKBoundaryContext = DddFixedKBoundaryContext()
    objective_floor: float = 0.0

    @property
    def fleet_cardinality(self) -> int:
        return len(self.trajectory_problem.cabin_ids)

    @property
    def resolved_trajectory_problem(self) -> DddTrajectoryProblem:
        if self.operating_mode is DddFixedKOperatingMode.SKIP_STOP:
            return self.trajectory_problem
        core = self.trajectory_problem.movement_core
        route_options = tuple(
            option
            for option in core.route_options
            if option.decision is DddRouteDecision.STOP
        )
        return replace(
            self.trajectory_problem,
            movement_core=replace(core, route_options=route_options),
        )

    @property
    def fingerprint(self) -> str:
        resolved = self.resolved_trajectory_problem
        payload = {
            "scenario_id": self.artifact.scenario_id,
            "fleet_cardinality": self.fleet_cardinality,
            "operating_mode": self.operating_mode.value,
            "start_policy": self.start_policy.value,
            "objective": self.objective.value,
            "objective_floor": self.objective_floor,
            "passenger_service_end_seconds": (
                resolved.movement_core.passenger_service_end_seconds
            ),
            "operational_end_seconds": resolved.movement_core.operational_end_seconds,
            "waiting_domain": resolved.waiting_policy.domain.value,
            "starts": [
                (
                    start.cabin_id,
                    start.state_id,
                    start.time_tick,
                    start.max_visit_count,
                )
                for start in resolved.start_domain.starts
            ],
            "boundary": {
                "source": self.boundary_context.source,
                "initial_states": [
                    (
                        state.cabin_id,
                        state.kind.value,
                        state.switch_id,
                        state.visit_index,
                        state.previous_event_time_seconds,
                        state.next_event_time_seconds,
                        state.previous_service,
                    )
                    for state in self.boundary_context.initial_states
                ],
                "resource_occurrences": [
                    (
                        item.resource_id,
                        item.cabin_id,
                        item.visit_index,
                        item.leader_clear_time_seconds,
                        item.follower_enter_time_seconds,
                        item.separation_after_seconds,
                        item.boundary_only,
                        item.boundary_origin,
                    )
                    for item in self.boundary_context.resource_occurrences
                ],
            },
            "route_option_ids": [
                option.id for option in resolved.movement_core.route_options
            ],
            "demands": [
                (
                    group.id,
                    group.origin_station_id,
                    group.destination_station_id,
                    group.release_time_seconds,
                    group.count,
                )
                for group in self.passenger_build.demand_groups
            ],
        }
        return sha256(
            json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()

    def validate(self) -> None:
        self.trajectory_problem.validate()
        self.artifact.validate()
        self.passenger_build.validate()
        if not isinstance(
            self.trajectory_problem.start_domain, DddFixedTrajectoryStartDomain
        ):
            raise ValueError("Fixed-K trajectory problem requires fixed starts")
        if self.trajectory_problem.waiting_policy.domain is not (
            DddTrajectoryWaitingDomain.NO_WAIT
        ):
            raise ValueError("certified Fixed-K v1 supports no-wait only")
        if self.fleet_cardinality <= 0:
            raise ValueError("Fixed-K fleet cardinality must be positive")
        if self.trajectory_problem.cabin_ids != tuple(range(self.fleet_cardinality)):
            raise ValueError("Fixed-K cabin IDs must be the canonical exact-K prefix")
        if not isinstance(self.operating_mode, DddFixedKOperatingMode):
            raise ValueError("Fixed-K operating mode is invalid")
        if not isinstance(self.start_policy, DddFixedKStartPolicy):
            raise ValueError("Fixed-K start policy is invalid")
        if not isinstance(self.objective, EanPassengerObjective):
            raise ValueError("Fixed-K passenger objective is invalid")
        if not math.isfinite(self.objective_floor):
            raise ValueError("Fixed-K objective floor must be finite")
        resolved = self.resolved_trajectory_problem
        resolved.validate()
        self.boundary_context.validate(resolved)
        if self.operating_mode is DddFixedKOperatingMode.ALL_STOP:
            state_ids = {state.id for state in resolved.movement_core.states}
            outgoing = {
                state_id: tuple(
                    option
                    for option in resolved.movement_core.route_options
                    if option.from_state_id == state_id
                )
                for state_id in state_ids
            }
            if any(len(options) != 1 for options in outgoing.values()):
                raise ValueError("All-Stop domain needs exactly one route per state")
