from __future__ import annotations

import math
from dataclasses import dataclass
from enum import StrEnum
from typing import Any

from ropeway_skip_stop_optimization.models import Scenario
from ropeway_skip_stop_optimization.optimization.ean.artifact import EanBuildArtifact
from ropeway_skip_stop_optimization.optimization.ean.builders.passenger_builder import (
    EanPassengerCandidateBuildResult,
)
from ropeway_skip_stop_optimization.optimization.ean.formulation_config import (
    EanHorizonFormulation,
)
from ropeway_skip_stop_optimization.optimization.ean.models import (
    EanDemandGroup,
    EanRideCandidate,
)
from ropeway_skip_stop_optimization.optimization.ean.passenger_objective import (
    EanPassengerObjective,
    ean_passenger_objective_definition,
)
from ropeway_skip_stop_optimization.optimization.ean.passenger_plan import (
    EanPassengerServicePlan,
    EanServedRideGroup,
)
from ropeway_skip_stop_optimization.optimization.ean.plan import (
    EanCabinVisit,
    EanMovementPlan,
    EanRouteDecision,
)
from ropeway_skip_stop_optimization.optimization.ean.validation import (
    validate_ean_movement_plan_against_artifact,
)


ASSIGNMENT_TOLERANCE = 1e-6


class EanPassengerAssignmentDomain(StrEnum):
    INTEGER = "integer"
    LP_RELAXATION = "lp_relaxation"


@dataclass(frozen=True)
class EanPassengerAssignment:
    ride_counts_by_candidate_id: dict[str, float]
    unserved_counts_by_demand_group_id: dict[str, float]
    fractional_ride_count: int
    fractional_distance_sum: float
    maximum_fractional_distance: float


@dataclass(frozen=True)
class EanFixedMovementRide:
    candidate: EanRideCandidate
    boarding_time_seconds: float
    alighting_time_seconds: float


@dataclass(frozen=True)
class EanFixedMovementPassengerVariables:
    ride_count: dict[str, Any]


@dataclass(frozen=True)
class EanFixedMovementPassengerConstraints:
    demand: dict[str, Any]
    capacity: dict[tuple[int, int], Any]


@dataclass(frozen=True)
class EanFixedMovementPassengerModel:
    model: Any
    artifact: EanBuildArtifact
    movement_plan: EanMovementPlan
    passenger_build: EanPassengerCandidateBuildResult
    group_by_id: dict[str, EanDemandGroup]
    ride_by_id: dict[str, EanFixedMovementRide]
    variables: EanFixedMovementPassengerVariables
    constraints: EanFixedMovementPassengerConstraints
    objective: EanPassengerObjective
    assignment_domain: EanPassengerAssignmentDomain

    @property
    def variable_count(self) -> int:
        return len(self.variables.ride_count)

    @property
    def constraint_count(self) -> int:
        return len(self.constraints.demand) + len(self.constraints.capacity)

    def extract_assignment(self) -> EanPassengerAssignment:
        ride_counts = {
            candidate_id: _variable_value(variable)
            for candidate_id, variable in self.variables.ride_count.items()
        }
        served_by_group_id = {group_id: 0.0 for group_id in self.group_by_id}
        for candidate_id, count in ride_counts.items():
            group_id = self.ride_by_id[candidate_id].candidate.demand_group_id
            served_by_group_id[group_id] += count
        unserved_counts = {
            group_id: max(0.0, group.count - served_by_group_id[group_id])
            for group_id, group in self.group_by_id.items()
        }
        distances = tuple(
            min(abs(count - math.floor(count)), abs(math.ceil(count) - count))
            for count in ride_counts.values()
            if not math.isclose(
                count,
                round(count),
                abs_tol=ASSIGNMENT_TOLERANCE,
            )
        )
        return EanPassengerAssignment(
            ride_counts_by_candidate_id=ride_counts,
            unserved_counts_by_demand_group_id=unserved_counts,
            fractional_ride_count=len(distances),
            fractional_distance_sum=sum(distances),
            maximum_fractional_distance=max(distances, default=0.0),
        )

    def extract_passenger_plan(
        self,
        assignment: EanPassengerAssignment,
    ) -> EanPassengerServicePlan:
        if self.assignment_domain is not EanPassengerAssignmentDomain.INTEGER:
            raise ValueError(
                "LP-relaxation assignments cannot be extracted as an integer passenger plan"
            )
        served_rides: list[EanServedRideGroup] = []
        for candidate_id, value in assignment.ride_counts_by_candidate_id.items():
            count = int(round(value))
            if count <= 0:
                continue
            ride = self.ride_by_id[candidate_id]
            candidate = ride.candidate
            served_rides.append(
                EanServedRideGroup(
                    demand_group_id=candidate.demand_group_id,
                    cabin_id=candidate.cabin_id,
                    board_visit_index=candidate.board_visit_index,
                    alight_visit_index=candidate.alight_visit_index,
                    count=count,
                    boarding_time_seconds=ride.boarding_time_seconds,
                    alighting_time_seconds=ride.alighting_time_seconds,
                )
            )
        unserved_counts = {
            group_id: int(round(value))
            for group_id, value in assignment.unserved_counts_by_demand_group_id.items()
        }
        plan = EanPassengerServicePlan(
            scenario_id=self.artifact.scenario_id,
            horizon_seconds=self.artifact.config.horizon_seconds,
            served_rides=tuple(served_rides),
            unserved_counts_by_demand_group_id=unserved_counts,
        )
        plan.validate()
        _validate_integer_accounting(self.group_by_id, plan)
        return plan


