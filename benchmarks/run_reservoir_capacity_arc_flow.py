"""Supervised, scoped reservoir capacity pilot (old runners stay unchanged)."""

import argparse
from ropeway_skip_stop_optimization.optimization.ddd.reservoir_boundary import add_boundary_arguments, apply_boundary_arguments
from dataclasses import asdict, replace
import json
from pathlib import Path
import sys
import time

from ropeway_skip_stop_optimization.benchmarking.process_supervisor import supervise
from ropeway_skip_stop_optimization.optimization.ddd.cp_sat_certificate import (
    atomic_json,
)
from ropeway_skip_stop_optimization.optimization.ddd.reservoir_arc_flow_problem import (
    DddReservoirOperatingMode,
)
from ropeway_skip_stop_optimization.optimization.ddd.reservoir_hybrid.domain import (
    load_reference,
)
from ropeway_skip_stop_optimization.optimization.ddd.reservoir_cp_sat_certificate import (
    DddReservoirCpPlan,
    validate_reservoir_cp_plan,
    write_reservoir_cp_checkpoint,
)
from ropeway_skip_stop_optimization.optimization.ddd.reservoir_capacity.network import (
    build_network,
)
from ropeway_skip_stop_optimization.optimization.ddd.reservoir_capacity.model import (
    build_model,
    solve,
)
from ropeway_skip_stop_optimization.optimization.ddd.reservoir_capacity.bound import (
    build_bound,
    solve_bound,
    comparison_fingerprint,
)


from ropeway_skip_stop_optimization.optimization.ddd.reservoir_capacity.formulation import (
    ReservoirPhaseFormulationConfig,
)


def formulation_config(a):
    config = ReservoirPhaseFormulationConfig(
        **{
            field: getattr(a, field, getattr(ReservoirPhaseFormulationConfig(), field))
            for field in ReservoirPhaseFormulationConfig.__dataclass_fields__
        }
    )
    config.validate(a.method)
    return config


def parser():
    p = argparse.ArgumentParser(description=__doc__, allow_abbrev=False)
    p.add_argument(
        "--method",
        choices=["phase_arc_flow", "all_stop_bound", "cp_sat"],
        required=True,
    )
    source = p.add_mutually_exclusive_group(required=True)
    source.add_argument("--reference", type=Path)
    source.add_argument("--example")
    p.add_argument("--operating-mode", choices=["all_stop", "skip_stop"])
    p.add_argument("--max-cabins", type=int)
    p.add_argument("--entry-state", default="A_entry_cw")
    p.add_argument("--warmup-seconds", type=float, default=300)
    p.add_argument("--service-seconds", type=float, default=1200)
    p.add_argument("--recovery-seconds", type=float, default=300)
    p.add_argument("--maximum-wait-seconds", type=float)
    p.add_argument("--waiting-step-seconds", type=float, default=0.000001)
    p.add_argument("--dispatch-step-seconds", type=float, default=0.000001)
    p.add_argument("--demand", type=int)
    p.add_argument("--require-full-service", action="store_true")
    p.add_argument("--time-limit", type=float, default=300)
    p.add_argument("--threads", type=int, default=12)
    p.add_argument("--seed", type=int, default=0)
    p.add_argument("--memory-gib", type=float, default=8)
    p.add_argument("--interval-seconds", type=int, default=60)
    p.add_argument("--parent-interval-seconds", type=int)
    p.add_argument("--output-dir", type=Path, required=True)
    p.add_argument(
        "--passenger-encoding",
        choices=["legacy", "od_flow", "od_queue"],
        default="legacy",
    )
    p.add_argument(
        "--passenger-integrality", choices=["all", "boarding"], default="all"
    )
    p.add_argument(
        "--passenger-network", choices=["legacy", "contracted"], default="legacy"
    )
    p.add_argument(
        "--resource-encoding", choices=["legacy", "maximal"], default="legacy"
    )
    p.add_argument("--conflict-cuts", choices=["none", "local_cliques"], default="none")
    p.add_argument("--conflict-work-limit", type=int, default=100_000)
    p.add_argument("--conflict-cut-limit", type=int, default=5_000)
    p.add_argument("--build-only", action="store_true")
    p.add_argument("--deadline-unix", type=float)
    p.add_argument("--_worker", action="store_true", help=argparse.SUPPRESS)
    add_boundary_arguments(p)
    return p


