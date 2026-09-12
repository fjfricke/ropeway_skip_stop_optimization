from __future__ import annotations

from dataclasses import asdict, dataclass
import math
import resource
import sys
from time import perf_counter

from ortools.sat.python import cp_model

from ..cp_sat_certificate import stable_fingerprint
from ..reservoir_cp_sat_certificate import (
    DddReservoirCpPlan,
    validate_reservoir_cp_plan,
)
from ..reservoir_cp_sat_problem import DddReservoirCpSatProblem
from .certificate import add_line_plan_hint, extract_line_plan
from .config import ReservoirLineConfig, ReservoirLineMode
from .cp_model import build_reservoir_line_model
from .preparation import prepare_line_problem


def _peak_rss_bytes() -> int:
    value = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    return int(value if sys.platform == "darwin" else value * 1024)


class _LineProgress(cp_model.CpSolverSolutionCallback):
    def __init__(self, built, started, events, event_callback):
        super().__init__()
        self.built, self.started, self.events = built, started, events
        self.event_callback = event_callback
        self.error = None

    def on_solution_callback(self):
        try:
            served = (
                0
                if not self.built.passengers.ride_count
                else int(self.value(self.built.passengers.served_expression))
            )
            event = {
                "kind": "incumbent",
                "elapsed_seconds": perf_counter() - self.started,
                "served": served,
                "used_fleet": sum(int(self.value(v)) for v in self.built.used),
                "native_bound": self.best_objective_bound,
            }
            self.events.append(event)
            if self.event_callback is not None:
                self.event_callback(event)
        except Exception as error:
            self.error = error
            self.stop_search()


