from __future__ import annotations

from dataclasses import dataclass, field
from collections import defaultdict
import math
from pathlib import Path
from time import perf_counter
from typing import Callable

from ortools.sat.python import cp_model

from .cp_formulation import formulation_identity, DddCpFormulationConfig, prepare_cp_structure, apply_cp_temporal
from .cp_hint_completion import complete_cp_hints

from .cp_sat_certificate import (
    FORMULATION_VERSION,
    DddCpSatIncumbent,
    stable_fingerprint,
    validate_ddd_cp_sat_domain,
    validate_ddd_cp_sat_incumbent,
    solution_from_cp_sat_payload,
    write_ddd_cp_sat_checkpoint,
)
from .cp_sat_movement import DddCpSatMovementModel, build_ddd_cp_sat_movement
from .cp_sat_passenger import (
    DddCpSatCostEncoding,
    DddCpSatPassengerModel,
    build_ddd_cp_sat_passengers,
)
from .fixed_k import DddFixedKTrajectoryProblem
from .reference import DddReferenceSolution
from .route_topology import unique_stop_route_option
from .time_ticks import DDD_TIME_TICKS_PER_SECOND, ddd_seconds_to_tick


@dataclass(frozen=True)
class DddIntegratedCpSatConfig:
    total_time_limit_seconds: float = 60.0
    num_workers: int = 1
    seed: int = 0
    cost_encoding: DddCpSatCostEncoding = DddCpSatCostEncoding.PRODUCT
    checkpoint_path: Path | None = None
    checkpoint_interval_seconds: float = 30.0
    log_search_progress: bool = False
    formulation: DddCpFormulationConfig = field(default_factory=DddCpFormulationConfig)

    def validate(self) -> None:
        self.formulation.validate()
        if (
            not math.isfinite(self.total_time_limit_seconds)
            or self.total_time_limit_seconds <= 0
        ):
            raise ValueError("CP-SAT time budget must be finite and positive")
        if (
            type(self.num_workers) is not int
            or self.num_workers <= 0
            or type(self.seed) is not int
            or self.seed < 0
        ):
            raise ValueError("CP-SAT workers/seed are invalid")
        if not isinstance(self.cost_encoding, DddCpSatCostEncoding):
            raise ValueError("CP-SAT cost encoding is invalid")
        if (
            not math.isfinite(self.checkpoint_interval_seconds)
            or self.checkpoint_interval_seconds <= 0
        ):
            raise ValueError("CP-SAT checkpoint interval must be positive")


@dataclass(frozen=True)
class DddIntegratedCpSatModel:
    movement: DddCpSatMovementModel
    passengers: DddCpSatPassengerModel
    domain_manifest: dict
    proof_scope: str
    model_fingerprint: str
    stats: dict[str, int]


def _movement_values(
    problem: DddFixedKTrajectoryProblem,
    built: DddCpSatMovementModel,
    solution: DddReferenceSolution,
) -> tuple[dict[int, int], dict[tuple[int, int], int]]:
    """Complete values for visible movement variables, including the terminal tail."""
    by_cabin = {t.cabin_id: t for t in solution.trajectories}
    movement = problem.resolved_trajectory_problem.structural_movement_problem
    values, alight_times = {}, {}
    for cabin, states in built.states_by_cabin.items():
        trajectory = by_cabin[cabin]
        visits = trajectory.visits
        terminal = ddd_seconds_to_tick(visits[-1].next_switch_time_seconds)
        for index, state in enumerate(states):
            active = index < len(visits)
            time = (
                ddd_seconds_to_tick(visits[index].switch_time_seconds)
                if active
                else terminal
            )
            values[built.time_by_cabin[cabin][index].index] = time
            values[built.active_by_cabin[cabin][index].index] = int(active)
            if index == len(states) - 1:
                continue
            values[built.wait_steps_by_key[cabin, index].index] = (
                ddd_seconds_to_tick(visits[index].wait_seconds)
                // built.waiting_step_tick
                if active
                else 0
            )
            for option in movement.route_options_by_state_id[state]:
                selected = active and visits[index].route_option_id == option.id
                values[built.selection_by_key[cabin, index, option.id].index] = int(
                    selected
                )
            stop = unique_stop_route_option(
                movement, state, error_context="CP-SAT hints"
            )
            alight_times[cabin, index] = time + ddd_seconds_to_tick(
                stop.platform_entry_offset_seconds
            )
    return values, alight_times


