from __future__ import annotations

import argparse
from pathlib import Path

from ropeway_skip_stop_optimization.exports.runner import DEFAULT_OUTPUT_ROOT, export_artifact_set, known_artifact_set_ids
from ropeway_skip_stop_optimization.optimization.discrete_time import MilpV0VariableStrategy
from ropeway_skip_stop_optimization.optimization.ean import GurobiSolverPolicyPreset
from ropeway_skip_stop_optimization.progress import configure_progress_logging


def main() -> None:
    parser = argparse.ArgumentParser(description="Export ropeway examples as frontend-discoverable JSON artifacts.")
    parser.add_argument("--example", default="three_station_v0", help="Example id to export.")
    parser.add_argument(
        "--artifact-set",
        choices=known_artifact_set_ids(),
        default="greedy_all_stop",
        help="Artifact set to export.",
    )
    parser.add_argument(
        "--output-root",
        type=Path,
        default=DEFAULT_OUTPUT_ROOT,
        help="Root directory for generated example artifacts and manifest.",
    )
    parser.add_argument("--clean", action="store_true", help="Remove the selected example output directory before export.")
    parser.add_argument("--progress", action="store_true", help="Show export phase logs and progress bars.")
    parser.add_argument("--milp-horizon", type=int, default=60, help="Horizon for MILP artifact sets.")
    parser.add_argument("--milp-cabin-count", type=int, default=23, help="Number of cabins for MILP artifact sets.")
    parser.add_argument(
        "--ean-solver-policy",
        choices=tuple(policy.value for policy in GurobiSolverPolicyPreset),
        default=GurobiSolverPolicyPreset.QUICK_GOOD_SOLUTION.value,
        help="Gurobi solver policy preset for EAN passenger optimization artifact sets.",
    )
    parser.add_argument(
        "--milp-variable-strategy",
        choices=tuple(strategy.value for strategy in MilpV0VariableStrategy),
        default=MilpV0VariableStrategy.DENSE.value,
        help="Variable strategy for MILP artifact sets.",
    )
    args = parser.parse_args()

    if args.progress:
        configure_progress_logging()

    result = export_artifact_set(
        example_id=args.example,
        artifact_set_id=args.artifact_set,
        output_root=args.output_root,
        milp_horizon_steps=args.milp_horizon,
        milp_cabin_count=args.milp_cabin_count,
        milp_variable_strategy=MilpV0VariableStrategy(args.milp_variable_strategy),
        ean_solver_policy_preset=GurobiSolverPolicyPreset(args.ean_solver_policy),
        progress=args.progress,
        clean=args.clean,
    )

    for output_path in (*result.artifact_paths, result.manifest_path):
        print(output_path)


if __name__ == "__main__":
    main()
