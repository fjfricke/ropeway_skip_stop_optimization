"""Certified infeasible-assumption cores for reservoir service assignments."""

from dataclasses import asdict, dataclass
import math
from time import perf_counter

from ortools.sat.python import cp_model

from .timing import (
    ReservoirAssignmentTimingConfig,
    ReservoirTimingAssumption,
    build_assignment_timing_model,
)
from ..time_ticks import ddd_seconds_to_tick


@dataclass(frozen=True)
class ReservoirConflictConfig:
    time_limit_seconds: float = 180.0
    deletion_limit_seconds: float = 300.0
    replay_limit_seconds: float = 120.0
    deletion_slice_seconds: float = 15.0
    workers: int = 1
    seed: int = 0

    def validate(self):
        values = (
            self.time_limit_seconds,
            self.deletion_limit_seconds,
            self.replay_limit_seconds,
            self.deletion_slice_seconds,
        )
        if any(not math.isfinite(value) or value <= 0 for value in values):
            raise ValueError("invalid conflict extraction time limit")
        if self.workers != 1:
            raise ValueError("conflict extraction requires one worker")
        if type(self.seed) is not int or self.seed < 0:
            raise ValueError("invalid conflict extraction seed")


@dataclass(frozen=True)
class ReservoirAssignmentConflict:
    problem_fingerprint: str
    passenger_fixing: str
    fix_routes: bool
    fix_witness_waits: bool
    assumptions: tuple[ReservoirTimingAssumption, ...]

    @property
    def id(self):
        from ..cp_sat_certificate import stable_fingerprint

        return stable_fingerprint(conflict_to_payload(self))


def conflict_to_payload(conflict):
    return {
        "schema": "reservoir_assignment_conflict_v1",
        "problem_fingerprint": conflict.problem_fingerprint,
        "passenger_fixing": conflict.passenger_fixing,
        "fix_routes": conflict.fix_routes,
        "fix_witness_waits": conflict.fix_witness_waits,
        "assumptions": [asdict(item) for item in conflict.assumptions],
    }


def conflict_from_payload(payload):
    if payload.get("schema") != "reservoir_assignment_conflict_v1":
        raise ValueError("invalid reservoir assignment conflict schema")
    return ReservoirAssignmentConflict(
        problem_fingerprint=payload["problem_fingerprint"],
        passenger_fixing=payload["passenger_fixing"],
        fix_routes=bool(payload["fix_routes"]),
        fix_witness_waits=bool(payload["fix_witness_waits"]),
        assumptions=tuple(
            ReservoirTimingAssumption(
                id=item["id"],
                kind=item["kind"],
                key=item["key"],
                value=item["value"],
                literal_index=item["literal_index"],
            )
            for item in payload["assumptions"]
        ),
    )


def assignment_violates_conflict(problem, assignment, conflict):
    """Return whether every assumption in a no-good holds for an assignment."""
    trips = {trip.cabin_id: trip for trip in assignment.trips}
    served = sum(assignment.ride_counts.values())
    for assumption in conflict.assumptions:
        if assumption.kind == "active":
            cabin, visit = map(int, assumption.key.split(":"))
            actual = int(cabin in trips and visit < len(trips[cabin].route_option_ids))
            holds = actual == assumption.value
        elif assumption.kind == "route":
            cabin_text, visit_text, option_id = assumption.key.split(":", 2)
            trip = trips.get(int(cabin_text))
            visit = int(visit_text)
            holds = (
                assumption.value == 1
                and trip is not None
                and visit < len(trip.route_option_ids)
                and trip.route_option_ids[visit] == option_id
            )
        elif assumption.kind == "wait":
            cabin, visit = map(int, assumption.key.split(":"))
            trip = trips.get(cabin)
            step = ddd_seconds_to_tick(problem.waiting_policy.step_seconds or 0.000001)
            holds = (
                trip is not None
                and visit < len(trip.witness_wait_ticks)
                and trip.witness_wait_ticks[visit] == assumption.value * step
            )
        elif assumption.kind == "ride_eq":
            holds = assignment.ride_counts.get(assumption.key, 0) == assumption.value
        elif assumption.kind == "ride_ge":
            holds = assignment.ride_counts.get(assumption.key, 0) >= assumption.value
        elif assumption.kind == "served_ge":
            holds = served >= assumption.value
        else:
            raise ValueError(f"unsupported assignment conflict kind: {assumption.kind}")
        if not holds:
            return False
    return True


def _solve_assumptions(base_model, literal_indices, seconds, config):
    model = base_model.clone()
    model.clear_assumptions()
    model.add_assumptions(
        model.get_bool_var_from_proto_index(index) for index in literal_indices
    )
    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = seconds
    solver.parameters.num_search_workers = config.workers
    solver.parameters.random_seed = config.seed
    code = solver.solve(model)
    return solver, code