@dataclass(frozen=True)
class EanFixedMovementPassengerModelBuilder:
    """Build the exact direct-ride passenger problem for fixed movement."""

    def build(
        self,
        *,
        model: Any,
        scenario: Scenario,
        artifact: EanBuildArtifact,
        movement_plan: EanMovementPlan,
        passenger_build: EanPassengerCandidateBuildResult,
        objective: EanPassengerObjective,
        assignment_domain: EanPassengerAssignmentDomain,
        grb: Any,
        gp: Any,
    ) -> EanFixedMovementPassengerModel:
        if scenario.id != artifact.scenario_id:
            raise ValueError(
                "fixed-movement passenger scenario does not match the build artifact: "
                f"{scenario.id!r} != {artifact.scenario_id!r}"
            )
        validation = validate_ean_movement_plan_against_artifact(
            artifact,
            movement_plan,
            tolerance_seconds=(
                1e-5
                if movement_plan.horizon_formulation
                is EanHorizonFormulation.EXACT_TIME_ACTIVATION
                else 1e-6
            ),
        )
        validation.raise_for_errors()
        group_by_id = {group.id: group for group in passenger_build.demand_groups}
        rides = build_ean_fixed_movement_rides(
            passenger_build=passenger_build,
            movement_plan=movement_plan,
            horizon_seconds=artifact.config.horizon_seconds,
        )
        filtered_build = EanPassengerCandidateBuildResult(
            demand_groups=passenger_build.demand_groups,
            ride_candidates=tuple(ride.candidate for ride in rides),
        )
        filtered_build.validate()
        ride_by_id = {ride.candidate.id: ride for ride in rides}
        variable_type = (
            grb.INTEGER
            if assignment_domain is EanPassengerAssignmentDomain.INTEGER
            else grb.CONTINUOUS
        )
        ride_count = {
            ride.candidate.id: model.addVar(
                lb=0.0,
                ub=min(
                    group_by_id[ride.candidate.demand_group_id].count,
                    artifact.config.cabin_capacity,
                ),
                vtype=variable_type,
                name=f"fixed_ride_count_{_var_id(ride.candidate.id)}",
            )
            for ride in rides
        }
        model.update()

        rides_by_group_id: dict[str, list[EanFixedMovementRide]] = {
            group.id: [] for group in filtered_build.demand_groups
        }
        rides_by_cabin_id: dict[int, list[EanFixedMovementRide]] = {}
        for ride in rides:
            rides_by_group_id[ride.candidate.demand_group_id].append(ride)
            rides_by_cabin_id.setdefault(ride.candidate.cabin_id, []).append(ride)

        demand_constraints = {
            group.id: model.addConstr(
                gp.quicksum(
                    ride_count[ride.candidate.id]
                    for ride in rides_by_group_id[group.id]
                )
                <= group.count,
                name=f"fixed_demand_{_var_id(group.id)}",
            )
            for group in filtered_build.demand_groups
        }
        capacity_constraints: dict[tuple[int, int], Any] = {}
        for trajectory in movement_plan.trajectories:
            cabin_rides = rides_by_cabin_id.get(trajectory.cabin_id, [])
            for visit in trajectory.visits:
                onboard = tuple(
                    ride_count[ride.candidate.id]
                    for ride in cabin_rides
                    if (
                        ride.candidate.board_visit_index
                        <= visit.visit_index
                        < ride.candidate.alight_visit_index
                    )
                )
                if not onboard:
                    continue
                key = (trajectory.cabin_id, visit.visit_index)
                capacity_constraints[key] = model.addConstr(
                    gp.quicksum(onboard) <= artifact.config.cabin_capacity,
                    name=f"fixed_capacity_cabin_{key[0]}_interval_{key[1]}",
                )

        objective_definition = ean_passenger_objective_definition(objective)
        objective_constant = 0.0
        objective_terms = []
        for group in filtered_build.demand_groups:
            unserved_cost = objective_definition.unserved_cost_seconds(
                release_time_seconds=group.release_time_seconds,
                horizon_seconds=artifact.config.horizon_seconds,
            )
            objective_constant += unserved_cost * group.count
            for ride in rides_by_group_id[group.id]:
                served_cost = _served_cost(ride, group, objective)
                objective_terms.append(
                    (served_cost - unserved_cost) * ride_count[ride.candidate.id]
                )
        model.setObjective(
            objective_constant + gp.quicksum(objective_terms),
            grb.MINIMIZE,
        )
        model.update()
        return EanFixedMovementPassengerModel(
            model=model,
            artifact=artifact,
            movement_plan=movement_plan,
            passenger_build=filtered_build,
            group_by_id=group_by_id,
            ride_by_id=ride_by_id,
            variables=EanFixedMovementPassengerVariables(
                ride_count=ride_count,
            ),
            constraints=EanFixedMovementPassengerConstraints(
                demand=demand_constraints,
                capacity=capacity_constraints,
            ),
            objective=objective,
            assignment_domain=assignment_domain,
        )


