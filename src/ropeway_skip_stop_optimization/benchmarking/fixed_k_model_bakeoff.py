from __future__ import annotations

from dataclasses import dataclass, field, replace
from enum import StrEnum
import json
from pathlib import Path
from time import perf_counter
from typing import Callable

from ropeway_skip_stop_optimization.benchmarking.ddd_fixed_k_arc_flow import (
    DddFixedKArcFlowFormulation,
    DddFixedKArcFlowRunConfig,
    DddPreparedFixedKArcFlowRun,
    prepare_ddd_fixed_k_arc_flow_run,
    run_ddd_fixed_k_arc_flow,
    write_ddd_fixed_k_arc_flow_result,
)
from ropeway_skip_stop_optimization.exports.json_codec import to_jsonable
from ropeway_skip_stop_optimization.optimization.ddd import (
    DddArcFlowResourceRowMode,
    DddFixedKArcFlowProgress,
    DddFixedKOperatingMode,
    DddFixedKStartPolicy,
)
from ropeway_skip_stop_optimization.optimization.ean import (
    AllPairsHeadwayPairBuilder,
    EanBuildProgressEvent,
    EanHeadwayPairScope,
    EanMipStartStrategy,
    EanOptimizationConfig,
    EanOptimizer,
    EanPassengerObjective,
    EanPassengerServiceProblem,
    EanSolveConfig,
    GurobiSolverPolicy,
)
from ropeway_skip_stop_optimization.optimization.solver_progress import (
    GurobiMipProgressRecorder,
    GurobiMipProgressSample,
)


class FixedKModelBakeoffMethod(StrEnum):
    EAN_PAIRWISE_SHARED = "ean_pairwise_shared"
    DDD_ARC_FLOW_LABELED = "ddd_arc_flow_labeled"


@dataclass(frozen=True, slots=True)
class FixedKModelBakeoffConfig:
    campaign_id: str
    example_id: str
    cabin_counts: tuple[int, ...]
    methods: tuple[FixedKModelBakeoffMethod, ...] = (
        FixedKModelBakeoffMethod.EAN_PAIRWISE_SHARED,
        FixedKModelBakeoffMethod.DDD_ARC_FLOW_LABELED,
    )
    objective: EanPassengerObjective = EanPassengerObjective.JOURNEY_TIME
    operating_mode: DddFixedKOperatingMode = DddFixedKOperatingMode.SKIP_STOP
    start_policy: DddFixedKStartPolicy = DddFixedKStartPolicy.BALANCED_REFERENCE
    total_time_limit_seconds: float = 1_800.0
    start_layout_time_limit_seconds: float = 600.0
    cp_seed_time_limit_seconds: float = 120.0
    seed_passenger_time_limit_seconds: float = 60.0
    sample_interval_seconds: float = 5.0
    threads: int | None = None
    cp_seed_workers: int = 8
    seed: int = 0

    @classmethod
    def from_dict(cls, value: dict[str, object]) -> FixedKModelBakeoffConfig:
        raw_threads = value.get("threads")
        return cls(
            campaign_id=str(value["campaign_id"]),
            example_id=str(value["example_id"]),
            cabin_counts=tuple(int(item) for item in value["cabin_counts"]),
            methods=tuple(
                FixedKModelBakeoffMethod(str(item)) for item in value["methods"]
            ),
            objective=EanPassengerObjective(
                str(value.get("objective", EanPassengerObjective.JOURNEY_TIME.value))
            ),
            operating_mode=DddFixedKOperatingMode(
                str(value.get("operating_mode", DddFixedKOperatingMode.SKIP_STOP.value))
            ),
            start_policy=DddFixedKStartPolicy(
                str(value.get("start_policy", DddFixedKStartPolicy.BALANCED_REFERENCE.value))
            ),
            total_time_limit_seconds=float(
                value.get("total_time_limit_seconds_per_trial", 1_800.0)
            ),
            start_layout_time_limit_seconds=float(
                value.get("start_layout_time_limit_seconds", 600.0)
            ),
            cp_seed_time_limit_seconds=float(
                value.get("cp_seed_time_limit_seconds", 120.0)
            ),
            seed_passenger_time_limit_seconds=float(
                value.get("seed_passenger_time_limit_seconds", 60.0)
            ),
            sample_interval_seconds=float(
                value.get("sample_interval_seconds", 5.0)
            ),
            threads=None if raw_threads is None else int(raw_threads),
            cp_seed_workers=int(value.get("cp_seed_workers", 8)),
            seed=int(value.get("seed", 0)),
        )

    def validate(self) -> None:
        if not self.campaign_id or not self.example_id:
            raise ValueError("fixed-K bake-off needs campaign and example ids")
        if not self.cabin_counts or any(value <= 0 for value in self.cabin_counts):
            raise ValueError("fixed-K bake-off needs positive cabin counts")
        if len(set(self.cabin_counts)) != len(self.cabin_counts):
            raise ValueError("fixed-K bake-off cabin counts must be unique")
        if not self.methods or len(set(self.methods)) != len(self.methods):
            raise ValueError("fixed-K bake-off methods must be unique and nonempty")
        if self.operating_mode is not DddFixedKOperatingMode.SKIP_STOP:
            raise NotImplementedError("the first bake-off tranche is Skip-Stop only")
        if min(
            self.total_time_limit_seconds,
            self.start_layout_time_limit_seconds,
            self.seed_passenger_time_limit_seconds,
            self.sample_interval_seconds,
        ) <= 0 or self.cp_seed_time_limit_seconds < 0:
            raise ValueError("fixed-K bake-off budgets are invalid")
        if self.threads is not None and self.threads <= 0:
            raise ValueError("fixed-K bake-off threads must be positive")
        if self.cp_seed_workers <= 0 or self.seed < 0:
            raise ValueError("fixed-K bake-off solver controls are invalid")


