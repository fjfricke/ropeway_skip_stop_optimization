from __future__ import annotations

from dataclasses import dataclass, field, replace
import math
from time import perf_counter
from typing import Mapping

import gurobipy as gp
from gurobipy import GRB

from ropeway_skip_stop_optimization.optimization.ddd.arc_flow_passenger_domain import (
    DddArcFlowPassengerDomain,
)
from .arc_flow_passenger_formulation import DddPreparedArcFlowPassengers
from ropeway_skip_stop_optimization.optimization.ddd.passenger_benders_cuts import (
    DddPassengerBendersCut,
    build_ddd_passenger_benders_cut,
    ddd_movement_vector_signature,
)
from ropeway_skip_stop_optimization.optimization.ean.optimizers.fixed_movement_passenger_model import (
    EanPassengerAssignmentDomain,
)


@dataclass(slots=True)
class DddArcFlowIntegratedPassengerModel:
    domain: DddArcFlowPassengerDomain
    variable_by_id: dict[str, gp.Var]
    link_constraint_by_variable_id: dict[str, gp.Constr]
    equality_constraint_by_id: dict[str, gp.Constr]
    demand_constraint_by_id: dict[str, gp.Constr]
    capacity_constraint_by_id: dict[str, gp.Constr]
    encoding: DddPreparedArcFlowPassengers | None = None
    ride_variable_by_id: dict[str, gp.Var] = field(default_factory=dict)
    extra_constraints: tuple[gp.Constr, ...] = ()
    route_by_arc_id: Mapping[str, gp.Var] = field(default_factory=dict)

    @property
    def variable_count(self) -> int:
        return len(self.variable_by_id) + len(self.ride_variable_by_id)

    @property
    def constraint_count(self) -> int:
        return (len(self.link_constraint_by_variable_id) + len(self.equality_constraint_by_id)
                + len(self.demand_constraint_by_id) + len(self.capacity_constraint_by_id)
                + len(self.extra_constraints))

    def canonical_values(self, variable_values=None, movement_values=None) -> dict[str, float]:
        """Reconstruct original ride flows only at an integer Movement solution."""
        raw = ({key: var.X for key, var in self.variable_by_id.items()}
               if variable_values is None else variable_values)
        if self.encoding is None:
            return raw
        projection = dict(self.encoding.projection)
        if not self.encoding.config.destination_flows:
            return {v.id: raw[projection[v.id]] if v.id in projection else 0.0
                    for v in self.domain.variables}
        movement = ({key: var.X for key, var in self.route_by_arc_id.items()}
                    if movement_values is None else movement_values)
        metadata = self.domain.variable_by_id
        values = {}
        for flow in self.domain.flows:
            count = sum(raw[projection[v]]
                        for _, v in flow.variable_ids_by_arc_id
                        if v in projection and metadata[v].visit_index == flow.board_visit_index)
            for arc_id, variable_id in flow.variable_ids_by_arc_id:
                values[variable_id] = (count if variable_id in projection
                                       and movement[arc_id] > 0.5 else 0.0)
        # The decomposition must reproduce every shared flow, not just its cost.
        totals = {key: 0.0 for key in self.variable_by_id}
        for old, new in projection.items():
            totals[new] += values[old]
        if any(abs(totals[key] - value) > 1e-5 for key, value in raw.items()):
            raise ValueError("destination flow cannot be decomposed into canonical rides")
        return values

    def apply_seed(
        self,
        *,
        ride_counts_by_candidate_id: Mapping[str, float],
        movement_values_by_arc_id: Mapping[str, float],
        tolerance: float = 1e-6,
    ) -> float:
        """Set a complete Passenger start on one selected Movement path set."""

        unknown = set(ride_counts_by_candidate_id) - {
            flow.candidate_id for flow in self.domain.flows
        }
        if unknown:
            raise ValueError("Passenger seed references a candidate outside the domain")
        if self.encoding is not None:
            return self._apply_encoded_seed(ride_counts_by_candidate_id, movement_values_by_arc_id, tolerance)
        variable_by_id = self.domain.variable_by_id
        objective = self.domain.objective_constant
        selected_count_by_flow: dict[str, int] = {}
        for flow in self.domain.flows:
            value = ride_counts_by_candidate_id.get(flow.candidate_id, 0.0)
            selected_count = 0
            for arc_id, variable_id in flow.variable_ids_by_arc_id:
                selected = movement_values_by_arc_id.get(arc_id, 0.0) > 0.5
                start = value if selected else 0.0
                self.variable_by_id[variable_id].Start = start
                objective += variable_by_id[variable_id].objective_coefficient * start
                selected_count += int(selected)
            selected_count_by_flow[flow.candidate_id] = selected_count
        if any(
            value > tolerance and selected_count_by_flow.get(candidate_id, 0) == 0
            for candidate_id, value in ride_counts_by_candidate_id.items()
        ):
            raise ValueError("Passenger seed ride is not supported by the Movement seed")
        return objective

    def _apply_encoded_seed(self, counts, movement, tolerance):
        projection = dict(self.encoding.projection)
        values = {key: 0.0 for key in self.variable_by_id}
        metadata = self.domain.variable_by_id
        objective = self.domain.objective_constant
        for flow in self.domain.flows:
            count = counts.get(flow.candidate_id, 0.0)
            if count < -tolerance or abs(count - round(count)) > tolerance:
                raise ValueError("Passenger seed quantities must be nonnegative integers")
            selected_layers = set()
            for arc_id, old in flow.variable_ids_by_arc_id:
                if movement.get(arc_id, 0.0) <= 0.5:
                    continue
                if count > tolerance and old not in projection:
                    raise ValueError("positive seed uses a pruned Passenger arc")
                selected_layers.add(metadata[old].visit_index)
                if old in projection:
                    values[projection[old]] += count
                    objective += metadata[old].objective_coefficient * count
            if count > tolerance and selected_layers != set(range(flow.board_visit_index, flow.alight_visit_index + 1)):
                raise ValueError("positive seed lacks a complete Passenger path")
            if flow.candidate_id in self.ride_variable_by_id:
                self.ride_variable_by_id[flow.candidate_id].Start = count
        for key, value in values.items():
            self.variable_by_id[key].Start = value
        return objective


