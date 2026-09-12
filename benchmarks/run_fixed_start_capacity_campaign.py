"""Calibrate a fixed All-Stop-38 timetable, then sequential fixed-start CP probes."""

import argparse
import json
from pathlib import Path

from ropeway_skip_stop_optimization.benchmarking.ddd_fixed_k_arc_flow import (
    DddFixedKArcFlowRunConfig,
    prepare_ddd_fixed_k_arc_flow_run,
)
from ropeway_skip_stop_optimization.benchmarking.ddd_cp_sat_waiting import (
    with_exit_waiting,
)
from ropeway_skip_stop_optimization.optimization.ddd.fixed_k import (
    DddFixedKOperatingMode,
    DddFixedKStartPolicy,
)
from ropeway_skip_stop_optimization.optimization.ddd.cp_sat_certificate import (
    atomic_json,
    read_ddd_cp_sat_checkpoint,
    validate_ddd_cp_sat_domain,
    write_ddd_cp_sat_checkpoint,
    validate_ddd_cp_sat_incumbent,
)
from ropeway_skip_stop_optimization.optimization.ddd.fixed_timetable_capacity import (
    NestedDemand,
    FixedTimetableCapacityProbe,
    find_fixed_timetable_capacity,
)

ROOT = Path(__file__).resolve().parents[1]
EXAMPLE = "five_station_circle_cw_half_skip_no_wait_headway_b_v0"
FROZEN = ROOT / "benchmarks/output/solver_followup_20260909/frozen"


def prepare(k, waiting=False):
    p = prepare_ddd_fixed_k_arc_flow_run(
        DddFixedKArcFlowRunConfig(
            EXAMPLE,
            k,
            DddFixedKOperatingMode.SKIP_STOP
            if waiting
            else DddFixedKOperatingMode.ALL_STOP,
            start_policy=DddFixedKStartPolicy.BALANCED_REFERENCE,
            cp_seed_time_limit_seconds=0,
        )
    )
    return (
        with_exit_waiting(p, maximum_seconds=1200, step_seconds=1e-6) if waiting else p
    )


def calibrate(output):
    output.mkdir(parents=True, exist_ok=False)
    p = prepare(38).problem
    original = read_ddd_cp_sat_checkpoint(
        FROZEN / "k38_all_stop/cp_seed.json",
        problem=p,
        manifest=validate_ddd_cp_sat_domain(p),
    )
    demand = NestedDemand(p.passenger_build.demand_groups)
    atomic_json(output / "original_domain.json", validate_ddd_cp_sat_domain(p))

    def report(n, problem, result):
        folder = output / f"n{n}"
        folder.mkdir()
        atomic_json(folder / "result.json", result)
        atomic_json(folder / "domain.json", validate_ddd_cp_sat_domain(problem))
        checked = validate_ddd_cp_sat_incumbent(
            problem,
            original.solution,
            result["incumbent"]["ride_counts"],
            provenance="fixed_timetable_capacity",
        )
        write_ddd_cp_sat_checkpoint(
            folder / "incumbent.json",
            problem=problem,
            manifest=validate_ddd_cp_sat_domain(problem),
            incumbent=checked,
        )
        print(
            json.dumps({k: v for k, v in result.items() if k != "incumbent"}),
            flush=True,
        )

    result = find_fixed_timetable_capacity(
        FixedTimetableCapacityProbe(30, 1),
        p,
        original.solution,
        demand,
        on_probe=report,
    )
    summary = {k: v for k, v in result.items() if k != "records"}
    summary.update(
        reference="fixed_all_stop_38_timetable",
        global_reservoir_capacity=False,
        demand_generator="weighted_deficit_nested_prefix_v1",
        source_checkpoint=str(FROZEN / "k38_all_stop/cp_seed.json"),
    )
    if result["exact"]:
        summary["test_demand"] = (6 * result["kappa_lower"] + 4) // 5
    atomic_json(output / "summary.json", summary)
    print("CAPACITY", json.dumps(summary), flush=True)


