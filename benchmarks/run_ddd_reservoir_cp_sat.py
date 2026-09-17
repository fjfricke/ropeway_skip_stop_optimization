"""Integrated single-use reservoir CP-SAT (separate from Fixed-K)."""

from __future__ import annotations

import argparse
from ropeway_skip_stop_optimization.optimization.ddd.reservoir_boundary import add_boundary_arguments
from ropeway_skip_stop_optimization.optimization.ddd.cp_formulation import add_formulation_arguments, formulation_from_args
import json
from pathlib import Path

from ropeway_skip_stop_optimization.benchmarking.ddd_reservoir_cp_sat import (
    DddReservoirCpSatRunConfig,
    run_ddd_reservoir_cp_sat,
)
from ropeway_skip_stop_optimization.benchmarking.ddd_reservoir_arc_flow import (
    DddReservoirArcFlowRunConfig,
)
from ropeway_skip_stop_optimization.optimization.ddd.cp_sat_integrated import (
    DddIntegratedCpSatConfig,
)
from ropeway_skip_stop_optimization.optimization.ddd.cp_sat_passenger import (
    DddCpSatCostEncoding,
    DddCpSatPassengerEncoding,
)
from ropeway_skip_stop_optimization.optimization.ddd.reservoir_arc_flow_problem import (
    DddReservoirOperatingMode,
)
from ropeway_skip_stop_optimization.optimization.ddd.reservoir_cp_sat import (
    DddReservoirCpObjective,
)


def main():
    p = argparse.ArgumentParser(allow_abbrev=False, description=__doc__)
    p.add_argument("--example", required=True)
    p.add_argument("--max-cabins", type=int, required=True)
    p.add_argument("--entry-state", default="A_entry_cw")
    p.add_argument("--warmup-seconds", type=float, default=300)
    p.add_argument("--service-seconds", type=float, default=1200)
    p.add_argument("--recovery-seconds", type=float, default=300)
    p.add_argument("--dispatch-step-seconds", type=float, default=0.000001)
    p.add_argument("--maximum-wait-seconds", type=float, default=0)
    p.add_argument("--waiting-step-seconds", type=float, default=0.000001)
    p.add_argument(
        "--mode", choices=list(DddReservoirOperatingMode), default="skip_stop"
    )
    p.add_argument(
        "--objective", choices=list(DddReservoirCpObjective), default="journey_time"
    )
    p.add_argument(
        "--cost-encoding", choices=list(DddCpSatCostEncoding), default="product"
    )
    p.add_argument(
        "--passenger-encoding",
        choices=list(DddCpSatPassengerEncoding),
        default="groups",
    )
    p.add_argument("--time-limit", type=float, default=60)
    p.add_argument("--seed-time-limit", type=float, default=10)
    p.add_argument("--num-workers", type=int, default=1)
    p.add_argument("--seed", type=int, default=0)
    p.add_argument("--resume-checkpoint", type=Path)
    p.add_argument("--log-search-progress", action="store_true")
    p.add_argument("--output-dir", type=Path, required=True)
    add_formulation_arguments(p, "cp_sat")
    add_boundary_arguments(p)
    a = p.parse_args()
    result = run_ddd_reservoir_cp_sat(
        DddReservoirCpSatRunConfig(
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
            reservoir_port_policy=a.reservoir_port_policy,
            port_headway_evidence=a.port_headway_evidence,
            solver=DddIntegratedCpSatConfig(
                total_time_limit_seconds=a.time_limit,
                formulation=formulation_from_args(a),
                num_workers=a.num_workers,
                seed=a.seed,
                cost_encoding=DddCpSatCostEncoding(a.cost_encoding),
                passenger_encoding=DddCpSatPassengerEncoding(a.passenger_encoding),
                log_search_progress=a.log_search_progress,
            ),
            objective=DddReservoirCpObjective(a.objective),
            dispatch_step_seconds=a.dispatch_step_seconds,
            seed_time_limit_seconds=a.seed_time_limit,
            resume_checkpoint=a.resume_checkpoint,
        )
    )
    print(
        json.dumps(
            {
                k: result[k]
                for k in [
                    "solver_status",
                    "proof_scope",
                    "objective",
                    "validated_upper_bound",
                    "cp_lower_bound",
                    "metrics",
                    "model_stats",
                    "end_to_end_seconds",
                    "peak_rss_mb",
                ]
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
