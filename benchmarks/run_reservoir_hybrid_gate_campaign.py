"""Sequential G0/G2 pilot with process deadlines and a 4 GiB RSS guard.

Only evaluates the gates: it never silently starts later implementation stages.
The parent records forced termination separately from solver certificates.
"""

import argparse
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import time


def terminate(process):
    if process.poll() is None:
        os.killpg(process.pid, signal.SIGTERM)
        try:
            process.wait(timeout=2)
        except subprocess.TimeoutExpired:
            os.killpg(process.pid, signal.SIGKILL)
            process.wait()


def run_case(command, log, deadline, memory_limit=4 * 1024**3):
    started = time.monotonic()
    peak = 0
    reason = None
    with log.open("w") as stream:
        process = subprocess.Popen(
            command, stdout=stream, stderr=subprocess.STDOUT, start_new_session=True
        )
        try:
            while process.poll() is None:
                # Both supported engines run in-process; RSS includes native allocations.
                sampled = subprocess.run(
                    ["ps", "-o", "rss=", "-p", str(process.pid)],
                    capture_output=True,
                    text=True,
                    check=False,
                ).stdout.strip()
                if sampled:
                    peak = max(peak, int(sampled) * 1024)
                if time.monotonic() >= deadline:
                    reason = "wall_time_limit"
                    break
                if peak > memory_limit:
                    reason = "rss_limit"
                    break
                time.sleep(0.2)
        finally:
            terminate(process)
    return {
        "return_code": process.returncode,
        "termination_reason": reason,
        "peak_sampled_rss_bytes": peak,
        "actual_seconds": time.monotonic() - started,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__, allow_abbrev=False)
    parser.add_argument("--resume-checkpoint", required=True, type=Path)
    parser.add_argument("--output-dir", required=True, type=Path)
    parser.add_argument(
        "--journey-encoding",
        choices=("legacy", "ride_bounds", "time_moments"),
        default="legacy",
    )
    parser.add_argument(
        "--no-size-caps",
        action="store_true",
        help="Use only the existing time and RSS limits",
    )
    args = parser.parse_args()
    args.output_dir.mkdir(parents=True, exist_ok=False)
    started = time.monotonic()
    deadline = started + 90 * 60
    report = {
        "cases": {},
        "total_budget_seconds": 5400,
        "size_caps_disabled": args.no_size_caps,
        "journey_encoding": args.journey_encoding,
    }
    for name in ("replay", "arrival_only", "movement_capacity", "resource_windows"):
        left = deadline - time.monotonic() - 3
        if left <= 0:
            break
        budget = min(300, left)
        output = args.output_dir / name
        command = [
            sys.executable,
            "benchmarks/run_ddd_reservoir_hybrid.py",
            "--resume-checkpoint",
            str(args.resume_checkpoint),
            "--output-dir",
            str(output),
            "--time-limit",
            str(max(0.01, budget - 3)),
            "--phase",
            "replay" if name == "replay" else "bound",
        ]
        if name != "replay":
            command += [
                "--bound-profile",
                name,
                "--journey-encoding",
                args.journey_encoding,
            ]
        if args.no_size_caps:
            command += ["--max-variables", "0", "--max-rows", "0"]
        result = run_case(
            command,
            args.output_dir / f"{name}.log",
            min(deadline - 2, time.monotonic() + budget - 2),
        )
        if (output / "result.json").exists():
            result["result"] = json.loads((output / "result.json").read_text())
        report["cases"][name] = result
        report["actual_total_seconds"] = time.monotonic() - started
        (args.output_dir / "campaign.json").write_text(
            json.dumps(report, indent=2) + "\n"
        )
        print(name, json.dumps(result), flush=True)
        if name == "replay" and (result["return_code"] or "result" not in result):
            report["gate"] = "G0_failed"
            break
    if "gate" not in report:
        case = report["cases"].get("resource_windows", {})
        result = case.get("result", {})
        analytic = result.get("analytical_lower_bound", 0)
        upper = result.get("validated_upper_bound", float("inf"))
        threshold = analytic + 0.10 * (upper - analytic)
        report["G2_threshold"] = threshold if threshold < float("inf") else None
        report["gate"] = (
            "G2_passed"
            if (
                case.get("return_code") == 0
                and result.get("status") == 2
                and result.get("certified_lower_bound", 0) >= threshold
            )
            else "G2_failed"
        )
    report["actual_total_seconds"] = time.monotonic() - started
    (args.output_dir / "campaign.json").write_text(json.dumps(report, indent=2) + "\n")


if __name__ == "__main__":
    main()