@dataclass(frozen=True, slots=True)
class FixedKModelBakeoffTrialResult:
    method: FixedKModelBakeoffMethod
    cabin_count: int
    problem_fingerprint: str
    status: str
    certified_lower_bound: float
    validated_upper_bound: float | None
    relative_gap: float | None
    total_seconds: float
    payload: dict[str, object]


ProgressCallback = Callable[[dict[str, object]], None]


def prepare_fixed_k_bakeoff_instance(
    config: FixedKModelBakeoffConfig,
    cabin_count: int,
) -> DddPreparedFixedKArcFlowRun:
    config.validate()
    return prepare_ddd_fixed_k_arc_flow_run(
        _ddd_run_config(config, cabin_count)
    )


def run_fixed_k_bakeoff_trial(
    config: FixedKModelBakeoffConfig,
    *,
    method: FixedKModelBakeoffMethod,
    prepared: DddPreparedFixedKArcFlowRun,
    output_dir: Path,
    progress_callback: ProgressCallback | None = None,
) -> FixedKModelBakeoffTrialResult:
    config.validate()
    cabin_count = prepared.problem.fleet_cardinality
    trial_dir = output_dir / method.value / f"k{cabin_count}"
    trial_dir.mkdir(parents=True, exist_ok=True)
    if method is FixedKModelBakeoffMethod.DDD_ARC_FLOW_LABELED:
        return _run_ddd_trial(
            config,
            prepared=prepared,
            trial_dir=trial_dir,
            progress_callback=progress_callback,
        )
    if method is FixedKModelBakeoffMethod.EAN_PAIRWISE_SHARED:
        return _run_ean_trial(
            config,
            prepared=prepared,
            trial_dir=trial_dir,
            progress_callback=progress_callback,
        )
    raise ValueError(f"unsupported fixed-K bake-off method: {method.value}")


