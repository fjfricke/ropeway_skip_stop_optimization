"""Run the solver-free no-wait line decoder with GA, TPE, or random search."""

from __future__ import annotations

import argparse
from collections import Counter
from dataclasses import asdict, replace
import hashlib
import importlib.metadata
import json
import math
from pathlib import Path
import sys
from time import perf_counter
import time

from ropeway_skip_stop_optimization.benchmarking.native_solvers import supervise
from ropeway_skip_stop_optimization.optimization.ddd.cp_sat_certificate import atomic_json, stable_fingerprint
from ropeway_skip_stop_optimization.optimization.ddd.reservoir_boundary import (
    add_boundary_arguments,
    apply_boundary_arguments,
)
from ropeway_skip_stop_optimization.optimization.ddd.reservoir_cp_sat_certificate import (
    validate_reservoir_cp_plan,
    write_reservoir_cp_checkpoint,
)
from ropeway_skip_stop_optimization.optimization.ddd.reservoir_hybrid.domain import load_reference
from ropeway_skip_stop_optimization.optimization.ddd.reservoir_lines import (
    ReservoirLineCatalogProfile,
    ReservoirLineConfig,
    ReservoirLineFormulation,
    ReservoirLineMode,
    ReservoirLinePreparation,
    ReservoirLineVariant,
    prepare_line_problem,
)
from ropeway_skip_stop_optimization.optimization.ddd.reservoir_lines.evolution import (
    DispatchSubproblem,
    EvolutionEngine,
    EvolutionSearchConfig,
    GenomeFactory,
    LineEvolutionEvaluator,
    LineGenome,
    OperatorProfile,
    PatternOnlyEvaluator,
    PatternSequenceGenome,
    genome_from_plan,
    run_search,
)


def _hashes():
    root = Path(__file__).resolve().parents[1]
    files = [Path(__file__), *sorted((
        root / "src/ropeway_skip_stop_optimization/optimization/ddd/reservoir_lines/evolution"
    ).glob("*.py"))]
    return {
        str(path.relative_to(root)): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in files
    }


def _payload(value):
    if value is None:
        return None
    data = asdict(value)
    plan = data.get("plan")
    if plan is not None:
        data["plan"] = {
            "trips": plan["trips"],
            "ride_counts": plan["ride_counts"],
        }
    return data


