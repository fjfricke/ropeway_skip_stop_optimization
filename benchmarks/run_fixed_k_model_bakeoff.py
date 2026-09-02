from __future__ import annotations

import argparse
import json
from pathlib import Path

from ropeway_skip_stop_optimization.benchmarking.fixed_k_model_bakeoff import (
    FixedKModelBakeoffConfig,
    FixedKModelBakeoffMethod,
    FixedKModelBakeoffTrialResult,
    prepare_fixed_k_bakeoff_instance,
    run_fixed_k_bakeoff_trial,
    write_fixed_k_bakeoff_summary,
)
from ropeway_skip_stop_optimization.benchmarking.optimization_events import (
    OptimizationEventKind,
)
from ropeway_skip_stop_optimization.benchmarking.optimization_live_store import (
    OptimizationLivePaths,
    OptimizationLiveStore,
    reduce_optimization_events,
)
from ropeway_skip_stop_optimization.optimization.ean import EanPassengerObjective


def main() -> None:
    args = _parse_args()
    if args.config is not None:
        config = FixedKModelBakeoffConfig.from_dict(
            json.loads(args.config.read_text(encoding="utf-8"))
        )
    else:
        if args.campaign_id is None:
            raise ValueError("--campaign-id is required without --config")
        config = FixedKModelBakeoffConfig(
            campaign_id=args.campaign_id,
            example_id=args.example,
            cabin_counts=tuple(args.cabins),
            methods=tuple(
                FixedKModelBakeoffMethod(value) for value in args.methods
            ),
            objective=EanPassengerObjective(args.objective),
            total_time_limit_seconds=args.time_limit,
            start_layout_time_limit_seconds=args.start_layout_time_limit,
            cp_seed_time_limit_seconds=args.cp_seed_time_limit,
            seed_passenger_time_limit_seconds=args.seed_passenger_time_limit,
            sample_interval_seconds=args.sample_interval,
            threads=args.threads,
            cp_seed_workers=args.cp_seed_workers,
            seed=args.seed,
        )
    config.validate()
    campaign_dir = args.output_root / config.campaign_id
    store = OptimizationLiveStore(
        OptimizationLivePaths(
            canonical_campaign_dir=campaign_dir,
            frontend_root=args.frontend_root if args.frontend_live else None,
        )
    )
    existing = store.read_events()
    if existing and not args.resume:
        raise ValueError(
            f"campaign {config.campaign_id!r} exists; use --resume or another id"
        )
    completed: set[tuple[str, int]] = set()
    results: list[FixedKModelBakeoffTrialResult] = []
    if existing:
        snapshot = reduce_optimization_events(existing)
        for trial in snapshot["trials"].values():
            if trial["status"] == "complete":
                completed.add(
                    (str(trial["policy_id"]), int(trial["available_fleet_count"]))
                )
                result_path = (
                    campaign_dir
                    / str(trial["policy_id"])
                    / f"k{trial['available_fleet_count']}"
                    / (
                        "bakeoff_result.json"
                        if str(trial["policy_id"]).startswith("ddd_")
                        else "result.json"
                    )
                )
                if result_path.exists():
                    results.append(_read_trial_result(result_path))
    else:
        store.append_new(
            OptimizationEventKind.CAMPAIGN_STARTED,
            config.campaign_id,
            payload={
                "label": "Five-station Fixed-K model bake-off",
                "objective": config.objective.value,
                "example_id": config.example_id,
                "method": "fixed_k_model_bakeoff",
                "campaign_kind": "model_bakeoff",
                "operating_mode": config.operating_mode.value,
                "waiting_policy": "no_wait",
                "time_limit_seconds_per_trial": config.total_time_limit_seconds,
                "trial_count": len(config.cabin_counts) * len(config.methods),
                "methods": [method.value for method in config.methods],
                "cabin_counts": list(config.cabin_counts),
            },
        )
        _publish(store)

    for cabin_count in config.cabin_counts:
        pending = tuple(
            method
            for method in config.methods
            if (method.value, cabin_count) not in completed
        )
        if not pending:
            continue
        print(f"preparing shared Fixed-K instance K={cabin_count}", flush=True)
        prepared = prepare_fixed_k_bakeoff_instance(config, cabin_count)
        fingerprint = prepared.problem.fingerprint
        print(
            f"prepared K={cabin_count} start={prepared.start_layout_kind} "
            f"fingerprint={fingerprint[:12]}",
            flush=True,
        )
        for method in pending:
            trial_started = __import__("time").perf_counter()
            line_width = 0
            store.append_new(
                OptimizationEventKind.TRIAL_STARTED,
                config.campaign_id,
                policy_id=method.value,
                available_fleet_count=cabin_count,
                trial_fingerprint=fingerprint,
                stage="setup",
                global_certified_lower_bound=0.0,
                payload={
                    "exact_active_cabin_count": cabin_count,
                    "method": method.value,
                    "start_policy": config.start_policy.value,
                    "start_layout_kind": prepared.start_layout_kind,
                    "waiting_policy": "no_wait",
                    "time_limit_seconds": config.total_time_limit_seconds,
                    "bound_semantics": {
                        "global": "certified_only",
                        "local_incumbent": "provisional_until_trial_validation",
                    },
                },
            )
            _publish(store)

            def progress(sample: dict[str, object]) -> None:
                nonlocal line_width
                lower = _optional_float(sample.get("certified_lower_bound"))
                incumbent = _optional_float(sample.get("solver_incumbent"))
                bound = _optional_float(sample.get("solver_bound"))
                gap = _optional_float(sample.get("solver_gap"))
                elapsed = float(sample.get("elapsed_seconds", 0.0))
                stage = str(sample.get("phase", "running"))
                store.append_new(
                    OptimizationEventKind.SOLVER_SAMPLE,
                    config.campaign_id,
                    policy_id=method.value,
                    available_fleet_count=cabin_count,
                    trial_fingerprint=fingerprint,
                    stage=stage,
                    global_certified_lower_bound=lower,
                    local_solver_incumbent=incumbent,
                    local_solver_bound=bound,
                    local_solver_gap=gap,
                    elapsed_seconds=elapsed,
                    payload={
                        key: value
                        for key, value in sample.items()
                        if key
                        not in {
                            "certified_lower_bound",
                            "solver_incumbent",
                            "solver_bound",
                            "solver_gap",
                            "elapsed_seconds",
                            "phase",
                        }
                    },
                )
                _publish(store)
                if args.progress:
                    text = _progress_line(
                        method,
                        cabin_count,
                        stage,
                        elapsed,
                        lower,
                        incumbent,
                        gap,
                    )
                    padding = " " * max(0, line_width - len(text))
                    print(f"\r{text}{padding}", end="", flush=True)
                    line_width = len(text)

            try:
                result = run_fixed_k_bakeoff_trial(
                    config,
                    method=method,
                    prepared=prepared,
                    output_dir=campaign_dir,
                    progress_callback=progress,
                )
            except Exception as error:
                if args.progress and line_width:
                    print()
                store.append_new(
                    OptimizationEventKind.TRIAL_FAILED,
                    config.campaign_id,
                    policy_id=method.value,
                    available_fleet_count=cabin_count,
                    trial_fingerprint=fingerprint,
                    stage="failed",
                    elapsed_seconds=__import__("time").perf_counter() - trial_started,
                    payload={"detail": str(error)},
                )
                _publish(store)
                raise
            if args.progress and line_width:
                print()
            results.append(result)
            store.append_new(
                OptimizationEventKind.INCUMBENT_VALIDATED,
                config.campaign_id,
                policy_id=method.value,
                available_fleet_count=cabin_count,
                trial_fingerprint=result.problem_fingerprint,
                stage="independent_validation",
                global_certified_lower_bound=result.certified_lower_bound,
                global_validated_upper_bound=result.validated_upper_bound,
                global_relative_gap=result.relative_gap,
                elapsed_seconds=result.total_seconds,
                payload={"status": result.status},
            )
            store.append_new(
                OptimizationEventKind.TRIAL_COMPLETED,
                config.campaign_id,
                policy_id=method.value,
                available_fleet_count=cabin_count,
                trial_fingerprint=result.problem_fingerprint,
                stage="complete",
                global_certified_lower_bound=result.certified_lower_bound,
                global_validated_upper_bound=result.validated_upper_bound,
                global_relative_gap=result.relative_gap,
                elapsed_seconds=result.total_seconds,
                payload={
                    "status": result.status,
                    "method": result.method.value,
                    "problem_fingerprint": result.problem_fingerprint,
                    "total_seconds": result.total_seconds,
                },
            )
            _publish(store)
            print(
                f"{method.value} K={cabin_count} status={result.status} "
                f"LB={result.certified_lower_bound:.3f} "
                f"UB={result.validated_upper_bound} gap={result.relative_gap}",
                flush=True,
            )

    final_results = tuple(results)
    write_fixed_k_bakeoff_summary(
        campaign_dir / "summary.json",
        config=config,
        results=final_results,
    )
    store.append_new(
        OptimizationEventKind.CAMPAIGN_COMPLETED,
        config.campaign_id,
        payload={"status": "complete"},
    )
    _publish(store)


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Compare exact Fixed-K EAN and DDD models on one contract."
    )
    parser.add_argument("--config", type=Path)
    parser.add_argument("--campaign-id")
    parser.add_argument(
        "--example",
        default="five_station_circle_cw_half_skip_no_wait_headway_b_v0",
    )
    parser.add_argument("--cabins", type=int, nargs="+", default=(20, 39))
    parser.add_argument(
        "--methods",
        nargs="+",
        choices=tuple(method.value for method in FixedKModelBakeoffMethod),
        default=tuple(method.value for method in FixedKModelBakeoffMethod),
    )
    parser.add_argument(
        "--objective",
        choices=tuple(value.value for value in EanPassengerObjective),
        default=EanPassengerObjective.JOURNEY_TIME.value,
    )
    parser.add_argument("--time-limit", type=float, default=1_800.0)
    parser.add_argument("--start-layout-time-limit", type=float, default=600.0)
    parser.add_argument("--cp-seed-time-limit", type=float, default=120.0)
    parser.add_argument("--seed-passenger-time-limit", type=float, default=60.0)
    parser.add_argument("--sample-interval", type=float, default=5.0)
    parser.add_argument("--threads", type=int)
    parser.add_argument("--cp-seed-workers", type=int, default=8)
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument(
        "--output-root",
        type=Path,
        default=Path("benchmarks/output/fixed_k_model_bakeoff"),
    )
    parser.add_argument(
        "--frontend-root",
        type=Path,
        default=Path("frontend/public/generated/optimization"),
    )
    parser.add_argument("--frontend-live", action="store_true")
    parser.add_argument("--progress", action="store_true")
    parser.add_argument("--resume", action="store_true")
    return parser.parse_args()


