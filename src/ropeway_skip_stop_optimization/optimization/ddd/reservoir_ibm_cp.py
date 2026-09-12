"""IBM CP Optimizer backend with shared primal certificates and native bounds."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
import math
from pathlib import Path
import shutil
import sys
from time import perf_counter

import docplex
from docplex.cp.solver.cpo_callback import CpoCallback
from docplex.cp.utils import CpoException

from .cp_sat_certificate import stable_fingerprint
from .cp_formulation import formulation_identity, DddCpFormulationConfig
from .reservoir_cp_sat import DddReservoirCpObjective
from .reservoir_cp_sat_certificate import (
    DddReservoirCpPlan,
    validate_reservoir_cp_plan,
    write_reservoir_cp_checkpoint,
)
from .reservoir_ibm_cp_model import build_ddd_reservoir_ibm_cp


@dataclass(frozen=True)
class DddReservoirIbmCpConfig:
    total_time_limit_seconds: float = 60.0
    num_workers: int = 1
    seed: int = 0
    executable: Path | None = None
    checkpoint_path: Path | None = None
    checkpoint_interval_seconds: float = 30.0
    export_path: Path | None = None
    log_search_progress: bool = True
    formulation: DddCpFormulationConfig = field(default_factory=DddCpFormulationConfig)

    def validate(self):
        self.formulation.validate("ibm")
        if (
            not math.isfinite(self.total_time_limit_seconds)
            or self.total_time_limit_seconds <= 0
        ):
            raise ValueError("IBM time budget must be finite and positive")
        if type(self.num_workers) is not int or self.num_workers < 1:
            raise ValueError("IBM worker count must be a positive integer")
        if type(self.seed) is not int or not 0 <= self.seed < 2**31:
            raise ValueError("invalid IBM random seed")
        if (
            not math.isfinite(self.checkpoint_interval_seconds)
            or self.checkpoint_interval_seconds < 0
        ):
            raise ValueError("invalid IBM checkpoint interval")


def resolve_cp_optimizer(executable: Path | None = None) -> str:
    if executable is not None:
        if not executable.is_file():
            raise FileNotFoundError(
                f"IBM CP Optimizer executable missing: {executable}"
            )
        return str(executable.resolve())
    found = shutil.which("cpoptimizer")
    if found:
        return found
    sibling = Path(sys.executable).parent / (
        "cpoptimizer.exe" if sys.platform == "win32" else "cpoptimizer"
    )
    if sibling.is_file():
        return str(sibling)
    raise FileNotFoundError("Install IBM CP Optimizer or supply --cpoptimizer PATH")


def _score(metrics, objective):
    return (
        metrics.journey_time_tick
        if objective is DddReservoirCpObjective.JOURNEY_TIME
        else metrics.unserved
    )


class _LogStream:
    def __init__(self, callback):
        self.callback = callback

    def write(self, data):
        if self.callback:
            self.callback(data)
        return len(data)

    def flush(self):
        pass


class _Progress(CpoCallback):
    def __init__(self, problem, built, config, objective, started, events, callback):
        self.problem, self.built, self.config, self.objective = (
            problem,
            built,
            config,
            objective,
        )
        self.started, self.events, self.callback = started, events, callback
        self.last_checkpoint = -math.inf
        self.error = None
        self.best_plan = None
        self.best_score = math.inf

    def emit(self, item):
        self.events.append(item)
        if self.callback:
            self.callback(item)

    def invoke(self, solver, event, result):
        try:
            if event not in ("Solution", "ObjBound", "StartSearch", "EndSearch"):
                return
            elapsed = perf_counter() - self.started
            bounds, values = (
                result.get_objective_bounds(),
                result.get_objective_values(),
            )
            item = dict(
                kind="incumbent"
                if event == "Solution"
                else "bound"
                if event == "ObjBound"
                else event,
                elapsed_seconds=elapsed,
                bound_raw=bounds[0] if bounds else None,
                objective_raw=values[0] if values else None,
            )
            self.emit(item)
            if (
                event == "Solution"
                and elapsed - self.last_checkpoint
                >= self.config.checkpoint_interval_seconds
            ):
                plan = self.built.extract(self.problem, result)
                metrics = validate_reservoir_cp_plan(self.problem, plan)
                score = _score(metrics, self.objective)
                if values is None or abs(values[0] - score) > 0.25:
                    raise ValueError(
                        "IBM callback cost differs from independent validation"
                    )
                if score < self.best_score:
                    self.best_plan, self.best_score = plan, score
                    if self.config.checkpoint_path:
                        write_reservoir_cp_checkpoint(
                            self.config.checkpoint_path, self.problem, plan
                        )
                self.last_checkpoint = elapsed
        except Exception as error:
            self.error = error
            solver.abort_search()


@dataclass(frozen=True)
class DddReservoirIbmCpOptimizer:
    config: DddReservoirIbmCpConfig = DddReservoirIbmCpConfig()
    objective: DddReservoirCpObjective = DddReservoirCpObjective.JOURNEY_TIME

    def solve(
        self,
        problem,
        *,
        primal_seed=None,
        fixed_plan=None,
        event_callback=None,
        log_callback=None,
    ):
        self.config.validate()
        if not isinstance(self.objective, DddReservoirCpObjective):
            raise ValueError("invalid IBM reservoir objective")
        started = perf_counter()
        deadline = started + self.config.total_time_limit_seconds
        problem.validate()
        plan = primal_seed or DddReservoirCpPlan((), {})
        if fixed_plan is not None:
            validate_reservoir_cp_plan(problem, fixed_plan)
            if primal_seed is not None and primal_seed.trips != fixed_plan.trips:
                raise ValueError("IBM fixed movement differs from seed")
            if primal_seed is None:
                plan = DddReservoirCpPlan(fixed_plan.trips, {})
        metrics = validate_reservoir_cp_plan(problem, plan)
        events = []

        def emit(item):
            events.append(item)
            if event_callback:
                event_callback(item)

        emit(
            dict(
                kind="validated_seed",
                elapsed_seconds=perf_counter() - started,
                objective_raw=_score(metrics, self.objective),
                bound_raw=None,
            )
        )
        built, model_hash, progress, native = None, None, None, None
        status, reason, error = "UNKNOWN", "BUILD_TIME_LIMIT", None
        bound = raw_bound = None
        optimal = False
        solve_seconds = validation_seconds = 0.0
        version = None
        hint_seconds = 0.0
        before = perf_counter()
        try:
            if perf_counter() >= deadline:
                raise TimeoutError()
            built = build_ddd_reservoir_ibm_cp(
                problem, objective=self.objective, deadline=deadline, formulation=self.config.formulation
            )
            hint_started = perf_counter()
            built.set_primal(problem, plan, fix_movement=fixed_plan is not None)
            hint_seconds = perf_counter() - hint_started
            built.model.add(built.objective <= _score(metrics, self.objective))
            cpo = built.model.get_cpo_string()
            model_hash = stable_fingerprint(
                {"version": "single_use_reservoir_ibm_cp_v1", "model": cpo, **formulation_identity(self.config.formulation, built.prepared)}
            )
            if self.config.export_path:
                self.config.export_path.parent.mkdir(parents=True, exist_ok=True)
                self.config.export_path.write_text(cpo)
        except TimeoutError:
            pass
        build_seconds = perf_counter() - before
        if built is not None and model_hash and perf_counter() < deadline:
            before = perf_counter()
            try:
                executable = resolve_cp_optimizer(self.config.executable)
                progress = _Progress(
                    problem,
                    built,
                    self.config,
                    self.objective,
                    started,
                    events,
                    event_callback,
                )
                built.model.add_solver_callback(progress)
                with built.model.create_solver(
                    execfile=executable,
                    agent="local",
                    TimeLimit=max(1e-9, deadline - perf_counter()),
                    Workers=self.config.num_workers,
                    RandomSeed=self.config.seed,
                    OptimalityTolerance=0,
                    RelativeOptimalityTolerance=0,
                    LogVerbosity="Normal"
                    if self.config.log_search_progress
                    else "Quiet",
                    log_output=_LogStream(log_callback),
                    log_exceptions=False,
                ) as solver:
                    version = solver.get_solver_version()
                    native = solver.solve()
                if progress.error:
                    raise RuntimeError(
                        "IBM callback plan validation failed"
                    ) from progress.error
                status, reason = native.get_solve_status(), native.get_stop_cause()
                if status in ("Infeasible", "Error"):
                    raise RuntimeError(
                        "IBM rejected a domain containing a validated feasible seed"
                    )
                before_validation = perf_counter()
                if native.is_solution():
                    found = built.extract(problem, native)
                    checked = validate_reservoir_cp_plan(problem, found)
                    raw_value = native.get_objective_values()[0]
                    if abs(raw_value - _score(checked, self.objective)) > 0.25:
                        raise RuntimeError(
                            "IBM final cost differs from independent validation"
                        )
                    if _score(checked, self.objective) <= _score(
                        metrics, self.objective
                    ):
                        plan, metrics = found, checked
                bounds = native.get_objective_bounds()
                if bounds and math.isfinite(bounds[0]):
                    raw_bound = bounds[0]
                    bound = max(0, math.floor(math.nextafter(raw_bound, -math.inf)))
                if native.is_solution_optimal():
                    effective = native.get_solver_infos().get(
                        "EffectiveOptimalityTolerance"
                    )
                    if (
                        effective not in (None, 0)
                        or bound is None
                        or abs(raw_bound - _score(metrics, self.objective)) > 0.25
                    ):
                        raise RuntimeError(
                            "IBM optimality report does not match exact checked objective"
                        )
                    optimal, bound = True, _score(metrics, self.objective)
                validation_seconds += perf_counter() - before_validation
            except (CpoException, FileNotFoundError) as exc:
                if progress is not None and progress.error:
                    raise RuntimeError(
                        "IBM callback validation failed"
                    ) from progress.error
                status, reason, error = "ERROR", "ENGINE_ERROR", str(exc)
                if "community" in str(exc).lower() or "size limit" in str(exc).lower():
                    reason = "LICENSE_LIMIT"
                if isinstance(exc, FileNotFoundError):
                    reason = "ENGINE_UNAVAILABLE"
            solve_seconds = perf_counter() - before - validation_seconds
        if (
            progress is not None
            and progress.best_plan is not None
            and progress.best_score < _score(metrics, self.objective)
        ):
            plan = progress.best_plan
            metrics = validate_reservoir_cp_plan(problem, plan)
        if bound is not None and bound > _score(metrics, self.objective):
            raise RuntimeError("IBM lower bound exceeds validated upper bound")
        if self.config.checkpoint_path:
            before = perf_counter()
            write_reservoir_cp_checkpoint(self.config.checkpoint_path, problem, plan)
            validation_seconds += perf_counter() - before
        scale = (
            1_000_000 if self.objective is DddReservoirCpObjective.JOURNEY_TIME else 1
        )
        upper = _score(metrics, self.objective) / scale
        lower = None if bound is None else bound / scale
        emit(
            dict(
                kind="final",
                elapsed_seconds=perf_counter() - started,
                objective_raw=_score(metrics, self.objective),
                bound_raw=bound,
                status=status,
            )
        )
        return dict(
            schema="single_use_reservoir_ibm_cp_result_v1",
            backend="ibm_cp_optimizer",
            problem_fingerprint=problem.fingerprint,
            domain_manifest=problem.manifest,
            proof_scope="FIXED_MOVEMENT"
            if fixed_plan is not None
            else "RESERVOIR_SINGLE_USE_GLOBAL",
            objective=self.objective.value,
            bound_units="passenger_seconds" if scale > 1 else "persons",
            solver_status=status,
            termination_reason=reason,
            error=error,
            proven_optimal=optimal,
            validated_upper_bound=upper,
            cp_lower_bound=lower,
            raw_cp_bound=raw_bound,
            relative_gap=None
            if lower is None
            else (upper - lower) / max(abs(upper), 1),
            metrics=asdict(metrics),
            plan=asdict(plan),
            model_stats={} if built is None else built.stats,
            model_fingerprint=model_hash,
            solver_version=version,
            docplex_version=docplex.__version__,
            num_workers=self.config.num_workers,
            seed=self.config.seed,
            absolute_gap_limit=0,
            relative_gap_limit=0,
            build_seconds=build_seconds,
            hint_seconds=hint_seconds, model_build_seconds=build_seconds-hint_seconds,
            solve_seconds=solve_seconds,
            validation_seconds=validation_seconds,
            total_wall_seconds=perf_counter() - started,
            events=events,
            solver_infos=None if native is None else dict(native.get_solver_infos()),
        )
