from __future__ import annotations

import argparse
from pathlib import Path

from ropeway_skip_stop_optimization.exports.ddd_root_cg import (
    export_ddd_root_cg_checkpoint_to_frontend,
)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Export a DDD root-CG incumbent to the scenario frontend."
    )
    parser.add_argument("--example", required=True)
    parser.add_argument("--checkpoint", type=Path, required=True)
    parser.add_argument(
        "--output-root",
        type=Path,
        default=Path("frontend/public/generated/examples"),
    )
    parser.add_argument("--passenger-time-limit", type=float, default=30.0)
    args = parser.parse_args()

    result = export_ddd_root_cg_checkpoint_to_frontend(
        example_id=args.example,
        checkpoint_path=args.checkpoint,
        output_root=args.output_root,
        passenger_time_limit_seconds=args.passenger_time_limit,
    )
    print(
        f"objective={result.objective_value_seconds:.6f} "
        f"passenger_recovered={result.passenger_assignment_recovered} "
        f"artifacts={len(result.artifact_paths)} manifest={result.manifest_path}"
    )


if __name__ == "__main__":
    main()