def inputs(a):
    formulation_config(a)
    derived_policy = None
    if a.reference:
        domain, seed = load_reference(a.reference)
        p = domain.problem
        if a.max_cabins is not None:
            p = replace(p, available_fleet_count=a.max_cabins)
        if a.maximum_wait_seconds is not None:
            p = replace(
                p,
                waiting_policy=replace(
                    p.waiting_policy,
                    maximum_wait_seconds_by_station_id=tuple(
                        (s, a.maximum_wait_seconds)
                        for s, w in p.waiting_policy.maximum_wait_seconds_by_station_id
                    ),
                ),
            )
    else:
        from ropeway_skip_stop_optimization.benchmarking.ddd_reservoir_arc_flow import (
            DddReservoirArcFlowRunConfig,
            prepare_ddd_reservoir_arc_flow_run,
        )
        from ropeway_skip_stop_optimization.benchmarking.ddd_reservoir_cp_sat import (
            all_stop_reservoir_movement,
        )
        from ropeway_skip_stop_optimization.optimization.ddd.reservoir_cp_sat_problem import (
            DddReservoirCpSatProblem,
        )

        physical = prepare_ddd_reservoir_arc_flow_run(
            DddReservoirArcFlowRunConfig(
                example_id=a.example,
                available_fleet_count=a.max_cabins or 50,
                entry_state_id=a.entry_state,
                warmup_seconds=a.warmup_seconds,
                service_seconds=a.service_seconds,
                recovery_seconds=a.recovery_seconds,
                waiting_max_seconds=a.maximum_wait_seconds or 0,
                waiting_step_seconds=a.waiting_step_seconds,
            )
        )
        p = replace(
            DddReservoirCpSatProblem.from_arc_flow(physical.problem),
            dispatch_step_seconds=a.dispatch_step_seconds,
        )
        derived_policy = physical.headway_policy
        p = apply_boundary_arguments(p, a, derived_policy=derived_policy)
        seed = all_stop_reservoir_movement(p, physical.problem) or DddReservoirCpPlan(
            (), {}
        )
    if a.operating_mode:
        p = replace(p, operating_mode=DddReservoirOperatingMode(a.operating_mode))
    if a.demand is not None:
        from ropeway_skip_stop_optimization.optimization.ddd.fixed_timetable_capacity import (
            NestedDemand,
        )

        p = replace(p, demand_groups=NestedDemand(p.demand_groups).groups(a.demand))
    p = apply_boundary_arguments(p, a, derived_policy=derived_policy)
    p.validate()
    validate_reservoir_cp_plan(p, seed)
    if (
        a.method == "all_stop_bound"
        and p.operating_mode is not DddReservoirOperatingMode.ALL_STOP
    ):
        raise ValueError(
            "all_stop_bound requires --operating-mode all_stop and a valid All-Stop reference"
        )
    return p, seed


