"""Controlled 300/800/1200 m scaling campaign for the fixed-line model."""

from __future__ import annotations

import argparse
from dataclasses import asdict
import hashlib
import json
import math
from pathlib import Path
import statistics
import subprocess
import sys
from time import perf_counter
from types import SimpleNamespace

from ropeway_skip_stop_optimization.benchmarking.ddd_reservoir_cp_sat import (
    all_stop_reservoir_movement,
)
from ropeway_skip_stop_optimization.optimization.ddd.cp_sat_certificate import (
    atomic_json,
)
from ropeway_skip_stop_optimization.optimization.ddd.reservoir_cp_sat_certificate import (
    read_reservoir_cp_checkpoint,
    write_reservoir_cp_checkpoint,
)
from ropeway_skip_stop_optimization.optimization.ddd.reservoir_hybrid.domain import (
    load_reference,
)
from ropeway_skip_stop_optimization.optimization.ddd.reservoir_lines import (
    ReservoirLineConfig,
    ReservoirLineOptimizer,
    UniformLengthScaling,
    prepare_line_problem,
    saturated_all_stop_reference,
    scale_uniform_rope_length,
    with_saturation_time_contract,
)


ROOT = Path(__file__).resolve().parents[1]


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(description=__doc__, allow_abbrev=False)
    result.add_argument("--reference-checkpoint", required=True, type=Path)
    result.add_argument("--output-dir", required=True, type=Path)
    result.add_argument("--lengths", nargs="+", type=float, default=(300, 800, 1200))
    result.add_argument("--source-length", type=float, default=150)
    result.add_argument("--rope-speed", type=float, default=5)
    result.add_argument("--fleet-multiplier", type=float, default=1.25)
    result.add_argument("--controlled-max-cabins", type=int, default=50)
    result.add_argument("--controlled-dispatch-window", type=float, default=300)
    result.add_argument("--build-repetitions", type=int, default=3)
    result.add_argument("--seed-seconds", type=float, default=60)
    result.add_argument("--search-seconds", type=float, default=300)
    result.add_argument("--workers", type=int, default=12)
    result.add_argument("--memory-limit-gib", type=float, default=24)
    result.add_argument("--skip-search", action="store_true")
    result.add_argument("--_worker-kind", choices=("build", "seed", "search"))
    result.add_argument("--_contract", choices=("controlled", "saturation"))
    result.add_argument("--_length", type=float)
    result.add_argument("--_seed", type=int, default=0)
    result.add_argument("--_seed-checkpoint", type=Path)
    return result


def _length_label(value: float) -> str:
    return str(int(value)) if value.is_integer() else str(value).replace(".", "p")


def _problem(args, length: float, contract: str):
    domain, _ = load_reference(args.reference_checkpoint)
    scaled = scale_uniform_rope_length(
        domain.problem,
        UniformLengthScaling(args.source_length, length, args.rope_speed),
    )
    saturation = saturated_all_stop_reference(
        scaled, fleet_multiplier=args.fleet_multiplier
    )
    if contract == "controlled":
        if args.controlled_max_cabins > scaled.available_fleet_count:
            from dataclasses import replace

            scaled = replace(
                scaled, available_fleet_count=args.controlled_max_cabins
            )
        maximum_cabins = args.controlled_max_cabins
        dispatch_window = args.controlled_dispatch_window
    else:
        scaled = with_saturation_time_contract(scaled, saturation)
        maximum_cabins = saturation.experimental_fleet_cap
        dispatch_window = saturation.cycle_seconds
    config = ReservoirLineConfig(
        dispatch_window_end_seconds=dispatch_window,
        maximum_cabins=maximum_cabins,
        time_limit_seconds=(
            args.seed_seconds if args._worker_kind == "seed" else args.search_seconds
        ),
        workers=args.workers,
        memory_limit_gib=args.memory_limit_gib,
        seed=args._seed,
        log_search_progress=args._worker_kind == "search",
    )
    return scaled, saturation, config


def worker(args) -> int:
    if args._length is None or args._contract is None or args._worker_kind is None:
        raise ValueError("internal worker arguments are incomplete")
    output = args.output_dir
    output.mkdir(parents=True, exist_ok=False)
    problem, saturation, config = _problem(args, args._length, args._contract)
    prepared = prepare_line_problem(problem, config)
    atomic_json(output / "prepared.json", prepared.payload)
    common = {
        "length_m": args._length,
        "contract": args._contract,
        "scaling": asdict(
            UniformLengthScaling(
                args.source_length, args._length, args.rope_speed
            )
        ),
        "saturation": asdict(saturation),
        "problem_manifest": problem.manifest,
    }
    reference = None
    fixed = None
    if args._worker_kind == "seed":
        movement = all_stop_reservoir_movement(
            problem,
            SimpleNamespace(
                all_stop_maximum_cabin_count=saturation.saturated_cabins,
                all_stop_cycle_seconds=saturation.cycle_seconds,
                warmup_seconds=saturation.cycle_seconds,
            ),
        )
        if movement is None:
            raise RuntimeError("failed to construct the regular All-Stop movement")
        write_reservoir_cp_checkpoint(output / "movement.json", problem, movement)
        reference = fixed = movement
    elif args._worker_kind == "search":
        if args._seed_checkpoint is None:
            raise ValueError("search worker needs --_seed-checkpoint")
        reference = read_reservoir_cp_checkpoint(args._seed_checkpoint, problem)

    events_path = output / "events.jsonl"

    def event(item):
        with events_path.open("a") as stream:
            stream.write(json.dumps(item, sort_keys=True) + "\n")

    result, plan = ReservoirLineOptimizer(config).solve(
        problem,
        reference_plan=reference,
        fixed_movement_plan=fixed,
        event_callback=event,
        prepared=prepared,
        build_only=args._worker_kind == "build",
    )
    result.update(common)
    atomic_json(output / "result.json", result)
    if plan is not None:
        write_reservoir_cp_checkpoint(output / "best.json", problem, plan)
    return 0