def build_ddd_integrated_cp_sat(
    problem: DddFixedKTrajectoryProblem,
    *,
    cost_encoding: DddCpSatCostEncoding = DddCpSatCostEncoding.PRODUCT,
    fixed_movement: DddReferenceSolution | None = None,
    deadline_monotonic: float | None = None,
    domain_manifest: dict | None = None,
    formulation: DddCpFormulationConfig = DddCpFormulationConfig(),
) -> DddIntegratedCpSatModel:
    formulation.validate()
    manifest = validate_ddd_cp_sat_domain(problem)
    if domain_manifest is not None and stable_fingerprint(
        manifest
    ) != stable_fingerprint(domain_manifest):
        raise ValueError("CP-SAT supplied domain manifest differs")
    if deadline_monotonic is not None and perf_counter() >= deadline_monotonic:
        raise TimeoutError("CP-SAT domain validation exhausted build budget")
    built = build_ddd_cp_sat_movement(
        problem.resolved_trajectory_problem.structural_movement_problem,
        boundary_occurrences=problem.boundary_context.resource_occurrences,
        waiting_policy=problem.resolved_trajectory_problem.waiting_policy,
        deadline_monotonic=deadline_monotonic,
        resource_encoding=formulation.resource_encoding,
    )
    preprocessing_started = perf_counter()
    prepared = None
    if not formulation.legacy:
        prepared = prepare_cp_structure(problem.resolved_trajectory_problem.structural_movement_problem, problem.passenger_build, built.states_by_cabin)
        if formulation.enabled("temporal"):
            apply_cp_temporal(built, prepared)
    preprocessing_seconds = perf_counter() - preprocessing_started
    scope = "FIXED_K_GLOBAL"
    if fixed_movement is not None:
        checked = validate_ddd_cp_sat_incumbent(
            problem, fixed_movement, {}, provenance="fixed movement"
        )
        values, _ = _movement_values(problem, built, checked.solution)
        for index, value in values.items():
            built.model.add(built.model.get_int_var_from_proto_index(index) == value)
        scope = "FIXED_MOVEMENT"
    passengers = build_ddd_cp_sat_passengers(
        problem,
        built,
        cost_encoding=cost_encoding,
        deadline_monotonic=deadline_monotonic,
        formulation=formulation, prepared=prepared,
    )
    error = built.model.validate()
    if error:
        raise ValueError(f"invalid integrated CP-SAT model: {error}")
    stats = {
        "visits": sum(len(s) - 1 for s in built.states_by_cabin.values()),
        "route_literals": len(built.selection_by_key),
        "free_wait_variables": sum(
            list(v.proto.domain)[-1] > 0 for v in built.wait_steps_by_key.values()
        ),
        "resource_intervals": sum(map(len, built.resource_intervals.values())),
        "demand_groups": len(problem.passenger_build.demand_groups),
        "ride_candidates": len(passengers.ride_count),
        "quantity_variables": len(passengers.ride_count),
        "used_literals": len(passengers.used),
        "capacity_constraints": passengers.capacity_row_count,
        "alighting_events": len(passengers.alight_count),
        "cost_auxiliaries": passengers.cost_auxiliary_count,
        "variables": len(built.model.proto.variables),
        "constraints": len(built.model.proto.constraints),
    }
    stats["preprocessing_seconds"] = preprocessing_seconds
    if not formulation.legacy:
        stats["preprocessing"] = formulation_identity(formulation, prepared)
    return DddIntegratedCpSatModel(
        built,
        passengers,
        manifest,
        scope,
        stable_fingerprint(
            {"version": FORMULATION_VERSION, "model": str(built.model.proto), **formulation_identity(formulation, prepared)}
        ),
        stats,
    )


