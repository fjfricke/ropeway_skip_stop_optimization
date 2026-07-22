from __future__ import annotations

import argparse
from pathlib import Path

from ropeway_skip_stop_optimization.exports.runner import DEFAULT_OUTPUT_ROOT, export_artifact_set, known_artifact_set_ids
from ropeway_skip_stop_optimization.optimization.discrete_time import MilpV0VariableStrategy
from ropeway_skip_stop_optimization.optimization.ean import (
    EanArtifactConstructionMode,
    EanMipStartStrategy,
    ALL_EAN_SELECTION_NAMES,
    EanOptimizationConfig,
    GurobiSolverPolicyPreset,
)
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
        "--ean-artifact-construction",
        choices=tuple(mode.value for mode in EanArtifactConstructionMode),
        default=EanArtifactConstructionMode.NETWORK.value,
        help="EAN artifact builder architecture; network is the opt-in compatibility path.",
    )
    parser.add_argument(
        "--ean-solver-policy",
        choices=tuple(policy.value for policy in GurobiSolverPolicyPreset),
        default=GurobiSolverPolicyPreset.QUICK_GOOD_SOLUTION.value,
        help="Gurobi solver policy preset for EAN passenger optimization artifact sets.",
    )
    parser.add_argument(
        "--ean-time-limit",
        type=float,
        default=None,
        help="Override the EAN solver-policy time limit in seconds.",
    )
    parser.add_argument(
        "--ean-build-only",
        action="store_true",
        help="Build and profile the selected EAN model without calling optimize().",
    )
    parser.add_argument(
        "--ean-checkpoint-dir",
        type=Path,
        default=None,
        help="Directory for EAN passenger-service Gurobi incumbent solution checkpoints.",
    )
    parser.add_argument(
        "--ean-resume-checkpoint",
        type=Path,
        default=None,
        help="Load this .sol or .mst file as an EAN passenger-service MIP start before optimizing.",
    )
    parser.add_argument(
        "--ean-resume-latest-checkpoint",
        action="store_true",
        help="Load the newest checkpoint for the selected EAN example/artifact set from --ean-checkpoint-dir.",
    )
    parser.add_argument(
        "--ean-optimizations",
        default="all",
        help=(
            "'all' for the current default set, 'none', or comma-separated "
            "optimization and formulation selections; 'all' may be combined "
            "with formulation overrides, with at most one value per category: "
            + ", ".join(ALL_EAN_SELECTION_NAMES)
        ),
    )
    parser.add_argument(
        "--ean-mip-start",
        choices=tuple(strategy.value for strategy in EanMipStartStrategy),
        default=EanMipStartStrategy.AUTO.value,
    )
    parser.add_argument(
        "--milp-variable-strategy",
        choices=tuple(strategy.value for strategy in MilpV0VariableStrategy),
        default=MilpV0VariableStrategy.DENSE.value,
        help="Variable strategy for MILP artifact sets.",
    )
    args = parser.parse_args()
    if args.ean_resume_checkpoint is not None and args.ean_resume_latest_checkpoint:
        parser.error("--ean-resume-checkpoint and --ean-resume-latest-checkpoint are mutually exclusive")
    if args.ean_resume_latest_checkpoint and args.ean_checkpoint_dir is None:
        parser.error("--ean-resume-latest-checkpoint requires --ean-checkpoint-dir")
    if args.ean_build_only and args.clean:
        parser.error("--ean-build-only cannot be combined with --clean")
    try:
        ean_optimization_config = EanOptimizationConfig.from_selection(args.ean_optimizations)
    except ValueError as error:
        parser.error(str(error))

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
        ean_time_limit_seconds=args.ean_time_limit,
        ean_checkpoint_dir=args.ean_checkpoint_dir,
        ean_resume_checkpoint=args.ean_resume_checkpoint,
        ean_resume_latest_checkpoint=args.ean_resume_latest_checkpoint,
        ean_optimization_config=ean_optimization_config,
        ean_mip_start_strategy=EanMipStartStrategy(args.ean_mip_start),
        ean_build_only=args.ean_build_only,
        ean_artifact_construction=EanArtifactConstructionMode(
            args.ean_artifact_construction
        ),
        progress=args.progress,
        clean=args.clean,
    )

    for output_path in (*result.artifact_paths, result.manifest_path):
        print(output_path)


if __name__ == "__main__":
    main()
