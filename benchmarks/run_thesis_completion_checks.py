"""Bounded corrective checks after the frozen G500 preflight, never the main study."""
import argparse
import json
from pathlib import Path
import subprocess
import sys
import time

from ropeway_skip_stop_optimization.benchmarking.native_solvers import supervise
from ropeway_skip_stop_optimization.optimization.ddd.cp_sat_certificate import atomic_json

ROOT = Path(__file__).resolve().parents[1]


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--output-dir", type=Path, required=True)
    p.add_argument("--_worker", action="store_true")
    args = p.parse_args()
    out = args.output_dir
    if not args._worker:
        out.mkdir(parents=True, exist_ok=False)
        metrics = supervise([sys.executable, str(Path(__file__).resolve()), *sys.argv[1:], "--_worker"], out,
                            seconds=2400, memory_bytes=32 * 1024**3, system_memory_pressure_seconds=30)
        if metrics["exit_code"] or metrics["supervisor_reason"]:
            raise SystemExit(1)
        return
    started = time.time()
    state = {"schema": "thesis_corrective_checks_v1", "status": "running", "jobs": []}
    tasks = []
    for topology, k in (("t5r", 62), ("t6r", 75)):
        for family in ("f2", "f0", "f3", "f4"):
            for resolution in ((15, 5) if family == "f2" else (15,)):
                if topology == "t5r" and family == "f2" and resolution == 15:
                    continue  # Already checked separately in the completion directory.
                reference = f"reference_{topology}_f2_r{resolution}" if family == "f2" else f"reference_{topology}_{family}_capacity_r15"
                extra = ["--capacity-search", "--capacity-reference-dir", str(ROOT / "results/thesis_g500_preflight_20260915" / reference)]
                if family == "f2":
                    extra += ["--capacity-probe-demand", "3000"]
                tasks.append((reference, topology, family, k, resolution, "unserved", "all_stop_phase", 10000 if family == "f2" else 50000, 180, extra))
    for family, demand in (("f0", 510), ("f3", 360), ("f4", 772)):
        for resolution in ((15, 5) if family == "f0" else (5,)):
            tasks.append((f"journey_t5r_{family}_skip_stop_r{resolution}", "t5r", family, 10, resolution,
                          "journey_time", "labelled_arc_flow", demand, 90, []))
    for name, topology, family, k, resolution, objective, method, demand, seconds, extra in tasks:
        if time.time() - started + seconds + 5 >= 2400:
            state["jobs"].append({"id": name, "status": "skipped", "reason": "deadline"})
            continue
        entry = {"id": name, "status": "running"}
        state["jobs"].append(entry); atomic_json(out / "checks.json", state)
        command = [sys.executable, str(ROOT / "benchmarks/run_thesis_experiment.py"), "--topology", topology,
                   "--geometry", "g500", "--demand-family", family, "--objective", objective,
                   "--demand", str(demand), "--method", method, "--cabins", str(k), "--release-resolution-seconds", str(resolution),
                   "--workers", "12", "--time-limit", str(seconds), "--output-dir", str(out / name), *extra]
        before = time.time(); result = subprocess.run(command, cwd=ROOT, check=False)
        entry.update(status="complete" if result.returncode == 0 else "failed", exitCode=result.returncode, wallSeconds=time.time() - before)
        atomic_json(out / "checks.json", state)
    state.update(status="complete" if all(job["status"] == "complete" for job in state["jobs"]) else "partial", wallSeconds=time.time() - started)
    atomic_json(out / "checks.json", state)


if __name__ == "__main__":
    main()