def search(output, budget, workers, formulation=None):
    from ropeway_skip_stop_optimization.optimization.ddd.cp_formulation import DddCpFormulationConfig
    formulation = formulation or DddCpFormulationConfig()
    formulation.validate()
    from ropeway_skip_stop_optimization.optimization.ddd.cp_sat_capacity import (
        DddCpSatCapacityOptimizer,
    )
    from ropeway_skip_stop_optimization.optimization.ddd.cp_sat_integrated import (
        DddIntegratedCpSatConfig,
    )

    summary = json.loads((output / "calibration/summary.json").read_text())
    if not summary["exact"]:
        raise RuntimeError(
            "capacity not certified; do not label a 120 percent experiment"
        )
    n = summary["test_demand"]
    for k in (38, 39):
        folder = output / f"k{k}_waiting_n{n}"
        folder.mkdir(exist_ok=False)
        p = prepare(k, True).problem
        source = (
            FROZEN / "k38_all_stop_in_waiting/cp_seed.json"
            if k == 38
            else ROOT
            / "benchmarks/output/solver_followup_20260909/k39_waiting_1800s_seed0/incumbent.json"
        )
        original = read_ddd_cp_sat_checkpoint(
            source, problem=p, manifest=validate_ddd_cp_sat_domain(p)
        )
        p = NestedDemand(p.passenger_build.demand_groups).apply(p, n)
        if k == 38:
            reference = json.loads(
                (output / "calibration/original_domain.json").read_text()
            )
            assert validate_ddd_cp_sat_domain(p)["starts"] == reference["starts"]
        seed_assignment = FixedTimetableCapacityProbe(30, 1).solve(p, original.solution)
        atomic_json(folder / "seed_assignment.json", seed_assignment)
        seed = validate_ddd_cp_sat_incumbent(
            p,
            original.solution,
            seed_assignment["incumbent"]["ride_counts"],
            provenance="same_motion_capacity_assignment_at_increased_demand",
        )
        atomic_json(folder / "domain.json", validate_ddd_cp_sat_domain(p))
        write_ddd_cp_sat_checkpoint(
            folder / "seed.json",
            problem=p,
            manifest=validate_ddd_cp_sat_domain(p),
            incumbent=seed,
        )
        atomic_json(
            folder / "config.json",
            dict(
                cabins=k,
                maximum_wait_seconds=1200,
                time_limit_seconds=budget,
                workers=workers,
                objective="unserved",
                source=str(source),
                total_demand=n,
            ),
        )
        with (
            (folder / "events.jsonl").open("w") as events,
            (folder / "solver.log").open("w") as log,
        ):

            def event(e):
                events.write(json.dumps(e) + "\n")
                events.flush()

            def line(s):
                log.write(s if s.endswith("\n") else s + "\n")
                log.flush()

            result = DddCpSatCapacityOptimizer(
                DddIntegratedCpSatConfig(
                    formulation=formulation,
                    total_time_limit_seconds=budget,
                    num_workers=workers,
                    log_search_progress=True,
                    checkpoint_path=folder / "incumbent.json",
                )
            ).solve(p, primal_seed=seed, event_callback=event, log_callback=line)
        atomic_json(folder / "result.json", result)
        print(
            "SEARCH_RESULT",
            k,
            json.dumps(
                {
                    key: value
                    for key, value in result.items()
                    if key
                    not in ["incumbent", "domain_manifest", "events", "response_stats"]
                }
            ),
            flush=True,
        )
    atomic_json(output / "completion.json", dict(status="complete", test_demand=n))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--stage", choices=["calibrate", "search"], required=True)
    parser.add_argument("--time-limit", type=float, default=900)
    parser.add_argument("--workers", type=int, default=12)
    from ropeway_skip_stop_optimization.optimization.ddd.cp_formulation import add_formulation_arguments, formulation_from_args
    add_formulation_arguments(parser)
    args = parser.parse_args()
    if args.stage == "calibrate":
        calibrate(args.output_dir / "calibration")
    else:
        search(args.output_dir, args.time_limit, args.workers, formulation_from_args(args))


if __name__ == "__main__":
    main()
