"""Run one versioned T5R/T6R thesis experiment under a supervised budget."""

from __future__ import annotations

import argparse
from dataclasses import asdict, replace
import hashlib
from importlib.metadata import PackageNotFoundError, version
import json
from pathlib import Path
import platform
import subprocess
import sys
import time

from ropeway_skip_stop_optimization.benchmarking.ddd_fixed_k_arc_flow import (
    run_ddd_fixed_k_arc_flow,
)
from ropeway_skip_stop_optimization.benchmarking.native_solvers import supervise
from ropeway_skip_stop_optimization.benchmarking.thesis_cases import (
    ExperimentCaseSpec,
    ThesisDemandFamily,
    ThesisDemandProfile,
    ThesisGeometry,
    ThesisObjective,
    ThesisTopology,
    prepare_experiment_case,
    prepare_fixed_k_experiment,
)
from ropeway_skip_stop_optimization.benchmarking.thesis_all_stop_capacity import (
    AllStopCapacitySearchConfig,
    search_all_stop_capacity,
    search_fixed_k_all_stop_capacity,
)
from ropeway_skip_stop_optimization.optimization.ddd.all_stop_phase import (
    AllStopPhaseConfig,
    prepare_all_stop_phase,
    solve_all_stop_phase,
)
from ropeway_skip_stop_optimization.optimization.ddd.fixed_k import (
    DddFixedKOperatingMode,
)
from ropeway_skip_stop_optimization.optimization.ddd.cp_sat_certificate import atomic_json
from ropeway_skip_stop_optimization.exports.json_codec import write_json
from ropeway_skip_stop_optimization.optimization.ddd.reservoir_cp_sat_certificate import (
    read_reservoir_cp_checkpoint,
    read_reservoir_cp_checkpoint_for_fleet_resize,
    write_reservoir_cp_checkpoint,
)
from ropeway_skip_stop_optimization.optimization.ddd.reservoir_lines import (
    ReservoirLineCatalogProfile,
    ReservoirLineConfig,
    ReservoirLineFormulation,
    ReservoirLinePipelineConfig,
    solve_reservoir_line_pipeline,
)


ROOT = Path(__file__).resolve().parents[1]


def parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description=__doc__, allow_abbrev=False)
    p.add_argument("--case-spec", type=Path)
    p.add_argument("--topology", choices=list(ThesisTopology))
    p.add_argument("--geometry", choices=list(ThesisGeometry))
    p.add_argument("--demand-family", choices=list(ThesisDemandFamily))
    p.add_argument("--demand-profile", choices=list(ThesisDemandProfile), default="p0")
    p.add_argument("--objective", choices=list(ThesisObjective))
    p.add_argument("--demand", type=int)
    p.add_argument("--release-resolution-seconds", type=int, default=30)
    p.add_argument("--maximum-wait-seconds", type=float, default=1200.0)
    p.add_argument(
        "--method",
        choices=("all_stop_phase", "line_planning", "labelled_arc_flow", "evolution"),
        required=True,
    )
    p.add_argument("--cabins", type=int)
    p.add_argument("--max-cabins", type=int)
    p.add_argument(
        "--operating-mode", choices=("all_stop", "skip_stop"), default="skip_stop"
    )
    p.add_argument("--formulation", choices=("shared_rounds", "shared_rides"), default="shared_rounds")
    p.add_argument("--catalog", choices=list(ReservoirLineCatalogProfile), default="relevant")
    p.add_argument("--pattern-search", choices=("independent", "line_groups"), default="independent")
    p.add_argument("--population-size", type=int, default=32)
    p.add_argument("--offspring-size", type=int, default=8)
    p.add_argument("--passenger-time-limit", type=float, default=2.0)
    p.add_argument(
        "--initial-pattern-sequences",
        type=Path,
        help="Optional JSON list of exact-K pattern sequences from an earlier stage.",
    )
    p.add_argument("--time-limit", type=float, default=300)
    p.add_argument("--mip-gap", type=float, default=0.0, help="Relative labelled arc-flow optimality gap (0.01 = 1 percent).")
    p.add_argument("--workers", type=int, default=12)
    p.add_argument("--memory-limit-gib", type=float, default=32)
    p.add_argument("--seed", type=int, default=0)
    p.add_argument("--checkpoint-import", type=Path)
    p.add_argument("--allow-fleet-resize-checkpoint", action="store_true")
    p.add_argument("--output-dir", type=Path, required=True)
    p.add_argument("--build-only", action="store_true")
    p.add_argument("--capacity-search", action="store_true")
    p.add_argument("--capacity-initial-demand", type=int, default=100)
    p.add_argument("--capacity-reference-dir", action="append", default=[])
    p.add_argument("--capacity-probe-demand", type=int, action="append", default=[])
    p.add_argument(
        "--all-stop-capacity-encoding",
        choices=("integrated", "phase_cells"),
        default="integrated",
    )
    p.add_argument("--log-search-progress", action="store_true")
    p.add_argument("--_worker", action="store_true", help=argparse.SUPPRESS)
    return p


