from __future__ import annotations

from dataclasses import asdict, dataclass, replace
from enum import StrEnum
from hashlib import sha256
import json
import math
from typing import Mapping

import gurobipy as gp
from gurobipy import GRB

from ropeway_skip_stop_optimization.optimization.ddd.arc_flow_passenger_domain import (
    DddArcFlowPassengerDomain,
    build_ddd_arc_flow_passenger_subdomain,
)
from ropeway_skip_stop_optimization.optimization.ddd.arc_flow_passenger_model import (
    DddArcFlowIntegratedPassengerModel,
    DddArcFlowPassengerModelBuilder,
    DddArcFlowPassengerRecourseModel,
    DddArcFlowPassengerRecourseResult,
)
from ropeway_skip_stop_optimization.optimization.ddd.arc_flow_preparation import (
    DddPreparedArcFlowProblem,
)
from ropeway_skip_stop_optimization.optimization.ean.passenger_objective import (
    ean_passenger_objective_definition,
)
from ropeway_skip_stop_optimization.optimization.ean.optimizers.fixed_movement_passenger_model import (
    EanPassengerAssignmentDomain,
)


class DddPassengerCorePolicy(StrEnum):
    NONE = "none"
    DEMAND_MASS = "demand_mass"
    SCARCE_RIDES = "scarce_rides"
    HYBRID = "hybrid"
    ALL = "all"


@dataclass(frozen=True, slots=True)
class DddPassengerCoreConfig:
    policy: DddPassengerCorePolicy = DddPassengerCorePolicy.NONE
    maximum_variable_count: int = 0
    maximum_nonzero_count: int = 0
    demand_weight: float = 1.0
    penalty_weight: float = 1.0
    scarcity_weight: float = 1.0
    bottleneck_weight: float = 1.0

    def validate(self) -> None:
        if not isinstance(self.policy, DddPassengerCorePolicy):
            raise ValueError("Passenger core policy is invalid")
        if self.maximum_variable_count < 0 or self.maximum_nonzero_count < 0:
            raise ValueError("Passenger core budgets must be nonnegative")
        weights = (
            self.demand_weight,
            self.penalty_weight,
            self.scarcity_weight,
            self.bottleneck_weight,
        )
        if any(not math.isfinite(value) or value < 0 for value in weights):
            raise ValueError("Passenger core weights must be finite and nonnegative")
        if self.policy not in {
            DddPassengerCorePolicy.NONE,
            DddPassengerCorePolicy.ALL,
        }:
            if self.maximum_variable_count <= 0 or self.maximum_nonzero_count <= 0:
                raise ValueError("selective Passenger cores need positive budgets")
        if self.policy is DddPassengerCorePolicy.HYBRID and sum(weights) <= 0:
            raise ValueError("hybrid Passenger core needs a positive weight")


@dataclass(frozen=True, slots=True)
class DddPassengerGroupStatistics:
    demand_group_id: str
    demand_count: float
    unserved_objective_constant: float
    ride_candidate_count: int
    variable_count: int
    passenger_nonzero_count: int
    capacity_row_count: int
    score: float


@dataclass(frozen=True, slots=True)
class DddPassengerCorePartition:
    passenger_domain_fingerprint: str
    policy: DddPassengerCorePolicy
    core_demand_group_ids: tuple[str, ...]
    residual_demand_group_ids: tuple[str, ...]
    statistics: tuple[DddPassengerGroupStatistics, ...]
    core_variable_count: int
    residual_variable_count: int
    core_nonzero_count: int
    residual_nonzero_count: int
    core_objective_constant: float
    residual_objective_constant: float
    fingerprint: str

    def validate(self, domain: DddArcFlowPassengerDomain) -> None:
        if self.passenger_domain_fingerprint != domain.fingerprint:
            raise ValueError("Passenger core partition and domain differ")
        core = set(self.core_demand_group_ids)
        residual = set(self.residual_demand_group_ids)
        known = {row.demand_group_id for row in domain.demand_rows}
        if core & residual or core | residual != known:
            raise ValueError("Passenger core partition is not exhaustive and disjoint")
        if tuple(sorted(core)) != self.core_demand_group_ids:
            raise ValueError("Passenger core group IDs are not canonical")
        if tuple(sorted(residual)) != self.residual_demand_group_ids:
            raise ValueError("Passenger residual group IDs are not canonical")
        if not math.isclose(
            self.core_objective_constant + self.residual_objective_constant,
            domain.objective_constant,
            rel_tol=0.0,
            abs_tol=1e-6,
        ):
            raise ValueError("Passenger objective constants do not partition exactly")
        if self.fingerprint != _partition_fingerprint(self):
            raise ValueError("Passenger core partition fingerprint is inconsistent")


