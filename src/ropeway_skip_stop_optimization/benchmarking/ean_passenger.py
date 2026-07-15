from __future__ import annotations

import hashlib
import json
import platform
import socket
import subprocess
import sys
from dataclasses import asdict, dataclass, field, replace
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from ropeway_skip_stop_optimization.examples.registry import get_example
from ropeway_skip_stop_optimization.exports.json_codec import to_jsonable, write_json
from ropeway_skip_stop_optimization.exports.runner import (
    DEFAULT_OUTPUT_ROOT,
    _safe_checkpoint_part,
    build_artifact_set,
    run_artifact_set,
)
from ropeway_skip_stop_optimization.optimization.ean import (
    EanOptimizationConfig,
    GurobiSolverPolicy,
    GurobiSolverPolicyPreset,
    gurobi_solver_policy_for_preset,
)
from ropeway_skip_stop_optimization.optimization.solver_progress import (
    GurobiMipProgressRecorder,
    GurobiMipProgressSample,
)
from ropeway_skip_stop_optimization.progress import ProgressReporter


DEFAULT_BENCHMARK_OUTPUT_DIR = Path("benchmarks/output")
_MAX_RUN_ID_SELECTION_PART_LENGTH = 96


@dataclass(frozen=True)
class BenchmarkRunConfig:
    example_id: str = "three_station_v0"
    artifact_set_id: str = "ean_passenger_journey_time"
    ean_solver_policy: GurobiSolverPolicyPreset = GurobiSolverPolicyPreset.QUICK_GOOD_SOLUTION
    time_limit_seconds: float | None = None
    sample_interval_seconds: float = 5.0
    ean_optimization_config: EanOptimizationConfig = field(default_factory=EanOptimizationConfig)
    label: str | None = None
    output_dir: Path = DEFAULT_BENCHMARK_OUTPUT_DIR
    result_dir: Path | None = None
    plot_dir: Path | None = None
    checkpoint_dir: Path | None = None
    resume_checkpoint: Path | None = None
    resume_latest_checkpoint: bool = False
    export_frontend_artifacts: bool = False
    frontend_output_root: Path = DEFAULT_OUTPUT_ROOT
    clean_frontend_output: bool = False
    progress: bool = True


@dataclass(frozen=True)
class BenchmarkRunResult:
    run_id: str
    label: str
    timestamp: str
    git_commit: str | None
    git_dirty: bool
    hostname: str
    platform: str
    python_version: str
    gurobi_version: str | None
    example_id: str
    family_id: str | None
    variant_id: str | None
    artifact_set_id: str
    objective: str | None
    solver_policy: dict[str, Any]
    ean_optimizations: tuple[str, ...]
    ean_optimization_config: dict[str, Any]
    ean_formulation_config: dict[str, Any]
    model_variable_count: int | None
    model_constraint_count: int | None
    model_nonzero_count: int | None
    model_setup_runtime_seconds: float | None
    demand_group_count: int | None
    ride_candidate_count: int | None
    slot_variable_count: int | None
    objective_value_seconds: float | None
    objective_passenger_hours: float | None
    best_bound: float | None
    mip_gap: float | None
    runtime_seconds: float | None
    node_count: float | None
    solution_count: int | None
    served_passenger_count: int | None
    unserved_passenger_count: int | None
    skipped_visit_count: int | None
    visible_skipped_visit_count: int | None
    checkpoint_read_path: str | None
    checkpoint_final_solution_path: str | None
    export_artifact_paths: tuple[str, ...]
    progress_samples: tuple[GurobiMipProgressSample, ...]