def main():
    parser = argparse.ArgumentParser(allow_abbrev=False)
    parser.add_argument("--reference-checkpoint", type=Path, required=True)
    parser.add_argument(
        "--initial-checkpoint",
        type=Path,
        help=(
            "optional common start plan; the reference checkpoint still defines "
            "the frozen problem"
        ),
    )
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--engine", choices=list(EvolutionEngine), default="ga")
    parser.add_argument("--operator-profile", choices=list(OperatorProfile), default="mixed_global")
    parser.add_argument("--pattern-search", choices=("independent", "line_groups"), default="independent")
    parser.add_argument(
        "--catalog",
        choices=list(ReservoirLineCatalogProfile),
        default="relevant",
        help="Deterministic stop-mask catalog; thesis runs use od_endpoints_v1.",
    )
    parser.add_argument("--representation", choices=("patterns_dispatch", "patterns_only"), default="patterns_dispatch")
    parser.add_argument("--dispatch-subproblem", choices=list(DispatchSubproblem), default="timing_then_passengers")
    parser.add_argument("--evaluation-time-limit", type=float, default=8,
                        help="Total model-build/search/validation limit for one patterns-only candidate")
    parser.add_argument(
        "--evaluation-parallelism",
        type=int,
        default=1,
        help="Number of independent patterns-only candidates evaluated concurrently",
    )
    parser.add_argument(
        "--elite-reevaluation-time-limit",
        type=float,
        default=0,
        help="Reserved final Gurobi reassessment time for the best fixed movement",
    )
    parser.add_argument("--pattern-waiting-seconds", type=float, default=0,
                        help="patterns_only: exact Waiting cap per STOP; dispatch and lap count remain free")
    parser.add_argument("--initial-pattern-sequences", type=Path,
                        help="JSON list of common initial pattern sequences for controlled comparisons")
    parser.add_argument("--dispatch-window-end", type=float, required=True)
    parser.add_argument("--max-cabins", type=int)
    parser.add_argument("--fixed-k", type=int, help="Exactly this many active cabins in every search candidate")
    parser.add_argument("--no-all-stop-initialization", action="store_true", help="Do not deliberately insert homogeneous All-Stop samples")
    parser.add_argument("--time-limit", type=float, default=120)
    parser.add_argument("--passenger-time-limit", type=float, default=2)
    parser.add_argument(
        "--objective",
        choices=("unserved", "journey_time", "service_then_journey"),
        default="unserved",
    )
    parser.add_argument("--workers", type=int, default=12)
    parser.add_argument("--memory-limit-gib", type=float, default=32)
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument("--selection-profile", choices=("legacy", "grouped", "pattern_status"), default="legacy")
    parser.add_argument("--population-size", type=int, default=32)
    parser.add_argument("--offspring-size", type=int, default=8)
    parser.add_argument("--exploration-parent-probability", type=float, default=0.25)
    parser.add_argument('--dispatch-decoder', choices=('legacy', 'intervals'), default='legacy')
    parser.add_argument('--waiting-construction', choices=('no_wait_first', 'prefix_first'), default='no_wait_first',
                        help='prefix_first checks only immutable pre-wait occupancy; with repair budget 0, score full No-Wait conflicts without timing repair')
    parser.add_argument('--waiting-repair-seconds', type=float, default=0,
                        help='Optional fixed-dispatch repair after interval insertion; e.g. 5 seconds.')
    parser.add_argument('--waiting-budget-fraction', type=float, default=None,
                        help='Optional aggregate repair cap for old comparisons; by default every new candidate gets its own budget.')
    parser.add_argument('--earliest-wait-seconds', type=float,
                        help='Explicit domain change, e.g. 0 to allow waiting during warmup.')
    parser.add_argument('--live-snapshot', type=Path,
                        help='Atomic JSON snapshot consumed by the local live dashboard.')
    parser.add_argument('--live-label', default='Evolution run')
    parser.add_argument("--build-only", action="store_true")
    parser.add_argument("--evaluate-only", type=Path)
    parser.add_argument("--no-reference-initialization", action="store_true")
    parser.add_argument("--_worker", action="store_true", help=argparse.SUPPRESS)
    add_boundary_arguments(parser)
    args = parser.parse_args()
    if not 0 < args.memory_limit_gib <= 32:
        parser.error("--memory-limit-gib must lie in (0, 32]")
    if args.build_only and args.evaluate_only:
        parser.error("--build-only conflicts with --evaluate-only")
    if args.selection_profile == "grouped" and args.engine != "ga":
        parser.error("--selection-profile grouped requires --engine ga")
    if args.representation == "patterns_only":
        if args.engine != "ga":
            parser.error("--representation patterns_only requires --engine ga")
        if args.waiting_repair_seconds:
            parser.error("patterns_only uses --pattern-waiting-seconds, not fixed-dispatch repair")
        if not math.isfinite(args.evaluation_time_limit) or args.evaluation_time_limit <= 0:
            parser.error("--evaluation-time-limit must be finite and positive")
        if not 1 <= args.evaluation_parallelism <= 16:
            parser.error("--evaluation-parallelism must lie in [1, 16]")
        # The dedicated survival rule is part of the representation contract.
        args.selection_profile = "pattern_status"
    if args.fixed_k is not None and (args.fixed_k < 1 or (args.max_cabins is not None and args.fixed_k > args.max_cabins)):
        parser.error("--fixed-k must be positive and fit --max-cabins")
    if args.engine != "ga" and (args.fixed_k is not None or args.no_all_stop_initialization):
        parser.error("fixed K and custom initialization currently require --engine ga")
    if args.initial_checkpoint and args.no_reference_initialization:
        parser.error("--initial-checkpoint conflicts with --no-reference-initialization")
    initial_pattern_sequences = ()
    if args.initial_pattern_sequences:
        raw_sequences = json.loads(args.initial_pattern_sequences.read_text())
        if not isinstance(raw_sequences, list) or any(not isinstance(x, list) for x in raw_sequences):
            parser.error("--initial-pattern-sequences must contain a JSON list of lists")
        initial_pattern_sequences = tuple(tuple(map(str, x)) for x in raw_sequences)
        if args.fixed_k is not None and any(len(x) != args.fixed_k for x in initial_pattern_sequences):
            parser.error("every initial pattern sequence must have exactly --fixed-k entries")
    if (args.waiting_repair_seconds < 0 or not math.isfinite(args.waiting_repair_seconds)
            or (args.waiting_budget_fraction is not None and not 0 <= args.waiting_budget_fraction <= 1)):
        parser.error('invalid waiting repair budget')
    if args.waiting_construction == 'prefix_first' and args.dispatch_decoder != 'intervals':
        parser.error('--waiting-construction prefix_first requires --dispatch-decoder intervals')
    if args.waiting_repair_seconds and args.dispatch_decoder != 'intervals':
        parser.error('--waiting-repair-seconds requires --dispatch-decoder intervals')
    if args.earliest_wait_seconds is not None and (not math.isfinite(args.earliest_wait_seconds) or args.earliest_wait_seconds < 0):
        parser.error('--earliest-wait-seconds must be finite and nonnegative')
    if not math.isfinite(args.pattern_waiting_seconds) or args.pattern_waiting_seconds < 0:
        parser.error('--pattern-waiting-seconds must be finite and nonnegative')
    if (
        not math.isfinite(args.elite_reevaluation_time_limit)
        or args.elite_reevaluation_time_limit < 0
        or args.elite_reevaluation_time_limit >= args.time_limit
    ):
        parser.error("elite reevaluation must be nonnegative and smaller than the run")
    if args.pattern_waiting_seconds and args.representation != 'patterns_only':
        parser.error('--pattern-waiting-seconds requires patterns_only')
    if not args._worker:
        args.output.mkdir(parents=True, exist_ok=False)
        atomic_json(args.output / "arguments.json", {
            **{key: str(value) if isinstance(value, Path) else value for key, value in vars(args).items()}
        })
        metrics = supervise(
            [sys.executable, str(Path(__file__).resolve()), *sys.argv[1:], "--_worker"],
            args.output,
            seconds=args.time_limit,
            memory_bytes=int(args.memory_limit_gib * 1024**3),
            system_memory_pressure_seconds=30,
        )
        result = None
        if (args.output / "result.json").exists():
            result = json.loads((args.output / "result.json").read_text())
        print(json.dumps({"supervisor": metrics, "result": result}, indent=2))
        return

    started = perf_counter()
    domain, external_reference = load_reference(args.reference_checkpoint)
    problem = apply_boundary_arguments(domain.problem, args)
    if args.pattern_waiting_seconds:
        from ropeway_skip_stop_optimization.optimization.ddd.reservoir_lines.evolution.pattern_waiting import with_pattern_waiting
        problem = with_pattern_waiting(problem, args.pattern_waiting_seconds)
    if args.earliest_wait_seconds is not None:
        problem = replace(problem, waiting_policy=replace(problem.waiting_policy,
                          earliest_wait_time_seconds=args.earliest_wait_seconds))
        problem.validate()
    external_metrics = None
    try:
        external_metrics = asdict(validate_reservoir_cp_plan(problem, external_reference))
    except ValueError:
        pass
    reference = external_reference
    reference_status = "external_reference_only"
    if args.initial_checkpoint is not None:
        try:
            _, reference = load_reference(args.initial_checkpoint)
            validate_reservoir_cp_plan(problem, reference)
            reference_status = "initial_checkpoint_valid"
        except ValueError as error:
            reference_status = f"initial_checkpoint_invalid:{error}"
            reference = None
    elif args.no_reference_initialization:
        reference = None
        reference_status = "initialization_disabled"
    else:
        # Backward compatible single-run behavior. Campaigns pass an explicit
        # all-stop initialization and keep good skip-stop plans external.
        reference_status = "problem_checkpoint_used_as_initialization"
    try:
        if reference is not None:
            validate_reservoir_cp_plan(problem, reference)
    except ValueError as error:
        reference_status = f"not_valid_under_selected_boundary:{error}"
        reference = None
    maximum = (args.fixed_k if args.representation == "patterns_only" and args.fixed_k is not None else
               problem.available_fleet_count if args.max_cabins is None else args.max_cabins)
    line_config = ReservoirLineConfig(
        dispatch_window_end_seconds=args.dispatch_window_end,
        passenger_service_start_seconds=args.dispatch_window_end,
        variant=ReservoirLineVariant.INTERVALS,
        preparation=ReservoirLinePreparation.ENCODING_SPECIFIC,
        formulation=ReservoirLineFormulation.SHARED_ROUNDS,
        mode=ReservoirLineMode.EXACT_SERVICE,
        catalog_profile=ReservoirLineCatalogProfile(args.catalog),
        maximum_cabins=maximum,
        time_limit_seconds=args.time_limit,
        workers=args.workers,
        memory_limit_gib=args.memory_limit_gib,
        seed=args.seed,
    )
    prepared = prepare_line_problem(problem, line_config)
    if args.representation == "patterns_dispatch":
        GenomeFactory(problem, prepared, fixed_k=args.fixed_k)
    else:
        from ropeway_skip_stop_optimization.optimization.ddd.reservoir_lines.evolution import (
            PatternGenomeFactory,
            PatternLineGroupGenomeFactory,
        )
        factory_type = (
            PatternLineGroupGenomeFactory
            if args.pattern_search == "line_groups"
            else PatternGenomeFactory
        )
        factory_type(problem, prepared, fixed_k=args.fixed_k)
    atomic_json(args.output / "prepared.json", {
        "problem_fingerprint": problem.fingerprint,
        "model_fingerprint": (prepared.model_fingerprint if args.dispatch_decoder == 'legacy' else
            stable_fingerprint({'preparation': prepared.model_fingerprint,
                'encoding': 'interval_dispatch_with_optional_waiting_v1',
                'repair_seconds': args.waiting_repair_seconds,
                'repair_fraction': args.waiting_budget_fraction,
                'fixed_k': args.fixed_k, 'seed_all_stop': not args.no_all_stop_initialization,
                'waiting_construction': args.waiting_construction,
                'selection_profile': args.selection_profile,
                'representation': args.representation,
                'dispatch_subproblem': args.dispatch_subproblem,
                'pattern_waiting_seconds': args.pattern_waiting_seconds,
                'evaluation_time_limit': args.evaluation_time_limit})),
        "representation": args.representation,
        "dispatch_subproblem": args.dispatch_subproblem,
        "evaluation_time_limit_seconds": args.evaluation_time_limit,
        "pattern_waiting_seconds": args.pattern_waiting_seconds,
        "selection_profile": args.selection_profile,
        "waiting_construction": args.waiting_construction,
        "fixed_k": args.fixed_k,
        "seed_all_stop": not args.no_all_stop_initialization,
        "dispatch_decoder": args.dispatch_decoder,
        "waiting_policy": asdict(problem.waiting_policy),
        "patterns": sorted({t.pattern_id for t in prepared.templates}),
        "catalog_profile": args.catalog,
        "templates": len(prepared.templates),
        "maximum_cabins": prepared.maximum_cabins,
        "reference_status": reference_status,
        "external_reference_metrics": external_metrics,
        "source_hashes": _hashes(),
        "versions": {name: importlib.metadata.version(name) for name in ("pymoo", "optuna", "gurobipy", "numpy", "ortools")},
        "execution": {"decoder_workers": 1, "passenger_threads": 1, "requested_workers": args.workers,
                      "parallel_candidate_evaluations": args.evaluation_parallelism,
                      "waiting_workers": args.workers if args.waiting_repair_seconds or args.pattern_waiting_seconds else 0},
        "search_engine": args.engine,
        "potential_semantics": "integer passenger assignment ignoring inter-cabin collisions; never validated service" if args.engine == "nsga2" else None,
    })
    if args.build_only:
        atomic_json(args.output / "result.json", {
            "schema": "reservoir_line_evolution_result_v1",
            "status": "BUILD_ONLY",
            "total_wall_seconds": perf_counter() - started,
        })
        return
    if args.representation == "patterns_only":
        evaluator = PatternOnlyEvaluator(
            problem, prepared, subproblem=args.dispatch_subproblem,
            evaluation_seconds=args.evaluation_time_limit, workers=args.workers,
            waiting=bool(args.pattern_waiting_seconds),
            memory_limit_gib=args.memory_limit_gib, seed=args.seed,
            deadline=started + args.time_limit - 1,
            passenger_objective=args.objective,
        )
    else:
        evaluator = LineEvolutionEvaluator(problem, prepared, args.passenger_time_limit,
            evaluate_infeasible_potential=args.engine == "nsga2",
            deadline=started+args.time_limit-1,
            dispatch_decoder=args.dispatch_decoder, waiting_repair_seconds=args.waiting_repair_seconds,
            waiting_budget_seconds=(None if args.waiting_budget_fraction is None else args.time_limit*args.waiting_budget_fraction),
            waiting_workers=args.workers, seed=args.seed, waiting_construction=args.waiting_construction)
    if args.evaluate_only:
        raw = json.loads(args.evaluate_only.read_text())
        genome = (PatternSequenceGenome(tuple(raw["pattern_ids"]))
                  if args.representation == "patterns_only" else
                  LineGenome(tuple(raw["pattern_ids"]), int(raw["phase_tick"]),
                             tuple(map(int, raw["extra_gap_ticks"]))))
        if args.fixed_k is not None and genome.fleet_size != args.fixed_k:
            raise ValueError("evaluation candidate must have exactly fixed_k active cabins")
        value = evaluator.evaluate(genome)
        result = {
            "schema": "reservoir_line_evolution_evaluation_v1",
            "evaluation": _payload(value),
            "total_wall_seconds": perf_counter() - started,
        }
        if value.passengers is not None:
            write_reservoir_cp_checkpoint(args.output / "best.json", problem, value.passengers.plan)
        atomic_json(args.output / "result.json", result)
        return
    reference_genome = None
    if reference is not None and args.representation == "patterns_dispatch":
        try:
            reference_genome = genome_from_plan(problem, prepared, reference)
        except ValueError as error:
            reference_status = f"not_representable:{error}"
    progress = args.output / "events.jsonl"
    live = {
        'schema': 'reservoir_line_evolution_live_v1', 'label': args.live_label,
        'status': 'running', 'time_limit_seconds': args.time_limit,
        'reference_served': (external_metrics or {}).get('served'),
        'reference_journey_time_tick': (external_metrics or {}).get('journey_time_tick'),
        'events_seen': 0, 'evaluations': 0,
        'feasible_evaluations': 0, 'best': None, 'best_mixed': None,
        'incumbents': [], 'mixed_incumbents': [],
        'repair_counts': {}, 'repair_seconds': 0.0, 'updated_unix': time.time(),
        'representation': args.representation, 'dispatch_subproblem': args.dispatch_subproblem,
        'timing_status_counts': {}, 'pattern_cache_hits': 0,
        'objective': args.objective,
        'catalog_profile': args.catalog,
        'allowed_pattern_count': len({t.pattern_id for t in prepared.templates}),
        'pattern_search': args.pattern_search,
        'evaluation_parallelism': args.evaluation_parallelism,
        'fixed_k': args.fixed_k, 'maximum_cabins': prepared.maximum_cabins,
        'fleet_evaluations': {},
        'workers_per_evaluation': args.workers,
    }
    if args.live_snapshot:
        args.live_snapshot.parent.mkdir(parents=True, exist_ok=True)
        atomic_json(args.live_snapshot, live)
    def emit(event):
        with progress.open("a") as stream:
            stream.write(json.dumps(event, sort_keys=True) + "\n")
        if args.live_snapshot:
            live['events_seen'] += 1
            live['elapsed_seconds'] = event.get('elapsed_seconds', 0)
            live['updated_unix'] = time.time()
            if event['kind'] == 'evaluation_window':
                live['evaluations'] = event['evaluations_total']
                live['feasible_evaluations'] = event['feasible_total']
            elif event['kind'] == 'incumbent':
                point = {key: event.get(key) for key in (
                    'elapsed_seconds','served','unserved','fleet_size','pattern_counts',
                    'total_wait_tick','repair_status','journey_time_tick')}
                live['incumbents'].append(point); live['best'] = point
                live['last_improvement_seconds'] = event['elapsed_seconds']
            elif event['kind'] == 'mixed_fleet_frontier':
                point = {key: event.get(key) for key in (
                    'elapsed_seconds','served','unserved','fleet_size','pattern_counts',
                    'total_wait_tick','repair_status','journey_time_tick')}
                live['mixed_incumbents'].append(point)
                if live['best_mixed'] is None or point['served'] > live['best_mixed']['served']:
                    live['best_mixed'] = point
            elif event['kind'] == 'waiting_repair':
                status = event['repair']['status']
                live['repair_counts'][status] = live['repair_counts'].get(status, 0) + 1
                live['repair_seconds'] += event['repair'].get('total_wall_seconds', 0)
            elif event['kind'] == 'pattern_subproblem':
                status = event['timing_status']
                k = str(len(event.get('pattern_ids', ())))
                live['fleet_evaluations'][k] = live['fleet_evaluations'].get(k, 0) + 1
                live['timing_status_counts'][status] = live['timing_status_counts'].get(status, 0) + 1
                live['last_pattern_subproblem'] = {key: event.get(key) for key in (
                    'elapsed_seconds', 'timing_status', 'native_status', 'subproblem',
                    'served', 'pattern_ids', 'preparation_seconds', 'model_build_seconds',
                    'solve_seconds', 'validation_seconds')}
            atomic_json(args.live_snapshot, live)
    config = EvolutionSearchConfig(
        EvolutionEngine(args.engine), OperatorProfile(args.operator_profile),
        max(
            0.001,
            args.time_limit
            - (perf_counter() - started)
            - args.elite_reevaluation_time_limit
            - 2,
        ),
        args.population_size, args.offspring_size, args.seed, args.exploration_parent_probability, args.passenger_time_limit,
        dispatch_decoder=args.dispatch_decoder, waiting_repair_seconds=args.waiting_repair_seconds,
        waiting_budget_fraction=args.waiting_budget_fraction, waiting_workers=args.workers,
        fixed_k=args.fixed_k, seed_all_stop=not args.no_all_stop_initialization,
        waiting_construction=args.waiting_construction, selection_profile=args.selection_profile,
        representation=args.representation, dispatch_subproblem=args.dispatch_subproblem,
        evaluation_time_limit_seconds=args.evaluation_time_limit,
        pattern_waiting=bool(args.pattern_waiting_seconds),
        initial_pattern_sequences=initial_pattern_sequences,
        objective=args.objective,
        pattern_search=args.pattern_search,
        evaluation_parallelism=args.evaluation_parallelism,
    )
    def save_incumbent(value):
        write_reservoir_cp_checkpoint(args.output / "best.json", problem, value.passengers.plan)
    result = run_search(
        problem, prepared, config,
        reference_genome=reference_genome,
        event_callback=emit,
        incumbent_callback=save_incumbent,
    )
    best = result.pop("best")
    if best is not None and args.elite_reevaluation_time_limit > 0:
        from ropeway_skip_stop_optimization.optimization.ddd.reservoir_lines.evolution.passengers import (
            optimize_fixed_movement_passengers,
        )
        reassessed = optimize_fixed_movement_passengers(
            problem,
            best.movement.plan,
            time_limit_seconds=min(
                args.elite_reevaluation_time_limit,
                max(0.001, started + args.time_limit - perf_counter() - 0.5),
            ),
            objective=args.objective,
        )
        from dataclasses import replace as dataclass_replace
        best = dataclass_replace(best, passengers=reassessed)
        result["elite_reevaluation"] = {
            "served": reassessed.served,
            "unserved": reassessed.unserved,
            "journey_time_tick": reassessed.journey_time_tick,
            "proven_optimal": reassessed.proven_optimal,
            "status": reassessed.status,
            "build_seconds": reassessed.build_seconds,
            "solve_seconds": reassessed.solve_seconds,
            "validation_seconds": reassessed.validation_seconds,
        }
        if args.live_snapshot:
            point = {
                "elapsed_seconds": perf_counter() - started,
                "served": reassessed.served,
                "unserved": reassessed.unserved,
                "fleet_size": best.movement.genome.fleet_size,
                "pattern_counts": dict(sorted(Counter(best.movement.genome.pattern_ids).items())),
                "total_wait_tick": sum(
                    sum(trip.wait_ticks) for trip in reassessed.plan.trips
                ),
                "repair_status": None,
                "journey_time_tick": reassessed.journey_time_tick,
            }
            live["best"] = point
            live["incumbents"].append(point)
            live["last_improvement_seconds"] = point["elapsed_seconds"]
            atomic_json(args.live_snapshot, live)
    payload = {
        **result,
        "best": _payload(best),
        "reference_status": reference_status,
        "external_reference_metrics": external_metrics,
        "runner_total_wall_seconds": perf_counter() - started,
    }
    if best is not None:
        write_reservoir_cp_checkpoint(args.output / "best.json", problem, best.passengers.plan)
    atomic_json(args.output / "result.json", payload)
    if args.live_snapshot:
        live.update(status='complete', elapsed_seconds=payload['runner_total_wall_seconds'],
                    evaluations=payload['evaluations'], feasible_evaluations=payload['feasible_evaluations'],
                    updated_unix=time.time())
        atomic_json(args.live_snapshot, live)
        manifest_path = args.live_snapshot.parent / "manifest.json"
        if manifest_path.exists():
            try:
                manifest = json.loads(manifest_path.read_text())
                snapshot_url = "/generated/evolution-live/" + args.live_snapshot.name
                for item in manifest.get("runs", []):
                    if item.get("snapshot") == snapshot_url:
                        item["status"] = "complete"
                manifest["completed_runs"] = sum(
                    item.get("status") == "complete"
                    for item in manifest.get("runs", [])
                )
                if manifest["completed_runs"] == manifest.get("total_runs"):
                    manifest["status"] = "complete"
                manifest["updated_unix"] = time.time()
                atomic_json(manifest_path, manifest)
            except (OSError, ValueError, TypeError):
                pass


if __name__ == "__main__":
    main()
