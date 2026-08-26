from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from hashlib import sha256
import math
from time import perf_counter
from typing import Callable

import gurobipy as gp
from gurobipy import GRB

from ropeway_skip_stop_optimization.optimization.ddd.arc_flow_movement_master import (
    DddArcFlowMovementMasterBuilder,
)
from ropeway_skip_stop_optimization.optimization.ddd.arc_flow_preparation import (
    DddArcFlowProblemPreparer,
    DddPreparedArcFlowProblem,
)
from ropeway_skip_stop_optimization.optimization.ddd.fixed_k import (
    DddFixedKTrajectoryProblem,
)
from ropeway_skip_stop_optimization.optimization.ddd.reference import (
    DddReferenceSolution,
    DddReferenceTrajectory,
    validate_ddd_reference_solution,
)


class DddFixedKMovementArcFlowStatus(StrEnum):
    FEASIBLE = "feasible"
    INFEASIBLE = "infeasible"
    UNKNOWN = "unknown"
    INTERNAL_VALIDATION_ERROR = "internal_validation_error"


class DddMovementArcFlowObjectiveMode(StrEnum):
    FEASIBILITY = "feasibility"
    DETERMINISTIC_DIVERSIFICATION = "deterministic_diversification"


@dataclass(frozen=True, slots=True)
class DddFixedKMovementArcFlowConfig:
    time_limit_seconds: float = 600.0
    threads: int | None = None
    seed: int = 0
    mip_focus: int = 1
    output_flag: bool = False
    objective_mode: DddMovementArcFlowObjectiveMode = (
        DddMovementArcFlowObjectiveMode.FEASIBILITY
    )

    def validate(self) -> None:
        if not math.isfinite(self.time_limit_seconds) or self.time_limit_seconds <= 0:
            raise ValueError("Movement arc-flow time limit must be positive")
        if self.threads is not None and self.threads <= 0:
            raise ValueError("Movement arc-flow threads must be positive")
        if self.seed < 0 or self.mip_focus not in range(4):
            raise ValueError("Movement arc-flow solver controls are invalid")
        if not isinstance(self.objective_mode, DddMovementArcFlowObjectiveMode):
            raise ValueError("Movement arc-flow objective mode is invalid")


@dataclass(frozen=True, slots=True)
class DddFixedKMovementArcFlowProgress:
    phase: str
    elapsed_seconds: float
    node_count: float
    solution_count: int
    movement_variable_count: int
    movement_constraint_count: int
    resource_row_count: int
    remaining_seconds: float


@dataclass(frozen=True, slots=True)
class DddFixedKMovementArcFlowResult:
    status: DddFixedKMovementArcFlowStatus
    problem_fingerprint: str
    solution: DddReferenceSolution | None
    solver_status: int
    solution_count: int
    node_count: float
    movement_variable_count: int
    movement_constraint_count: int
    resource_row_count: int
    linear_constraint_count: int
    network_build_seconds: float
    model_build_seconds: float
    solve_seconds: float
    total_seconds: float
    time_to_first_incumbent_seconds: float | None
    root_node_reached: bool
    detail: str | None = None


DddFixedKMovementArcFlowProgressHook = Callable[
    [DddFixedKMovementArcFlowProgress], None
]