def run_ean_passenger_benchmark(config: BenchmarkRunConfig) -> tuple[BenchmarkRunResult, Path]:
    run_id = _run_id(config)
    result_dir = config.result_dir or config.output_dir / "results"
    artifact_output_root = (
        config.frontend_output_root if config.export_frontend_artifacts else config.output_dir / "artifacts" / run_id
    )
    checkpoint_dir = config.checkpoint_dir or config.output_dir / "checkpoints" / run_id
    resume_checkpoint = config.resume_checkpoint
    if config.resume_latest_checkpoint:
        resume_checkpoint = _latest_checkpoint_in_root(
            config.checkpoint_dir or config.output_dir / "checkpoints",
            example_id=config.example_id,
            artifact_set_id=config.artifact_set_id,
        )

    recorder = GurobiMipProgressRecorder()
    solver_policy = _solver_policy(config)
    example = get_example(config.example_id)
    artifact_set = build_artifact_set(config.artifact_set_id)

    export_result = run_artifact_set(
        example,
        artifact_set,
        output_root=artifact_output_root,
        ean_solver_policy=solver_policy,
        ean_checkpoint_dir=checkpoint_dir,
        ean_resume_checkpoint=resume_checkpoint,
        ean_optimization_config=config.ean_optimization_config,
        ean_progress_recorder=recorder,
        ean_progress_sample_interval_seconds=config.sample_interval_seconds,
        progress=ProgressReporter(enabled=config.progress),
        clean=config.clean_frontend_output if config.export_frontend_artifacts else True,
    )
    passenger_result = _load_passenger_result(export_result.artifact_paths)
    metadata = passenger_result.get("metadata", {})
    resolved_optimization_config = metadata.get("optimization_config")
    if not isinstance(resolved_optimization_config, dict):
        resolved_optimization_config = to_jsonable(config.ean_optimization_config)
    resolved_formulation_config = resolved_optimization_config.get("formulation")
    if not isinstance(resolved_formulation_config, dict):
        resolved_formulation_config = to_jsonable(config.ean_optimization_config.formulation)

    result = BenchmarkRunResult(
        run_id=run_id,
        label=config.label or _default_label(config),
        timestamp=datetime.now(timezone.utc).isoformat(timespec="seconds"),
        git_commit=_git_commit(),
        git_dirty=_git_dirty(),
        hostname=socket.gethostname(),
        platform=platform.platform(),
        python_version=sys.version.split()[0],
        gurobi_version=_gurobi_version(),
        example_id=example.metadata.id,
        family_id=example.metadata.family_id,
        variant_id=example.metadata.variant_id,
        artifact_set_id=artifact_set.id,
        objective=metadata.get("objective_kind"),
        solver_policy=to_jsonable(solver_policy),
        ean_optimizations=tuple(name.value for name in config.ean_optimization_config.enabled_names()),
        ean_optimization_config=resolved_optimization_config,
        ean_formulation_config=resolved_formulation_config,
        model_variable_count=metadata.get("variable_count"),
        model_constraint_count=metadata.get("constraint_count"),
        model_nonzero_count=metadata.get("model_nonzero_count"),
        model_setup_runtime_seconds=metadata.get("model_setup_runtime_seconds"),
        demand_group_count=metadata.get("demand_group_count"),
        ride_candidate_count=metadata.get("ride_candidate_count"),
        slot_variable_count=metadata.get("slot_variable_count"),
        objective_value_seconds=metadata.get("objective_value_seconds"),
        objective_passenger_hours=metadata.get("objective_passenger_hours"),
        best_bound=metadata.get("best_bound"),
        mip_gap=metadata.get("mip_gap"),
        runtime_seconds=metadata.get("runtime_seconds"),
        node_count=metadata.get("node_count"),
        solution_count=metadata.get("solution_count"),
        served_passenger_count=metadata.get("served_passenger_count"),
        unserved_passenger_count=metadata.get("unserved_passenger_count"),
        skipped_visit_count=metadata.get("skipped_visit_count"),
        visible_skipped_visit_count=metadata.get("visible_skipped_visit_count"),
        checkpoint_read_path=metadata.get("checkpoint_read_path"),
        checkpoint_final_solution_path=metadata.get("checkpoint_final_solution_path"),
        export_artifact_paths=tuple(path.as_posix() for path in export_result.artifact_paths),
        progress_samples=tuple(recorder.samples),
    )

    output_path = result_dir / f"{run_id}.json"
    write_json(output_path, result)
    return result, output_path


def _solver_policy(config: BenchmarkRunConfig) -> GurobiSolverPolicy:
    policy = gurobi_solver_policy_for_preset(config.ean_solver_policy)
    if config.time_limit_seconds is not None:
        policy = replace(policy, time_limit_seconds=config.time_limit_seconds)
    return policy


def _load_passenger_result(paths: tuple[Path, ...]) -> dict[str, Any]:
    for path in paths:
        if (
            path.name.startswith("ean_passenger_service")
            and path.name.endswith(".json")
            and "movement_plan" not in path.name
            and "physical_replay" not in path.name
        ):
            return json.loads(path.read_text(encoding="utf-8"))
    raise ValueError("EAN passenger benchmark did not produce a passenger service result JSON")


def _latest_checkpoint_in_root(root: Path, *, example_id: str, artifact_set_id: str) -> Path:
    prefix = f"{_safe_checkpoint_part(example_id)}__{_safe_checkpoint_part(artifact_set_id)}__incumbent"
    candidates = [
        path
        for suffix in ("*.sol", "*.mst")
        for path in root.glob(f"**/{prefix}{suffix}")
        if path.is_file()
    ]
    if not candidates:
        raise ValueError(f"No checkpoint found for {example_id}/{artifact_set_id} under {root}")
    return max(candidates, key=lambda path: (path.stat().st_mtime_ns, path.name))


def _run_id(config: BenchmarkRunConfig) -> str:
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    selection = _safe_checkpoint_part(config.ean_optimization_config.selection_label().replace(",", "+"))
    return "__".join(
        (
            timestamp,
            _safe_checkpoint_part(config.example_id),
            _safe_checkpoint_part(config.artifact_set_id),
            _safe_checkpoint_part(str(config.ean_solver_policy.value)),
            _short_run_id_part(selection),
        )
    )


def _short_run_id_part(value: str) -> str:
    if len(value) <= _MAX_RUN_ID_SELECTION_PART_LENGTH:
        return value
    digest = hashlib.sha256(value.encode("utf-8")).hexdigest()[:12]
    prefix_length = _MAX_RUN_ID_SELECTION_PART_LENGTH - len(digest) - 2
    return f"{value[:prefix_length]}__{digest}"


def _default_label(config: BenchmarkRunConfig) -> str:
    return f"{config.example_id} / {config.artifact_set_id} / {config.ean_solver_policy.value}"


def _git_commit() -> str | None:
    try:
        return subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip()
    except Exception:
        return None


def _git_dirty() -> bool:
    try:
        return bool(subprocess.check_output(["git", "status", "--porcelain"], text=True).strip())
    except Exception:
        return False


def _gurobi_version() -> str | None:
    try:
        import gurobipy as gp

        return ".".join(str(part) for part in gp.gurobi.version())
    except Exception:
        return None


def benchmark_result_to_dict(result: BenchmarkRunResult) -> dict[str, Any]:
    return to_jsonable(asdict(result))
