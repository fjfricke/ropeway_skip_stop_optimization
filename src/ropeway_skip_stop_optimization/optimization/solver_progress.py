from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any, Callable


@dataclass(frozen=True)
class GurobiMipProgressSample:
    runtime_seconds: float
    node_count: float | None
    incumbent_objective: float | None
    best_bound: float | None
    mip_gap: float | None
    solution_count: int | None
    work: float | None = None
    event: str = "interval"


@dataclass(frozen=True)
class GurobiSolvePhaseMetrics:
    presolve_runtime_seconds: float | None
    root_relaxation_start_seconds: float | None
    root_relaxation_end_seconds: float | None
    root_relaxation_runtime_seconds: float | None
    first_incumbent_runtime_seconds: float | None
    peak_memory_gb: float | None


@dataclass
class GurobiMipProgressRecorder:
    samples: list[GurobiMipProgressSample] = field(default_factory=list)
    on_sample: Callable[[GurobiMipProgressSample], None] | None = None
    _last_interval_runtime: float | None = None
    _last_solution_count: int | None = None
    _last_incumbent_objective: float | None = None
    _presolve_runtime_seconds: float | None = None
    _root_relaxation_start_seconds: float | None = None
    _root_relaxation_end_seconds: float | None = None
    _first_incumbent_runtime_seconds: float | None = None
    _peak_memory_gb: float | None = None

    def begin_run(self) -> int:
        self._last_interval_runtime = None
        self._last_solution_count = None
        self._last_incumbent_objective = None
        self._presolve_runtime_seconds = None
        self._root_relaxation_start_seconds = None
        self._root_relaxation_end_seconds = None
        self._first_incumbent_runtime_seconds = None
        self._peak_memory_gb = None
        return len(self.samples)

    def record_callback(self, model: Any, grb: Any, where: int, *, sample_interval_seconds: float) -> None:
        callback = grb.Callback
        self._record_phase_metrics(model, callback, where)
        if where == callback.MIPSOL:
            sample = self._sample_callback(model, grb, where, event="incumbent")
            if self._is_new_incumbent(sample):
                self._append(sample)
            return
        if where != callback.MIP:
            return

        sample = self._sample_callback(model, grb, where, event="interval")
        if self._last_interval_runtime is None or (
            sample.runtime_seconds - self._last_interval_runtime >= sample_interval_seconds
        ):
            self._append(sample)
            self._last_interval_runtime = sample.runtime_seconds

    def record_final(self, model: Any, grb: Any) -> None:
        if self._peak_memory_gb is None:
            final_memory = _safe_float_attr(model, "MemUsed")
            if final_memory is None:
                final_memory = _safe_float_attr(model, "MaxMemUsed")
            self._peak_memory_gb = final_memory
        if (
            self._first_incumbent_runtime_seconds is None
            and (_safe_int_attr(model, "SolCount") or 0) > 0
        ):
            self._first_incumbent_runtime_seconds = (
                _safe_float_attr(model, "Runtime") or 0.0
            )
        self._append(
            GurobiMipProgressSample(
                runtime_seconds=_safe_float_attr(model, "Runtime") or 0.0,
                node_count=_safe_float_attr(model, "NodeCount"),
                incumbent_objective=(
                    _safe_float_attr(model, "ObjVal") if (_safe_int_attr(model, "SolCount") or 0) > 0 else None
                ),
                best_bound=_safe_float_attr(model, "ObjBound"),
                mip_gap=_safe_float_attr(model, "MIPGap") if (_safe_int_attr(model, "SolCount") or 0) > 0 else None,
                solution_count=_safe_int_attr(model, "SolCount"),
                work=_safe_float_attr(model, "Work"),
                event="final",
            )
        )

    def _append(self, sample: GurobiMipProgressSample) -> None:
        self.samples.append(sample)
        if self.on_sample is not None:
            self.on_sample(sample)

    @property
    def phase_metrics(self) -> GurobiSolvePhaseMetrics:
        root_runtime = None
        if (
            self._root_relaxation_start_seconds is not None
            and self._root_relaxation_end_seconds is not None
        ):
            root_runtime = max(
                0.0,
                self._root_relaxation_end_seconds
                - self._root_relaxation_start_seconds,
            )
        return GurobiSolvePhaseMetrics(
            presolve_runtime_seconds=self._presolve_runtime_seconds,
            root_relaxation_start_seconds=(
                self._root_relaxation_start_seconds
            ),
            root_relaxation_end_seconds=self._root_relaxation_end_seconds,
            root_relaxation_runtime_seconds=root_runtime,
            first_incumbent_runtime_seconds=(
                self._first_incumbent_runtime_seconds
            ),
            peak_memory_gb=self._peak_memory_gb,
        )

    def _record_phase_metrics(
        self,
        model: Any,
        callback: Any,
        where: int,
    ) -> None:
        runtime = _cb_get(model, _callback_code(callback, "RUNTIME"))
        memory = _cb_get(model, _callback_code(callback, "MEMUSED"))
        if memory is None:
            memory = _cb_get(model, _callback_code(callback, "MAXMEMUSED"))
        if memory is not None:
            self._peak_memory_gb = max(self._peak_memory_gb or 0.0, memory)

        if runtime is None:
            return
        if where == getattr(callback, "PRESOLVE", None):
            self._presolve_runtime_seconds = runtime
            return
        if where in {
            getattr(callback, "SIMPLEX", None),
            getattr(callback, "BARRIER", None),
        }:
            if self._root_relaxation_start_seconds is None:
                self._root_relaxation_start_seconds = runtime
            return
        if where == getattr(callback, "MIPNODE", None):
            node_count = _cb_get(
                model,
                _callback_code(callback, "MIPNODE_NODCNT"),
            )
            if (
                self._root_relaxation_end_seconds is None
                and (node_count is None or node_count <= 0.0)
            ):
                self._root_relaxation_end_seconds = runtime
            return
        if (
            where == getattr(callback, "MIPSOL", None)
            and self._first_incumbent_runtime_seconds is None
        ):
            self._first_incumbent_runtime_seconds = runtime

    def _sample_callback(self, model: Any, grb: Any, where: int, *, event: str) -> GurobiMipProgressSample:
        callback = grb.Callback
        runtime = _cb_get(model, _callback_code(callback, "RUNTIME")) or 0.0
        work = _cb_get(model, _callback_code(callback, "WORK"))
        if where == callback.MIPSOL:
            incumbent = _cb_get(model, _callback_code(callback, "MIPSOL_OBJ"))
            best_bound = _cb_get(model, _callback_code(callback, "MIPSOL_OBJBND"))
            node_count = _cb_get(model, _callback_code(callback, "MIPSOL_NODCNT"))
            solution_count = _safe_int(_cb_get(model, _callback_code(callback, "MIPSOL_SOLCNT")))
        else:
            incumbent = _cb_get(model, _callback_code(callback, "MIP_OBJBST"))
            best_bound = _cb_get(model, _callback_code(callback, "MIP_OBJBND"))
            node_count = _cb_get(model, _callback_code(callback, "MIP_NODCNT"))
            solution_count = _safe_int(_cb_get(model, _callback_code(callback, "MIP_SOLCNT")))

        incumbent = _finite_or_none(incumbent, grb)
        best_bound = _finite_or_none(best_bound, grb)
        return GurobiMipProgressSample(
            runtime_seconds=runtime,
            node_count=_finite_or_none(node_count, grb),
            incumbent_objective=incumbent,
            best_bound=best_bound,
            mip_gap=_mip_gap(incumbent, best_bound),
            solution_count=solution_count,
            work=_finite_or_none(work, grb),
            event=event,
        )

    def _is_new_incumbent(self, sample: GurobiMipProgressSample) -> bool:
        if sample.incumbent_objective is None:
            return False
        if self._last_incumbent_objective is None or not math.isclose(
            sample.incumbent_objective,
            self._last_incumbent_objective,
        ):
            self._last_incumbent_objective = sample.incumbent_objective
            self._last_solution_count = sample.solution_count
            return True
        return False


