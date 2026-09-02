from __future__ import annotations

from dataclasses import dataclass
from collections import defaultdict, deque
import math
from time import perf_counter
from typing import Mapping

import gurobipy as gp
from gurobipy import GRB

from ropeway_skip_stop_optimization.optimization.ddd.passenger_partial_master import (
    DddPartialPassengerBendersCut,
    DddPartialPassengerDomain,
    build_ddd_partial_passenger_benders_cut,
    ddd_partial_passenger_point_signature,
)


@dataclass(frozen=True, slots=True)
class DddPassengerCouplingComponent:
    id: str
    demand_group_ids: tuple[str, ...]
    capacity_row_ids: tuple[str, ...]
    variable_ids: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class DddPassengerCouplingComponentIndex:
    passenger_domain_fingerprint: str
    components: tuple[DddPassengerCouplingComponent, ...]

    @classmethod
    def build(
        cls,
        domain: DddPartialPassengerDomain,
    ) -> DddPassengerCouplingComponentIndex:
        residual = domain.residual_domain
        group_by_variable = {
            variable.id: variable.demand_group_id
            for variable in residual.variables
        }
        rows_by_group: dict[str, set[str]] = defaultdict(set)
        groups_by_row: dict[str, set[str]] = defaultdict(set)
        for row in residual.capacity_rows:
            for variable_id in row.variable_ids:
                group_id = group_by_variable[variable_id]
                rows_by_group[group_id].add(row.id)
                groups_by_row[row.id].add(group_id)
        all_groups = tuple(
            sorted(row.demand_group_id for row in residual.demand_rows)
        )
        unseen = set(all_groups)
        components = []
        while unseen:
            first = min(unseen)
            queue = deque([first])
            component_groups: set[str] = set()
            component_rows: set[str] = set()
            while queue:
                group_id = queue.popleft()
                if group_id in component_groups:
                    continue
                component_groups.add(group_id)
                unseen.discard(group_id)
                for row_id in rows_by_group.get(group_id, ()):
                    component_rows.add(row_id)
                    for neighbor in groups_by_row[row_id]:
                        if neighbor not in component_groups:
                            queue.append(neighbor)
            group_tuple = tuple(sorted(component_groups))
            components.append(
                DddPassengerCouplingComponent(
                    id=f"passenger_component[{len(components)}]",
                    demand_group_ids=group_tuple,
                    capacity_row_ids=tuple(sorted(component_rows)),
                    variable_ids=tuple(
                        variable.id
                        for variable in residual.variables
                        if variable.demand_group_id in component_groups
                    ),
                )
            )
        result = cls(
            passenger_domain_fingerprint=residual.fingerprint,
            components=tuple(components),
        )
        result.validate(domain)
        return result

    def validate(self, domain: DddPartialPassengerDomain) -> None:
        residual = domain.residual_domain
        if self.passenger_domain_fingerprint != residual.fingerprint:
            raise ValueError("Passenger coupling index and residual domain differ")
        groups = [
            group_id
            for component in self.components
            for group_id in component.demand_group_ids
        ]
        expected_groups = sorted(
            row.demand_group_id for row in residual.demand_rows
        )
        if sorted(groups) != expected_groups or len(groups) != len(set(groups)):
            raise ValueError("Passenger coupling components do not partition demand")
        variables = [
            variable_id
            for component in self.components
            for variable_id in component.variable_ids
        ]
        expected_variables = sorted(variable.id for variable in residual.variables)
        if sorted(variables) != expected_variables or len(variables) != len(
            set(variables)
        ):
            raise ValueError("Passenger coupling components do not partition variables")
        component_by_group = {
            group_id: component.id
            for component in self.components
            for group_id in component.demand_group_ids
        }
        group_by_variable = {
            variable.id: variable.demand_group_id
            for variable in residual.variables
        }
        for row in residual.capacity_rows:
            component_ids = {
                component_by_group[group_by_variable[variable_id]]
                for variable_id in row.variable_ids
            }
            if len(component_ids) > 1:
                raise ValueError("shared Passenger capacity crosses components")


