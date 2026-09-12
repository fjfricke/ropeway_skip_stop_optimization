"""Continuous fixed-pattern CP-SAT diagnostic with complete matching hints."""

from dataclasses import dataclass
from time import perf_counter
import math
from ortools.sat.python import cp_model
from .pattern_search import PatternTimingOracle, unserved
from .cp_sat_integrated import _movement_values, _raw_incumbent
from .cp_sat_certificate import (
    validate_ddd_cp_sat_incumbent,
    solution_from_cp_sat_payload,
    stable_fingerprint,
)
from .cp_hint_completion import complete_cp_hints
from .fixed_timetable_capacity import conservative_count_bound


@dataclass(frozen=True)
class PatternProbeConfig:
    seconds: float = 300
    workers: int = 12
    seed: int = 0

    def validate(self):
        if (
            not math.isfinite(self.seconds)
            or self.seconds <= 0
            or type(self.workers) is not int
            or self.workers < 1
            or type(self.seed) is not int
            or self.seed < 0
        ):
            raise ValueError("invalid probe settings")


class ProbeProgress:
    def __init__(self, problem, pattern, seed, started, callback=None, checkpoint=None):
        self.problem, self.pattern, self.started = problem, pattern, started
        self.callback, self.checkpoint = callback, checkpoint
        self.events = []
        self.best = None
        if seed is not None and pattern.matches(seed.solution):
            self.best = validate_ddd_cp_sat_incumbent(
                problem,
                seed.solution,
                seed.ride_counts,
                provenance="matching_pattern_seed",
            )
            self.emit("initial", unserved=unserved(self.best))
            if checkpoint:
                checkpoint(self.best)

    def emit(self, kind, **data):
        row = dict(kind=kind, elapsed_seconds=perf_counter() - self.started, **data)
        self.events.append(row)
        if self.callback:
            self.callback(row)

    def accept(self, solution, counts):
        found = validate_ddd_cp_sat_incumbent(
            self.problem, solution, counts, provenance="fixed_pattern_probe"
        )
        if not self.pattern.matches(found.solution):
            raise RuntimeError("pattern mismatch")
        improved = self.best is None or unserved(found) < unserved(self.best)
        if improved:
            self.best = found
        self.emit("solver_incumbent", unserved=unserved(found), improved=improved)
        if improved and self.checkpoint:
            self.checkpoint(found)
        return found

    def result(
        self, *, backend, status, lower, stats, build_seconds, solve_seconds, **extra
    ):
        upper = None if self.best is None else unserved(self.best)
        if lower is not None and upper is not None and lower > upper:
            raise RuntimeError("local bound exceeds certificate")
        if status == "INFEASIBLE" and self.best is not None:
            raise RuntimeError("infeasibility contradicts seed")
        native = [e for e in self.events if e["kind"] == "solver_incumbent"]
        return dict(
            schema="fixed_pattern_oracle_probe_v1",
            backend=backend,
            proof_scope="FIXED_PATTERN",
            status=status,
            pattern_id=self.pattern.id,
            pattern_upper_bound=upper,
            pattern_lower_bound=lower,
            model_stats=stats,
            build_seconds=build_seconds,
            solve_seconds=solve_seconds,
            total_seconds=perf_counter() - self.started,
            events=self.events,
            first_native_feasible_seconds=None
            if not native
            else native[0]["elapsed_seconds"],
            incumbent=None if self.best is None else self.best.to_payload(),
            **extra,
        )