@dataclass(frozen=True)
class ReservoirLineOptimizer:
    config: ReservoirLineConfig

    def solve(
        self,
        problem: DddReservoirCpSatProblem,
        *,
        reference_plan: DddReservoirCpPlan | None = None,
        event_callback=None,
        log_callback=None,
        build_only: bool = False,
        prepared=None,
        fixed_movement_plan: DddReservoirCpPlan | None = None,
    ):
        started = perf_counter()
        problem.validate()
        self.config.validate(problem.available_fleet_count)
        demand = sum(group.count for group in problem.demand_groups)
        if (
            fixed_movement_plan is not None
            and self.config.mode is not ReservoirLineMode.EXACT_SERVICE
        ):
            raise ValueError("fixed movement passenger optimization requires exact_service")
        if (
            reference_plan is not None
            and fixed_movement_plan is not None
            and reference_plan.trips != fixed_movement_plan.trips
        ):
            raise ValueError("reference and fixed line movement differ")
        seed_plan = reference_plan or fixed_movement_plan
        reference_metrics = None
        if seed_plan is not None:
            reference_metrics = validate_reservoir_cp_plan(problem, seed_plan)

        before = perf_counter()
        prepared = prepared or prepare_line_problem(problem, self.config)
        if prepared.problem_fingerprint != problem.fingerprint:
            raise ValueError("prepared line problem has a different physical domain")
        preparation_seconds = perf_counter() - before
        before = perf_counter()
        built = build_reservoir_line_model(problem, prepared, self.config)
        model_build_seconds = perf_counter() - before
        reference_status, reference_reason = "absent", None
        if seed_plan is not None:
            try:
                add_line_plan_hint(
                    problem,
                    prepared,
                    built,
                    seed_plan,
                    fix_movement=fixed_movement_plan is not None,
                )
                reference_status = (
                    "fixed_movement" if fixed_movement_plan is not None else "hinted"
                )
            except ValueError as error:
                reference_status, reference_reason = "not_representable", str(error)

        base = {
            "schema": "single_use_reservoir_line_result_v1",
            "problem_fingerprint": problem.fingerprint,
            "model_fingerprint": stable_fingerprint(
                {
                    "built": built.fingerprint,
                    "fixed_movement": (
                        None
                        if fixed_movement_plan is None
                        else [asdict(trip) for trip in fixed_movement_plan.trips]
                    ),
                }
            ),
            "prepared_fingerprint": prepared.model_fingerprint,
            "proof_scope": (
                "FIXED_LINE_MOVEMENT"
                if fixed_movement_plan is not None
                else "RESERVOIR_SINGLE_USE_FIXED_LINES_NO_WAIT"
            ),
            "config": asdict(self.config),
            "model_stats": {
                **built.stats,
                "constraints_after_seed_or_fix": len(built.model.proto.constraints),
            },
            "preparation_seconds": preparation_seconds,
            "model_build_seconds": model_build_seconds,
            "reference_status": reference_status,
            "reference_reason": reference_reason,
            "reference_metrics": None if reference_metrics is None else asdict(reference_metrics),
        }
        if build_only:
            return {
                **base,
                "solver_status": "NOT_RUN",
                "termination_reason": "BUILD_ONLY",
                "total_wall_seconds": perf_counter() - started,
                "peak_rss_bytes": _peak_rss_bytes(),
            }, None

        solver = cp_model.CpSolver()
        solver.parameters.max_time_in_seconds = self.config.time_limit_seconds
        solver.parameters.num_search_workers = self.config.workers
        solver.parameters.random_seed = self.config.seed
        solver.parameters.max_memory_in_mb = int(self.config.memory_limit_gib * 1024)
        solver.parameters.log_search_progress = self.config.log_search_progress
        solver.parameters.cp_model_presolve = self.config.presolve
        if log_callback is not None:
            solver.log_callback = log_callback
            solver.parameters.log_to_stdout = False
        events = []
        callback = _LineProgress(built, started, events, event_callback)
        before = perf_counter()
        status_code = solver.solve(built.model, callback)
        solve_seconds = perf_counter() - before
        if callback.error is not None:
            raise RuntimeError("reservoir line progress callback failed") from callback.error
        status = solver.status_name(status_code)
        plan, metrics, movement_metrics, validation_seconds = None, None, None, 0.0
        if status_code in (cp_model.FEASIBLE, cp_model.OPTIMAL):
            before = perf_counter()
            exact = self.config.mode is not ReservoirLineMode.OPTIMISTIC_SERVICE
            plan = extract_line_plan(
                problem, prepared, built, solver.value, include_rides=exact
            )
            movement_metrics = validate_reservoir_cp_plan(problem, plan)
            metrics = movement_metrics if exact else None
            validation_seconds = perf_counter() - before
            if self.config.mode is ReservoirLineMode.EXACT_SERVICE:
                native_served = int(solver.value(built.passengers.served_expression))
                if native_served != metrics.served:
                    raise RuntimeError("line objective differs from independent passenger validation")
        elif status_code == cp_model.INFEASIBLE and reference_status in (
            "hinted",
            "fixed_movement",
        ):
            raise RuntimeError("line model rejects its independently valid represented reference")

        native_bound = None
        served_upper_bound = None
        unserved_lower_bound = None
        if (
            self.config.mode is not ReservoirLineMode.FEASIBILITY
            and status_code in (cp_model.FEASIBLE, cp_model.OPTIMAL)
        ):
            raw = float(solver.best_objective_bound)
            if math.isfinite(raw):
                native_bound = raw
                objective_upper = math.ceil(math.nextafter(raw, math.inf))
                scale = built.stats["objective_served_scale"]
                served_upper = (objective_upper + prepared.maximum_cabins) // scale
                served_upper_bound = min(demand, served_upper)
                unserved_lower_bound = max(0, demand - served_upper)
        result = {
            **base,
            "solver_status": status,
            "termination_reason": (
                "OPTIMAL"
                if status_code == cp_model.OPTIMAL
                else "INFEASIBLE"
                if status_code == cp_model.INFEASIBLE
                else "TIME_LIMIT"
            ),
            "proven_optimal": status_code == cp_model.OPTIMAL,
            "validated_served": None if metrics is None else metrics.served,
            "validated_unserved": None if metrics is None else metrics.unserved,
            "used_fleet": None if metrics is None else metrics.used_fleet,
            "physical_plan_metrics": (
                None if movement_metrics is None else asdict(movement_metrics)
            ),
            "native_optimistic_served": (
                int(solver.value(built.passengers.served_expression))
                if status_code in (cp_model.FEASIBLE, cp_model.OPTIMAL)
                and self.config.mode is ReservoirLineMode.OPTIMISTIC_SERVICE
                else None
            ),
            "native_objective_upper_bound_raw": native_bound,
            "native_served_upper_bound": served_upper_bound,
            "line_domain_unserved_lower_bound": unserved_lower_bound,
            "metrics": None if metrics is None else asdict(metrics),
            "plan": None if plan is None else asdict(plan),
            "events": events,
            "response_stats": solver.response_stats(),
            "solve_seconds": solve_seconds,
            "validation_seconds": validation_seconds,
            "total_wall_seconds": perf_counter() - started,
            "peak_rss_bytes": _peak_rss_bytes(),
        }
        return result, plan
