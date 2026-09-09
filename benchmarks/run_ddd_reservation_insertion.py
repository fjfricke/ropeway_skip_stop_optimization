"""Run the bounded reservation insertion pilot; no automatic follow-up campaign."""

import argparse
import json
from pathlib import Path

from ropeway_skip_stop_optimization.benchmarking.ddd_reservation_insertion import (
    DddReservationInsertionRunConfig,
    run_ddd_reservation_insertion,
)
from ropeway_skip_stop_optimization.optimization.ddd.reservation_models import (
    DddReservationInsertionConfig,
)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source_run", type=Path)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--seconds", type=float, default=30)
    parser.add_argument("--attempt-seconds", type=float, default=0.25)
    parser.add_argument("--cabins", type=int, default=4)
    parser.add_argument("--beam", type=int, default=8)
    parser.add_argument("--requests", type=int, default=100)
    parser.add_argument("--passenger-seconds", type=float, default=0)
    parser.add_argument("--accept-improvements", action="store_true")
    args = parser.parse_args()
    report = run_ddd_reservation_insertion(
        DddReservationInsertionRunConfig(
            args.source_run,
            args.output_dir,
            DddReservationInsertionConfig(
                total_time_limit_seconds=args.seconds,
                attempt_time_limit_seconds=args.attempt_seconds,
                maximum_affected_cabins=args.cabins,
                beam_width=args.beam,
                accept_improvements=args.accept_improvements,
            ),
            args.requests,
            passenger_refinement_seconds=args.passenger_seconds,
        )
    )
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