@dataclass(frozen=True, slots=True)
class DddArcFlowPassengerModelBuilder:
    def build_integrated(
        self,
        *,
        model: gp.Model,
        domain: DddArcFlowPassengerDomain,
        route_by_arc_id: Mapping[str, gp.Var],
        assignment_domain: EanPassengerAssignmentDomain = (
            EanPassengerAssignmentDomain.INTEGER
        ),
        encoding: DddPreparedArcFlowPassengers | None = None,
    ) -> DddArcFlowIntegratedPassengerModel:
        source_domain = domain
        if encoding is not None:
            domain = encoding.algebra
        variable_type = (
            GRB.INTEGER
            if assignment_domain is EanPassengerAssignmentDomain.INTEGER
            else GRB.CONTINUOUS
        )
        flow_type = (GRB.CONTINUOUS if encoding is not None and encoding.config.ride_integrality
                     else variable_type)
        variable_by_id = {
            variable.id: model.addVar(
                lb=0.0,
                obj=variable.objective_coefficient,
                vtype=flow_type,
                name=variable.id,
            )
            for variable in domain.variables
        }
        model.update()
        dropped = set() if encoding is None else {key for key, _ in encoding.dropped_links}
        link = {
            variable.id: model.addConstr(
                variable_by_id[variable.id]
                <= variable.upper_bound * route_by_arc_id[variable.arc_id],
                name=f"passenger_route[{index}]",
            )
            for index, variable in enumerate(domain.variables)
            if variable.id not in dropped
        }
        equality = {
            row.id: model.addConstr(
                gp.quicksum(
                    coefficient * variable_by_id[variable_id]
                    for variable_id, coefficient in row.coefficients
                )
                == 0.0,
                name=row.id,
            )
            for row in domain.equality_rows
        }
        demand = {
            row.id: model.addConstr(
                gp.quicksum(variable_by_id[item] for item in row.variable_ids)
                <= row.right_hand_side,
                name=row.id,
            )
            for row in domain.demand_rows
        }
        capacity = {
            row.id: model.addConstr(
                gp.quicksum(variable_by_id[item] for item in row.variable_ids)
                <= row.movement_coefficient * route_by_arc_id[row.arc_id],
                name=row.id,
            )
            for row in domain.capacity_rows
        }
        model.ObjCon = domain.objective_constant
        ride_variables = {}
        extra = []
        if encoding is not None:
            if encoding.config.ride_integrality:
                metadata = source_domain.variable_by_id
                projection = dict(encoding.projection)
                for flow in source_domain.flows:
                    board_ids = [projection[v] for _, v in flow.variable_ids_by_arc_id
                                 if v in projection and metadata[v].visit_index == flow.board_visit_index]
                    if not board_ids:
                        continue
                    ride = model.addVar(lb=0.0, vtype=variable_type, name=f"ride_count[{flow.candidate_id}]")
                    ride_variables[flow.candidate_id] = ride
                    extra.append(model.addConstr(ride == gp.quicksum(
                        variable_by_id[v] for v in board_ids
                    ), name=f"ride_count_link[{flow.candidate_id}]"))
            for arc_id, ids, capacity_value in encoding.alight_rows:
                extra.append(model.addConstr(gp.quicksum(variable_by_id[v] for v in ids)
                                             <= capacity_value * route_by_arc_id[arc_id],
                                             name=f"alight_capacity[{arc_id}]"))
        model.update()
        return DddArcFlowIntegratedPassengerModel(
            domain=source_domain,
            variable_by_id=variable_by_id,
            link_constraint_by_variable_id=link,
            equality_constraint_by_id=equality,
            demand_constraint_by_id=demand,
            capacity_constraint_by_id=capacity,
            encoding=encoding,
            ride_variable_by_id=ride_variables,
            extra_constraints=tuple(extra),
            route_by_arc_id=route_by_arc_id,
        )

    def build_recourse(
        self,
        *,
        domain: DddArcFlowPassengerDomain,
        assignment_domain: EanPassengerAssignmentDomain,
        output_flag: bool = False,
        threads: int | None = None,
    ) -> DddArcFlowPassengerRecourseModel:
        model = gp.Model(
            f"ddd_passenger_recourse_{assignment_domain.value}"
        )
        model.Params.OutputFlag = int(output_flag)
        if threads is not None:
            model.Params.Threads = threads
        variable_type = (
            GRB.INTEGER
            if assignment_domain is EanPassengerAssignmentDomain.INTEGER
            else GRB.CONTINUOUS
        )
        variable_by_id = {
            variable.id: model.addVar(
                lb=0.0,
                obj=variable.objective_coefficient,
                vtype=variable_type,
                name=variable.id,
            )
            for variable in domain.variables
        }
        model.update()
        link = {
            variable.id: model.addConstr(
                variable_by_id[variable.id] <= 0.0,
                name=f"passenger_route[{index}]",
            )
            for index, variable in enumerate(domain.variables)
        }
        equality = {
            row.id: model.addConstr(
                gp.quicksum(
                    coefficient * variable_by_id[variable_id]
                    for variable_id, coefficient in row.coefficients
                )
                == 0.0,
                name=row.id,
            )
            for row in domain.equality_rows
        }
        demand = {
            row.id: model.addConstr(
                gp.quicksum(variable_by_id[item] for item in row.variable_ids)
                <= row.right_hand_side,
                name=row.id,
            )
            for row in domain.demand_rows
        }
        capacity = {
            row.id: model.addConstr(
                gp.quicksum(variable_by_id[item] for item in row.variable_ids)
                <= 0.0,
                name=row.id,
            )
            for row in domain.capacity_rows
        }
        model.ObjCon = domain.objective_constant
        model.ModelSense = GRB.MINIMIZE
        model.update()
        return DddArcFlowPassengerRecourseModel(
            domain=domain,
            assignment_domain=assignment_domain,
            model=model,
            variable_by_id=variable_by_id,
            link_constraint_by_variable_id=link,
            equality_constraint_by_id=equality,
            demand_constraint_by_id=demand,
            capacity_constraint_by_id=capacity,
        )