def _source_identity() -> dict:
    head = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=ROOT, check=True, text=True,
        capture_output=True,
    ).stdout.strip()
    status = subprocess.run(
        ["git", "status", "--porcelain"], cwd=ROOT, check=True, text=True,
        capture_output=True,
    ).stdout
    source = (ROOT / "benchmarks/run_reservoir_line_length_scaling.py").read_bytes()
    return {
        "git_head": head,
        "working_tree_dirty": bool(status),
        "campaign_sha256": hashlib.sha256(source).hexdigest(),
    }


def _run_job(args, *, name: str, kind: str, contract: str, length: float,
             seed: int = 0, seed_checkpoint: Path | None = None) -> dict:
    output = args.output_dir / name
    command = [
        sys.executable,
        str(Path(__file__).resolve()),
        "--reference-checkpoint", str(args.reference_checkpoint.resolve()),
        "--output-dir", str(output.resolve()),
        "--source-length", str(args.source_length),
        "--rope-speed", str(args.rope_speed),
        "--fleet-multiplier", str(args.fleet_multiplier),
        "--controlled-max-cabins", str(args.controlled_max_cabins),
        "--controlled-dispatch-window", str(args.controlled_dispatch_window),
        "--seed-seconds", str(args.seed_seconds),
        "--search-seconds", str(args.search_seconds),
        "--workers", str(args.workers),
        "--memory-limit-gib", str(args.memory_limit_gib),
        "--_worker-kind", kind,
        "--_contract", contract,
        "--_length", str(length),
        "--_seed", str(seed),
    ]
    if seed_checkpoint is not None:
        command.extend(("--_seed-checkpoint", str(seed_checkpoint.resolve())))
    print(f"START {name}", flush=True)
    started = perf_counter()
    completed = subprocess.run(command, cwd=ROOT, text=True, capture_output=True)
    record = {
        "name": name,
        "kind": kind,
        "contract": contract,
        "length_m": length,
        "seed": seed,
        "returncode": completed.returncode,
        "wall_seconds": perf_counter() - started,
    }
    (args.output_dir / f"{name}.stdout.txt").write_text(completed.stdout)
    (args.output_dir / f"{name}.stderr.txt").write_text(completed.stderr)
    if (output / "result.json").exists():
        record["result"] = json.loads((output / "result.json").read_text())
    print(
        f"DONE  {name} rc={completed.returncode} wall={record['wall_seconds']:.1f}s",
        flush=True,
    )
    return record


def _median(values):
    return None if not values else statistics.median(values)