@dataclass(frozen=True)
class DddIntegratedCpSatResult:
    problem_fingerprint: str
    domain_manifest: dict
    proof_scope: str
    model_fingerprint: str | None
    solver_status: str
    termination_reason: str
    proven_optimal: bool
    incumbent: DddCpSatIncumbent | None
    cp_objective_tick: int | None
    cp_best_bound_tick: int | None
    raw_cp_best_bound_tick: float | None
    objective_constant_tick: int
    cost_encoding: str
    build_seconds: float
    solve_seconds: float
    validation_seconds: float
    total_wall_seconds: float
    model_stats: dict
    events: tuple[dict, ...]
    solver_response_stats: str | None
    seed_provenance: str | None
    num_workers: int
    random_seed: int
    callback_extraction_seconds: float = 0.0
    callback_validation_seconds: float = 0.0
    progress_delivery_seconds: float = 0.0
    hint_seconds: float = 0.0
    model_build_seconds: float = 0.0

    @property
    def cp_lower_bound(self) -> float | None:
        return (
            None
            if self.cp_best_bound_tick is None
            else self.cp_best_bound_tick / DDD_TIME_TICKS_PER_SECOND
        )

    @property
    def validated_upper_bound(self) -> float | None:
        return None if self.incumbent is None else self.incumbent.objective

    @property
    def relative_gap(self) -> float | None:
        ub, lb = self.validated_upper_bound, self.cp_lower_bound
        return (
            None
            if ub is None or ub == 0 or lb is None
            else max(0.0, (ub - lb) / abs(ub))
        )

    def to_payload(self) -> dict:
        from ..ean.horizon_contract import FINITE_EVENT_ENTRY_CONTRACT

        payload = {k: v for k, v in self.__dict__.items() if k != "incumbent"}
        payload.update(
            {
                "formulation_version": FORMULATION_VERSION,
                "horizon_contract": FINITE_EVENT_ENTRY_CONTRACT,
                "continuation_status": "NOT_PROVEN",
                "domain_fingerprint": stable_fingerprint(self.domain_manifest),
                "time_ticks_per_second": DDD_TIME_TICKS_PER_SECOND,
                "objective": "journey_time",
                "cp_lower_bound": self.cp_lower_bound,
                "validated_upper_bound": self.validated_upper_bound,
                "combined_lower_bound": self.cp_lower_bound,
                "relative_gap": self.relative_gap,
                "absolute_gap": None
                if self.validated_upper_bound is None or self.cp_lower_bound is None
                else max(0.0, self.validated_upper_bound - self.cp_lower_bound),
                "incumbent": None
                if self.incumbent is None
                else self.incumbent.to_payload(),
                # Existing Arc-Flow runners consume these timetable fields along
                # with the canonical metadata added by the benchmark runner.
                "trajectory_supports": []
                if self.incumbent is None
                else self.incumbent.to_payload()["trajectory_supports"],
                "served_count": None
                if self.incumbent is None
                else sum(self.incumbent.ride_counts.values()),
                "unserved_count": None
                if self.incumbent is None
                else sum(self.incumbent.unserved_counts.values()),
            }
        )
        return payload


def _raw_incumbent(built: DddIntegratedCpSatModel, value: Callable) -> dict:
    supports = []
    chosen = defaultdict(list)
    for (cabin, visit, option), literal in built.movement.selection_by_key.items():
        if value(literal):
            chosen[cabin, visit].append(option)
    for cabin, states in built.movement.states_by_cabin.items():
        routes, ticks, waits = [], [], []
        for visit in range(len(states) - 1):
            if not value(built.movement.active_by_cabin[cabin][visit]):
                break
            selected = chosen[cabin, visit]
            if len(selected) != 1:
                raise RuntimeError("CP-SAT solution lacks a unique route")
            routes.append(selected[0])
            ticks.append(int(value(built.movement.time_by_cabin[cabin][visit])))
            waits.append(
                int(value(built.movement.wait_steps_by_key[cabin, visit]))
                * built.movement.waiting_step_tick
            )
        supports.append(
            {
                "cabin_id": cabin,
                "route_option_ids": routes,
                "switch_times_tick": ticks,
                "wait_ticks": waits,
            }
        )
    return {
        "trajectory_supports": supports,
        "ride_counts": {
            q: int(value(y)) for q, y in built.passengers.ride_count.items() if value(y)
        },
        "objective_tick": int(value(built.passengers.objective_expression)),
    }


def _validate_raw(problem: DddFixedKTrajectoryProblem, raw: dict) -> DddCpSatIncumbent:
    return validate_ddd_cp_sat_incumbent(
        problem,
        solution_from_cp_sat_payload(problem, raw),
        raw["ride_counts"],
        provenance="integrated_cp_sat",
        expected_objective_tick=raw["objective_tick"],
    )


class _ProgressEvents(list):
    """Keep the result history while optionally streaming each event live."""

    def __init__(self, callback):
        super().__init__()
        self.callback = callback
        self.delivery_seconds = 0.0

    def append(self, event):
        super().append(event)
        if self.callback is not None:
            before = perf_counter()
            self.callback(event)
            self.delivery_seconds += perf_counter() - before