@dataclass(frozen=True, slots=True)
class DddPassengerCorePoint:
    movement_values: tuple[tuple[str, float], ...]
    core_values: tuple[tuple[str, float], ...]
    observation_count: int

    @property
    def movement_value_by_arc_id(self) -> dict[str, float]:
        return dict(self.movement_values)

    @property
    def core_value_by_variable_id(self) -> dict[str, float]:
        return dict(self.core_values)

    @classmethod
    def from_point(
        cls,
        movement_values: Mapping[str, float],
        core_values: Mapping[str, float],
    ) -> DddPassengerCorePoint:
        return cls(
            movement_values=tuple(sorted(movement_values.items())),
            core_values=tuple(sorted(core_values.items())),
            observation_count=1,
        )

    def update(
        self,
        movement_values: Mapping[str, float],
        core_values: Mapping[str, float],
        *,
        previous_weight: float = 0.5,
    ) -> DddPassengerCorePoint:
        if not math.isfinite(previous_weight) or not 0 < previous_weight < 1:
            raise ValueError("Passenger core-point weight must lie in (0, 1)")
        old_movement = self.movement_value_by_arc_id
        old_core = self.core_value_by_variable_id
        if old_movement.keys() != movement_values.keys():
            raise ValueError("Passenger core-point Movement domain changed")
        if old_core.keys() != core_values.keys():
            raise ValueError("Passenger core-point variable domain changed")
        return DddPassengerCorePoint(
            movement_values=tuple(
                (item_id, previous_weight * old_movement[item_id] + (
                    1.0 - previous_weight
                ) * movement_values[item_id])
                for item_id in sorted(old_movement)
            ),
            core_values=tuple(
                (item_id, previous_weight * old_core[item_id] + (
                    1.0 - previous_weight
                ) * core_values[item_id])
                for item_id in sorted(old_core)
            ),
            observation_count=self.observation_count + 1,
        )


@dataclass(frozen=True, slots=True)
class DddParetoPassengerCutResult:
    cut: DddPartialPassengerBendersCut | None
    solver_status: int
    optimal: bool
    solve_seconds: float
    source_value: float | None
    core_point_value: float | None
    detail: str | None = None


