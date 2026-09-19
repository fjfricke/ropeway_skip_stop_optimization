from __future__ import annotations

import argparse
from dataclasses import replace
from pathlib import Path
from time import perf_counter

from ropeway_skip_stop_optimization.benchmarking.oip_pattern_screening import (
    OipScreeningDemandFamily,
    materialize_pattern_allocation,
    pattern_allocations,
)
from ropeway_skip_stop_optimization.benchmarking.oip_pattern_waiting import (
    prepare_oip_pattern_waiting_pilot,
)
from ropeway_skip_stop_optimization.examples.registry import EXAMPLES, get_example
from ropeway_skip_stop_optimization.optimization.ean import (
    EanFleetCardinalityMode,
    EanFleetMode,
    StationWaitingMode,
)
from ropeway_skip_stop_optimization.optimization.oip import (
    OipBackend,
    OipOperation,
    OipPassengerEncoding,
    OipRunConfig,
    OipTimeGrid,
    prepare_oip_domain,
    run_oip,
    shift_scenario_for_oip_warmup,
)


def main() -> None:
    trial_started = perf_counter()
    args = _parse_args()
    if args.thesis_f2_pilot:
        cabin_count = args.fixed_k or 62
        demand_family = OipScreeningDemandFamily(args.demand_family)
        prepared = prepare_oip_pattern_waiting_pilot(
            maximum_wait_seconds=args.maximum_wait_seconds,
            cabin_count=cabin_count,
            demand_total=args.demand_total,
            ticks_per_second=args.ticks_per_second,
            demand_family=demand_family.value,
            operation=OipOperation(args.operation),
        )
        domain = prepared.domain
        if args.type_catalog is not None:
            fixed_stop_patterns = None
        elif args.pattern_mix in prepared.pattern_mixes:
            fixed_stop_patterns = prepared.pattern_mixes[args.pattern_mix]
        else:
            station_ids = tuple(
                dict.fromkeys(timing.station_id for timing in domain.artifact.timings)
            )
            allocation = next(
                item
                for item in pattern_allocations(demand_family, station_ids)
                if item.id == args.pattern_mix
            )
            fixed_stop_patterns = materialize_pattern_allocation(
                allocation, cabin_count, station_ids
            ).patterns_by_cabin_id
    else:
        domain, fixed_stop_patterns = _prepare_generic(args)
    remaining_time = (
        None
        if args.time_limit is None
        else max(0.001, args.time_limit - (perf_counter() - trial_started))
    )
    result = run_oip(
        domain,
        OipRunConfig(
            backend=OipBackend(args.backend),
            passenger_encoding=OipPassengerEncoding(args.passenger_encoding),
            time_limit_seconds=remaining_time,
            deadline_unix=args.deadline_unix,
            seed=args.seed,
            workers=args.workers,
            mip_gap=args.mip_gap,
            build_only=args.build_only,
            movement_only=args.movement_only,
            fixed_stop_patterns=fixed_stop_patterns,
            stop_if_cannot_beat_reference=args.stop_if_cannot_beat_reference,
            type_catalog=args.type_catalog,
            fixed_type_counts=args.fixed_type_counts,
            passenger_evaluation_time_limit_seconds=args.passenger_evaluation_time_limit,
            output_directory=args.output,
            log_to_console=args.log_to_console,
            memory_limit_gib=args.memory_limit_gib,
            reference_directory=args.all_stop_reference,
            start_checkpoint_directory=args.start_checkpoint,
            formulation=args.formulation,
            objective=args.objective,
        ),
    )
    status = getattr(result, "status", None) or getattr(
        getattr(result, "metadata", None), "status", "build_only"
    )
    print(f"OIP {args.backend} finished with status {status}; output: {args.output}")