def _spec(args) -> ExperimentCaseSpec:
    if args.case_spec:
        raw = json.loads(args.case_spec.read_text(encoding="utf-8"))
        if raw.get("schema") == "thesis_experiment_case_v1":
            data = raw
        else:
            data = raw.get("case_spec", raw)
        return ExperimentCaseSpec(
            topology=ThesisTopology(data["topology"]),
            geometry=ThesisGeometry(data["geometry"]),
            demand_family=ThesisDemandFamily(data["demand_family"]),
            demand_profile=ThesisDemandProfile(data["demand_profile"]),
            objective=ThesisObjective(data["objective"]),
            demand_total=int(data["demand_total"]),
            release_resolution_seconds=int(data.get("release_resolution_seconds", 30)),
            maximum_wait_seconds=float(data.get("maximum_wait_seconds", 1200)),
        )
    missing = [
        name
        for name in ("topology", "geometry", "demand_family", "objective", "demand")
        if getattr(args, name) is None
    ]
    if missing:
        raise ValueError("case flags are incomplete: " + ", ".join(missing))
    return ExperimentCaseSpec(
        ThesisTopology(args.topology),
        ThesisGeometry(args.geometry),
        ThesisDemandFamily(args.demand_family),
        ThesisDemandProfile(args.demand_profile),
        ThesisObjective(args.objective),
        args.demand,
        args.release_resolution_seconds,
        float(args.maximum_wait_seconds),
    )


def _source_identity() -> dict:
    files = sorted({
        *ROOT.joinpath("src").rglob("*.py"),
        *ROOT.joinpath("benchmarks").glob("*.py"),
        *[path for path in (ROOT / "pyproject.toml", ROOT / "uv.lock") if path.is_file()],
    })
    versions = {}
    for package in ("ortools", "gurobipy", "pymoo", "numpy", "psutil"):
        try:
            versions[package] = version(package)
        except PackageNotFoundError:
            versions[package] = None
    try:
        revision = subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=ROOT, text=True
        ).strip()
        dirty = bool(
            subprocess.check_output(
                ["git", "status", "--porcelain"], cwd=ROOT, text=True
            ).strip()
        )
    except (OSError, subprocess.CalledProcessError):
        revision, dirty = None, None
    return {
        "git_revision": revision,
        "git_dirty": dirty,
        "python": sys.version,
        "platform": platform.platform(),
        "package_versions": versions,
        "source_sha256": {
            str(path.relative_to(ROOT)): hashlib.sha256(path.read_bytes()).hexdigest()
            for path in files
        },
    }


