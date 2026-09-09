from __future__ import annotations

import argparse
from dataclasses import asdict
from datetime import UTC, datetime
import json
from pathlib import Path

from ropeway_skip_stop_optimization.benchmarking.ddd_reservoir_arc_flow import (
    DddReservoirArcFlowRunConfig,
    prepare_ddd_reservoir_arc_flow_run,
)
from ropeway_skip_stop_optimization.benchmarking.optimization_events import (
    OptimizationEventKind,
)
from ropeway_skip_stop_optimization.benchmarking.optimization_live_store import (
    OptimizationLivePaths,
    OptimizationLiveStore,
    reduce_optimization_events,
)
from ropeway_skip_stop_optimization.optimization.ddd.reservoir_arc_flow import (
    DddReservoirArcFlowOptimizer,
    DddReservoirArcFlowProgress,
    DddReservoirArcFlowSolveConfig,
)
from ropeway_skip_stop_optimization.optimization.ddd.reservoir_arc_flow_problem import (
    DddReservoirOperatingMode,
)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Solve an anonymous dispatch-service-recovery reservoir arc-flow."
    )
    parser.add_argument("--config", type=Path)
    parser.add_argument("--example")
    parser.add_argument("--available-fleet", type=int)
    parser.add_argument("--fleet-multiplier", type=float, default=1.5)
    parser.add_argument("--entry-state", default="A_entry_cw")
    parser.add_argument("--warmup", type=float, default=300.0)
    parser.add_argument("--service", type=float, default=1200.0)
    parser.add_argument("--recovery", type=float, default=300.0)
    parser.add_argument("--dispatch-step", type=float, default=1.0)
    parser.add_argument("--waiting-max", type=float)
    parser.add_argument("--waiting-step", type=float, default=1.0)
    parser.add_argument(
        "--mode",
        choices=tuple(item.value for item in DddReservoirOperatingMode),
        default=DddReservoirOperatingMode.SKIP_STOP.value,
    )
    parser.add_argument("--time-limit", type=float, default=600.0)
    parser.add_argument("--threads", type=int, default=8)
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument("--mip-focus", type=int, choices=range(4), default=1)
    parser.add_argument("--mip-gap", type=float, default=0.0)
    parser.add_argument("--nodefile-start", type=float, default=8.0)
    parser.add_argument("--soft-memory-limit", type=float, default=28.0)
    parser.add_argument("--progress-interval", type=float, default=30.0)
    parser.add_argument("--build-only", action="store_true")
    parser.add_argument("--resume-incumbent", type=Path)
    parser.add_argument(
        "--import-incumbent",
        type=Path,
        help="Validated compatible no-wait checkpoint used as a waiting MIP start.",
    )
    parser.add_argument("--gurobi-output", action="store_true")
    parser.add_argument("--progress", action="store_true")
    parser.add_argument("--frontend-live", action="store_true")
    parser.add_argument(
        "--frontend-root",
        type=Path,
        default=Path("frontend/public/generated/optimization"),
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("benchmarks/output/ddd_reservoir_arc_flow"),
    )
    parser.add_argument("--campaign-id")
    args = parser.parse_args()
    raw = _load_config(args.config)
    example_id = args.example or raw.get("example_id")
    if not example_id:
        parser.error("--example or config.example_id is required")
    campaign_id = args.campaign_id or raw.get("campaign_id") or (
        f"{example_id}_reservoir_k{args.available_fleet or raw.get('available_fleet_count') or 'auto'}"
        f"_wait{(args.waiting_max if args.waiting_max is not None else float(raw.get('waiting_max_seconds', 0.0))):g}"
    )
    run = DddReservoirArcFlowRunConfig(
        example_id=str(example_id),
        available_fleet_count=_pick(args.available_fleet, raw, "available_fleet_count"),
        fleet_multiplier_over_all_stop=float(
            raw.get("fleet_multiplier_over_all_stop", args.fleet_multiplier)
        ),
        entry_state_id=str(raw.get("entry_state_id", args.entry_state)),
        warmup_seconds=float(raw.get("warmup_seconds", args.warmup)),
        service_seconds=float(raw.get("service_seconds", args.service)),
        recovery_seconds=float(raw.get("recovery_seconds", args.recovery)),
        dispatch_step_seconds=float(raw.get("dispatch_step_seconds", args.dispatch_step)),
        waiting_max_seconds=float(
            args.waiting_max
            if args.waiting_max is not None
            else raw.get("waiting_max_seconds", 0.0)
        ),
        waiting_step_seconds=float(raw.get("waiting_step_seconds", args.waiting_step)),
        operating_mode=DddReservoirOperatingMode(str(raw.get("mode", args.mode))),
    )
    prepared = prepare_ddd_reservoir_arc_flow_run(run)
    output_dir = args.output_dir / campaign_id
    checkpoint = output_dir / "incumbent.json"
    store = (
        OptimizationLiveStore(
            OptimizationLivePaths(
                canonical_campaign_dir=output_dir,
                frontend_root=args.frontend_root,
            )
        )
        if args.frontend_live
        else None
    )
    policy_id = f"reservoir_{run.operating_mode.value}_wait_{run.waiting_max_seconds:g}"
    if store is not None:
        store.append_new(
            OptimizationEventKind.CAMPAIGN_STARTED,
            campaign_id,
            payload={
                "label": raw.get("label", f"{example_id}: anonymous reservoir arc-flow"),
                "objective": "lex_unserved_then_journey_time",
                "method": "ddd_anonymous_reservoir_arc_flow",
                "formulation": "anonymous_reservoir_arc_flow",
                "campaign_kind": "reservoir_arc_flow",
                "trial_count": 1,
            },
        )
        store.append_new(
            OptimizationEventKind.TRIAL_STARTED,
            campaign_id,
            policy_id=policy_id,
            available_fleet_count=prepared.problem.available_fleet_count,
            trial_fingerprint=prepared.problem.fingerprint,
            stage="build",
            payload={
                "total_demand": prepared.problem.total_demand,
                "all_stop_maximum_cabin_count": prepared.all_stop_maximum_cabin_count,
                "waiting_max_seconds": run.waiting_max_seconds,
            },
        )
        _publish(store)

    width = 0

    def progress(sample: DddReservoirArcFlowProgress) -> None:
        nonlocal width
        line = (
            f"RES K<={prepared.problem.available_fleet_count:03d} "
            f"phase={sample.phase:<13} | "
            f"U={_number(sample.primary_lower_bound)}/{_number(sample.primary_upper_bound)} "
            f"served={_number(sample.served_lower_bound)}/{_number(sample.served_upper_bound)} | "
            f"JT={_number(sample.secondary_lower_bound)}/{_number(sample.secondary_upper_bound)} | "
            f"nodes={sample.node_count:,.0f} sol={sample.solution_count:03d} | "
            f"N/A={sample.network_node_count:,}/{sample.network_arc_count:,} "
            f"p={sample.passenger_variable_count:,} rows={sample.linear_constraint_count:,} "
            f"rss={sample.peak_rss_gb:.1f}GB | left={_clock(sample.remaining_seconds)}"
        )
        if args.progress:
            print("\r" + line + " " * max(0, width - len(line)), end="", flush=True)
            width = len(line)
        if store is not None:
            store.append_new(
                OptimizationEventKind.SOLVER_SAMPLE,
                campaign_id,
                policy_id=policy_id,
                available_fleet_count=prepared.problem.available_fleet_count,
                trial_fingerprint=prepared.problem.fingerprint,
                stage=sample.phase,
                global_certified_lower_bound=sample.primary_lower_bound,
                global_validated_upper_bound=sample.primary_upper_bound,
                global_relative_gap=(
                    None
                    if sample.primary_lower_bound is None
                    or sample.primary_upper_bound is None
                    else max(0.0, sample.primary_upper_bound - sample.primary_lower_bound)
                    / max(1.0, abs(sample.primary_upper_bound))
                ),
                elapsed_seconds=sample.elapsed_seconds,
                payload={
                    **asdict(sample),
                    "primary_objective": "unserved_passengers",
                    "remaining_budget_seconds": sample.remaining_seconds,
                },
            )
            _publish(store)

    solver_config = DddReservoirArcFlowSolveConfig(
        total_time_limit_seconds=float(raw.get("time_limit_seconds", args.time_limit)),
        threads=int(raw.get("threads", args.threads)),
        seed=int(raw.get("seed", args.seed)),
        mip_focus=int(raw.get("mip_focus", args.mip_focus)),
        mip_gap=float(raw.get("mip_gap", args.mip_gap)),
        output_flag=bool(raw.get("gurobi_output", args.gurobi_output)),
        progress_interval_seconds=float(
            raw.get("progress_interval_seconds", args.progress_interval)
        ),
        nodefile_start_gb=float(raw.get("nodefile_start_gb", args.nodefile_start)),
        soft_memory_limit_gb=float(
            raw.get("soft_memory_limit_gb", args.soft_memory_limit)
        ),
        nodefile_dir=output_dir / "nodefiles",
        checkpoint_path=checkpoint,
    )
    result = DddReservoirArcFlowOptimizer(solver_config).solve(
        prepared.problem,
        progress_hook=progress,
        resume_checkpoint_path=args.resume_incumbent,
        import_checkpoint_path=args.import_incumbent,
        build_only=args.build_only,
    )
    if args.progress:
        print()
    output_dir.mkdir(parents=True, exist_ok=True)
    result_path = output_dir / "result.json"
    payload = {
        "schema_version": 1,
        "campaign_id": campaign_id,
        "example_id": example_id,
        "run_config": _jsonable(asdict(run)),
        **result.to_payload(),
    }
    _atomic_write(result_path, payload)
    if store is not None:
        store.append_new(
            OptimizationEventKind.TRIAL_COMPLETED,
            campaign_id,
            policy_id=policy_id,
            available_fleet_count=prepared.problem.available_fleet_count,
            trial_fingerprint=prepared.problem.fingerprint,
            stage="validation",
            global_certified_lower_bound=result.primary_lower_bound,
            global_validated_upper_bound=result.primary_upper_bound,
            elapsed_seconds=result.total_seconds,
            payload={
                **payload,
                "status": result.status.value,
                "result_path": str(result_path),
            },
        )
        store.append_new(
            OptimizationEventKind.CAMPAIGN_COMPLETED,
            campaign_id,
            payload={"status": "complete", "result_path": str(result_path)},
        )
        _publish(store)
    print(
        f"status={result.status.value} U={_number(result.primary_lower_bound)}/"
        f"{_number(result.primary_upper_bound)} served={_number(result.served_lower_bound)}/"
        f"{_number(result.served_upper_bound)} fleet={result.dispatched_fleet_count or '-'} "
        f"time={result.total_seconds:.1f}s output={result_path}"
    )


def _load_config(path: Path | None) -> dict[str, object]:
    if path is None:
        return {}
    return dict(json.loads(path.read_text(encoding="utf-8")))


def _pick(cli_value, raw: dict[str, object], key: str):
    return cli_value if cli_value is not None else raw.get(key)


def _number(value: float | None) -> str:
    return "-" if value is None else f"{value:,.1f}"


def _clock(value: float) -> str:
    seconds = max(0, int(value))
    return f"{seconds // 3600:02d}:{seconds % 3600 // 60:02d}:{seconds % 60:02d}"


def _publish(store: OptimizationLiveStore) -> None:
    store.publish(reduce_optimization_events(store.read_events()))


def _jsonable(value):
    if hasattr(value, "value"):
        return value.value
    if isinstance(value, dict):
        return {key: _jsonable(item) for key, item in value.items()}
    if isinstance(value, (tuple, list)):
        return [_jsonable(item) for item in value]
    return value


def _atomic_write(path: Path, payload: dict[str, object]) -> None:
    import os
    import tempfile

    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.", suffix=".tmp")
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            json.dump(payload, stream, indent=2, sort_keys=True)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    except BaseException:
        Path(temporary).unlink(missing_ok=True)
        raise


if __name__ == "__main__":
    main()
