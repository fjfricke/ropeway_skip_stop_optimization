from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
import math
from time import perf_counter
from typing import Callable

import gurobipy as gp
from gurobipy import GRB

from ropeway_skip_stop_optimization.optimization.ddd.arc_flow_movement_master import (
    DddArcFlowMovementMasterBuilder,
)
from ropeway_skip_stop_optimization.optimization.ddd.arc_flow_passenger_domain import (
    DddArcFlowPassengerDomainBuilder,
)
from ropeway_skip_stop_optimization.optimization.ddd.arc_flow_passenger_model import (
    DddArcFlowPassengerModelBuilder,
)
from ropeway_skip_stop_optimization.optimization.ddd.arc_flow_preparation import (
    DddPreparedArcFlowProblem,
)
from ropeway_skip_stop_optimization.optimization.ddd.passenger_benders_cuts import (
    DddPassengerBendersCut,
    DddPassengerBendersCutPool,
)
from ropeway_skip_stop_optimization.optimization.ddd.reference import (
    DddReferenceSolution,
    DddReferenceTrajectory,
    validate_ddd_reference_solution,
)
from ropeway_skip_stop_optimization.optimization.ean.optimizers.fixed_movement_passenger_model import (
    EanPassengerAssignmentDomain,
)


class DddOuterLoopLpBendersStatus(StrEnum):
    INTEGER_OPTIMAL = "integer_optimal"
    PROJECTED_LP_OPTIMAL_WITH_INTEGER_GAP = (
        "projected_lp_optimal_with_integer_gap"
    )
    PROJECTED_FULL_LP_OPTIMAL = "projected_full_lp_optimal"
    TIME_LIMIT_WITH_CERTIFIED_INTERVAL = "time_limit_with_certified_interval"
    ITERATION_LIMIT_WITH_CERTIFIED_INTERVAL = (
        "iteration_limit_with_certified_interval"
    )
    MOVEMENT_INFEASIBLE = "movement_infeasible"
    UNKNOWN_NO_INCUMBENT = "unknown_no_incumbent"
    INTERNAL_CERTIFICATE_ERROR = "internal_certificate_error"


@dataclass(frozen=True, slots=True)
class DddOuterLoopLpBendersConfig:
    time_limit_seconds: float = 600.0
    max_iterations: int = 100
    threads: int | None = None
    seed: int = 0
    master_mip_focus: int = 2
    output_flag: bool = False
    cut_violation_tolerance: float = 1e-5
    certificate_tolerance: float = 1e-5
    relax_movement: bool = False

    def validate(self) -> None:
        if not math.isfinite(self.time_limit_seconds) or self.time_limit_seconds <= 0:
            raise ValueError("outer Benders time limit must be positive")
        if self.max_iterations <= 0:
            raise ValueError("outer Benders iteration limit must be positive")
        if self.threads is not None and self.threads <= 0:
            raise ValueError("outer Benders threads must be positive")
        if self.seed < 0 or self.master_mip_focus not in range(4):
            raise ValueError("outer Benders solver controls are invalid")
        if self.cut_violation_tolerance <= 0 or self.certificate_tolerance <= 0:
            raise ValueError("outer Benders tolerances must be positive")


@dataclass(frozen=True, slots=True)
class DddOuterLoopLpBendersIteration:
    iteration: int
    master_status: int
    master_objective: float | None
    master_bound: float | None
    theta_value: float | None
    passenger_lp_objective: float | None
    passenger_ip_objective: float | None
    cut_violation: float | None
    cut_added: bool
    cut_count: int
    certified_lower_bound: float
    validated_upper_bound: float | None
    relative_gap: float | None
    elapsed_seconds: float


@dataclass(frozen=True, slots=True)
class DddOuterLoopLpBendersProgress:
    phase: str
    iteration: int
    cut_count: int
    certified_lower_bound: float
    validated_upper_bound: float | None
    elapsed_seconds: float
    remaining_seconds: float


DddOuterLoopLpBendersProgressHook = Callable[
    [DddOuterLoopLpBendersProgress], None
]