def report(args, records: list[dict]) -> None:
    builds = []
    searches = []
    for length in args.lengths:
        for contract in ("controlled", "saturation"):
            rows = [
                item["result"]
                for item in records
                if item["kind"] == "build"
                and item["contract"] == contract
                and item["length_m"] == length
                and "result" in item
            ]
            if rows:
                stats = [row["model_stats"] for row in rows]
                builds.append(
                    {
                        "length_m": length,
                        "contract": contract,
                        "k_max": rows[0]["config"]["maximum_cabins"],
                        "all_stop_saturation": rows[0]["saturation"]["saturated_cabins"],
                        "templates": _median([s["templates"] for s in stats]),
                        "variables": _median([s["variables"] for s in stats]),
                        "constraints": _median([s["constraints"] for s in stats]),
                        "intervals": _median([s["native_resource_intervals"] for s in stats]),
                        "ride_variables": _median([s["integer_ride_variables"] for s in stats]),
                        "proto_bytes": _median(
                            [s["serialized_model_bytes"] for s in stats]
                        ),
                        "build_wall_seconds": _median([row["total_wall_seconds"] for row in rows]),
                        "peak_rss_bytes": _median([row["peak_rss_bytes"] for row in rows]),
                    }
                )
        for seed in (0, 1):
            item = next(
                (
                    row
                    for row in records
                    if row["kind"] == "search"
                    and row["length_m"] == length
                    and row["seed"] == seed
                    and "result" in row
                ),
                None,
            )
            if item:
                result = item["result"]
                searches.append(
                    {
                        "length_m": length,
                        "seed": seed,
                        "status": result["solver_status"],
                        "served": result["validated_served"],
                        "unserved": result["validated_unserved"],
                        "used_fleet": result["used_fleet"],
                        "served_upper_bound": result["native_served_upper_bound"],
                        "solve_seconds": result["solve_seconds"],
                        "total_wall_seconds": result["total_wall_seconds"],
                        "peak_rss_bytes": result["peak_rss_bytes"],
                        "incumbents": len(result["events"]),
                    }
                )
    atomic_json(args.output_dir / "build_summary.json", builds)
    atomic_json(args.output_dir / "search_summary.json", searches)
    lines = [
        "# Reservoir line length scaling",
        "",
        "The controlled rows retain Kmax=50 and the historical absolute time contract. "
        "The saturation rows extend only the final return horizon, allow dispatch during "
        "one All-Stop cycle, and use ceil(1.25 K_AS). All rows use the default "
        "intervals + encoding_specific + shared_rounds formulation and fix station-local "
        "times, resources, demand, and headways.",
        "",
        "## Build medians",
        "",
        "| length m | contract | Kmax | K_AS | templates | vars | constraints | intervals | ride vars | proto MiB | wall s | RSS MiB |",
        "|---:|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for row in builds:
        lines.append(
            f"| {row['length_m']:g} | {row['contract']} | {row['k_max']} | "
            f"{row['all_stop_saturation']} | {row['templates']:g} | {row['variables']:g} | "
            f"{row['constraints']:g} | {row['intervals']:g} | {row['ride_variables']:g} | "
            f"{row['proto_bytes']/2**20:.2f} | {row['build_wall_seconds']:.2f} | "
            f"{row['peak_rss_bytes']/2**20:.0f} |"
        )
    lines.extend(
        [
            "",
            f"## Saturation searches ({args.search_seconds:g} solver seconds)",
            "",
            "| length m | seed | status | served | unserved | fleet | served UB | solve s | wall s | RSS MiB | incumbents |",
            "|---:|---:|---|---:|---:|---:|---:|---:|---:|---:|---:|",
        ]
    )
    for row in searches:
        lines.append(
            f"| {row['length_m']:g} | {row['seed']} | {row['status']} | "
            f"{row['served']} | {row['unserved']} | {row['used_fleet']} | "
            f"{row['served_upper_bound']} | {row['solve_seconds']:.1f} | "
            f"{row['total_wall_seconds']:.1f} | {row['peak_rss_bytes']/2**20:.0f} | "
            f"{row['incumbents']} |"
        )
    (args.output_dir / "report.md").write_text("\n".join(lines) + "\n")


def campaign(args) -> int:
    if args.output_dir.exists():
        raise FileExistsError(args.output_dir)
    args.output_dir.mkdir(parents=True)
    args.lengths = tuple(args.lengths)
    if not args.lengths or any(not math.isfinite(x) or x <= 0 for x in args.lengths):
        raise ValueError("lengths must be finite and positive")
    atomic_json(
        args.output_dir / "manifest.json",
        {
            "schema": "reservoir_line_length_scaling_campaign_v1",
            "arguments": {
                key: str(value) if isinstance(value, Path) else value
                for key, value in vars(args).items()
                if not key.startswith("_")
            },
            "default_formulation": {
                "variant": "intervals",
                "preparation": "encoding_specific",
                "formulation": "shared_rounds",
            },
            "source": _source_identity(),
        },
    )
    records = []
    for repetition in range(args.build_repetitions):
        for length in args.lengths:
            for contract in ("controlled", "saturation"):
                label = _length_label(length)
                records.append(
                    _run_job(
                        args,
                        name=f"build_{contract}_{label}m_r{repetition}",
                        kind="build",
                        contract=contract,
                        length=length,
                    )
                )
    seed_paths = {}
    if not args.skip_search:
        for length in args.lengths:
            label = _length_label(length)
            name = f"seed_saturation_{label}m"
            item = _run_job(
                args, name=name, kind="seed", contract="saturation", length=length
            )
            records.append(item)
            best = args.output_dir / name / "best.json"
            if item["returncode"] == 0 and best.exists():
                seed_paths[length] = best
        for seed in (0, 1):
            for length in args.lengths:
                if length not in seed_paths:
                    continue
                label = _length_label(length)
                records.append(
                    _run_job(
                        args,
                        name=f"search_saturation_{label}m_s{seed}",
                        kind="search",
                        contract="saturation",
                        length=length,
                        seed=seed,
                        seed_checkpoint=seed_paths[length],
                    )
                )
    atomic_json(args.output_dir / "records.json", records)
    report(args, records)
    return 0 if all(item["returncode"] == 0 for item in records) else 1


def main() -> int:
    args = parser().parse_args()
    if args._worker_kind:
        return worker(args)
    return campaign(args)


if __name__ == "__main__":
    raise SystemExit(main())