def worker(args) -> None:
    started = time.monotonic()

    def remaining_budget() -> float:
        # The parent enforces the advertised end-to-end budget. Model builders
        # and independent validation are outside the native solver limit, so a
        # percentage tail is needed for large cases. Capping it at 15 seconds
        # leaves almost all of a long run to the solver while allowing atomic
        # result and checkpoint writes before the supervisor deadline.
        finalization_reserve = min(15.0, max(2.0, args.time_limit * 0.1))
        return max(
            0.001,
            args.time_limit - (time.monotonic() - started) - finalization_reserve,
        )

    spec = _spec(args)
    spec.validate()
    if args.capacity_reference_dir and (args.method != "all_stop_phase" or not args.capacity_search or spec.objective.value != "unserved"):
        raise ValueError("capacity-reference-dir requires a reservoir All-Stop capacity search")
    out = args.output_dir
    atomic_json(out / "case_spec.json", asdict(spec))
    atomic_json(out / "source_identity.json", _source_identity())
    with (out / "events.jsonl").open("w", encoding="utf-8") as stream:
        def emit(event):
            stream.write(
                json.dumps(
                    {**event, "runner_elapsed_seconds": time.monotonic() - started},
                    sort_keys=True,
                )
                + "\n"
            )
            stream.flush()

        if args.method == "labelled_arc_flow":
            if spec.objective is not ThesisObjective.JOURNEY_TIME or args.cabins is None:
                raise ValueError("labelled_arc_flow requires journey_time and --cabins")
            config, prepared, case_manifest = prepare_fixed_k_experiment(
                spec,
                cabins=args.cabins,
                time_limit_seconds=remaining_budget(),
                workers=args.workers,
                seed=args.seed,
                output_flag=args.log_search_progress,
                operating_mode=DddFixedKOperatingMode(args.operating_mode),
            )
            atomic_json(out / "prepared_case.json", case_manifest)
            write_json(out / "scenario.json", prepared.scenario)
            if args.build_only:
                result = {
                    "schema": "thesis_experiment_result_v1",
                    "method": args.method,
                    "status": "PREPARATION_ONLY",
                    "build_only": True,
                    "problem_fingerprint": prepared.problem.fingerprint,
                    "case": case_manifest,
                }
            else:
                config = replace(
                    config,
                    total_time_limit_seconds=remaining_budget(),
                    mip_gap=args.mip_gap,
                    cp_seed_time_limit_seconds=min(
                        config.cp_seed_time_limit_seconds,
                        max(0.0, remaining_budget() * 0.1),
                    ),
                )
                run = run_ddd_fixed_k_arc_flow(
                    config,
                    prepared_run=prepared,
                    progress_hook=lambda progress: emit(
                        {"kind": "progress", **asdict(progress)}
                    ),
                )
                result = {
                    "schema": "thesis_experiment_result_v1",
                    "method": args.method,
                    "case_fingerprint": spec.fingerprint,
                    "problem_fingerprint": prepared.problem.fingerprint,
                    "case": case_manifest,
                    "run": run.to_payload(),
                }
        elif (
            args.method == "all_stop_phase"
            and args.capacity_search
            and spec.objective is ThesisObjective.JOURNEY_TIME
        ):
            if args.build_only or args.cabins is None:
                raise ValueError("Journey capacity search needs --cabins and cannot use --build-only")
            native = search_fixed_k_all_stop_capacity(
                spec,
                AllStopCapacitySearchConfig(
                    maximum_demand=spec.demand_total,
                    initial_demand=min(args.capacity_initial_demand, spec.demand_total),
                    time_limit_seconds=remaining_budget(), workers=args.workers,
                    seed=args.seed, cabins=args.cabins,
                    log_search_progress=args.log_search_progress,
                    probe_demands=tuple(args.capacity_probe_demand),
                ),
                cabins=args.cabins, event_callback=emit,
            )
            # Each probe contains its actual fixed-start physical manifest.
            # Do not wrap this result in an unrelated reservoir domain.
            result = {
                "schema": "thesis_experiment_result_v1", "method": args.method,
                "case_fingerprint": spec.fingerprint,
                "case": native["probes"][-1]["case"] if native["probes"] else None,
                "run": native,
            }
        else:
            requested_fleet = (
                args.cabins
                if args.method == "evolution" and args.max_cabins is None
                else args.max_cabins
            )
            prepared = prepare_experiment_case(spec, fleet_cap=requested_fleet)
            atomic_json(out / "prepared_case.json", prepared.manifest)
            write_json(out / "scenario.json", prepared.scenario)
            reference = None
            if args.checkpoint_import:
                reader = (
                    read_reservoir_cp_checkpoint_for_fleet_resize
                    if args.allow_fleet_resize_checkpoint
                    else read_reservoir_cp_checkpoint
                )
                reference = reader(args.checkpoint_import, prepared.problem)
            if args.method == "all_stop_phase":
                if args.capacity_search:
                    if args.build_only:
                        raise ValueError("capacity search cannot be combined with --build-only")
                    capacity_config = AllStopCapacitySearchConfig(
                            maximum_demand=spec.demand_total,
                            initial_demand=min(args.capacity_initial_demand, spec.demand_total),
                            time_limit_seconds=remaining_budget(),
                            workers=args.workers,
                            seed=args.seed,
                            cabins=args.cabins,
                            log_search_progress=args.log_search_progress,
                            probe_demands=tuple(args.capacity_probe_demand),
                            compact_time_links=True,
                            reference_directories=tuple(str(path) for path in args.capacity_reference_dir),
                            encoding=args.all_stop_capacity_encoding,
                        )
                    if spec.objective is ThesisObjective.JOURNEY_TIME:
                        if args.cabins is None:
                            raise ValueError(
                                "Journey capacity calibration requires exact --cabins"
                            )
                        native = search_fixed_k_all_stop_capacity(
                            spec,
                            capacity_config,
                            cabins=args.cabins,
                            event_callback=emit,
                        )
                        plan, plan_case = None, None
                    else:
                        def save_capacity_incumbent(value, value_case):
                            atomic_json(out / "best_case.json", value_case.manifest)
                            write_reservoir_cp_checkpoint(out / "best.json", value_case.problem, value)

                        native, plan, plan_case = search_all_stop_capacity(
                            spec,
                            capacity_config,
                            event_callback=emit,
                            incumbent_callback=save_capacity_incumbent,
                        )
                    if plan is not None:
                        atomic_json(out / "best_case.json", plan_case.manifest)
                        write_reservoir_cp_checkpoint(
                            out / "best.json", plan_case.problem, plan
                        )
                    result = {
                        "schema": "thesis_experiment_result_v1",
                        "method": args.method,
                        "case_fingerprint": spec.fingerprint,
                        "problem_fingerprint": prepared.problem.fingerprint,
                        "case": prepared.manifest,
                        "run": native,
                    }
                    atomic_json(out / "result.json", {
                        **result,
                        "total_wall_seconds": time.monotonic() - started,
                    })
                    return
                cabins = args.cabins or prepared.all_stop_reference_cabins
                phase = prepare_all_stop_phase(
                    prepared.problem,
                    AllStopPhaseConfig(
                        cabins=cabins,
                        objective=spec.objective.value,
                        require_full_service=(spec.objective is ThesisObjective.JOURNEY_TIME),
                        time_limit_seconds=remaining_budget(),
                        workers=args.workers,
                        seed=args.seed,
                        log_search_progress=args.log_search_progress,
                    ),
                )
                native, plan = solve_all_stop_phase(
                    phase, event_callback=emit, build_only=args.build_only
                )
                if plan is not None:
                    write_reservoir_cp_checkpoint(out / "best.json", prepared.problem, plan)
                result = {
                    "schema": "thesis_experiment_result_v1",
                    "method": args.method,
                    "case_fingerprint": spec.fingerprint,
                    "problem_fingerprint": prepared.problem.fingerprint,
                    "case": prepared.manifest,
                    "run": native,
                }
            elif args.method == "line_planning":
                if spec.objective is not ThesisObjective.UNSERVED:
                    raise ValueError("line_planning currently supports only unserved")
                line = ReservoirLineConfig(
                    dispatch_window_end_seconds=prepared.all_stop_cycle_tick / 1_000_000,
                    passenger_service_start_seconds=prepared.all_stop_cycle_tick / 1_000_000,
                    formulation=ReservoirLineFormulation(args.formulation),
                    catalog_profile=ReservoirLineCatalogProfile(args.catalog),
                    maximum_cabins=prepared.problem.available_fleet_count,
                    time_limit_seconds=remaining_budget() * 0.7,
                    workers=args.workers,
                    memory_limit_gib=args.memory_limit_gib,
                    seed=args.seed,
                    log_search_progress=args.log_search_progress,
                )
                native, plan = solve_reservoir_line_pipeline(
                    prepared.problem,
                    ReservoirLinePipelineConfig(
                        line,
                        remaining_budget(),
                        checkpoint_path=out / "timing_best.json",
                        construction_checkpoint_path=out / "construction_best.json",
                    ),
                    reference_plan=reference,
                    event_callback=emit,
                    build_only=args.build_only,
                )
                if plan is not None:
                    write_reservoir_cp_checkpoint(out / "best.json", prepared.problem, plan)
                result = {
                    "schema": "thesis_experiment_result_v1",
                    "method": args.method,
                    "case_fingerprint": spec.fingerprint,
                    "problem_fingerprint": prepared.problem.fingerprint,
                    "case": prepared.manifest,
                    "run": native,
                }
            else:
                if spec.objective is not ThesisObjective.UNSERVED or args.cabins is None:
                    raise ValueError("evolution requires unserved and exact --cabins")
                if args.checkpoint_import:
                    raise ValueError(
                        "the first thesis evolution integration does not import an external seed; "
                        "K-series transfer is handled by the campaign runner"
                    )
                from ropeway_skip_stop_optimization.optimization.ddd.reservoir_lines import (
                    ReservoirLinePreparation,
                    ReservoirLineVariant,
                    prepare_line_problem,
                )
                from ropeway_skip_stop_optimization.optimization.ddd.reservoir_lines.evolution import (
                    EvolutionEngine,
                    EvolutionSearchConfig,
                    OperatorProfile,
                    run_search,
                )
                initial_pattern_sequences = ()
                if args.initial_pattern_sequences is not None:
                    raw_sequences = json.loads(
                        args.initial_pattern_sequences.read_text(encoding="utf-8")
                    )
                    if not isinstance(raw_sequences, list) or any(
                        not isinstance(sequence, list)
                        or len(sequence) != args.cabins
                        or any(not isinstance(item, str) for item in sequence)
                        for sequence in raw_sequences
                    ):
                        raise ValueError(
                            "initial pattern sequences must be a JSON list of exact-K string lists"
                        )
                    initial_pattern_sequences = tuple(
                        tuple(sequence) for sequence in raw_sequences
                    )

                line = ReservoirLineConfig(
                    dispatch_window_end_seconds=prepared.all_stop_cycle_tick / 1_000_000,
                    passenger_service_start_seconds=prepared.all_stop_cycle_tick / 1_000_000,
                    variant=ReservoirLineVariant.INTERVALS,
                    preparation=ReservoirLinePreparation.ENCODING_SPECIFIC,
                    formulation=ReservoirLineFormulation.SHARED_ROUNDS,
                    catalog_profile=ReservoirLineCatalogProfile(args.catalog),
                    maximum_cabins=args.cabins,
                    fixed_cabins=args.cabins,
                    time_limit_seconds=remaining_budget(),
                    workers=args.workers,
                    memory_limit_gib=args.memory_limit_gib,
                    seed=args.seed,
                )
                line_prepared = prepare_line_problem(prepared.problem, line)
                atomic_json(
                    out / "evolution_prepared.json",
                    {
                        "model_fingerprint": line_prepared.model_fingerprint,
                        "catalog_profile": args.catalog,
                        "pattern_search": args.pattern_search,
                        "patterns": sorted({template.pattern_id for template in line_prepared.templates}),
                        "templates": len(line_prepared.templates),
                        "fixed_k": args.cabins,
                        "waiting_fixed_to_zero": True,
                        "initialization": "no_external_plan_and_no_forced_all_stop",
                    },
                )
                if args.build_only:
                    native = {
                        "schema": "thesis_evolution_result_v1",
                        "status": "PREPARATION_ONLY",
                        "best": None,
                    }
                    best = None
                else:
                    incumbent_number = 0

                    def save_incumbent(value):
                        nonlocal incumbent_number
                        incumbent_number += 1
                        certificate = out / "incumbents" / f"{incumbent_number:05d}.json"
                        write_reservoir_cp_checkpoint(certificate, prepared.problem, value.passengers.plan)
                        write_reservoir_cp_checkpoint(out / "best.json", prepared.problem, value.passengers.plan)
                        emit({"kind": "saved_validated_incumbent",
                              "certificate": str(certificate.relative_to(out)),
                              "served": value.passengers.served,
                              "unserved": value.passengers.unserved})

                    native = run_search(
                        prepared.problem,
                        line_prepared,
                        EvolutionSearchConfig(
                            engine=EvolutionEngine.GA,
                            operator_profile=OperatorProfile.MIXED_GLOBAL,
                            time_limit_seconds=remaining_budget(),
                            population_size=args.population_size,
                            offspring_size=args.offspring_size,
                            seed=args.seed,
                            passenger_time_limit_seconds=args.passenger_time_limit,
                            dispatch_decoder="intervals",
                            fixed_k=args.cabins,
                            seed_all_stop=False,
                            waiting_construction="no_wait_first",
                            selection_profile="grouped",
                            representation="patterns_dispatch",
                            initial_pattern_sequences=initial_pattern_sequences,
                            objective="service_then_journey",
                            # Full service only completes the primary objective.
                            # Continue searching for lower journey time (and thus
                            # useful skip-stop structures) until the run budget ends.
                            stop_on_full_service=False,
                            pattern_search=args.pattern_search,
                        ),
                        event_callback=emit,
                        incumbent_callback=save_incumbent,
                    )
                    best = native.pop("best")
                    native["status"] = "COMPLETE"
                    if best is not None:
                        write_reservoir_cp_checkpoint(
                            out / "best.json", prepared.problem, best.passengers.plan
                        )
                result = {
                    "schema": "thesis_experiment_result_v1",
                    "method": args.method,
                    "case_fingerprint": spec.fingerprint,
                    "problem_fingerprint": prepared.problem.fingerprint,
                    "case": prepared.manifest,
                    "run": {
                        **native,
                        "best": None if best is None else asdict(best),
                        "proof_scope": "HEURISTIC_FIXED_K_NO_WAIT_CONFIGURED_PATTERN_CATALOG",
                    },
                }
    result["total_wall_seconds"] = time.monotonic() - started
    atomic_json(out / "result.json", result)


