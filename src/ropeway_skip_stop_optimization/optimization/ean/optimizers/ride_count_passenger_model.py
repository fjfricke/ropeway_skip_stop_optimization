from __future__ import annotations

from dataclasses import dataclass
import math
from typing import Any

from ropeway_skip_stop_optimization.models import Scenario
from ropeway_skip_stop_optimization.optimization.ean.builders.passenger_builder import (
    EanPassengerCandidateBuildResult,
    EanPassengerCandidateBuilder,
)
from ropeway_skip_stop_optimization.optimization.ean.fleet import EanFleetPlan
from ropeway_skip_stop_optimization.optimization.ean.models import (
    EanDemandGroup,
    EanRideCandidate,
)
from ropeway_skip_stop_optimization.optimization.ean.optimization_config import (
    EanOptimizationConfig,
)
from ropeway_skip_stop_optimization.optimization.ean.optimizers.movement_model import (
    EanMovementModel,
    platform_entry_time_expr,
    platform_exit_time_expr,
)
from ropeway_skip_stop_optimization.optimization.ean.passenger_objective import (
    EanPassengerObjective,
    EanPassengerObjectiveEvent,
    ean_passenger_objective_definition,
)
from ropeway_skip_stop_optimization.optimization.ean.passenger_plan import (
    EanPassengerServicePlan,
    EanServedRideGroup,
)
from ropeway_skip_stop_optimization.optimization.ean.plan import EanMovementPlan


@dataclass(frozen=True)
class EanRideCountPassengerVariables:
    ride_count: dict[str, Any]
    used: dict[str, Any]
    count_bit: dict[tuple[str, int], Any]
    selected_event_time: dict[tuple[str, int], Any]
    unserved: dict[str, Any]

    @property
    def slot(self) -> dict[tuple[str, int], Any]:
        """Compatibility view for existing model-size reporting."""

        return self.count_bit


@dataclass(frozen=True)
class EanRideCountPassengerModel:
    movement: EanMovementModel
    passenger_build: EanPassengerCandidateBuildResult
    group_by_id: dict[str, EanDemandGroup]
    variables: EanRideCountPassengerVariables
    objective: EanPassengerObjective
    objective_expression: Any
    lexicographic_expression: Any
    lexicographic_weight: float

    def apply_all_stop_mip_start(
        self,
        movement_plan: EanMovementPlan,
        fleet_plan: EanFleetPlan | None,
    ) -> tuple[int, float]:
        # The empty assignment is always a valid passenger start and avoids
        # reproducing the historical unary-slot greedy heuristic here.
        self.movement.apply_mip_start(movement_plan, fleet_plan)
        for variable in self.variables.ride_count.values():
            variable.Start = 0.0
        for variable in self.variables.used.values():
            variable.Start = 0.0
        for variable in self.variables.count_bit.values():
            variable.Start = 0.0
        for variable in self.variables.selected_event_time.values():
            variable.Start = 0.0
        unserved = 0
        secondary = 0.0
        definition = ean_passenger_objective_definition(self.objective)
        horizon = self.movement.artifact.config.horizon_seconds
        for group_id, variable in self.variables.unserved.items():
            count = self.group_by_id[group_id].count
            variable.Start = float(count)
            unserved += count
            secondary += count * definition.unserved_cost_seconds(
                release_time_seconds=self.group_by_id[group_id].release_time_seconds,
                horizon_seconds=horizon,
            )
        return unserved, secondary

    def apply_mip_start(
        self,
        movement_plan: EanMovementPlan,
        passenger_plan: EanPassengerServicePlan,
        fleet_plan: EanFleetPlan | None = None,
    ) -> None:
        if passenger_plan.scenario_id != self.movement.artifact.scenario_id:
            raise ValueError("ride-count MIP start scenario mismatch")
        self.movement.apply_mip_start(movement_plan, fleet_plan)
        count_by_candidate = {candidate.id: 0 for candidate in self.passenger_build.ride_candidates}
        candidate_id_by_key = {
            (
                candidate.demand_group_id,
                candidate.cabin_id,
                candidate.board_visit_index,
                candidate.alight_visit_index,
            ): candidate.id
            for candidate in self.passenger_build.ride_candidates
        }
        for ride in passenger_plan.served_rides:
            key = (
                ride.demand_group_id,
                ride.cabin_id,
                ride.board_visit_index,
                ride.alight_visit_index,
            )
            try:
                count_by_candidate[candidate_id_by_key[key]] += ride.count
            except KeyError as error:
                raise ValueError("passenger MIP start contains an unknown ride") from error
        for candidate_id, variable in self.variables.ride_count.items():
            count = count_by_candidate[candidate_id]
            variable.Start = float(count)
            self.variables.used[candidate_id].Start = float(count > 0)
            for (bit_candidate_id, bit_index), bit in self.variables.count_bit.items():
                if bit_candidate_id == candidate_id:
                    bit.Start = float(bool(count & (1 << bit_index)))
        for group_id, variable in self.variables.unserved.items():
            variable.Start = float(
                passenger_plan.unserved_counts_by_demand_group_id[group_id]
            )

    def extract_passenger_plan(self) -> EanPassengerServicePlan:
        movement = self.movement
        variables = movement.variables
        rides: list[EanServedRideGroup] = []
        served_by_group = {group_id: 0 for group_id in self.group_by_id}
        for candidate in self.passenger_build.ride_candidates:
            count = int(round(float(self.variables.ride_count[candidate.id].X)))
            if count <= 0:
                continue
            board_key = (candidate.cabin_id, candidate.board_visit_index)
            alight_key = (candidate.cabin_id, candidate.alight_visit_index)
            board_time = float(
                platform_exit_time_expr(
                    board_key,
                    variables.switch_time,
                    variables.wait_time,
                    movement.visits_by_key,
                    movement.timing_by_switch_id,
                ).getValue()
            )
            alight_time = float(
                platform_entry_time_expr(
                    alight_key,
                    variables.switch_time,
                    movement.visits_by_key,
                    movement.timing_by_switch_id,
                ).getValue()
            )
            rides.append(
                EanServedRideGroup(
                    demand_group_id=candidate.demand_group_id,
                    cabin_id=candidate.cabin_id,
                    board_visit_index=candidate.board_visit_index,
                    alight_visit_index=candidate.alight_visit_index,
                    count=count,
                    boarding_time_seconds=max(0.0, board_time),
                    alighting_time_seconds=max(0.0, alight_time),
                )
            )
            served_by_group[candidate.demand_group_id] += count
        unserved = {
            group_id: int(round(float(variable.X)))
            for group_id, variable in self.variables.unserved.items()
        }
        for group_id, group in self.group_by_id.items():
            if served_by_group[group_id] + unserved[group_id] != group.count:
                raise ValueError("ride-count passenger extraction violates demand balance")
        plan = EanPassengerServicePlan(
            scenario_id=movement.artifact.scenario_id,
            horizon_seconds=movement.artifact.config.horizon_seconds,
            served_rides=tuple(rides),
            unserved_counts_by_demand_group_id=unserved,
        )
        plan.validate()
        return plan


