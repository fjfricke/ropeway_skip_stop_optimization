"""One bounded anonymous No-Wait run with the validated CP No-Wait seed."""

from __future__ import annotations

from dataclasses import asdict
from datetime import datetime, timezone
import json
from pathlib import Path
import resource
import subprocess
import sys
from time import perf_counter

from ropeway_skip_stop_optimization.benchmarking.ddd_fixed_k_arc_flow import (
    DddFixedKArcFlowFormulation,
    DddFixedKArcFlowRunConfig,
    prepare_ddd_fixed_k_arc_flow_run,
    run_ddd_fixed_k_arc_flow,
    write_ddd_fixed_k_arc_flow_result,
)
from ropeway_skip_stop_optimization.optimization.ddd.cp_sat_certificate import (
    atomic_json,
    read_ddd_cp_sat_checkpoint,
    validate_ddd_cp_sat_domain,
)
from ropeway_skip_stop_optimization.optimization.ddd.fixed_k import (
    DddFixedKOperatingMode,
    DddFixedKStartPolicy,
)

ROOT = Path(__file__).resolve().parents[1]
BASE = ROOT / "benchmarks/output/solver_followup_20260909"
EXAMPLE = "five_station_circle_cw_half_skip_no_wait_headway_b_v0"


def main():
    output = BASE / "k39_anonymous_1800s_seed0"
    output.mkdir(exist_ok=False)
    started = perf_counter()
    config = DddFixedKArcFlowRunConfig(
        EXAMPLE,
        39,
        DddFixedKOperatingMode.SKIP_STOP,
        start_policy=DddFixedKStartPolicy.BALANCED_REFERENCE,
        total_time_limit_seconds=1800,
        cp_seed_time_limit_seconds=0,
        solver_threads=8,
        seed=0,
        output_flag=True,
        seed_passenger_time_limit_seconds=30,
        formulation=DddFixedKArcFlowFormulation.EXACT_ANONYMOUS,
        primal_seed_result_path=output / "primal_seed.json",
    )
    prepared = prepare_ddd_fixed_k_arc_flow_run(config)
    problem = prepared.problem
    seed = read_ddd_cp_sat_checkpoint(
        BASE / "frozen/k39_no_wait/cp_seed.json",
        problem=problem,
        manifest=validate_ddd_cp_sat_domain(problem),
    )
    # Timetable-only interchange: source LB and its solver state are absent.
    atomic_json(
        output / "primal_seed.json",
        {
            "example_id": EXAMPLE,
            "exact_active_cabin_count": 39,
            "operating_mode": "skip_stop",
            "start_policy": "balanced_reference",
            "objective": "journey_time",
            "validated_upper_bound": seed.objective,
            "trajectory_supports": seed.to_payload()["trajectory_supports"],
            "problem_fingerprint": problem.fingerprint,
            "source": "frozen/k39_no_wait/cp_seed.json",
        },
    )
    atomic_json(
        output / "config.json",
        {
            "solver": json.loads(json.dumps(asdict(config), default=str)),
            "git_commit": subprocess.check_output(
                ["git", "rev-parse", "HEAD"], cwd=ROOT, text=True
            ).strip(),
            "started_utc": datetime.now(timezone.utc).isoformat(),
            "seed_upper_bound": seed.objective,
        },
    )
    with (output / "events.jsonl").open("w") as stream:

        def progress(event):
            stream.write(
                json.dumps(
                    {
                        **asdict(event),
                        "runner_elapsed_seconds": perf_counter() - started,
                        "peak_rss_mb": resource.getrusage(
                            resource.RUSAGE_SELF
                        ).ru_maxrss
                        / (1024**2 if sys.platform == "darwin" else 1024),
                    },
                    default=str,
                )
                + "\n"
            )
            stream.flush()

        result = run_ddd_fixed_k_arc_flow(
            config, prepared_run=prepared, progress_hook=progress
        )
    write_ddd_fixed_k_arc_flow_result(result, output / "result.json")
    atomic_json(
        output / "metrics.json",
        dict(
            end_to_end_seconds=perf_counter() - started,
            peak_rss_mb=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
            / (1024**2 if sys.platform == "darwin" else 1024),
            seed_upper_bound=seed.objective,
        ),
    )
    print(
        json.dumps(
            {
                key: result.to_payload().get(key)
                for key in (
                    "status",
                    "validated_upper_bound",
                    "certified_lower_bound",
                    "relative_gap",
                    "total_seconds",
                )
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