class _IncumbentCallback(cp_model.CpSolverSolutionCallback):
    def __init__(self, problem, built, config, started, events, seed_upper_tick=None):
        super().__init__()
        self.problem, self.built, self.config = problem, built, config
        self.started, self.events = started, events
        self.raw = None
        self.error = None
        self.last_checkpoint = -math.inf
        self.validation_seconds = 0.0
        self.extraction_seconds = 0.0
        self.saved_upper_tick = seed_upper_tick

    def on_solution_callback(self):
        try:
            before = perf_counter()
            self.raw = _raw_incumbent(self.built, self.value)
            self.extraction_seconds += perf_counter() - before
            elapsed = perf_counter() - self.started
            self.events.append(
                {
                    "elapsed_seconds": elapsed,
                    "kind": "cp_incumbent",
                    "objective_tick": self.raw["objective_tick"],
                    "raw_bound_tick": self.best_objective_bound,
                }
            )
            improves_saved = (
                self.saved_upper_tick is None
                or self.raw["objective_tick"] <= self.saved_upper_tick
            )
            if (
                self.config.checkpoint_path is not None
                and improves_saved
                and elapsed - self.last_checkpoint
                >= self.config.checkpoint_interval_seconds
            ):
                before = perf_counter()
                incumbent = _validate_raw(self.problem, self.raw)
                write_ddd_cp_sat_checkpoint(
                    self.config.checkpoint_path,
                    problem=self.problem,
                    manifest=self.built.domain_manifest,
                    incumbent=incumbent,
                )
                self.validation_seconds += perf_counter() - before
                self.last_checkpoint = elapsed
                self.saved_upper_tick = incumbent.objective_tick
        except Exception as error:
            self.error = error
            self.stop_search()


