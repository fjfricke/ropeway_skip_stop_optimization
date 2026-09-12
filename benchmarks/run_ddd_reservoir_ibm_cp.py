"""Native IBM CP Optimizer on the same single-use reservoir domain as CP-SAT."""

from __future__ import annotations

import argparse
from ropeway_skip_stop_optimization.optimization.ddd.cp_formulation import add_formulation_arguments, formulation_from_args
import json
from pathlib import Path

from ropeway_skip_stop_optimization.benchmarking.ddd_reservoir_arc_flow import (
    DddReservoirArcFlowRunConfig,
)
from ropeway_skip_stop_optimization.benchmarking.ddd_reservoir_ibm_cp import (
    DddReservoirIbmCpRunConfig,
    run_ddd_reservoir_ibm_cp,
)
from ropeway_skip_stop_optimization.optimization.ddd.reservoir_arc_flow_problem import (
    DddReservoirOperatingMode,
)
from ropeway_skip_stop_optimization.optimization.ddd.reservoir_cp_sat import (
    DddReservoirCpObjective,
)
from ropeway_skip_stop_optimization.optimization.ddd.reservoir_ibm_cp import (
    DddReservoirIbmCpConfig,
)


def main():
    p = argparse.ArgumentParser(description=__doc__, allow_abbrev=False)
    p.add_argument("--example", required=True)
    p.add_argument("--max-cabins", type=int, required=True)
    p.add_argument("--entry-state", default="A_entry_cw")
    p.add_argument("--warmup-seconds", type=float, default=300)
    p.add_argument("--service-seconds", type=float, default=1200)
    p.add_argument("--recovery-seconds", type=float, default=300)
    p.add_argument("--dispatch-step-seconds", type=float, default=1e-6)
    p.add_argument("--maximum-wait-seconds", type=float, default=0)
    p.add_argument("--waiting-step-seconds", type=float, default=1e-6)
    p.add_argument(
        "--mode", choices=list(DddReservoirOperatingMode), default="skip_stop"
    )
    p.add_argument(
        "--objective", choices=list(DddReservoirCpObjective), default="journey_time"
    )
    p.add_argument("--time-limit", type=float, default=60)
    p.add_argument("--num-workers", type=int, default=1)
    p.add_argument("--seed", type=int, default=0)
    p.add_argument("--resume-checkpoint", type=Path)
    p.add_argument(
        "--cpoptimizer",
        type=Path,
        help="Path to an IBM engine, e.g. the academic unlimited runtime",
    )
    p.add_argument("--output-dir", type=Path, required=True)
    add_formulation_arguments(p, "ibm")
    a = p.parse_args()
    r = run_ddd_reservoir_ibm_cp(
        DddReservoirIbmCpRunConfig(
            physical=DddReservoirArcFlowRunConfig(
                example_id=a.example,
                available_fleet_count=a.max_cabins,
                entry_state_id=a.entry_state,
                warmup_seconds=a.warmup_seconds,
                service_seconds=a.service_seconds,
                recovery_seconds=a.recovery_seconds,
                waiting_max_seconds=a.maximum_wait_seconds,
                waiting_step_seconds=a.waiting_step_seconds,
                operating_mode=DddReservoirOperatingMode(a.mode),
            ),
            output_dir=a.output_dir,
            solver=DddReservoirIbmCpConfig(
                total_time_limit_seconds=a.time_limit,
                formulation=formulation_from_args(a),
                num_workers=a.num_workers,
                seed=a.seed,
                executable=a.cpoptimizer,
            ),
            objective=DddReservoirCpObjective(a.objective),
            dispatch_step_seconds=a.dispatch_step_seconds,
            resume_checkpoint=a.resume_checkpoint,
        )
    )
    print(
        json.dumps(
            {
                k: r[k]
                for k in (
                    "solver_status",
                    "termination_reason",
                    "error",
                    "validated_upper_bound",
                    "cp_lower_bound",
                    "metrics",
                    "model_stats",
                    "end_to_end_seconds",
                    "solver_version",
                )
            },
            indent=2,
        )
    )
    if r["solver_status"] == "ERROR":
        raise SystemExit(2)


if __name__ == "__main__":
    main()