def _prepare_generic(args):
    example = get_example(args.example)
    scenario = shift_scenario_for_oip_warmup(
        example.build_scenario(), args.warmup_seconds
    )
    if not hasattr(example, "build_ean_config") or not hasattr(
        example, "build_ean_artifact_builder"
    ):
        raise ValueError(f"example {args.example!r} cannot build an EAN OIP domain")
    config = example.build_ean_config(scenario)
    config = replace(
        config,
        station_configs=tuple(
            replace(
                item,
                waiting_mode=(
                    StationWaitingMode.NO_WAITING
                    if args.maximum_wait_seconds == 0
                    else StationWaitingMode.END_OF_PLATFORM_WAIT
                ),
                max_wait_seconds=(
                    None
                    if args.maximum_wait_seconds == 0
                    else args.maximum_wait_seconds
                ),
            )
            for item in config.station_configs
        ),
    )
    builder = example.build_ean_artifact_builder(scenario, config)
    builder = replace(
        builder,
        fleet_config=replace(
            builder.fleet_config,
            mode=EanFleetMode.OPTIMIZED_INITIAL_PLACEMENT,
            available_fleet_count=args.k_max if args.fixed_k is None else args.fixed_k,
            cardinality_mode=(
                EanFleetCardinalityMode.UP_TO_AVAILABLE
                if args.fixed_k is None
                else EanFleetCardinalityMode.EXACT
            ),
        ),
    )
    artifact = builder.build(scenario, config)
    fixed_stop_patterns = _patterns_for_mix(args.pattern_mix, args.k_max, artifact)
    domain = prepare_oip_domain(
        scenario=scenario,
        artifact=artifact,
        operation=OipOperation(args.operation),
        fixed_k=args.fixed_k,
        grid=OipTimeGrid(args.ticks_per_second),
    )
    return domain, fixed_stop_patterns


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run the common 1-ms optimized-initial-placement comparison."
    )
    parser.add_argument("--example", choices=tuple(sorted(EXAMPLES)))
    parser.add_argument("--thesis-f2-pilot", action="store_true")
    parser.add_argument(
        "--demand-family",
        choices=tuple(OipScreeningDemandFamily),
        default=OipScreeningDemandFamily.F2.value,
        help="Demand family for the frozen technical OIP pilot",
    )
    parser.add_argument(
        "--demand-total",
        type=int,
        default=3_210,
        help="Total profile demand for the short-horizon thesis pilot",
    )
    parser.add_argument("--backend", choices=tuple(OipBackend), default=OipBackend.CP_SAT)
    parser.add_argument("--operation", choices=tuple(OipOperation), default=OipOperation.SKIP_STOP)
    fleet = parser.add_mutually_exclusive_group()
    fleet.add_argument("--k-max", type=int)
    fleet.add_argument("--fixed-k", type=int)
    parser.add_argument(
        "--passenger-encoding",
        choices=tuple(OipPassengerEncoding),
        default=None,
    )
    parser.add_argument("--ticks-per-second", type=int, default=1_000)
    parser.add_argument("--warmup-seconds", type=float, default=0.0)
    parser.add_argument("--maximum-wait-seconds", type=float, default=0.0)
    parser.add_argument("--time-limit", type=float, default=None)
    parser.add_argument("--deadline-unix", type=float, default=None)
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument("--workers", type=int, default=1)
    parser.add_argument("--memory-limit-gib", type=float, default=32.0)
    parser.add_argument("--mip-gap", type=float, default=None)
    parser.add_argument("--build-only", action="store_true")
    parser.add_argument("--movement-only", action="store_true",
                        help="Find a feasible movement without building passenger variables")
    parser.add_argument(
        "--formulation", choices=("ean", "nowait_templates"), default="ean",
    )
    parser.add_argument(
        "--objective", choices=("lexicographic", "served"),
        default="lexicographic",
    )
    patterns = parser.add_mutually_exclusive_group()
    patterns.add_argument(
        "--pattern-mix",
        help=(
            "Fix a repeating per-cabin station mask. Integrated passenger "
            "optimization with fixed patterns is supported by CP-SAT."
        ),
    )
    patterns.add_argument(
        "--type-catalog",
        choices=("all_stop_alternating", "all_stop_bd_ce"),
        help="Let CP-SAT choose one of a small set of cabin-wide stop types.",
    )
    parser.add_argument("--fixed-type-counts", help="JSON object of exact catalog type counts")
    parser.add_argument("--log-to-console", action="store_true")
    parser.add_argument("--stop-if-cannot-beat-reference", action="store_true")
    parser.add_argument("--all-stop-reference", type=Path, default=None)
    parser.add_argument("--start-checkpoint", type=Path, default=None)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--passenger-evaluation-time-limit", type=float, default=None)
    args = parser.parse_args()
    if args.fixed_type_counts is not None:
        import json
        try:
            args.fixed_type_counts = json.loads(args.fixed_type_counts)
        except ValueError:
            parser.error("--fixed-type-counts must be a JSON object")
        if not isinstance(args.fixed_type_counts, dict) or args.formulation != "nowait_templates" or args.start_checkpoint is not None:
            parser.error("fixed type counts require nowait_templates without a start checkpoint")
    if args.thesis_f2_pilot:
        if args.example is not None or args.k_max is not None:
            parser.error("--thesis-f2-pilot fixes the example and accepts only --fixed-k")
        if args.fixed_k is not None and args.fixed_k <= 0:
            parser.error("--fixed-k must be positive")
        if args.demand_total <= 0:
            parser.error("--demand-total must be positive")
        if args.pattern_mix is None and args.type_catalog is None:
            parser.error("the thesis pilot requires --pattern-mix or --type-catalog")
        if args.formulation == "nowait_templates" and (
            args.type_catalog is None
            or args.maximum_wait_seconds != 0
            or args.movement_only
            or args.objective != "served"
            or args.backend != OipBackend.CP_SAT
        ):
            parser.error(
                "--formulation nowait_templates requires CP-SAT, No-Wait, "
                "a type catalog, passengers, and --objective served"
            )
        if not args.movement_only and args.backend != OipBackend.CP_SAT:
            parser.error(
                "integrated thesis-pilot pattern solves currently require CP-SAT"
            )
        if args.passenger_encoding is None:
            args.passenger_encoding = (
                OipPassengerEncoding.OD_INVENTORY
                if args.backend == OipBackend.CP_SAT
                else OipPassengerEncoding.RIDE_COUNTS
            )
        return args
    if args.example is None:
        parser.error("--example is required outside --thesis-f2-pilot")
    if args.k_max is None and args.fixed_k is None:
        parser.error("--k-max or --fixed-k is required")
    if args.fixed_k is not None:
        args.k_max = args.fixed_k
    if args.passenger_encoding is None:
        args.passenger_encoding = (
            OipPassengerEncoding.OD_INVENTORY
            if args.backend == OipBackend.CP_SAT
            else OipPassengerEncoding.RIDE_COUNTS
        )
    if (
        args.pattern_mix is not None
        and not args.movement_only
        and args.backend != OipBackend.CP_SAT
    ):
        parser.error("integrated --pattern-mix currently requires CP-SAT")
    return args


def _patterns_for_mix(name, cabin_count, artifact):
    if name is None:
        return None
    station_ids = tuple(dict.fromkeys(timing.station_id for timing in artifact.timings))
    all_stop = tuple(station_ids)
    if name == "all_stop":
        return tuple(all_stop for _ in range(cabin_count))
    required = {"S1", "S2", "S3", "S4"}
    if not required <= set(station_ids):
        raise ValueError(f"{name} requires stations S1 through S4")
    direct_a = ("S1", "S3")
    direct_b = ("S2", "S4")
    if name in {"f2_alternating", "f2_direct"}:
        return tuple(direct_a if index % 2 == 0 else direct_b for index in range(cabin_count))
    cycle = (direct_a, direct_b, all_stop, all_stop)
    return tuple(cycle[index % len(cycle)] for index in range(cabin_count))


if __name__ == "__main__":
    main()