@dataclass(frozen=True, slots=True)
class DddOuterLoopLpBendersResult:
    status: DddOuterLoopLpBendersStatus
    problem_fingerprint: str
    passenger_domain_fingerprint: str
    certified_lower_bound: float
    validated_upper_bound: float | None
    relative_gap: float | None
    best_solution: DddReferenceSolution | None
    projected_lp_certified: bool
    cut_count: int
    cuts: tuple[DddPassengerBendersCut, ...]
    iterations: tuple[DddOuterLoopLpBendersIteration, ...]
    movement_variable_count: int
    movement_constraint_count: int
    resource_row_count: int
    master_constraint_count: int
    passenger_variable_count: int
    network_build_seconds: float
    passenger_domain_build_seconds: float
    master_build_seconds: float
    passenger_lp_seconds: float
    passenger_ip_seconds: float
    total_seconds: float
    detail: str | None = None


@dataclass(slots=True)
class DddOuterLoopLpBendersSolver:
    config: DddOuterLoopLpBendersConfig = DddOuterLoopLpBendersConfig()

    def solve(
        self,
        prepared: DddPreparedArcFlowProblem,
        *,
        seed_trajectories: tuple[DddReferenceTrajectory, ...] = (),
        initial_cuts: tuple[DddPassengerBendersCut, ...] = (),
        progress_hook: DddOuterLoopLpBendersProgressHook | None = None,
    ) -> DddOuterLoopLpBendersResult:
        self.config.validate()
        prepared.validate()
        started = perf_counter()
        domain_started = perf_counter()
        passenger_domain = DddArcFlowPassengerDomainBuilder().build(prepared)
        domain_seconds = perf_counter() - domain_started
        model_started = perf_counter()
        model = gp.Model("ddd_outer_loop_lp_benders")
        model.Params.OutputFlag = int(self.config.output_flag)
        model.Params.Seed = self.config.seed
        model.Params.MIPFocus = self.config.master_mip_focus
        if self.config.threads is not None:
            model.Params.Threads = self.config.threads
        movement_master = DddArcFlowMovementMasterBuilder().build(
            model=model,
            prepared=prepared,
            variable_type=(
                GRB.CONTINUOUS if self.config.relax_movement else GRB.BINARY
            ),
        )
        theta = model.addVar(
            lb=prepared.problem.objective_floor,
            name="passenger_recourse",
        )
        model.setObjective(theta, GRB.MINIMIZE)
        movement_master.apply_seed(seed_trajectories)
        model.update()
        master_build_seconds = perf_counter() - model_started
        recourse_builder = DddArcFlowPassengerModelBuilder()
        lp_recourse = recourse_builder.build_recourse(
            domain=passenger_domain,
            assignment_domain=EanPassengerAssignmentDomain.LP_RELAXATION,
            output_flag=self.config.output_flag,
            threads=self.config.threads,
        )
        ip_recourse = (
            None
            if self.config.relax_movement
            else recourse_builder.build_recourse(
                domain=passenger_domain,
                assignment_domain=EanPassengerAssignmentDomain.INTEGER,
                output_flag=self.config.output_flag,
                threads=self.config.threads,
            )
        )
        cut_pool = DddPassengerBendersCutPool(
            violation_tolerance=self.config.cut_violation_tolerance
        )
        for cut in initial_cuts:
            if not cut_pool.add(cut):
                continue
            model.addConstr(
                theta
                >= cut.constant
                + gp.quicksum(
                    coefficient * movement_master.route_by_arc_id[arc_id]
                    for arc_id, coefficient in cut.coefficients
                ),
                name=f"passenger_benders[{len(cut_pool.cuts) - 1}]",
            )
        model.update()
        iterations: list[DddOuterLoopLpBendersIteration] = []
        lower_bound = prepared.problem.objective_floor
        upper_bound: float | None = None
        best_solution: DddReferenceSolution | None = None
        lp_seconds = 0.0
        ip_seconds = 0.0
        projected_certified = False
        status = DddOuterLoopLpBendersStatus.UNKNOWN_NO_INCUMBENT
        detail: str | None = None

        for iteration_index in range(1, self.config.max_iterations + 1):
            remaining = self.config.time_limit_seconds - (perf_counter() - started)
            if remaining <= 0:
                status = (
                    DddOuterLoopLpBendersStatus.TIME_LIMIT_WITH_CERTIFIED_INTERVAL
                )
                break
            self._publish(
                progress_hook,
                "master",
                iteration_index,
                len(cut_pool.cuts),
                lower_bound,
                upper_bound,
                started,
            )
            model.Params.TimeLimit = max(0.001, remaining)
            model.optimize()
            master_bound = _finite_value(model.ObjBound)
            if master_bound is not None:
                lower_bound = max(lower_bound, master_bound)
            if model.Status == GRB.INFEASIBLE:
                status = DddOuterLoopLpBendersStatus.MOVEMENT_INFEASIBLE
                break
            if int(model.SolCount) <= 0:
                status = DddOuterLoopLpBendersStatus.UNKNOWN_NO_INCUMBENT
                break
            master_objective = float(model.ObjVal)
            theta_value = float(theta.X)
            movement_values = {
                arc_id: float(variable.X)
                for arc_id, variable in movement_master.route_by_arc_id.items()
            }
            movement_solution = None
            if not self.config.relax_movement:
                try:
                    movement_solution = movement_master.extract_solution(
                        boundary_occurrences=(
                            prepared.problem.boundary_context.resource_occurrences
                        )
                    )
                    validate_ddd_reference_solution(
                        prepared.movement,
                        movement_solution,
                    )
                except (RuntimeError, ValueError) as error:
                    status = DddOuterLoopLpBendersStatus.INTERNAL_CERTIFICATE_ERROR
                    detail = str(error)
                    break

            remaining = self.config.time_limit_seconds - (perf_counter() - started)
            if remaining <= 0:
                status = (
                    DddOuterLoopLpBendersStatus.TIME_LIMIT_WITH_CERTIFIED_INTERVAL
                )
                break
            self._publish(
                progress_hook,
                "passenger_lp",
                iteration_index,
                len(cut_pool.cuts),
                lower_bound,
                upper_bound,
                started,
            )
            lp = lp_recourse.evaluate(
                movement_values,
                time_limit_seconds=remaining,
                tightness_tolerance=self.config.certificate_tolerance,
            )
            lp_seconds += lp.solve_seconds
            if not lp.optimal or lp.objective_value is None or lp.benders_cut is None:
                status = (
                    DddOuterLoopLpBendersStatus.TIME_LIMIT_WITH_CERTIFIED_INTERVAL
                )
                break

            remaining = self.config.time_limit_seconds - (perf_counter() - started)
            if remaining <= 0:
                status = (
                    DddOuterLoopLpBendersStatus.TIME_LIMIT_WITH_CERTIFIED_INTERVAL
                )
                break
            integer_objective = None
            if not self.config.relax_movement:
                assert ip_recourse is not None
                self._publish(
                    progress_hook,
                    "passenger_ip",
                    iteration_index,
                    len(cut_pool.cuts),
                    lower_bound,
                    upper_bound,
                    started,
                )
                integer = ip_recourse.evaluate(
                    movement_values,
                    time_limit_seconds=remaining,
                )
                ip_seconds += integer.solve_seconds
                integer_objective = integer.objective_value
                if integer.objective_value is not None and (
                    upper_bound is None
                    or integer.objective_value
                    < upper_bound - self.config.certificate_tolerance
                ):
                    upper_bound = integer.objective_value
                    best_solution = movement_solution

            violation = lp.benders_cut.violation(
                movement_values,
                theta_value,
            )
            cut_added = cut_pool.add_if_violated(
                lp.benders_cut,
                movement_values,
                theta_value,
            )
            if cut_added:
                model.addConstr(
                    theta
                    >= lp.benders_cut.constant
                    + gp.quicksum(
                        coefficient
                        * movement_master.route_by_arc_id[arc_id]
                        for arc_id, coefficient in lp.benders_cut.coefficients
                    ),
                    name=f"passenger_benders[{len(cut_pool.cuts) - 1}]",
                )
                model.update()
            elif violation > self.config.cut_violation_tolerance:
                status = DddOuterLoopLpBendersStatus.INTERNAL_CERTIFICATE_ERROR
                detail = "violated Passenger cut was already present"

            iterations.append(
                DddOuterLoopLpBendersIteration(
                    iteration=iteration_index,
                    master_status=int(model.Status),
                    master_objective=master_objective,
                    master_bound=master_bound,
                    theta_value=theta_value,
                    passenger_lp_objective=lp.objective_value,
                    passenger_ip_objective=integer_objective,
                    cut_violation=violation,
                    cut_added=cut_added,
                    cut_count=len(cut_pool.cuts),
                    certified_lower_bound=lower_bound,
                    validated_upper_bound=upper_bound,
                    relative_gap=_relative_gap(lower_bound, upper_bound),
                    elapsed_seconds=perf_counter() - started,
                )
            )
            if status is DddOuterLoopLpBendersStatus.INTERNAL_CERTIFICATE_ERROR:
                break
            if not cut_added and model.Status == GRB.OPTIMAL:
                lower_bound = max(lower_bound, lp.objective_value)
                projected_certified = True
                if self.config.relax_movement:
                    status = DddOuterLoopLpBendersStatus.PROJECTED_FULL_LP_OPTIMAL
                elif (
                    upper_bound is not None
                    and upper_bound
                    <= lower_bound + self.config.certificate_tolerance
                ):
                    status = DddOuterLoopLpBendersStatus.INTEGER_OPTIMAL
                else:
                    status = (
                        DddOuterLoopLpBendersStatus.PROJECTED_LP_OPTIMAL_WITH_INTEGER_GAP
                    )
                break
        else:
            status = (
                DddOuterLoopLpBendersStatus.ITERATION_LIMIT_WITH_CERTIFIED_INTERVAL
            )

        if (
            upper_bound is not None
            and lower_bound > upper_bound + self.config.certificate_tolerance
        ):
            status = DddOuterLoopLpBendersStatus.INTERNAL_CERTIFICATE_ERROR
            detail = "outer Benders lower bound exceeds integer upper bound"
        self._publish(
            progress_hook,
            "complete",
            len(iterations),
            len(cut_pool.cuts),
            lower_bound,
            upper_bound,
            started,
        )
        return DddOuterLoopLpBendersResult(
            status=status,
            problem_fingerprint=prepared.problem.fingerprint,
            passenger_domain_fingerprint=passenger_domain.fingerprint,
            certified_lower_bound=lower_bound,
            validated_upper_bound=upper_bound,
            relative_gap=_relative_gap(lower_bound, upper_bound),
            best_solution=best_solution,
            projected_lp_certified=projected_certified,
            cut_count=len(cut_pool.cuts),
            cuts=cut_pool.cuts,
            iterations=tuple(iterations),
            movement_variable_count=movement_master.movement_variable_count,
            movement_constraint_count=movement_master.movement_constraint_count,
            resource_row_count=movement_master.resource_row_count,
            master_constraint_count=int(model.NumConstrs),
            passenger_variable_count=len(passenger_domain.variables),
            network_build_seconds=prepared.network_build_seconds,
            passenger_domain_build_seconds=domain_seconds,
            master_build_seconds=master_build_seconds,
            passenger_lp_seconds=lp_seconds,
            passenger_ip_seconds=ip_seconds,
            total_seconds=perf_counter() - started,
            detail=detail,
        )

    def _publish(
        self,
        hook: DddOuterLoopLpBendersProgressHook | None,
        phase: str,
        iteration: int,
        cut_count: int,
        lower_bound: float,
        upper_bound: float | None,
        started: float,
    ) -> None:
        if hook is None:
            return
        elapsed = perf_counter() - started
        hook(
            DddOuterLoopLpBendersProgress(
                phase=phase,
                iteration=iteration,
                cut_count=cut_count,
                certified_lower_bound=lower_bound,
                validated_upper_bound=upper_bound,
                elapsed_seconds=elapsed,
                remaining_seconds=max(
                    0.0,
                    self.config.time_limit_seconds - elapsed,
                ),
            )
        )


def _relative_gap(lower: float, upper: float | None) -> float | None:
    if upper is None:
        return None
    return max(0.0, upper - lower) / max(1.0, abs(upper))


def _finite_value(value: float) -> float | None:
    return value if math.isfinite(value) and abs(value) < GRB.INFINITY / 2 else None