@dataclass(frozen=True, slots=True)
class DddPassengerCapacityCoupling:
    capacity_row_id: str
    movement_arc_id: str
    movement_coefficient: float
    core_variable_ids: tuple[str, ...]
    residual_variable_ids: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class DddPartialPassengerDomain:
    partition: DddPassengerCorePartition
    core_domain: DddArcFlowPassengerDomain
    residual_domain: DddArcFlowPassengerDomain
    capacity_couplings: tuple[DddPassengerCapacityCoupling, ...]

    def validate(
        self,
        prepared: DddPreparedArcFlowProblem,
        full_domain: DddArcFlowPassengerDomain,
    ) -> None:
        self.partition.validate(full_domain)
        self.core_domain.validate(prepared)
        self.residual_domain.validate(prepared)
        core_variables = {item.id for item in self.core_domain.variables}
        residual_variables = {item.id for item in self.residual_domain.variables}
        full_variables = {item.id for item in full_domain.variables}
        if core_variables & residual_variables:
            raise ValueError("Passenger core and residual variables overlap")
        if core_variables | residual_variables != full_variables:
            raise ValueError("Passenger variable partition is incomplete")
        coupling_by_id = {
            coupling.capacity_row_id: coupling
            for coupling in self.capacity_couplings
        }
        if len(coupling_by_id) != len(self.capacity_couplings):
            raise ValueError("Passenger capacity coupling IDs must be unique")
        for row in full_domain.capacity_rows:
            coupling = coupling_by_id.get(row.id)
            if coupling is None:
                raise ValueError("Passenger capacity coupling row is missing")
            if coupling.movement_arc_id != row.arc_id or not math.isclose(
                coupling.movement_coefficient,
                row.movement_coefficient,
                rel_tol=0.0,
                abs_tol=1e-9,
            ):
                raise ValueError("Passenger capacity coupling changed Movement capacity")
            if tuple(
                variable_id
                for variable_id in row.variable_ids
                if variable_id in core_variables
            ) != coupling.core_variable_ids:
                raise ValueError("Passenger core capacity incidence is inconsistent")
            if tuple(
                variable_id
                for variable_id in row.variable_ids
                if variable_id in residual_variables
            ) != coupling.residual_variable_ids:
                raise ValueError("Passenger residual capacity incidence is inconsistent")

    def capacity_offsets(
        self,
        core_values: Mapping[str, float],
    ) -> dict[str, float]:
        known = {variable.id for variable in self.core_domain.variables}
        missing = known - core_values.keys()
        unknown = core_values.keys() - known
        if missing or unknown:
            raise ValueError(
                "Passenger core vector does not match the core domain: "
                f"missing={sorted(missing)[:3]}, unknown={sorted(unknown)[:3]}"
            )
        if any(
            not math.isfinite(value) or value < -1e-8
            for value in core_values.values()
        ):
            raise ValueError("Passenger core values must be finite and nonnegative")
        residual_rows = {row.id for row in self.residual_domain.capacity_rows}
        return {
            coupling.capacity_row_id: sum(
                core_values[variable_id]
                for variable_id in coupling.core_variable_ids
            )
            for coupling in self.capacity_couplings
            if coupling.capacity_row_id in residual_rows
        }


@dataclass(frozen=True, slots=True)
class DddPartialPassengerBendersCut:
    id: str
    constant: float
    movement_coefficients: tuple[tuple[str, float], ...]
    core_coefficients: tuple[tuple[str, float], ...]
    source_objective: float
    source_signature: str
    kind: str = "partial_lp_dual_optimality"

    def evaluate(
        self,
        movement_values: Mapping[str, float],
        core_values: Mapping[str, float],
    ) -> float:
        return (
            self.constant
            + sum(
                coefficient * movement_values.get(arc_id, 0.0)
                for arc_id, coefficient in self.movement_coefficients
            )
            + sum(
                coefficient * core_values.get(variable_id, 0.0)
                for variable_id, coefficient in self.core_coefficients
            )
        )

    def validate(self) -> None:
        if not self.id or not self.source_signature:
            raise ValueError("partial Passenger cut needs stable provenance")
        if not math.isfinite(self.constant) or not math.isfinite(
            self.source_objective
        ):
            raise ValueError("partial Passenger cut values must be finite")
        for coefficients in (
            self.movement_coefficients,
            self.core_coefficients,
        ):
            ids = tuple(item_id for item_id, _ in coefficients)
            if ids != tuple(sorted(ids)) or len(ids) != len(set(ids)):
                raise ValueError("partial Passenger cut is not canonical")
            if any(not math.isfinite(value) for _, value in coefficients):
                raise ValueError("partial Passenger cut coefficient is invalid")
        if self.id != _partial_cut_fingerprint(self):
            raise ValueError("partial Passenger cut fingerprint is inconsistent")