@dataclass(slots=True)
class DddParetoPassengerCutGenerator:
    """Magnanti-Wong auxiliary dual for the residual Passenger LP."""

    domain: DddPartialPassengerDomain
    output_flag: bool = False
    threads: int | None = None
    _model: gp.Model | None = None
    _link_dual_by_variable_id: dict[str, gp.Var] | None = None
    _equality_dual_by_row_id: dict[str, gp.Var] | None = None
    _demand_dual_by_row_id: dict[str, gp.Var] | None = None
    _capacity_dual_by_row_id: dict[str, gp.Var] | None = None
    _source_tightness: gp.Constr | None = None

    def __post_init__(self) -> None:
        if self.threads is not None and self.threads <= 0:
            raise ValueError("Pareto Passenger cut threads must be positive")
        self._build()

    def generate(
        self,
        *,
        source_movement_values: Mapping[str, float],
        source_core_values: Mapping[str, float],
        source_objective: float,
        core_point: DddPassengerCorePoint,
        time_limit_seconds: float | None = None,
        tightness_tolerance: float = 1e-5,
    ) -> DddParetoPassengerCutResult:
        if not math.isfinite(source_objective):
            raise ValueError("Pareto Passenger source objective must be finite")
        if time_limit_seconds is not None and (
            not math.isfinite(time_limit_seconds) or time_limit_seconds <= 0
        ):
            raise ValueError("Pareto Passenger time limit must be positive")
        self.domain.capacity_offsets(source_core_values)
        self.domain.capacity_offsets(core_point.core_value_by_variable_id)
        model = self._required_model()
        source_coefficients = self._dual_objective_coefficients(
            source_movement_values,
            source_core_values,
        )
        core_coefficients = self._dual_objective_coefficients(
            core_point.movement_value_by_arc_id,
            core_point.core_value_by_variable_id,
        )
        tightness = self._required_source_tightness()
        for variable in self._all_dual_variables():
            model.chgCoeff(
                tightness,
                variable,
                source_coefficients.get(variable.VarName, 0.0),
            )
        tightness.RHS = source_objective - self.domain.residual_domain.objective_constant
        model.setObjective(
            gp.quicksum(
                core_coefficients.get(variable.VarName, 0.0) * variable
                for variable in self._all_dual_variables()
                if abs(core_coefficients.get(variable.VarName, 0.0)) > 1e-12
            ),
            GRB.MAXIMIZE,
        )
        model.Params.TimeLimit = (
            GRB.INFINITY if time_limit_seconds is None else time_limit_seconds
        )
        model.update()
        started = perf_counter()
        model.optimize()
        solve_seconds = perf_counter() - started
        if model.Status != GRB.OPTIMAL:
            return DddParetoPassengerCutResult(
                cut=None,
                solver_status=int(model.Status),
                optimal=False,
                solve_seconds=solve_seconds,
                source_value=None,
                core_point_value=None,
                detail="Magnanti-Wong auxiliary dual did not solve to optimality",
            )
        cut = self._extract_cut(
            source_objective=source_objective,
            source_signature=ddd_partial_passenger_point_signature(
                source_movement_values,
                source_core_values,
            ),
        )
        source_value = cut.evaluate(source_movement_values, source_core_values)
        core_value = cut.evaluate(
            core_point.movement_value_by_arc_id,
            core_point.core_value_by_variable_id,
        )
        if not math.isclose(
            source_value,
            source_objective,
            rel_tol=0.0,
            abs_tol=tightness_tolerance,
        ):
            return DddParetoPassengerCutResult(
                cut=None,
                solver_status=int(model.Status),
                optimal=True,
                solve_seconds=solve_seconds,
                source_value=source_value,
                core_point_value=core_value,
                detail="Magnanti-Wong cut is not tight at the source point",
            )
        return DddParetoPassengerCutResult(
            cut=cut,
            solver_status=int(model.Status),
            optimal=True,
            solve_seconds=solve_seconds,
            source_value=source_value,
            core_point_value=core_value,
        )

    def _build(self) -> None:
        residual = self.domain.residual_domain
        model = gp.Model("ddd_partial_passenger_magnanti_wong")
        model.Params.OutputFlag = int(self.output_flag)
        if self.threads is not None:
            model.Params.Threads = self.threads
        link = {
            variable.id: model.addVar(
                lb=-GRB.INFINITY,
                ub=0.0,
                name=f"dual_link::{variable.id}",
            )
            for variable in residual.variables
        }
        equality = {
            row.id: model.addVar(
                lb=-GRB.INFINITY,
                ub=GRB.INFINITY,
                name=f"dual_equality::{row.id}",
            )
            for row in residual.equality_rows
        }
        demand = {
            row.id: model.addVar(
                lb=-GRB.INFINITY,
                ub=0.0,
                name=f"dual_demand::{row.id}",
            )
            for row in residual.demand_rows
        }
        capacity = {
            row.id: model.addVar(
                lb=-GRB.INFINITY,
                ub=0.0,
                name=f"dual_capacity::{row.id}",
            )
            for row in residual.capacity_rows
        }
        model.update()
        equality_by_variable: dict[str, list[tuple[gp.Var, float]]] = {}
        for row in residual.equality_rows:
            for variable_id, coefficient in row.coefficients:
                equality_by_variable.setdefault(variable_id, []).append(
                    (equality[row.id], coefficient)
                )
        demand_by_variable = {
            variable_id: demand[row.id]
            for row in residual.demand_rows
            for variable_id in row.variable_ids
        }
        capacity_by_variable: dict[str, list[gp.Var]] = {}
        for row in residual.capacity_rows:
            for variable_id in row.variable_ids:
                capacity_by_variable.setdefault(variable_id, []).append(
                    capacity[row.id]
                )
        for variable in residual.variables:
            model.addConstr(
                link[variable.id]
                + gp.quicksum(
                    coefficient * dual
                    for dual, coefficient in equality_by_variable.get(
                        variable.id, ()
                    )
                )
                + (
                    0.0
                    if variable.id not in demand_by_variable
                    else demand_by_variable[variable.id]
                )
                + gp.quicksum(capacity_by_variable.get(variable.id, ()))
                <= variable.objective_coefficient,
                name=f"dual_feasibility::{variable.id}",
            )
        source_tightness = model.addConstr(
            gp.LinExpr() == 0.0,
            name="source_tightness",
        )
        model.ModelSense = GRB.MAXIMIZE
        model.update()
        self._model = model
        self._link_dual_by_variable_id = link
        self._equality_dual_by_row_id = equality
        self._demand_dual_by_row_id = demand
        self._capacity_dual_by_row_id = capacity
        self._source_tightness = source_tightness

    def _dual_objective_coefficients(
        self,
        movement_values: Mapping[str, float],
        core_values: Mapping[str, float],
    ) -> dict[str, float]:
        residual = self.domain.residual_domain
        offsets = self.domain.capacity_offsets(core_values)
        result = {
            self._required_link()[variable.id].VarName: (
                variable.upper_bound * movement_values[variable.arc_id]
            )
            for variable in residual.variables
        }
        result.update(
            {
                self._required_demand()[row.id].VarName: row.right_hand_side
                for row in residual.demand_rows
            }
        )
        result.update(
            {
                self._required_capacity()[row.id].VarName: (
                    row.movement_coefficient * movement_values[row.arc_id]
                    - offsets.get(row.id, 0.0)
                )
                for row in residual.capacity_rows
            }
        )
        return result

    def _extract_cut(
        self,
        *,
        source_objective: float,
        source_signature: str,
    ) -> DddPartialPassengerBendersCut:
        residual = self.domain.residual_domain
        constant = residual.objective_constant + sum(
            row.right_hand_side * self._required_demand()[row.id].X
            for row in residual.demand_rows
        )
        movement: dict[str, float] = {}
        for variable in residual.variables:
            movement[variable.arc_id] = (
                movement.get(variable.arc_id, 0.0)
                + variable.upper_bound * self._required_link()[variable.id].X
            )
        coupling_by_id = {
            item.capacity_row_id: item for item in self.domain.capacity_couplings
        }
        core: dict[str, float] = {}
        for row in residual.capacity_rows:
            dual = self._required_capacity()[row.id].X
            movement[row.arc_id] = (
                movement.get(row.arc_id, 0.0)
                + row.movement_coefficient * dual
            )
            for variable_id in coupling_by_id[row.id].core_variable_ids:
                core[variable_id] = core.get(variable_id, 0.0) - dual
        return build_ddd_partial_passenger_benders_cut(
            constant=constant,
            movement_coefficients=movement,
            core_coefficients=core,
            source_objective=source_objective,
            source_signature=source_signature,
            kind="core_point_strengthened",
        )

    def _all_dual_variables(self) -> tuple[gp.Var, ...]:
        return tuple(
            variable
            for mapping in (
                self._required_link(),
                self._required_equality(),
                self._required_demand(),
                self._required_capacity(),
            )
            for variable in mapping.values()
        )

    def _required_model(self) -> gp.Model:
        assert self._model is not None
        return self._model

    def _required_link(self) -> dict[str, gp.Var]:
        assert self._link_dual_by_variable_id is not None
        return self._link_dual_by_variable_id

    def _required_equality(self) -> dict[str, gp.Var]:
        assert self._equality_dual_by_row_id is not None
        return self._equality_dual_by_row_id

    def _required_demand(self) -> dict[str, gp.Var]:
        assert self._demand_dual_by_row_id is not None
        return self._demand_dual_by_row_id

    def _required_capacity(self) -> dict[str, gp.Var]:
        assert self._capacity_dual_by_row_id is not None
        return self._capacity_dual_by_row_id

    def _required_source_tightness(self) -> gp.Constr:
        assert self._source_tightness is not None
        return self._source_tightness