def build_ean_fixed_movement_rides(
    *,
    passenger_build: EanPassengerCandidateBuildResult,
    movement_plan: EanMovementPlan,
    horizon_seconds: float,
) -> tuple[EanFixedMovementRide, ...]:
    """Return every direct ride enabled by one exact movement plan.

    This is shared by the fixed-plan Passenger Assignment and the restricted
    DDD trajectory-slot proposal master. It deliberately performs no movement
    validation; callers that combine trajectories must validate the resulting
    complete plan independently.
    """

    if horizon_seconds <= 0:
        raise ValueError("fixed-movement passenger horizon must be positive")
    passenger_build.validate()
    movement_plan.validate()
    group_by_id = {group.id: group for group in passenger_build.demand_groups}
    visits_by_key = _plan_visits_by_key(movement_plan)
    return tuple(
        ride
        for candidate in passenger_build.ride_candidates
        if (
            ride := _fixed_movement_ride(
                candidate,
                group_by_id[candidate.demand_group_id],
                visits_by_key,
                horizon_seconds,
            )
        )
        is not None
    )


def _fixed_movement_ride(
    candidate: EanRideCandidate,
    group: EanDemandGroup,
    visits_by_key: dict[tuple[int, int], EanCabinVisit],
    horizon_seconds: float,
) -> EanFixedMovementRide | None:
    board_visit = visits_by_key.get((candidate.cabin_id, candidate.board_visit_index))
    alight_visit = visits_by_key.get((candidate.cabin_id, candidate.alight_visit_index))
    if (
        board_visit is None
        or alight_visit is None
        or board_visit.decision is not EanRouteDecision.STOP
        or alight_visit.decision is not EanRouteDecision.STOP
        or board_visit.platform_exit_time_seconds is None
        or alight_visit.platform_entry_time_seconds is None
    ):
        return None
    board_time = board_visit.platform_exit_time_seconds
    alight_time = alight_visit.platform_entry_time_seconds
    if board_time + ASSIGNMENT_TOLERANCE < group.release_time_seconds:
        return None
    if (
        board_time > horizon_seconds + ASSIGNMENT_TOLERANCE
        or alight_time > horizon_seconds + ASSIGNMENT_TOLERANCE
    ):
        return None
    return EanFixedMovementRide(
        candidate=candidate,
        boarding_time_seconds=board_time,
        alighting_time_seconds=alight_time,
    )


def _served_cost(
    ride: EanFixedMovementRide,
    group: EanDemandGroup,
    objective: EanPassengerObjective,
) -> float:
    return ean_passenger_objective_definition(objective).served_cost_seconds(
        release_time_seconds=group.release_time_seconds,
        boarding_time_seconds=ride.boarding_time_seconds,
        alighting_time_seconds=ride.alighting_time_seconds,
    )


def _plan_visits_by_key(
    movement_plan: EanMovementPlan,
) -> dict[tuple[int, int], EanCabinVisit]:
    return {
        (visit.cabin_id, visit.visit_index): visit
        for trajectory in movement_plan.trajectories
        for visit in trajectory.visits
    }


def _validate_integer_accounting(
    group_by_id: dict[str, EanDemandGroup],
    plan: EanPassengerServicePlan,
) -> None:
    served_by_group_id = {group_id: 0 for group_id in group_by_id}
    for ride in plan.served_rides:
        served_by_group_id[ride.demand_group_id] += ride.count
    for group_id, group in group_by_id.items():
        if (
            served_by_group_id[group_id]
            + plan.unserved_counts_by_demand_group_id[group_id]
            != group.count
        ):
            raise ValueError(
                "fixed-movement passenger accounting mismatch for demand group "
                f"{group_id!r}"
            )


def _variable_value(variable: Any) -> float:
    return float(variable.X)


def _var_id(value: str) -> str:
    return (
        value.replace("::", "__").replace(":", "_").replace("-", "_").replace(" ", "_")
    )