def write_fixed_k_bakeoff_summary(
    path: Path,
    *,
    config: FixedKModelBakeoffConfig,
    results: tuple[FixedKModelBakeoffTrialResult, ...],
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "schema_version": 1,
        "config": to_jsonable(config),
        "results": [to_jsonable(result) for result in results],
        "portfolio_by_k": _portfolio_by_k(results),
    }
    path.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _run_ddd_trial(
    config: FixedKModelBakeoffConfig,
    *,
    prepared: DddPreparedFixedKArcFlowRun,
    trial_dir: Path,
    progress_callback: ProgressCallback | None,
) -> FixedKModelBakeoffTrialResult:
    started = perf_counter()

    def progress(sample: DddFixedKArcFlowProgress) -> None:
        if progress_callback is None:
            return
        progress_callback(
            {
                "phase": sample.phase,
                "elapsed_seconds": perf_counter() - started,
                "certified_lower_bound": sample.certified_lower_bound,
                "solver_incumbent": sample.solver_incumbent,
                "solver_bound": sample.solver_bound,
                "solver_gap": sample.solver_gap,
                "node_count": sample.node_count,
                "solution_count": sample.solution_count,
                "remaining_seconds": sample.remaining_seconds,
                "movement_variable_count": sample.movement_variable_count,
                "passenger_variable_count": sample.passenger_variable_count,
                "linear_constraint_count": sample.linear_constraint_count,
                "resource_row_count": sample.resource_row_count,
            }
        )

    run_result = run_ddd_fixed_k_arc_flow(
        _ddd_run_config(config, prepared.problem.fleet_cardinality),
        progress_hook=progress,
        prepared_run=prepared,
    )
    write_ddd_fixed_k_arc_flow_result(run_result, trial_dir / "result.json")
    solve = run_result.solve_result
    result = FixedKModelBakeoffTrialResult(
        method=FixedKModelBakeoffMethod.DDD_ARC_FLOW_LABELED,
        cabin_count=prepared.problem.fleet_cardinality,
        problem_fingerprint=solve.problem_fingerprint,
        status=solve.status.value,
        certified_lower_bound=solve.certified_lower_bound,
        validated_upper_bound=solve.validated_upper_bound,
        relative_gap=solve.relative_gap,
        total_seconds=run_result.total_seconds,
        payload=run_result.to_payload(),
    )
    _write_trial_result(trial_dir / "bakeoff_result.json", result)
    return result


def _run_ean_trial(
    config: FixedKModelBakeoffConfig,
    *,
    prepared: DddPreparedFixedKArcFlowRun,
    trial_dir: Path,
    progress_callback: ProgressCallback | None,
) -> FixedKModelBakeoffTrialResult:
    started = perf_counter()
    sparse_artifact = prepared.problem.artifact
    pair_started = perf_counter()
    if progress_callback is not None:
        progress_callback(
            {
                "phase": "artifact_pairs",
                "elapsed_seconds": 0.0,
                "certified_lower_bound": 0.0,
            }
        )

    def pair_progress(processed: int, pair_count: int) -> None:
        if progress_callback is not None:
            progress_callback(
                {
                    "phase": "artifact_pairs",
                    "elapsed_seconds": perf_counter() - started,
                    "certified_lower_bound": 0.0,
                    "processed_checkpoint_count": processed,
                    "pair_count": pair_count,
                }
            )

    pairs = AllPairsHeadwayPairBuilder().build(
        sparse_artifact.headway_candidates,
        sparse_artifact.headway_checkpoints,
        progress_callback=pair_progress,
    )
    pair_seconds = perf_counter() - pair_started
    build_metrics = sparse_artifact.build_metrics
    if build_metrics is not None:
        build_metrics = replace(
            build_metrics,
            pair_seconds=pair_seconds,
            total_seconds=build_metrics.total_seconds + pair_seconds,
            pair_count=len(pairs),
            original_pair_count=len(pairs),
        )
    artifact = replace(
        sparse_artifact,
        headway_pairs=pairs,
        headway_pair_scope=EanHeadwayPairScope.COMPLETE,
        build_metrics=build_metrics,
    )
    artifact.validate()

    recorder = _PublishingProgressRecorder(
        started=started,
        callback=progress_callback,
    )

    def build_progress(event: EanBuildProgressEvent) -> None:
        if progress_callback is None:
            return
        progress_callback(
            {
                "phase": event.stage.value,
                "phase_event": event.kind.value,
                "elapsed_seconds": perf_counter() - started,
                "certified_lower_bound": 0.0,
                "pair_count": event.pair_count,
                "variable_count": event.variable_count,
                "constraint_count": event.constraint_count,
                "nonzero_count": event.nonzero_count,
            }
        )

    optimization = EanOptimizationConfig.from_selection(
        "all,tight_big_m_bounds,fixed_start_headway_precedence,"
        "headway_order_pairwise_shared"
    )
    remaining_total_seconds = max(
        0.001,
        config.total_time_limit_seconds - (perf_counter() - started),
    )
    result = EanOptimizer(
        EanSolveConfig(
            solver_policy=GurobiSolverPolicy(
                mip_gap=0.0,
                threads=config.threads,
                mip_focus=0,
                numeric_focus=3,
                feasibility_tolerance=1e-9,
            ),
            optimization_config=optimization,
            progress_recorder=recorder,
            progress_sample_interval_seconds=config.sample_interval_seconds,
            total_time_limit_seconds=remaining_total_seconds,
            build_progress_callback=build_progress,
        )
    ).solve(
        EanPassengerServiceProblem(
            scenario=prepared.scenario,
            artifact=artifact,
            objective=config.objective,
            mip_start_strategy=(
                EanMipStartStrategy.OPTIMIZED_ALL_STOP
                if prepared.all_stop_maximum_cabin_count is not None
                and prepared.problem.fleet_cardinality
                <= prepared.all_stop_maximum_cabin_count
                else EanMipStartStrategy.NONE
            ),
        )
    )
    metadata = result.metadata
    lower_bound = max(0.0, metadata.best_bound or 0.0)
    upper_bound = metadata.objective_value_seconds
    gap = (
        None
        if upper_bound is None
        else max(0.0, upper_bound - lower_bound) / max(abs(upper_bound), 1e-9)
    )
    payload = {
        "method": FixedKModelBakeoffMethod.EAN_PAIRWISE_SHARED.value,
        "problem_fingerprint": prepared.problem.fingerprint,
        "metadata": to_jsonable(metadata),
        "artifact_pair_count": len(pairs),
        "pair_materialization_seconds": pair_seconds,
        "validated_movement_plan": result.movement_plan is not None,
        "validated_passenger_plan": result.passenger_plan is not None,
    }
    trial = FixedKModelBakeoffTrialResult(
        method=FixedKModelBakeoffMethod.EAN_PAIRWISE_SHARED,
        cabin_count=prepared.problem.fleet_cardinality,
        problem_fingerprint=prepared.problem.fingerprint,
        status=metadata.status,
        certified_lower_bound=lower_bound,
        validated_upper_bound=upper_bound,
        relative_gap=gap,
        total_seconds=perf_counter() - started,
        payload=payload,
    )
    _write_trial_result(trial_dir / "result.json", trial)
    return trial