@dataclass(slots=True)
class DddPartialPassengerMasterContribution:
    domain: DddPartialPassengerDomain
    passenger_core: DddArcFlowIntegratedPassengerModel
    residual_theta: gp.Var
    route_by_arc_id: Mapping[str, gp.Var]
    cut_constraint_by_id: dict[str, gp.Constr]

    def core_values(self) -> dict[str, float]:
        return {
            variable_id: float(variable.X)
            for variable_id, variable in self.passenger_core.variable_by_id.items()
        }

    def add_cut(
        self,
        model: gp.Model,
        cut: DddPartialPassengerBendersCut,
    ) -> bool:
        cut.validate()
        if cut.id in self.cut_constraint_by_id:
            return False
        unknown_arcs = {
            arc_id for arc_id, _ in cut.movement_coefficients
        } - self.route_by_arc_id.keys()
        unknown_core = {
            variable_id for variable_id, _ in cut.core_coefficients
        } - self.passenger_core.variable_by_id.keys()
        if unknown_arcs or unknown_core:
            raise ValueError("partial Passenger cut references unknown variables")
        constraint = model.addConstr(
            self.residual_theta
            >= cut.constant
            + gp.quicksum(
                coefficient * self.route_by_arc_id[arc_id]
                for arc_id, coefficient in cut.movement_coefficients
            )
            + gp.quicksum(
                coefficient * self.passenger_core.variable_by_id[variable_id]
                for variable_id, coefficient in cut.core_coefficients
            ),
            name=f"partial_passenger_benders[{len(self.cut_constraint_by_id)}]",
        )
        self.cut_constraint_by_id[cut.id] = constraint
        return True


@dataclass(frozen=True, slots=True)
class DddPartialPassengerRecourseResult:
    recourse: DddArcFlowPassengerRecourseResult
    cut: DddPartialPassengerBendersCut | None


@dataclass(slots=True)
class DddPartialPassengerRecourseModel:
    domain: DddPartialPassengerDomain
    recourse: DddArcFlowPassengerRecourseModel

    def evaluate(
        self,
        movement_values: Mapping[str, float],
        core_values: Mapping[str, float],
        *,
        time_limit_seconds: float | None = None,
        tightness_tolerance: float = 1e-5,
    ) -> DddPartialPassengerRecourseResult:
        offsets = self.domain.capacity_offsets(core_values)
        result = self.recourse.evaluate(
            movement_values,
            capacity_rhs_offsets=offsets,
            time_limit_seconds=time_limit_seconds,
            tightness_tolerance=tightness_tolerance,
        )
        cut = None
        if result.optimal and result.objective_value is not None:
            cut = self._dual_cut(
                movement_values,
                core_values,
                result.objective_value,
            )
            if not math.isclose(
                cut.evaluate(movement_values, core_values),
                result.objective_value,
                rel_tol=0.0,
                abs_tol=tightness_tolerance,
            ):
                raise RuntimeError("partial Passenger LP dual cut is not tight")
        return DddPartialPassengerRecourseResult(recourse=result, cut=cut)

    def _dual_cut(
        self,
        movement_values: Mapping[str, float],
        core_values: Mapping[str, float],
        objective: float,
    ) -> DddPartialPassengerBendersCut:
        residual = self.domain.residual_domain
        constant = residual.objective_constant + sum(
            row.right_hand_side
            * self.recourse.demand_constraint_by_id[row.id].Pi
            for row in residual.demand_rows
        )
        movement_coefficients: dict[str, float] = {}
        for variable in residual.variables:
            movement_coefficients[variable.arc_id] = (
                movement_coefficients.get(variable.arc_id, 0.0)
                + variable.upper_bound
                * self.recourse.link_constraint_by_variable_id[variable.id].Pi
            )
        coupling_by_id = {
            item.capacity_row_id: item for item in self.domain.capacity_couplings
        }
        core_coefficients: dict[str, float] = {}
        for row in residual.capacity_rows:
            dual = self.recourse.capacity_constraint_by_id[row.id].Pi
            movement_coefficients[row.arc_id] = (
                movement_coefficients.get(row.arc_id, 0.0)
                + row.movement_coefficient * dual
            )
            for variable_id in coupling_by_id[row.id].core_variable_ids:
                core_coefficients[variable_id] = (
                    core_coefficients.get(variable_id, 0.0) - dual
                )
        return build_ddd_partial_passenger_benders_cut(
            constant=constant,
            movement_coefficients=movement_coefficients,
            core_coefficients=core_coefficients,
            source_objective=objective,
            source_signature=ddd_partial_passenger_point_signature(
                movement_values,
                core_values,
            ),
        )


