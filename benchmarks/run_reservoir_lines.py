"""Build or solve the compact single-use reservoir fixed-line model."""

import argparse
from ropeway_skip_stop_optimization.optimization.ddd.reservoir_boundary import add_boundary_arguments, apply_boundary_arguments
import json
from pathlib import Path
import subprocess
from time import perf_counter

from ropeway_skip_stop_optimization.optimization.ddd.cp_sat_certificate import (
    atomic_json,
)
from ropeway_skip_stop_optimization.optimization.ddd.reservoir_cp_sat_certificate import (
    write_reservoir_cp_checkpoint,
)
from ropeway_skip_stop_optimization.optimization.ddd.reservoir_hybrid.domain import (
    load_reference,
)
from ropeway_skip_stop_optimization.optimization.ddd.reservoir_cp_sat_certificate import (
    validate_reservoir_cp_plan,
)
from ropeway_skip_stop_optimization.optimization.ddd.reservoir_lines import (
    ReservoirLineCatalogProfile,
    ReservoirLineConfig,
    ReservoirLineFormulation,
    ReservoirLineMode,
    ReservoirLineOptimizer,
    ReservoirLinePreparation,
    ReservoirLineVariant,
    prepare_line_problem,
)


def _pattern_sequence(path: Path | None) -> tuple[str, ...]:
    if path is None:
        return ()
    value = json.loads(path.read_text())
    if not isinstance(value, list) or not all(
        isinstance(item, str) and item for item in value
    ):
        raise ValueError("fixed pattern sequence must be a JSON string list")
    return tuple(value)


def _source_identity() -> dict:
    head = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    dirty = bool(
        subprocess.run(
            ["git", "status", "--porcelain"],
            check=True,
            capture_output=True,
            text=True,
        ).stdout
    )
    return {"git_head": head, "working_tree_dirty": dirty}


def main():
    parser = argparse.ArgumentParser(description=__doc__, allow_abbrev=False)
    parser.add_argument("--reference-checkpoint", required=True, type=Path)
    parser.add_argument(
        "--initial-checkpoint",
        type=Path,
        help="optional start plan when the reference checkpoint is domain-only",
    )
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument(
        "--variant", choices=list(ReservoirLineVariant), default="intervals"
    )
    parser.add_argument(
        "--mode", choices=list(ReservoirLineMode), default="exact_service"
    )
    parser.add_argument(
        "--preparation",
        choices=list(ReservoirLinePreparation),
        default="encoding_specific",
    )
    parser.add_argument(
        "--formulation",
        choices=list(ReservoirLineFormulation),
        default="shared_rounds",
    )
    parser.add_argument(
        "--catalog", choices=list(ReservoirLineCatalogProfile), default="small"
    )
    parser.add_argument(
        "--dispatch-window-end",
        required=True,
        type=float,
        help=(
            "end of the passenger-free dispatch phase and start of passenger "
            "service, in seconds"
        ),
    )
    parser.add_argument("--max-cabins", type=int)
    parser.add_argument("--fixed-cabins", type=int)
    parser.add_argument("--fixed-pattern-sequence", type=Path)
    parser.add_argument("--time-limit", type=float, default=60)
    parser.add_argument("--workers", type=int, default=12)
    parser.add_argument("--memory-limit-gib", type=float, default=24)
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument("--log-search-progress", action="store_true")
    parser.add_argument(
        "--presolve", action=argparse.BooleanOptionalAction, default=True
    )
    parser.add_argument("--build-only", action="store_true")
    parser.add_argument("--fix-reference-movement", action="store_true")
    parser.add_argument(
        "--no-reference-hint",
        action="store_true",
        help="load the physical problem from the checkpoint but do not hint its plan",
    )
    add_boundary_arguments(parser)
    args = parser.parse_args()

    if args.no_reference_hint and args.fix_reference_movement:
        parser.error("--no-reference-hint conflicts with --fix-reference-movement")
    if args.no_reference_hint and args.initial_checkpoint:
        parser.error("--no-reference-hint conflicts with --initial-checkpoint")

    runner_started = perf_counter()
    args.output.mkdir(parents=True, exist_ok=False)
    domain, reference_plan = load_reference(args.reference_checkpoint)
    from dataclasses import replace

    domain = replace(domain, problem=apply_boundary_arguments(domain.problem, args))
    if args.initial_checkpoint is not None:
        _, reference_plan = load_reference(args.initial_checkpoint)
        validate_reservoir_cp_plan(domain.problem, reference_plan)
    config = ReservoirLineConfig(
        dispatch_window_end_seconds=args.dispatch_window_end,
        variant=ReservoirLineVariant(args.variant),
        preparation=ReservoirLinePreparation(args.preparation),
        formulation=ReservoirLineFormulation(args.formulation),
        mode=ReservoirLineMode(args.mode),
        catalog_profile=ReservoirLineCatalogProfile(args.catalog),
        maximum_cabins=args.max_cabins,
        fixed_cabins=args.fixed_cabins,
        fixed_pattern_sequence=_pattern_sequence(args.fixed_pattern_sequence),
        time_limit_seconds=args.time_limit,
        workers=args.workers,
        memory_limit_gib=args.memory_limit_gib,
        seed=args.seed,
        log_search_progress=args.log_search_progress,
        presolve=args.presolve,
    )
    prepared = prepare_line_problem(domain.problem, config)
    atomic_json(args.output / "prepared.json", prepared.payload)
    progress = args.output / "events.jsonl"

    def event_callback(event):
        with progress.open("a") as stream:
            stream.write(json.dumps(event, sort_keys=True) + "\n")

    logs = []

    def solver_log_callback(message):
        logs.append(message)
        # Preserve presolve/search progress while long runs are still active.
        with (args.output / "solver.log").open("a") as stream:
            stream.write(message if message.endswith("\n") else message + "\n")

    result, plan = ReservoirLineOptimizer(config).solve(
        domain.problem,
        reference_plan=None if args.no_reference_hint else reference_plan,
        event_callback=event_callback,
        log_callback=solver_log_callback if args.log_search_progress else None,
        build_only=args.build_only,
        prepared=prepared,
        fixed_movement_plan=reference_plan if args.fix_reference_movement else None,
    )
    result["runner_total_wall_seconds"] = perf_counter() - runner_started
    result["source_identity"] = _source_identity()
    if logs:
        (args.output / "solver.log").write_text("".join(logs))
    if plan is not None:
        write_reservoir_cp_checkpoint(
            args.output / "best.json", domain.problem, plan
        )
    atomic_json(args.output / "result.json", result)
    print(json.dumps(result, indent=2, default=str))


if __name__ == "__main__":
    main()