def replay_assignment_conflict(problem, assignment, timing_config, conflict, seconds=120):
    """Rebuild and prove a stored core under its exact original background."""
    if conflict.problem_fingerprint != problem.fingerprint:
        raise ValueError("conflict problem fingerprint mismatch")
    expected = (
        str(timing_config.passenger_fixing),
        timing_config.fix_routes,
        timing_config.fix_witness_waits,
    )
    actual = (
        conflict.passenger_fixing,
        conflict.fix_routes,
        conflict.fix_witness_waits,
    )
    if expected != actual:
        raise ValueError("conflict background does not match timing configuration")
    built = build_assignment_timing_model(
        problem, assignment, timing_config, assumptionize=True
    )
    available = {item.id: item for item in built.assumptions}
    if any(item.id not in available for item in conflict.assumptions):
        raise ValueError("conflict assumption is unavailable in rebuilt model")
    selected = [available[item.id].literal_index for item in conflict.assumptions]
    solver, code = _solve_assumptions(
        built.built.movement.model,
        selected,
        seconds,
        ReservoirConflictConfig(replay_limit_seconds=seconds),
    )
    return {
        "status": solver.status_name(code),
        "proved_infeasible": code == cp_model.INFEASIBLE,
        "response_stats": solver.response_stats(),
    }


def extract_assignment_conflict(
    problem,
    assignment,
    timing_config=ReservoirAssignmentTimingConfig(),
    config=ReservoirConflictConfig(),
):
    """Extract, shrink, and replay a sufficient infeasible assumption core."""
    config.validate()
    started = perf_counter()
    built = build_assignment_timing_model(
        problem, assignment, timing_config, assumptionize=True
    )
    by_index = {item.literal_index: item for item in built.assumptions}
    by_id = {item.id: item for item in built.assumptions}
    solver, code = _solve_assumptions(
        built.built.movement.model,
        by_index,
        config.time_limit_seconds,
        config,
    )
    initial_status = solver.status_name(code)
    if code != cp_model.INFEASIBLE:
        return {
            "schema": "reservoir_assignment_conflict_result_v1",
            "status": initial_status,
            "proved_infeasible": False,
            "conflict": None,
            "initial_assumption_count": len(by_index),
            "core_size": None,
            "deletion_attempts": 0,
            "total_seconds": perf_counter() - started,
            "response_stats": solver.response_stats(),
        }, None
    core_indices = [
        index if index >= 0 else -index - 1
        for index in solver.sufficient_assumptions_for_infeasibility()
    ]
    if any(index not in by_index for index in core_indices):
        raise RuntimeError("CP-SAT returned an unknown assignment assumption")
    current = [by_index[index].id for index in core_indices]
    deletion_started = perf_counter()
    attempts = 0
    for candidate_id in tuple(current):
        remaining = config.deletion_limit_seconds - (perf_counter() - deletion_started)
        if remaining <= 0:
            break
        trial = [item for item in current if item != candidate_id]
        trial_indices = [by_id[item].literal_index for item in trial]
        trial_solver, trial_code = _solve_assumptions(
            built.built.movement.model,
            trial_indices,
            min(config.deletion_slice_seconds, remaining),
            config,
        )
        attempts += 1
        if trial_code == cp_model.INFEASIBLE:
            returned = {
                index if index >= 0 else -index - 1
                for index in trial_solver.sufficient_assumptions_for_infeasibility()
            }
            current = [
                item for item in trial if by_id[item].literal_index in returned
            ]
    conflict = ReservoirAssignmentConflict(
        problem_fingerprint=problem.fingerprint,
        passenger_fixing=str(timing_config.passenger_fixing),
        fix_routes=timing_config.fix_routes,
        fix_witness_waits=timing_config.fix_witness_waits,
        assumptions=tuple(by_id[item] for item in current),
    )
    replay = replay_assignment_conflict(
        problem,
        assignment,
        timing_config,
        conflict,
        seconds=config.replay_limit_seconds,
    )
    if not replay["proved_infeasible"]:
        conflict = None
    return {
        "schema": "reservoir_assignment_conflict_result_v1",
        "status": initial_status,
        "proved_infeasible": True,
        "conflict": None if conflict is None else conflict_to_payload(conflict),
        "initial_assumption_count": len(by_index),
        "initial_core_size": len(core_indices),
        "core_size": None if conflict is None else len(conflict.assumptions),
        "deletion_attempts": attempts,
        "replay": replay,
        "total_seconds": perf_counter() - started,
        "response_stats": solver.response_stats(),
    }, conflict