def _read_trial_result(path: Path) -> FixedKModelBakeoffTrialResult:
    payload = json.loads(path.read_text(encoding="utf-8"))
    return FixedKModelBakeoffTrialResult(
        method=FixedKModelBakeoffMethod(payload["method"]),
        cabin_count=int(payload["cabin_count"]),
        problem_fingerprint=str(payload["problem_fingerprint"]),
        status=str(payload["status"]),
        certified_lower_bound=float(payload["certified_lower_bound"]),
        validated_upper_bound=_optional_float(payload.get("validated_upper_bound")),
        relative_gap=_optional_float(payload.get("relative_gap")),
        total_seconds=float(payload["total_seconds"]),
        payload=dict(payload.get("payload", {})),
    )


def _progress_line(
    method: FixedKModelBakeoffMethod,
    cabin_count: int,
    stage: str,
    elapsed: float,
    lower: float | None,
    incumbent: float | None,
    gap: float | None,
) -> str:
    return (
        f"{method.value:<24.24} K={cabin_count:03d} "
        f"t={elapsed:7.1f}s stage={stage:<20.20} "
        f"LB={_number(lower)} pUB={_number(incumbent)} "
        f"gap={('-' if gap is None else f'{100 * gap:.2f}%'):>8}"
    )


def _number(value: float | None) -> str:
    return "-" if value is None else f"{value:,.1f}"


def _optional_float(value: object) -> float | None:
    return None if value is None else float(value)


def _publish(store: OptimizationLiveStore) -> None:
    store.publish(reduce_optimization_events(store.read_events()))


if __name__ == "__main__":
    main()