@dataclass
class _PublishingProgressRecorder:
    started: float
    callback: ProgressCallback | None
    delegate: GurobiMipProgressRecorder = field(
        default_factory=GurobiMipProgressRecorder
    )
    _last_heartbeat_elapsed: float = 0.0
    _current_phase: str = "presolve"
    _last_certified_lower_bound: float | None = None
    _last_solver_incumbent: float | None = None
    _last_solver_bound: float | None = None
    _last_solver_gap: float | None = None

    @property
    def samples(self) -> list[GurobiMipProgressSample]:
        return self.delegate.samples

    @property
    def phase_metrics(self):
        return self.delegate.phase_metrics

    def begin_run(self) -> int:
        return self.delegate.begin_run()

    def record_callback(
        self,
        model,
        grb,
        where: int,
        *,
        sample_interval_seconds: float,
    ) -> None:
        before = len(self.delegate.samples)
        self.delegate.record_callback(
            model,
            grb,
            where,
            sample_interval_seconds=sample_interval_seconds,
        )
        self._publish_new(before)
        elapsed = perf_counter() - self.started
        observed_phase = _gurobi_callback_phase(grb, where)
        if observed_phase is not None and _phase_rank(observed_phase) > _phase_rank(
            self._current_phase
        ):
            self._current_phase = observed_phase
        if (
            self.callback is not None
            and len(self.delegate.samples) == before
            and elapsed - self._last_heartbeat_elapsed >= sample_interval_seconds
        ):
            self.callback(
                {
                    "phase": self._current_phase,
                    "elapsed_seconds": elapsed,
                    "certified_lower_bound": self._last_certified_lower_bound,
                    "solver_incumbent": self._last_solver_incumbent,
                    "solver_bound": self._last_solver_bound,
                    "solver_gap": self._last_solver_gap,
                    "heartbeat": True,
                }
            )
            self._last_heartbeat_elapsed = elapsed

    def record_final(self, model, grb) -> None:
        before = len(self.delegate.samples)
        self.delegate.record_final(model, grb)
        self._publish_new(before)

    def _publish_new(self, start: int) -> None:
        if self.callback is None:
            return
        for sample in self.delegate.samples[start:]:
            lower = max(0.0, sample.best_bound or 0.0)
            self._last_certified_lower_bound = lower
            self._last_solver_incumbent = sample.incumbent_objective
            self._last_solver_bound = sample.best_bound
            self._last_solver_gap = sample.mip_gap
            self.callback(
                {
                    "phase": (
                        "branch_and_bound"
                        if (sample.node_count or 0.0) > 0
                        else "root_relaxation"
                    ),
                    "sample_event": sample.event,
                    "elapsed_seconds": perf_counter() - self.started,
                    "solver_runtime_seconds": sample.runtime_seconds,
                    "certified_lower_bound": lower,
                    "solver_incumbent": sample.incumbent_objective,
                    "solver_bound": sample.best_bound,
                    "solver_gap": sample.mip_gap,
                    "node_count": sample.node_count,
                    "solution_count": sample.solution_count,
                    "work": sample.work,
                }
            )
            self._last_heartbeat_elapsed = perf_counter() - self.started