@dataclass(frozen=True, slots=True)
class DddPartialPassengerModelBuilder:
    passenger_builder: DddArcFlowPassengerModelBuilder = (
        DddArcFlowPassengerModelBuilder()
    )

    def build_master_contribution(
        self,
        *,
        model: gp.Model,
        domain: DddPartialPassengerDomain,
        route_by_arc_id: Mapping[str, gp.Var],
        assignment_domain: EanPassengerAssignmentDomain,
    ) -> DddPartialPassengerMasterContribution:
        core = self.passenger_builder.build_integrated(
            model=model,
            domain=domain.core_domain,
            route_by_arc_id=route_by_arc_id,
            assignment_domain=assignment_domain,
        )
        theta = model.addVar(
            lb=0.0,
            obj=1.0,
            vtype=GRB.CONTINUOUS,
            name="residual_passenger_recourse",
        )
        model.ModelSense = GRB.MINIMIZE
        model.update()
        return DddPartialPassengerMasterContribution(
            domain=domain,
            passenger_core=core,
            residual_theta=theta,
            route_by_arc_id=route_by_arc_id,
            cut_constraint_by_id={},
        )

    def build_residual_recourse(
        self,
        *,
        domain: DddPartialPassengerDomain,
        output_flag: bool = False,
        threads: int | None = None,
    ) -> DddPartialPassengerRecourseModel:
        return DddPartialPassengerRecourseModel(
            domain=domain,
            recourse=self.passenger_builder.build_recourse(
                domain=domain.residual_domain,
                assignment_domain=EanPassengerAssignmentDomain.LP_RELAXATION,
                output_flag=output_flag,
                threads=threads,
            ),
        )


@dataclass(frozen=True, slots=True)
class DddPassengerCoreSelector:
    def build_partition(
        self,
        prepared: DddPreparedArcFlowProblem,
        domain: DddArcFlowPassengerDomain,
        config: DddPassengerCoreConfig,
    ) -> DddPassengerCorePartition:
        config.validate()
        domain.validate(prepared)
        raw_statistics = _group_statistics(prepared, domain)
        scores = _group_scores(raw_statistics, config)
        statistics = tuple(
            DddPassengerGroupStatistics(
                demand_group_id=item.demand_group_id,
                demand_count=item.demand_count,
                unserved_objective_constant=item.unserved_objective_constant,
                ride_candidate_count=item.ride_candidate_count,
                variable_count=item.variable_count,
                passenger_nonzero_count=item.passenger_nonzero_count,
                capacity_row_count=item.capacity_row_count,
                score=scores[item.demand_group_id],
            )
            for item in raw_statistics
        )
        if config.policy is DddPassengerCorePolicy.NONE:
            selected: set[str] = set()
        elif config.policy is DddPassengerCorePolicy.ALL:
            selected = {item.demand_group_id for item in statistics}
        else:
            selected = set()
            used_variables = 0
            used_nonzeros = 0
            for item in sorted(
                statistics,
                key=lambda value: (-value.score, value.demand_group_id),
            ):
                if (
                    used_variables + item.variable_count
                    > config.maximum_variable_count
                    or used_nonzeros + item.passenger_nonzero_count
                    > config.maximum_nonzero_count
                ):
                    continue
                selected.add(item.demand_group_id)
                used_variables += item.variable_count
                used_nonzeros += item.passenger_nonzero_count
        all_groups = {item.demand_group_id for item in statistics}
        core = tuple(sorted(selected))
        residual = tuple(sorted(all_groups - selected))
        by_id = {item.demand_group_id: item for item in statistics}
        incomplete = DddPassengerCorePartition(
            passenger_domain_fingerprint=domain.fingerprint,
            policy=config.policy,
            core_demand_group_ids=core,
            residual_demand_group_ids=residual,
            statistics=statistics,
            core_variable_count=sum(by_id[item].variable_count for item in core),
            residual_variable_count=sum(
                by_id[item].variable_count for item in residual
            ),
            core_nonzero_count=sum(
                by_id[item].passenger_nonzero_count for item in core
            ),
            residual_nonzero_count=sum(
                by_id[item].passenger_nonzero_count for item in residual
            ),
            core_objective_constant=sum(
                by_id[item].unserved_objective_constant for item in core
            ),
            residual_objective_constant=sum(
                by_id[item].unserved_objective_constant for item in residual
            ),
            fingerprint="",
        )
        result = replace(
            incomplete,
            fingerprint=_partition_fingerprint(incomplete),
        )
        result.validate(domain)
        return result