def main() -> None:
    args = parser().parse_args()
    if not 0 <= args.mip_gap <= 1:
        raise ValueError("--mip-gap must be between 0 and 1")
    if args.time_limit <= 0 or args.workers <= 0:
        raise ValueError("time limit and workers must be positive")
    if not 0 < args.memory_limit_gib <= 32:
        raise ValueError("memory limit must lie in (0, 32] GiB on the calibrated host")
    if args.population_size <= 0 or args.offspring_size <= 0:
        raise ValueError("population and offspring sizes must be positive")
    if args.passenger_time_limit <= 0:
        raise ValueError("passenger time limit must be positive")
    _spec(args).validate()
    if args.method == "evolution" and args.operating_mode != "skip_stop":
        raise ValueError("evolution selects its catalogue; use all_stop_phase for All-Stop")
    if args.method == "labelled_arc_flow" and args.checkpoint_import:
        raise ValueError("thesis arc-flow runs do not import a primal start")
    if args._worker:
        try:
            worker(args)
        except BaseException as error:
            atomic_json(
                args.output_dir / "failure.json",
                {"type": type(error).__name__, "error": str(error), "proof": False},
            )
            raise
        return
    args.output_dir.mkdir(parents=True, exist_ok=False)
    atomic_json(
        args.output_dir / "arguments.json",
        {
            **vars(args),
            "case_spec": None if args.case_spec is None else str(args.case_spec),
            "checkpoint_import": (
                None if args.checkpoint_import is None else str(args.checkpoint_import)
            ),
            "initial_pattern_sequences": (
                None
                if args.initial_pattern_sequences is None
                else str(args.initial_pattern_sequences)
            ),
            "output_dir": str(args.output_dir),
        },
    )
    outcome = supervise(
        [sys.executable, str(Path(__file__).resolve()), *sys.argv[1:], "--_worker"],
        args.output_dir,
        seconds=args.time_limit,
        memory_bytes=int(args.memory_limit_gib * 1024**3),
        system_memory_pressure_seconds=30.0,
    )
    if outcome["supervisor_reason"] or outcome["exit_code"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