@dataclass(slots=True)
class DddFixedKMovementArcFlowOptimizer:
    config: DddFixedKMovementArcFlowConfig = DddFixedKMovementArcFlowConfig()

    def solve(
        self,
        problem: DddFixedKTrajectoryProblem,
        *,
        seed_trajectories: tuple[DddReferenceTrajectory, ...] = (),
        progress_hook: DddFixedKMovementArcFlowProgressHook | None = None,
    ) -> DddFixedKMovementArcFlowResult:
        self.config.validate()
        started = perf_counter()

        def preparation_phase(phase: str) -> None:
            if progress_hook is not None:
                elapsed = perf_counter() - started
                progress_hook(
                    DddFixedKMovementArcFlowProgress(
                        phase=phase,
                        elapsed_seconds=elapsed,
                        node_count=0.0,
                        solution_count=0,
                        movement_variable_count=0,
                        movement_constraint_count=0,
                        resource_row_count=0,
                        remaining_seconds=max(
                            0.0,
                            self.config.time_limit_seconds - elapsed,
                        ),
                    )
                )

        prepared = DddArcFlowProblemPreparer().build(
            problem,
            phase_hook=preparation_phase,
        )
        return self.solve_prepared(
            prepared,
            seed_trajectories=seed_trajectories,
            progress_hook=progress_hook,
            total_started=started,
        )

    def solve_prepared(
        self,
        prepared: DddPreparedArcFlowProblem,
        *,
        seed_trajectories: tuple[DddReferenceTrajectory, ...] = (),
        progress_hook: DddFixedKMovementArcFlowProgressHook | None = None,
        total_started: float | None = None,
    ) -> DddFixedKMovementArcFlowResult:
        self.config.validate()
        prepared.validate()
        started = perf_counter() if total_started is None else total_started

        model_started = perf_counter()
        model = gp.Model("ddd_fixed_k_movement_arc_flow")
        model.Params.OutputFlag = int(self.config.output_flag)
        model.Params.Seed = self.config.seed
        model.Params.MIPFocus = self.config.mip_focus
        if self.config.threads is not None:
            model.Params.Threads = self.config.threads
        model.ModelSense = GRB.MINIMIZE
        master = DddArcFlowMovementMasterBuilder().build(
            model=model,
            prepared=prepared,
        )
        model.setObjective(
            gp.quicksum(
                self._objective_coefficient(arc_id) * variable
                for arc_id, variable in master.route_by_arc_id.items()
            ),
            GRB.MINIMIZE,
        )
        master.apply_seed(seed_trajectories)
        model.update()
        model_build_seconds = perf_counter() - model_started
        self._publish(
            progress_hook,
            phase="mip_solve",
            started=started,
            master=master,
        )

        first_incumbent: float | None = None
        root_node_reached = False
        last_sample = -math.inf

        def callback(callback_model: gp.Model, where: int) -> None:
            nonlocal first_incumbent, root_node_reached, last_sample
            if where == GRB.Callback.MIPSOL and first_incumbent is None:
                first_incumbent = perf_counter() - started
            if where == GRB.Callback.MIPNODE:
                root_node_reached = True
            if progress_hook is None or where not in {
                GRB.Callback.PRESOLVE,
                GRB.Callback.SIMPLEX,
                GRB.Callback.BARRIER,
                GRB.Callback.MIP,
                GRB.Callback.MIPNODE,
            }:
                return
            elapsed = perf_counter() - started
            if elapsed - last_sample < 1.0:
                return
            last_sample = elapsed
            phase = {
                GRB.Callback.PRESOLVE: "presolve",
                GRB.Callback.SIMPLEX: "root_simplex",
                GRB.Callback.BARRIER: "root_barrier",
                GRB.Callback.MIP: "branch_and_bound",
                GRB.Callback.MIPNODE: "root_node",
            }[where]
            if where == GRB.Callback.MIP:
                nodes = float(callback_model.cbGet(GRB.Callback.MIP_NODCNT))
                solutions = int(callback_model.cbGet(GRB.Callback.MIP_SOLCNT))
            elif where == GRB.Callback.MIPNODE:
                nodes = float(callback_model.cbGet(GRB.Callback.MIPNODE_NODCNT))
                solutions = int(callback_model.cbGet(GRB.Callback.MIPNODE_SOLCNT))
                if nodes > 0:
                    phase = "branch_and_bound"
            else:
                nodes = 0.0
                solutions = 0
            progress_hook(
                DddFixedKMovementArcFlowProgress(
                    phase=phase,
                    elapsed_seconds=elapsed,
                    node_count=nodes,
                    solution_count=solutions,
                    movement_variable_count=master.movement_variable_count,
                    movement_constraint_count=master.movement_constraint_count,
                    resource_row_count=master.resource_row_count,
                    remaining_seconds=max(
                        0.0,
                        self.config.time_limit_seconds - elapsed,
                    ),
                )
            )

        solve_started = perf_counter()
        model.Params.TimeLimit = max(
            0.001,
            self.config.time_limit_seconds - (solve_started - started),
        )
        model.optimize(callback)
        solve_seconds = perf_counter() - solve_started

        solution: DddReferenceSolution | None = None
        detail: str | None = None
        if int(model.SolCount) > 0:
            try:
                solution = master.extract_solution(
                    boundary_occurrences=(
                        prepared.problem.boundary_context.resource_occurrences
                    ),
                )
                validate_ddd_reference_solution(prepared.movement, solution)
            except (RuntimeError, ValueError) as error:
                status = DddFixedKMovementArcFlowStatus.INTERNAL_VALIDATION_ERROR
                detail = str(error)
                solution = None
            else:
                status = DddFixedKMovementArcFlowStatus.FEASIBLE
        elif model.Status == GRB.INFEASIBLE:
            status = DddFixedKMovementArcFlowStatus.INFEASIBLE
        else:
            status = DddFixedKMovementArcFlowStatus.UNKNOWN

        self._publish(
            progress_hook,
            phase="solve_complete",
            started=started,
            master=master,
            node_count=float(model.NodeCount),
            solution_count=int(model.SolCount),
        )
        return DddFixedKMovementArcFlowResult(
            status=status,
            problem_fingerprint=prepared.problem.fingerprint,
            solution=solution,
            solver_status=int(model.Status),
            solution_count=int(model.SolCount),
            node_count=float(model.NodeCount),
            movement_variable_count=master.movement_variable_count,
            movement_constraint_count=master.movement_constraint_count,
            resource_row_count=master.resource_row_count,
            linear_constraint_count=int(model.NumConstrs),
            network_build_seconds=prepared.network_build_seconds,
            model_build_seconds=model_build_seconds,
            solve_seconds=solve_seconds,
            total_seconds=perf_counter() - started,
            time_to_first_incumbent_seconds=first_incumbent,
            root_node_reached=root_node_reached,
            detail=detail,
        )

    def _objective_coefficient(self, arc_id: str) -> float:
        if self.config.objective_mode is DddMovementArcFlowObjectiveMode.FEASIBILITY:
            return 0.0
        digest = sha256(f"{self.config.seed}:{arc_id}".encode()).digest()
        return (int.from_bytes(digest[:4], "big") + 1) / (2**32)

    def _publish(
        self,
        hook: DddFixedKMovementArcFlowProgressHook | None,
        *,
        phase: str,
        started: float,
        master,
        node_count: float = 0.0,
        solution_count: int = 0,
    ) -> None:
        if hook is None:
            return
        elapsed = perf_counter() - started
        hook(
            DddFixedKMovementArcFlowProgress(
                phase=phase,
                elapsed_seconds=elapsed,
                node_count=node_count,
                solution_count=solution_count,
                movement_variable_count=master.movement_variable_count,
                movement_constraint_count=master.movement_constraint_count,
                resource_row_count=master.resource_row_count,
                remaining_seconds=max(
                    0.0,
                    self.config.time_limit_seconds - elapsed,
                ),
            )
        )