@dataclass(frozen=True, slots=True)
class DddArcFlowPassengerRecourseResult:
    assignment_domain: EanPassengerAssignmentDomain
    movement_signature: str
    solver_status: int
    objective_value: float | None
    best_bound: float | None
    optimal: bool
    variable_values: tuple[tuple[str, float], ...]
    fractional_variable_count: int
    maximum_fractional_distance: float
    benders_cut: DddPassengerBendersCut | None
    solve_seconds: float
    evaluation_index: int
    cache_hit: bool = False


@dataclass(slots=True)
class DddArcFlowPassengerRecourseModel:
    domain: DddArcFlowPassengerDomain
    assignment_domain: EanPassengerAssignmentDomain
    model: gp.Model
    variable_by_id: dict[str, gp.Var]
    link_constraint_by_variable_id: dict[str, gp.Constr]
    equality_constraint_by_id: dict[str, gp.Constr]
    demand_constraint_by_id: dict[str, gp.Constr]
    capacity_constraint_by_id: dict[str, gp.Constr]
    evaluation_count: int = 0
    _optimal_cache: dict[str, DddArcFlowPassengerRecourseResult] = field(
        default_factory=dict,
        repr=False,
    )

    def evaluate(
        self,
        movement_values: Mapping[str, float],
        *,
        capacity_rhs_offsets: Mapping[str, float] | None = None,
        time_limit_seconds: float | None = None,
        tightness_tolerance: float = 1e-5,
    ) -> DddArcFlowPassengerRecourseResult:
        if time_limit_seconds is not None and (
            not math.isfinite(time_limit_seconds) or time_limit_seconds <= 0
        ):
            raise ValueError("Passenger recourse time limit must be positive")
        required_arcs = {
            variable.arc_id for variable in self.domain.variables
        } | {row.arc_id for row in self.domain.capacity_rows}
        missing = required_arcs - movement_values.keys()
        if missing:
            raise ValueError(
                "Passenger recourse Movement vector misses arcs: "
                f"{sorted(missing)[:3]}"
            )
        if any(
            not math.isfinite(value) or value < -1e-8 or value > 1.0 + 1e-8
            for value in movement_values.values()
        ):
            raise ValueError("Passenger recourse Movement values must lie in [0, 1]")
        offsets = {} if capacity_rhs_offsets is None else dict(capacity_rhs_offsets)
        unknown_offsets = offsets.keys() - self.capacity_constraint_by_id.keys()
        if unknown_offsets:
            raise ValueError(
                "Passenger recourse capacity offsets reference unknown rows: "
                f"{sorted(unknown_offsets)[:3]}"
            )
        if any(not math.isfinite(value) or value < -1e-8 for value in offsets.values()):
            raise ValueError(
                "Passenger recourse capacity offsets must be finite and nonnegative"
            )
        movement_signature = _recourse_vector_signature(movement_values, offsets)
        self.evaluation_count += 1
        cached = self._optimal_cache.get(movement_signature)
        if cached is not None:
            return replace(
                cached,
                solve_seconds=0.0,
                evaluation_index=self.evaluation_count,
                cache_hit=True,
            )
        for variable in self.domain.variables:
            self.link_constraint_by_variable_id[variable.id].RHS = (
                variable.upper_bound * movement_values[variable.arc_id]
            )
        for row in self.domain.capacity_rows:
            self.capacity_constraint_by_id[row.id].RHS = (
                row.movement_coefficient * movement_values[row.arc_id]
                - offsets.get(row.id, 0.0)
            )
        if time_limit_seconds is not None:
            self.model.Params.TimeLimit = time_limit_seconds
        else:
            self.model.Params.TimeLimit = GRB.INFINITY
        self.model.update()
        started = perf_counter()
        self.model.optimize()
        solve_seconds = perf_counter() - started
        has_solution = int(self.model.SolCount) > 0
        objective = float(self.model.ObjVal) if has_solution else None
        values = tuple(
            (variable_id, float(variable.X))
            for variable_id, variable in self.variable_by_id.items()
        ) if has_solution else ()
        distances = tuple(
            abs(value - round(value))
            for _, value in values
            if not math.isclose(value, round(value), abs_tol=1e-6)
        )
        cut = None
        if (
            self.assignment_domain is EanPassengerAssignmentDomain.LP_RELAXATION
            and self.model.Status == GRB.OPTIMAL
            and objective is not None
            and not offsets
        ):
            cut = self._dual_cut(movement_values, objective)
            if not math.isclose(
                cut.evaluate(movement_values),
                objective,
                rel_tol=0.0,
                abs_tol=tightness_tolerance,
            ):
                raise RuntimeError("Passenger LP dual cut is not tight")
        result = DddArcFlowPassengerRecourseResult(
            assignment_domain=self.assignment_domain,
            movement_signature=movement_signature,
            solver_status=int(self.model.Status),
            objective_value=objective,
            best_bound=(
                float(self.model.ObjBound)
                if math.isfinite(float(self.model.ObjBound))
                else None
            ),
            optimal=self.model.Status == GRB.OPTIMAL,
            variable_values=values,
            fractional_variable_count=len(distances),
            maximum_fractional_distance=max(distances, default=0.0),
            benders_cut=cut,
            solve_seconds=solve_seconds,
            evaluation_index=self.evaluation_count,
        )
        if result.optimal:
            self._optimal_cache[movement_signature] = result
        return result

    def _dual_cut(
        self,
        movement_values: Mapping[str, float],
        objective: float,
    ) -> DddPassengerBendersCut:
        constant = self.domain.objective_constant + sum(
            row.right_hand_side * self.demand_constraint_by_id[row.id].Pi
            for row in self.domain.demand_rows
        )
        coefficients: dict[str, float] = {}
        for variable in self.domain.variables:
            coefficients[variable.arc_id] = coefficients.get(variable.arc_id, 0.0) + (
                variable.upper_bound
                * self.link_constraint_by_variable_id[variable.id].Pi
            )
        for row in self.domain.capacity_rows:
            coefficients[row.arc_id] = coefficients.get(row.arc_id, 0.0) + (
                row.movement_coefficient * self.capacity_constraint_by_id[row.id].Pi
            )
        return build_ddd_passenger_benders_cut(
            constant=constant,
            coefficients=coefficients,
            source_objective=objective,
            source_movement_signature=ddd_movement_vector_signature(
                movement_values
            ),
        )


def _recourse_vector_signature(
    movement_values: Mapping[str, float],
    capacity_rhs_offsets: Mapping[str, float],
) -> str:
    if not capacity_rhs_offsets:
        return ddd_movement_vector_signature(movement_values)
    return ddd_movement_vector_signature(
        {
            **movement_values,
            **{
                f"capacity_offset::{row_id}": value
                for row_id, value in capacity_rhs_offsets.items()
            },
        }
    )