@dataclass(frozen=True)
class EanRideCountPassengerModelBuilder:
    """Exact bundled passenger formulation for variable EAN event times."""

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
        objective_ticks_per_second: int = 1,
    ) -> EanRideCountPassengerModel:
        artifact = movement_model.artifact
        if scenario.id != artifact.scenario_id:
            raise ValueError("ride-count passenger scenario does not match artifact")
        if objective_ticks_per_second <= 0:
            raise ValueError("objective_ticks_per_second must be positive")
        passenger_build = passenger_build or (
            passenger_builder
            or EanPassengerCandidateBuilder(optimization_config=optimization_config)
        ).build(scenario, artifact)
        passenger_build.validate()
        groups = {group.id: group for group in passenger_build.demand_groups}
        model = movement_model.model
        capacity = artifact.config.cabin_capacity

        ride_count: dict[str, Any] = {}
        used: dict[str, Any] = {}
        count_bit: dict[tuple[str, int], Any] = {}
        selected_event_time: dict[tuple[str, int], Any] = {}
        upper_by_candidate: dict[str, int] = {}
        for candidate in passenger_build.ride_candidates:
            upper = min(groups[candidate.demand_group_id].count, capacity)
            upper_by_candidate[candidate.id] = upper
            stem = _var_id(candidate.id)
            ride_count[candidate.id] = model.addVar(
                lb=0.0, ub=upper, vtype=grb.INTEGER, name=f"ride_count_{stem}"
            )
            used[candidate.id] = model.addVar(vtype=grb.BINARY, name=f"ride_used_{stem}")
            for bit_index in range(max(1, upper.bit_length())):
                count_bit[candidate.id, bit_index] = model.addVar(
                    vtype=grb.BINARY, name=f"ride_count_bit_{stem}_{bit_index}"
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

        rides_by_group: dict[str, list[EanRideCandidate]] = {
            group.id: [] for group in passenger_build.demand_groups
        }
        rides_by_cabin: dict[int, list[EanRideCandidate]] = {}
        event_products: dict[str, Any] = {}
        definition = ean_passenger_objective_definition(objective)
        for candidate in passenger_build.ride_candidates:
            rides_by_group[candidate.demand_group_id].append(candidate)
            rides_by_cabin.setdefault(candidate.cabin_id, []).append(candidate)
            upper = upper_by_candidate[candidate.id]
            bits = [
                (bit_index, count_bit[candidate.id, bit_index])
                for bit_index in range(max(1, upper.bit_length()))
            ]
            model.addConstr(
                ride_count[candidate.id]
                == gp.quicksum((1 << index) * bit for index, bit in bits),
                name=f"ride_binary_expansion_{_var_id(candidate.id)}",
            )
            model.addConstr(
                ride_count[candidate.id] <= upper * used[candidate.id],
                name=f"ride_used_ub_{_var_id(candidate.id)}",
            )
            model.addConstr(
                ride_count[candidate.id] >= used[candidate.id],
                name=f"ride_used_lb_{_var_id(candidate.id)}",
            )
            board_key = (candidate.cabin_id, candidate.board_visit_index)
            alight_key = (candidate.cabin_id, candidate.alight_visit_index)
            board_time = platform_exit_time_expr(
                board_key,
                movement_model.variables.switch_time,
                movement_model.variables.wait_time,
                movement_model.visits_by_key,
                movement_model.timing_by_switch_id,
            )
            alight_time = platform_entry_time_expr(
                alight_key,
                movement_model.variables.switch_time,
                movement_model.visits_by_key,
                movement_model.timing_by_switch_id,
            )
            group = groups[candidate.demand_group_id]
            active = used[candidate.id]
            big_m = movement_model.big_m
            model.addConstr(active <= movement_model.variables.stop[board_key])
            model.addConstr(active <= movement_model.variables.stop[alight_key])
            model.addConstr(board_time >= group.release_time_seconds - big_m * (1 - active))
            model.addConstr(board_time <= artifact.config.horizon_seconds + big_m * (1 - active))
            model.addConstr(alight_time <= artifact.config.horizon_seconds + big_m * (1 - active))

            event_expr = (
                board_time
                if definition.event is EanPassengerObjectiveEvent.BOARDING
                else alight_time
            )
            lower, upper_time = _event_bounds(
                movement_model,
                board_key if definition.event is EanPassengerObjectiveEvent.BOARDING else alight_key,
                board=definition.event is EanPassengerObjectiveEvent.BOARDING,
            )
            product_terms = []
            for bit_index, bit in bits:
                product = model.addVar(
                    lb=min(0.0, lower),
                    ub=max(0.0, upper_time),
                    name=f"ride_event_bit_{_var_id(candidate.id)}_{bit_index}",
                )
                selected_event_time[candidate.id, bit_index] = product
                model.addConstr(product >= lower * bit)
                model.addConstr(product <= upper_time * bit)
                model.addConstr(product >= event_expr - upper_time * (1 - bit))
                model.addConstr(product <= event_expr - lower * (1 - bit))
                product_terms.append((1 << bit_index) * product)
            event_products[candidate.id] = gp.quicksum(product_terms)

        for group in passenger_build.demand_groups:
            model.addConstr(
                gp.quicksum(ride_count[item.id] for item in rides_by_group[group.id])
                + unserved[group.id]
                == group.count,
                name=f"ride_demand_{_var_id(group.id)}",
            )
        for cabin_id, visits in movement_model.visits_by_cabin_id.items():
            cabin_rides = rides_by_cabin.get(cabin_id, ())
            for visit in visits:
                onboard = [
                    ride_count[candidate.id]
                    for candidate in cabin_rides
                    if candidate.board_visit_index <= visit.visit_index < candidate.alight_visit_index
                ]
                if onboard:
                    model.addConstr(
                        gp.quicksum(onboard) <= capacity,
                        name=f"ride_capacity_{cabin_id}_{visit.visit_index}",
                    )

        secondary_terms = []
        for candidate in passenger_build.ride_candidates:
            group = groups[candidate.demand_group_id]
            secondary_terms.append(
                event_products[candidate.id]
                - group.release_time_seconds * ride_count[candidate.id]
            )
        for group in passenger_build.demand_groups:
            secondary_terms.append(
                definition.unserved_cost_seconds(
                    release_time_seconds=group.release_time_seconds,
                    horizon_seconds=artifact.config.horizon_seconds,
                )
                * unserved[group.id]
            )
        objective_expression = gp.quicksum(secondary_terms)
        total_demand = sum(group.count for group in passenger_build.demand_groups)
        lexicographic_weight = (
            total_demand
            * artifact.config.horizon_seconds
            * objective_ticks_per_second
            + 1.0
        )
        lexicographic_expression = (
            lexicographic_weight * gp.quicksum(unserved.values())
            + objective_ticks_per_second * objective_expression
        )
        model.setObjective(lexicographic_expression, grb.MINIMIZE)
        model.update()
        return EanRideCountPassengerModel(
            movement=movement_model,
            passenger_build=passenger_build,
            group_by_id=groups,
            variables=EanRideCountPassengerVariables(
                ride_count=ride_count,
                used=used,
                count_bit=count_bit,
                selected_event_time=selected_event_time,
                unserved=unserved,
            ),
            objective=objective,
            objective_expression=objective_expression,
            lexicographic_expression=lexicographic_expression,
            lexicographic_weight=lexicographic_weight,
        )


def _event_bounds(
    movement: EanMovementModel,
    key: tuple[int, int],
    *,
    board: bool,
) -> tuple[float, float]:
    bounds = movement.model_time_bounds.by_visit[key]
    timing = movement.timing_by_switch_id[movement.visits_by_key[key].switch_id]
    if board:
        offset = (
            timing.entry_to_platform_entry_seconds
            + timing.min_platform_entry_to_platform_exit_seconds
        )
        return bounds.switch_lower + offset, bounds.switch_upper + offset + bounds.wait_upper
    offset = timing.entry_to_platform_entry_seconds
    return bounds.switch_lower + offset, bounds.switch_upper + offset


def _var_id(value: str) -> str:
    return value.replace("::", "__").replace(":", "_").replace("-", "_").replace(" ", "_")