@dataclass(frozen=True)
class DddIntegratedCpSatOptimizer:
    config: DddIntegratedCpSatConfig = field(default_factory=DddIntegratedCpSatConfig)

    def solve(
        self,
        problem: DddFixedKTrajectoryProblem,
        *,
        primal_seed: DddCpSatIncumbent | None = None,
        fixed_movement: DddReferenceSolution | None = None,
        log_callback: Callable[[str], None] | None = None,
        event_callback: Callable[[dict], None] | None = None,
    ) -> DddIntegratedCpSatResult:
        self.config.validate()
        started = perf_counter()
        deadline = started + self.config.total_time_limit_seconds
        manifest = validate_ddd_cp_sat_domain(problem)
        incumbent = None
        if primal_seed is not None:
            incumbent = validate_ddd_cp_sat_incumbent(
                problem,
                primal_seed.solution,
                primal_seed.ride_counts,
                provenance=primal_seed.provenance,
                expected_objective_tick=primal_seed.objective_tick,
            )
        if fixed_movement is not None:
            fixed_checked = validate_ddd_cp_sat_incumbent(
                problem, fixed_movement, {}, provenance="fixed"
            )
            if incumbent is not None and fixed_checked.solution != incumbent.solution:
                raise ValueError("CP-SAT seed differs from fixed-movement proof scope")
            if incumbent is None:
                incumbent = fixed_checked
        built = None
        cp_objective = cp_bound = raw_bound = None
        events = _ProgressEvents(event_callback)
        callback_extraction_seconds = callback_validation_seconds = 0.0
        solve_seconds = validation_seconds = 0.0
        status_name, termination, optimal = "UNKNOWN", "BUILD_TIME_LIMIT", False
        response = None
        scope = "FIXED_MOVEMENT" if fixed_movement is not None else "FIXED_K_GLOBAL"
        try:
            built = build_ddd_integrated_cp_sat(
                problem,
                cost_encoding=self.config.cost_encoding,
                fixed_movement=fixed_movement,
                deadline_monotonic=deadline,
                domain_manifest=manifest,
                formulation=self.config.formulation,
            )
        except TimeoutError:
            pass
        hint_started = perf_counter()
        model_build_seconds = hint_started - started
        if built is not None and incumbent is not None:
            values, alight_times = _movement_values(
                problem, built.movement, incumbent.solution
            )
            for index, value in values.items():
                built.movement.model.add_hint(
                    built.movement.model.get_int_var_from_proto_index(index), value
                )
            built.passengers.add_hints(
                problem, built.movement.model, incumbent.ride_counts, alight_times
            )
        if built is not None and self.config.formulation.enabled("hints"):
            complete_cp_hints(built.movement.model)
        hint_seconds = perf_counter() - hint_started
        build_seconds = perf_counter() - started
        if built is not None and perf_counter() < deadline:
            solver = cp_model.CpSolver()
            solver.parameters.max_time_in_seconds = deadline - perf_counter()
            solver.parameters.num_search_workers = self.config.num_workers
            solver.parameters.random_seed = self.config.seed
            solver.parameters.relative_gap_limit = 0.0
            solver.parameters.absolute_gap_limit = 0.0
            solver.parameters.stop_after_first_solution = False
            solver.parameters.log_search_progress = self.config.log_search_progress
            if log_callback is not None:
                solver.log_callback = log_callback
                solver.parameters.log_to_stdout = False
            last_sample = [-math.inf]

            def record_bound(bound):
                elapsed = perf_counter() - started
                if elapsed - last_sample[0] >= 0.5:
                    events.append(
                        {
                            "elapsed_seconds": elapsed,
                            "kind": "cp_bound",
                            "raw_bound_tick": bound,
                        }
                    )
                    last_sample[0] = elapsed

            solver.best_bound_callback = record_bound
            callback = _IncumbentCallback(
                problem,
                built,
                self.config,
                started,
                events,
                None if incumbent is None else incumbent.objective_tick,
            )
            before = perf_counter()
            status = solver.solve(built.movement.model, callback)
            solve_seconds = perf_counter() - before
            callback_extraction_seconds = callback.extraction_seconds
            callback_validation_seconds = callback.validation_seconds
            if callback.error is not None:
                raise RuntimeError(
                    "CP-SAT callback validation failed"
                ) from callback.error
            status_name = solver.status_name(status)
            response = solver.response_stats()
            termination = (
                "OPTIMAL"
                if status == cp_model.OPTIMAL
                else ("TIME_LIMIT" if perf_counter() >= deadline else "SOLVER_STOPPED")
                if status in (cp_model.FEASIBLE, cp_model.UNKNOWN)
                else status_name
            )
            if status == cp_model.MODEL_INVALID:
                raise ValueError(f"CP-SAT rejected model: {response}")
            if status == cp_model.INFEASIBLE and incumbent is not None:
                raise RuntimeError("CP-SAT infeasible contradicts validated seed")
            if status in (cp_model.OPTIMAL, cp_model.FEASIBLE):
                before = perf_counter()
                cp_incumbent = _validate_raw(
                    problem, _raw_incumbent(built, solver.value)
                )
                validation_seconds += perf_counter() - before
                cp_objective = cp_incumbent.objective_tick
                if (
                    incumbent is None
                    or cp_incumbent.objective_tick <= incumbent.objective_tick
                ):
                    incumbent = cp_incumbent
            raw_bound = (
                float(solver.best_objective_bound)
                if status != cp_model.INFEASIBLE
                else None
            )
            if raw_bound is not None and math.isfinite(raw_bound):
                cp_bound = max(0, math.floor(math.nextafter(raw_bound, -math.inf)))
            if status == cp_model.OPTIMAL:
                # CP's internal objective normalization may introduce a tiny
                # floating report error even below 2**53. OPTIMAL with both gap
                # limits zero supplies the proof; allow less than 1/4 tick in
                # that report, never strengthen a time-limited bound this way.
                if cp_objective is None or abs(raw_bound - cp_objective) > 0.25:
                    raise RuntimeError(
                        "CP-SAT optimal status has inconsistent objective/bound"
                    )
                cp_bound = cp_objective
                optimal = True
            if (
                incumbent is not None
                and cp_bound is not None
                and cp_bound > incumbent.objective_tick
            ):
                raise RuntimeError("CP-SAT lower bound exceeds validated upper bound")
            events.append(
                {
                    "elapsed_seconds": perf_counter() - started,
                    "kind": "final",
                    "cp_objective_tick": cp_objective,
                    "cp_bound_tick": cp_bound,
                    "status": status_name,
                }
            )
            # Callback checking is already charged to solve_seconds. Keep the
            # final validation component separate to avoid double-counting.
        if incumbent is not None and self.config.checkpoint_path is not None:
            before = perf_counter()
            write_ddd_cp_sat_checkpoint(
                self.config.checkpoint_path,
                problem=problem,
                manifest=manifest,
                incumbent=incumbent,
            )
            validation_seconds += perf_counter() - before
        horizon = (
            problem.resolved_trajectory_problem.movement_core.passenger_service_end_tick
        )
        constant = sum(
            g.count * max(0, horizon - ddd_seconds_to_tick(g.release_time_seconds))
            for g in problem.passenger_build.demand_groups
        )
        return DddIntegratedCpSatResult(
            problem.fingerprint,
            manifest,
            scope,
            None if built is None else built.model_fingerprint,
            status_name,
            termination,
            optimal,
            incumbent,
            cp_objective,
            cp_bound,
            raw_bound,
            constant,
            self.config.cost_encoding.value,
            build_seconds,
            solve_seconds,
            validation_seconds,
            perf_counter() - started,
            {} if built is None else built.stats,
            tuple(events),
            response,
            None if primal_seed is None else primal_seed.provenance,
            self.config.num_workers,
            self.config.seed,
            callback_extraction_seconds,
            callback_validation_seconds,
            events.delivery_seconds,
            hint_seconds, model_build_seconds,
        )