def _cb_get(model: Any, code: Any) -> float | None:
    if code is None:
        return None
    try:
        return float(model.cbGet(code))
    except Exception:
        return None


def _callback_code(callback: Any, name: str) -> Any | None:
    return getattr(callback, name, None)


def _safe_float_attr(model: Any, name: str) -> float | None:
    try:
        return _finite_or_none(float(getattr(model, name)))
    except Exception:
        return None


def _safe_int_attr(model: Any, name: str) -> int | None:
    try:
        return int(getattr(model, name))
    except Exception:
        return None


def _safe_int(value: float | None) -> int | None:
    if value is None:
        return None
    try:
        return int(value)
    except Exception:
        return None


def _finite_or_none(value: float | None, grb: Any | None = None) -> float | None:
    if value is None or not math.isfinite(value):
        return None
    infinity = getattr(grb, "INFINITY", None)
    if infinity is not None and abs(value) >= float(infinity) * 0.5:
        return None
    return float(value)


def _mip_gap(incumbent: float | None, best_bound: float | None) -> float | None:
    if incumbent is None or best_bound is None:
        return None
    denominator = abs(incumbent)
    if denominator <= 1e-12:
        return 0.0 if abs(incumbent - best_bound) <= 1e-12 else None
    return abs(incumbent - best_bound) / denominator