def _ddd_run_config(
    config: FixedKModelBakeoffConfig,
    cabin_count: int,
) -> DddFixedKArcFlowRunConfig:
    return DddFixedKArcFlowRunConfig(
        example_id=config.example_id,
        cabin_count=cabin_count,
        operating_mode=config.operating_mode,
        objective=config.objective,
        start_policy=config.start_policy,
        start_layout_time_limit_seconds=config.start_layout_time_limit_seconds,
        total_time_limit_seconds=config.total_time_limit_seconds,
        cp_seed_time_limit_seconds=config.cp_seed_time_limit_seconds,
        cp_seed_workers=config.cp_seed_workers,
        solver_threads=config.threads,
        mip_gap=0.0,
        mip_focus=0,
        seed=config.seed,
        seed_passenger_time_limit_seconds=(
            config.seed_passenger_time_limit_seconds
        ),
        formulation=DddFixedKArcFlowFormulation.LABELED,
        waiting_headway_multiplier=0.0,
        resource_row_mode=DddArcFlowResourceRowMode.EAGER_MAXIMAL_CLIQUES,
    )


def _gurobi_callback_phase(grb, where: int) -> str | None:
    callback = grb.Callback
    if where == getattr(callback, "PRESOLVE", None):
        return "presolve"
    if where in {
        getattr(callback, "SIMPLEX", None),
        getattr(callback, "BARRIER", None),
    }:
        return "root_relaxation"
    if where == getattr(callback, "MIPNODE", None):
        return "branch_and_bound"
    if where == getattr(callback, "MIPSOL", None):
        return None
    return None


def _phase_rank(phase: str) -> int:
    return {
        "presolve": 0,
        "root_relaxation": 1,
        "branch_and_bound": 2,
    }.get(phase, -1)


def _portfolio_by_k(
    results: tuple[FixedKModelBakeoffTrialResult, ...],
) -> dict[str, dict[str, float | None]]:
    output: dict[str, dict[str, float | None]] = {}
    for cabin_count in sorted({item.cabin_count for item in results}):
        values = [item for item in results if item.cabin_count == cabin_count]
        fingerprints = {item.problem_fingerprint for item in values}
        if len(fingerprints) != 1:
            raise ValueError(
                f"cannot combine K={cabin_count} trials from different problems: "
                f"{sorted(fingerprints)}"
            )
        lower = max(item.certified_lower_bound for item in values)
        uppers = [
            item.validated_upper_bound
            for item in values
            if item.validated_upper_bound is not None
        ]
        upper = min(uppers) if uppers else None
        output[str(cabin_count)] = {
            "certified_lower_bound": lower,
            "validated_upper_bound": upper,
            "relative_gap": (
                None
                if upper is None
                else max(0.0, upper - lower) / max(abs(upper), 1e-9)
            ),
        }
    return output


def _write_trial_result(
    path: Path,
    result: FixedKModelBakeoffTrialResult,
) -> None:
    path.write_text(
        json.dumps(to_jsonable(result), indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