def worker(a):
    started = time.perf_counter()
    closing_reserve = (
        min(8.0, a.time_limit * 0.1) if a.method == "phase_arc_flow" else 2.0
    )
    deadline = started + max(0.01, a.time_limit - closing_reserve)
    if a.deadline_unix:
        deadline = min(deadline, started + max(0.01, a.deadline_unix - time.time() - 1))
    p, seed = inputs(a)
    out = a.output_dir
    write_reservoir_cp_checkpoint(out / "reference.json", p, seed)
    write_reservoir_cp_checkpoint(out / "best.json", p, seed)
    before = asdict(validate_reservoir_cp_plan(p, seed))
    with (out / "events.jsonl").open("w") as stream:

        def emit(event):
            stream.write(json.dumps(event) + "\n")
            stream.flush()

        if a.method == "phase_arc_flow":
            network = build_network(p, [seed], deadline=deadline)
            atomic_json(
                out / "network.json",
                dict(
                    fingerprint=network.fingerprint,
                    profile=network.profile,
                    dispatch_ticks=network.dispatch_ticks,
                    arcs=[asdict(x) for x in network.arcs],
                    build_seconds=network.build_seconds,
                    removed_arcs=network.removed_arcs,
                ),
            )
            built = build_model(
                network,
                reference=seed,
                deadline=deadline,
                require_full_service=a.require_full_service,
                output=True,
                formulation=formulation_config(a),
            )
            atomic_json(
                out / "model_ready.json",
                dict(
                    variables=built.model.NumVars,
                    rows=built.model.NumConstrs,
                    nonzeros=built.model.NumNZs,
                    model_fingerprint=built.fingerprint,
                    network_fingerprint=network.fingerprint,
                    model_seconds=max(
                        0.0,
                        built.build_seconds
                        - built.passengers.structure.seconds
                        - built.resources.seconds,
                    ),
                    total_build_seconds=built.build_seconds,
                    passenger_preparation_seconds=built.passengers.structure.seconds,
                    resource_preparation_seconds=built.resources.seconds,
                    hint_seconds=built.hint_seconds,
                    network_seconds=network.build_seconds,
                    ready_elapsed_seconds=time.perf_counter() - started,
                    closing_reserve_seconds=closing_reserve,
                ),
            )
            atomic_json(
                out / "passenger_structure.json",
                dict(
                    fingerprint=built.passengers.structure.fingerprint,
                    encoding=built.passengers.structure.encoding,
                    groups=[asdict(g) for g in built.passengers.structure.groups],
                    contracted_projection=[
                        (k, v)
                        for k, v in built.passengers.structure.projection
                        if k != v
                    ],
                    queue_steps=built.passengers.structure.queue_steps,
                    key_contract="legacy/group boarding: (g, group_id, arc); shared: (od, class_id, arc)",
                ),
            )
            atomic_json(
                out / "resource_structure.json",
                dict(
                    fingerprint=built.resources.fingerprint,
                    rows=[asdict(r) for r in built.resources.rows]
                    if built.config.resource_encoding != "legacy"
                    or built.config.conflict_cuts != "none"
                    else [],
                    retained=built.resources.retained,
                    implied_by=built.resources.implied_by,
                    cliques=built.resources.cliques,
                ),
            )
            atomic_json(
                out / "formulation.json",
                dict(
                    configuration=built.config.as_dict(),
                    model_fingerprint=built.fingerprint,
                    passenger_fingerprint=built.passengers.structure.fingerprint,
                    passenger_variables=len(built.passengers.variables),
                    passenger_original_keys=len(built.passengers.structure.projection),
                    contracted_equalities=built.passengers.structure.removed_equalities,
                    resource_fingerprint=built.resources.fingerprint,
                    resource_rows=len(built.resources.rows),
                    retained_resource_rows=len(built.resources.retained),
                    removed_resource_rows=built.resources.implied_by,
                    additional_cliques=built.resources.cliques,
                    conflict_work=built.resources.work,
                    conflict_truncated=built.resources.truncated,
                ),
            )
            try:
                if a.build_only:
                    result = dict(
                        build_only=True,
                        variables=built.model.NumVars,
                        rows=built.model.NumConstrs,
                        model_fingerprint=built.fingerprint,
                        network_fingerprint=network.fingerprint,
                        formulation=built.config.as_dict(),
                        row_families=built.families,
                        passenger_preparation_seconds=built.passengers.structure.seconds,
                        bound_scope="restricted_phase_network",
                    )
                else:
                    search_offset = time.perf_counter() - started
                    atomic_json(
                        out / "search_started.json",
                        dict(search_start_offset_seconds=search_offset),
                    )
                    _, result = solve(
                        built,
                        deadline=deadline,
                        threads=a.threads,
                        seed=a.seed,
                        reference=seed,
                        checkpoint=out / "best.json",
                        emit=emit,
                        soft_memory_gb=a.memory_gib * 1024**3 / 1e9,
                    )
                    result["search_start_offset_seconds"] = search_offset
            finally:
                built.model.dispose()
        elif a.method == "all_stop_bound":
            built = build_bound(
                p,
                interval_tick=a.interval_seconds * 1_000_000,
                parent_interval_tick=a.parent_interval_seconds * 1_000_000
                if a.parent_interval_seconds
                else None,
                deadline=deadline,
            )
            try:
                projection = built.project(seed)
                result = (
                    dict(
                        build_only=True,
                        variables=built.model.NumVars,
                        rows=built.model.NumConstrs,
                    )
                    if a.build_only
                    else solve_bound(built, deadline=deadline, threads=a.threads)
                )
                result["reference_projection"] = projection
            finally:
                built.model.dispose()
        else:
            from ropeway_skip_stop_optimization.optimization.ddd.cp_sat_integrated import (
                DddIntegratedCpSatConfig,
            )
            from ropeway_skip_stop_optimization.optimization.ddd.reservoir_cp_sat import (
                DddReservoirCpSatOptimizer,
                DddReservoirCpObjective,
                build_reservoir_cp_sat,
            )

            cfg = DddIntegratedCpSatConfig(
                total_time_limit_seconds=max(0.01, deadline - time.perf_counter()),
                num_workers=a.threads,
                seed=a.seed,
                checkpoint_path=out / "best.json",
                log_search_progress=True,
            )
            if a.build_only:
                built = build_reservoir_cp_sat(
                    p,
                    config=cfg,
                    objective=DddReservoirCpObjective.UNSERVED,
                    deadline=deadline,
                )
                result = dict(build_only=True, model_stats=built.stats)
            else:
                result = DddReservoirCpSatOptimizer(
                    cfg, DddReservoirCpObjective.UNSERVED
                ).solve(
                    p,
                    primal_seed=seed,
                    event_callback=emit,
                    require_full_service=a.require_full_service,
                )
                result["bound_scope"] = (
                    "global_" + p.operating_mode.value + "_single_use_reservoir"
                )
                result["global_lower_bound"] = result["cp_lower_bound"]
    result.update(
        method=a.method,
        problem_fingerprint=p.fingerprint,
        comparison_fingerprint=comparison_fingerprint(p),
        reference_metrics=before,
        total_seconds=time.perf_counter() - started,
    )
    atomic_json(out / "result.json", result)


def main():
    a = parser().parse_args()
    formulation_config(a)
    if a.time_limit <= 0 or a.threads < 1 or a.memory_gib <= 0:
        raise ValueError("invalid budget")
    if a._worker:
        try:
            worker(a)
        except BaseException as e:
            atomic_json(
                a.output_dir / "failure.json",
                dict(type=type(e).__name__, error=str(e), proof=False),
            )
            raise
        return
    a.output_dir.mkdir(parents=True, exist_ok=False)
    atomic_json(
        a.output_dir / "arguments.json",
        vars(a)
        | {
            "output_dir": str(a.output_dir),
            "reference": str(a.reference) if a.reference else None,
        },
    )
    command = [
        sys.executable,
        str(Path(__file__).resolve()),
        *sys.argv[1:],
        "--_worker",
    ]
    supervise(
        command,
        a.output_dir,
        seconds=a.time_limit,
        memory_bytes=int(a.memory_gib * 1024**3),
        global_deadline=a.deadline_unix,
    )


if __name__ == "__main__":
    main()