@dataclass(frozen=True, slots=True)
class DddPartialPassengerDomainBuilder:
    selector: DddPassengerCoreSelector = DddPassengerCoreSelector()

    def build(
        self,
        prepared: DddPreparedArcFlowProblem,
        domain: DddArcFlowPassengerDomain,
        config: DddPassengerCoreConfig,
    ) -> DddPartialPassengerDomain:
        partition = self.selector.build_partition(prepared, domain, config)
        core_ids = frozenset(partition.core_demand_group_ids)
        residual_ids = frozenset(partition.residual_demand_group_ids)
        core = build_ddd_arc_flow_passenger_subdomain(
            domain,
            demand_group_ids=core_ids,
            objective_constant=partition.core_objective_constant,
            prepared=prepared,
        )
        residual = build_ddd_arc_flow_passenger_subdomain(
            domain,
            demand_group_ids=residual_ids,
            objective_constant=partition.residual_objective_constant,
            prepared=prepared,
        )
        core_variables = {item.id for item in core.variables}
        residual_variables = {item.id for item in residual.variables}
        result = DddPartialPassengerDomain(
            partition=partition,
            core_domain=core,
            residual_domain=residual,
            capacity_couplings=tuple(
                DddPassengerCapacityCoupling(
                    capacity_row_id=row.id,
                    movement_arc_id=row.arc_id,
                    movement_coefficient=row.movement_coefficient,
                    core_variable_ids=tuple(
                        item for item in row.variable_ids if item in core_variables
                    ),
                    residual_variable_ids=tuple(
                        item for item in row.variable_ids if item in residual_variables
                    ),
                )
                for row in domain.capacity_rows
            ),
        )
        result.validate(prepared, domain)
        return result


def _group_statistics(
    prepared: DddPreparedArcFlowProblem,
    domain: DddArcFlowPassengerDomain,
) -> tuple[DddPassengerGroupStatistics, ...]:
    groups = {
        group.id: group for group in prepared.problem.passenger_build.demand_groups
    }
    definition = ean_passenger_objective_definition(prepared.problem.objective)
    horizon = prepared.problem.artifact.config.horizon_seconds
    variables_by_group: dict[str, list[str]] = {group_id: [] for group_id in groups}
    for variable in domain.variables:
        variables_by_group[variable.demand_group_id].append(variable.id)
    candidates_by_group: dict[str, set[str]] = {
        group_id: set() for group_id in groups
    }
    for flow in domain.flows:
        candidates_by_group[flow.demand_group_id].add(flow.candidate_id)
    equality_nonzeros: dict[str, int] = {group_id: 0 for group_id in groups}
    group_by_variable = {
        variable.id: variable.demand_group_id for variable in domain.variables
    }
    for row in domain.equality_rows:
        for variable_id, _ in row.coefficients:
            equality_nonzeros[group_by_variable[variable_id]] += 1
    demand_nonzeros = {
        row.demand_group_id: len(row.variable_ids) for row in domain.demand_rows
    }
    capacity_nonzeros: dict[str, int] = {group_id: 0 for group_id in groups}
    capacity_rows: dict[str, set[str]] = {group_id: set() for group_id in groups}
    for row in domain.capacity_rows:
        for variable_id in row.variable_ids:
            group_id = group_by_variable[variable_id]
            capacity_nonzeros[group_id] += 1
            capacity_rows[group_id].add(row.id)
    result = []
    for group_id, group in sorted(groups.items()):
        variable_count = len(variables_by_group[group_id])
        result.append(
            DddPassengerGroupStatistics(
                demand_group_id=group_id,
                demand_count=float(group.count),
                unserved_objective_constant=float(group.count)
                * definition.unserved_cost_seconds(
                    release_time_seconds=group.release_time_seconds,
                    horizon_seconds=horizon,
                ),
                ride_candidate_count=len(candidates_by_group[group_id]),
                variable_count=variable_count,
                passenger_nonzero_count=(
                    variable_count
                    + equality_nonzeros[group_id]
                    + demand_nonzeros.get(group_id, 0)
                    + capacity_nonzeros[group_id]
                ),
                capacity_row_count=len(capacity_rows[group_id]),
                score=0.0,
            )
        )
    return tuple(result)