@dataclass
class FixedPatternCpSatProbe:
    config: PatternProbeConfig = PatternProbeConfig()

    def solve(
        self,
        problem,
        pattern,
        *,
        seed=None,
        time_hint=None,
        certificate_callback=None,
        event_callback=None,
        log_callback=None,
        checkpoint=None,
    ):
        self.config.validate()
        if seed is not None and time_hint is not None:
            raise ValueError("choose incumbent seed or time-only hint")
        started = perf_counter()
        progress = ProbeProgress(
            problem, pattern, seed, started, event_callback, checkpoint
        )
        oracle = PatternTimingOracle(
            problem, workers=self.config.workers, seed=self.config.seed
        )
        oracle.validate_pattern(pattern)
        model = oracle.built.movement.model.clone()
        b = oracle.built.movement
        var = model.get_int_var_from_proto_index
        for c, v, o in pattern.choices:
            model.add(
                var(b.selection_by_key[c, v, o].index)
                == var(b.active_by_cabin[c][v].index)
            )
        hint_stats = {}
        if progress.best is not None:
            values, alight = _movement_values(problem, b, progress.best.solution)
            for i, value in values.items():
                model.add_hint(var(i), value)
            oracle.built.passengers.add_hints(
                problem, model, progress.best.ride_counts, alight
            )
            hint_stats = complete_cp_hints(model)
            # Valid only because the certificate matches this exact pattern.
            model.add(
                sum(oracle.built.passengers.unserved.values())
                <= unserved(progress.best)
            )
        elif time_hint is not None:
            checked = validate_ddd_cp_sat_incumbent(
                problem,
                time_hint.solution,
                time_hint.ride_counts,
                provenance="time_hint_source",
            )
            values, _ = _movement_values(problem, b, checked.solution)
            indices = {x.index for seq in b.time_by_cabin.values() for x in seq}
            for index in sorted(indices):
                model.add_hint(var(index), values[index])
            hint_stats = dict(hinted_variables=len(indices), hint_scope="TIMES_ONLY")
        structure = model.clone()
        structure.clear_hints()
        model_fingerprint = stable_fingerprint(str(structure.proto))
        if model.validate():
            raise ValueError(model.validate())
        build_seconds = perf_counter() - started
        stats = dict(
            hint_stats,
            variables=len(model.proto.variables),
            constraints=len(model.proto.constraints),
        )
        progress.emit("model_built", model_stats=stats, build_seconds=build_seconds)
        solver = cp_model.CpSolver()
        solver.parameters.num_search_workers = self.config.workers
        solver.parameters.random_seed = self.config.seed
        solver.parameters.absolute_gap_limit = 0
        solver.parameters.relative_gap_limit = 0
        if log_callback:
            solver.parameters.log_search_progress = True
            solver.parameters.log_to_stdout = False
            solver.log_callback = log_callback
        error = []

        class Callback(cp_model.CpSolverSolutionCallback):
            def on_solution_callback(self):
                try:
                    raw = _raw_incumbent(oracle.built, self.value)
                    found = progress.accept(
                        solution_from_cp_sat_payload(problem, raw), raw["ride_counts"]
                    )
                    if certificate_callback:
                        certificate_callback(found)
                except Exception as exc:
                    error.append(exc)
                    self.stop_search()

        last_bound = [None]

        def bound(value):
            v = conservative_count_bound(value)
            if v != last_bound[0]:
                last_bound[0] = v
                progress.emit("bound", lower_bound=v)

        solver.best_bound_callback = bound
        remaining = self.config.seconds - build_seconds
        status = cp_model.UNKNOWN
        lower = None
        before = perf_counter()
        if remaining > 0:
            solver.parameters.max_time_in_seconds = remaining
            status = solver.solve(model, Callback())
            if error:
                raise RuntimeError("certificate callback failed") from error[0]
            if status == cp_model.MODEL_INVALID:
                raise RuntimeError(solver.response_stats())
            if status in (cp_model.FEASIBLE, cp_model.OPTIMAL):
                raw = _raw_incumbent(oracle.built, solver.value)
                found = progress.accept(
                    solution_from_cp_sat_payload(problem, raw), raw["ride_counts"]
                )
                if certificate_callback:
                    certificate_callback(found)
            if status != cp_model.INFEASIBLE:
                lower = conservative_count_bound(float(solver.best_objective_bound))
            if status == cp_model.OPTIMAL:
                lower = unserved(progress.best)
        return progress.result(
            backend="cp_sat",
            status=solver.status_name(status),
            lower=lower,
            stats=stats,
            build_seconds=build_seconds,
            solve_seconds=perf_counter() - before,
            response_stats=solver.response_stats(),
            domain_manifest=oracle.manifest,
            model_fingerprint=model_fingerprint,
        )
