"""Consolidate the 2026-09-13 reservoir-line compaction campaign."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import platform
from pathlib import Path
import shutil
import subprocess
import sys

import ortools


ROOT = Path(__file__).resolve().parents[1]
SOURCE_FILES = (
    "benchmarks/run_reservoir_lines.py",
    "benchmarks/summarize_reservoir_line_compaction.py",
    "src/ropeway_skip_stop_optimization/optimization/ddd/reservoir_lines/config.py",
    "src/ropeway_skip_stop_optimization/optimization/ddd/"
    "reservoir_lines/preparation.py",
    "src/ropeway_skip_stop_optimization/optimization/ddd/reservoir_lines/cp_model.py",
    "src/ropeway_skip_stop_optimization/optimization/ddd/"
    "reservoir_lines/passenger_model.py",
    "src/ropeway_skip_stop_optimization/optimization/ddd/"
    "reservoir_lines/certificate.py",
    "src/ropeway_skip_stop_optimization/optimization/ddd/reservoir_lines/optimizer.py",
)


def _json(path: Path) -> dict:
    return json.loads(path.read_text())


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _git(*args: str) -> str:
    return subprocess.run(
        ["git", *args], cwd=ROOT, check=True, capture_output=True, text=True
    ).stdout.strip()


def _sysctl(name: str) -> int | None:
    if platform.system() != "Darwin":
        return None
    value = subprocess.run(
        ["sysctl", "-n", name], check=True, capture_output=True, text=True
    ).stdout.strip()
    return int(value)


def _write_csv(path: Path, rows: list[dict]) -> None:
    if not rows:
        raise ValueError(f"cannot write empty campaign table {path.name}")
    with path.open("w", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def _value_at(events: list[dict], second: float) -> int | None:
    values = [event["served"] for event in events if event["elapsed_seconds"] <= second]
    return values[-1] if values else None


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--reference-checkpoint", required=True, type=Path)
    args = parser.parse_args()
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=False)

    build_rows = []
    for variant in ("v0", "v1", "v2", "v3"):
        for repeat in (2, 3, 4):
            run = ROOT / "benchmarks/output" / (
                f"reservoir_line_compaction_20260913_build_{variant}_r{repeat}"
            )
            result = _json(run / "result.json")
            stats = result["model_stats"]
            build_rows.append(
                {
                    "variant": variant,
                    "repeat": repeat,
                    "run_path": str(run.relative_to(ROOT)),
                    "preparation": stats["preparation_mode"],
                    "formulation": stats["line_formulation"],
                    "templates": stats["templates"],
                    "ride_variables": stats["integer_ride_variables"],
                    "positive_literals": stats["positive_literals"],
                    "round_active_variables": stats["round_active_variables"],
                    "native_intervals": stats["native_resource_intervals"],
                    "variables": stats["variables"],
                    "constraints": stats["constraints"],
                    "protobuf_bytes": stats["serialized_model_bytes"],
                    "preparation_seconds": result["preparation_seconds"],
                    "model_build_seconds": result["model_build_seconds"],
                    "total_wall_seconds": result["total_wall_seconds"],
                    "runner_total_wall_seconds": result["runner_total_wall_seconds"],
                    "load_prepare_export_seconds": (
                        result["runner_total_wall_seconds"]
                        - result["total_wall_seconds"]
                    ),
                    "peak_rss_bytes": result["peak_rss_bytes"],
                    "model_fingerprint": result["model_fingerprint"],
                }
            )
    _write_csv(output / "build_metrics.csv", build_rows)

    run_rows, combined_events = [], []
    for condition in ("hint", "nohint"):
        for variant in ("v0", "v2", "v3"):
            for seed in (0, 1):
                run_id = f"{condition}_{variant}_s{seed}"
                run = ROOT / "benchmarks/output" / (
                    f"reservoir_line_compaction_20260913_search_{run_id}"
                )
                result = _json(run / "result.json")
                events = result["events"]
                reference_served = (
                    None
                    if result["reference_metrics"] is None
                    else result["reference_metrics"]["served"]
                )
                first_improvement = next(
                    (
                        event
                        for event in events
                        if reference_served is not None
                        and event["served"] > reference_served
                    ),
                    None,
                )
                first_full = next(
                    (event for event in events if event["served"] == 3074), None
                )
                first_k37 = next(
                    (
                        event
                        for event in events
                        if event["served"] == 3074 and event["used_fleet"] <= 37
                    ),
                    None,
                )
                stats = result["model_stats"]
                run_rows.append(
                    {
                        "run_id": run_id,
                        "run_path": str(run.relative_to(ROOT)),
                        "condition": condition,
                        "variant": variant,
                        "formulation": stats["line_formulation"],
                        "seed": seed,
                        "reference_served": reference_served,
                        "first_solution_seconds": (
                            events[0]["elapsed_seconds"] if events else None
                        ),
                        "first_improvement_seconds": (
                            None
                            if first_improvement is None
                            else first_improvement["elapsed_seconds"]
                        ),
                        "first_full_service_seconds": (
                            None
                            if first_full is None
                            else first_full["elapsed_seconds"]
                        ),
                        "first_full_service_k37_seconds": (
                            None if first_k37 is None else first_k37["elapsed_seconds"]
                        ),
                        "served_30s": _value_at(events, 30),
                        "served_60s": _value_at(events, 60),
                        "served_180s": _value_at(events, 180),
                        "served_300s": _value_at(events, 300),
                        "validated_served": result["validated_served"],
                        "validated_unserved": result["validated_unserved"],
                        "used_fleet": result["used_fleet"],
                        "native_objective_bound": result[
                            "native_objective_upper_bound_raw"
                        ],
                        "served_upper_bound": result["native_served_upper_bound"],
                        "unserved_lower_bound": result[
                            "line_domain_unserved_lower_bound"
                        ],
                        "last_progress_seconds": (
                            events[-1]["elapsed_seconds"] if events else None
                        ),
                        "solve_seconds": result["solve_seconds"],
                        "total_wall_seconds": result["total_wall_seconds"],
                        "runner_total_wall_seconds": result[
                            "runner_total_wall_seconds"
                        ],
                        "peak_rss_bytes": result["peak_rss_bytes"],
                        "solver_status": result["solver_status"],
                        "checkpoint": str((run / "best.json").relative_to(ROOT)),
                    }
                )
                for event in events:
                    combined_events.append({"run_id": run_id, **event})
    _write_csv(output / "run_summary.csv", run_rows)
    with (output / "progress.jsonl").open("w") as stream:
        for event in combined_events:
            stream.write(json.dumps(event, sort_keys=True) + "\n")

    replay_rows = []
    for variant in ("v0", "v2", "v3"):
        run = ROOT / "benchmarks/output" / (
            f"reservoir_line_compaction_20260913_replay_{variant}"
        )
        result = _json(run / "result.json")
        replay_rows.append(
            {
                "variant": variant,
                "run_path": str(run.relative_to(ROOT)),
                "reference_status": result["reference_status"],
                "solver_status": result["solver_status"],
                "proven_optimal": result["proven_optimal"],
                "validated_served": result["validated_served"],
                "validated_unserved": result["validated_unserved"],
                "used_fleet": result["used_fleet"],
                "total_wall_seconds": result["total_wall_seconds"],
            }
        )
    correctness = {
        "unit_test_command": (
            ".venv/bin/python -m pytest tests/test_reservoir_lines.py -q"
        ),
        "unit_test_result": "23 passed",
        "targeted_regression_command": (
            ".venv/bin/python -m pytest tests/test_reservoir_lines.py "
            "tests/test_optimization_ddd_reservoir_cp_sat.py -q"
        ),
        "targeted_regression_result": "44 passed",
        "full_suite_command": ".venv/bin/python -m pytest tests -q",
        "full_suite_result": "1519 passed, 22 skipped",
        "prefix_contract_checked_during_preparation": True,
        "historical_fixed_movement_replays": replay_rows,
        "search_released": all(
            row["proven_optimal"]
            and row["validated_served"] == 3074
            and row["validated_unserved"] == 0
            for row in replay_rows
        ),
        "scope": "fixed-line single-use reservoir, no waiting",
    }
    (output / "correctness.json").write_text(
        json.dumps(correctness, indent=2, sort_keys=True) + "\n"
    )

    reference_target = output / "reference_u38.json"
    shutil.copy2(args.reference_checkpoint, reference_target)
    manifest = {
        "schema": "reservoir_line_compaction_campaign_v1",
        "problem_fingerprint": _json(args.reference_checkpoint)["problem_fingerprint"],
        "reference_checkpoint": reference_target.name,
        "reference_checkpoint_sha256": _sha256(reference_target),
        "git_head": _git("rev-parse", "HEAD"),
        "working_tree_dirty": bool(_git("status", "--porcelain")),
        "python": sys.version,
        "ortools": ortools.__version__,
        "platform": platform.platform(),
        "machine": platform.machine(),
        "physical_cpu_count": _sysctl("hw.physicalcpu"),
        "logical_cpu_count": _sysctl("hw.logicalcpu"),
        "memory_bytes": _sysctl("hw.memsize"),
        "workers": 12,
        "memory_limit_gib": 24,
        "solver_time_limit_seconds": 300,
        "source_sha256": {
            path: _sha256(ROOT / path) for path in SOURCE_FILES
        },
        "build_repetitions": [2, 3, 4],
        "search_conditions": ["hint", "nohint"],
        "seeds": [0, 1],
        "variants": {
            "v0": "legacy_eager build baseline; equivalent encoding_specific search",
            "v1": "encoding_specific preparation + legacy_templates (build only)",
            "v2": "encoding_specific preparation + shared_rounds",
            "v3": "encoding_specific preparation + shared_rides",
        },
        "notes": [
            "Search time limit is CP-SAT wall time; build and validation are "
            "reported separately.",
            "The reference checkpoint is a native hint only in condition=hint.",
            "All validated checkpoints remain in their per-run directories.",
        ],
    }
    (output / "manifest.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n"
    )


if __name__ == "__main__":
    main()