def _group_scores(
    statistics: tuple[DddPassengerGroupStatistics, ...],
    config: DddPassengerCoreConfig,
) -> dict[str, float]:
    if config.policy is DddPassengerCorePolicy.DEMAND_MASS:
        return {item.demand_group_id: item.demand_count for item in statistics}
    if config.policy is DddPassengerCorePolicy.SCARCE_RIDES:
        return {
            item.demand_group_id: (
                1.0 / (1.0 + item.ride_candidate_count)
                + item.unserved_objective_constant
                / max(
                    1.0,
                    max(
                        value.unserved_objective_constant for value in statistics
                    ),
                )
            )
            for item in statistics
        }
    maxima = {
        "demand": max((item.demand_count for item in statistics), default=1.0),
        "penalty": max(
            (item.unserved_objective_constant for item in statistics), default=1.0
        ),
        "bottleneck": max(
            (item.capacity_row_count for item in statistics), default=1
        ),
    }
    return {
        item.demand_group_id: (
            config.demand_weight * item.demand_count / max(1.0, maxima["demand"])
            + config.penalty_weight
            * item.unserved_objective_constant
            / max(1.0, maxima["penalty"])
            + config.scarcity_weight / (1.0 + item.ride_candidate_count)
            + config.bottleneck_weight
            * item.capacity_row_count
            / max(1.0, float(maxima["bottleneck"]))
        )
        for item in statistics
    }


def _partition_fingerprint(partition: DddPassengerCorePartition) -> str:
    payload = asdict(partition)
    payload.pop("fingerprint")
    return sha256(
        json.dumps(payload, separators=(",", ":"), sort_keys=True).encode()
    ).hexdigest()


def build_ddd_partial_passenger_benders_cut(
    *,
    constant: float,
    movement_coefficients: Mapping[str, float],
    core_coefficients: Mapping[str, float],
    source_objective: float,
    source_signature: str,
    kind: str = "partial_lp_dual_optimality",
    zero_tolerance: float = 1e-10,
) -> DddPartialPassengerBendersCut:
    incomplete = DddPartialPassengerBendersCut(
        id="",
        constant=constant,
        movement_coefficients=tuple(
            sorted(
                (item_id, value)
                for item_id, value in movement_coefficients.items()
                if abs(value) > zero_tolerance
            )
        ),
        core_coefficients=tuple(
            sorted(
                (item_id, value)
                for item_id, value in core_coefficients.items()
                if abs(value) > zero_tolerance
            )
        ),
        source_objective=source_objective,
        source_signature=source_signature,
        kind=kind,
    )
    result = replace(incomplete, id=_partial_cut_fingerprint(incomplete))
    result.validate()
    return result


def _partial_cut_fingerprint(cut: DddPartialPassengerBendersCut) -> str:
    payload = asdict(cut)
    payload.pop("id")
    return sha256(
        json.dumps(payload, separators=(",", ":"), sort_keys=True).encode()
    ).hexdigest()


def ddd_partial_passenger_point_signature(
    movement_values: Mapping[str, float],
    core_values: Mapping[str, float],
) -> str:
    payload = {
        "movement": tuple(
            (item_id, round(float(value), 12))
            for item_id, value in sorted(movement_values.items())
        ),
        "core": tuple(
            (item_id, round(float(value), 12))
            for item_id, value in sorted(core_values.items())
        ),
    }
    return sha256(
        json.dumps(payload, separators=(",", ":"), sort_keys=True).encode()
    ).hexdigest()
