"""Finish the first thesis Evo attempt, pause its queue, then run matched Greedy controls."""
from __future__ import annotations

import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import time

import psutil

from ropeway_skip_stop_optimization.optimization.ddd.cp_sat_certificate import atomic_json

ROOT = Path(__file__).resolve().parents[1]
STUDY = ROOT / "results/thesis_evo_capacity_20260916"
LIVE = ROOT / "frontend/public/generated/evolution-live"
OUT = ROOT / "results/thesis_greedy_journey_t5r_f2_20260916"
FIRST_KEY = "capacity_t5r_f2_g500_p0/seed0/n2918_k62_skip_stop"


def pause_evo_queue() -> None:
    subprocess.run(["launchctl", "bootout", f"gui/{os.getuid()}/local.ropeway.thesis-evo-capacity"], check=False)
    subprocess.run(["launchctl", "bootout", f"gui/{os.getuid()}/local.ropeway.thesis-evo-live"], check=False)
    for process in psutil.process_iter(["pid", "cmdline"]):
        command = " ".join(process.info["cmdline"] or [])
        if str(STUDY) in command and process.pid != os.getpid():
            try: process.send_signal(signal.SIGTERM)
            except psutil.Error: pass


def live_manifest(run_id: str, label: str, status: str) -> None:
    atomic_json(LIVE / "manifest.json", {
        "schema": "reservoir_line_evolution_live_manifest_v1",
        "label": "T5/F2 · Evo versus Greedy", "status": status,
        "runs": [{"id": run_id, "label": label, "status": status,
                  "snapshot": f"/generated/evolution-live/{run_id}.json"}],
        "updated_unix": time.time(),
    })


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=False)
    atomic_json(OUT / "controller.json", {"status": "waiting_for_first_evo_attempt", "key": FIRST_KEY})
    while True:
        state_path = STUDY / "study.json"
        if state_path.exists():
            state = json.loads(state_path.read_text())
            attempt = next((a for a in state.get("attempts", []) if a["key"] == FIRST_KEY and a["status"] == "complete"), None)
            if attempt: break
        time.sleep(.2)
    pause_evo_queue()
    time.sleep(3)
    reference = ROOT / "results/thesis_capacity_preparation_20260916_v2/reference_t5r_f2_r15/best.json"
    common = [sys.executable, str(ROOT / "benchmarks/run_reservoir_greedy.py"),
              "--reference-checkpoint", str(reference), "--all-stop-reference", str(reference),
              "--backend", "cp_sat", "--objective", "journey_time", "--mode", "construct",
              "--maximum-cabins", "62", "--dispatch-window-end", "732",
              "--time-limit", "1800", "--insertion-time-limit", "30", "--extended-time-limit", "120",
              "--workers", "12", "--memory-limit-gib", "32", "--seed", "0", "--wait-for-solvers"]
    results = []
    for name, waiting in (("no_wait", 0), ("waiting_120", 120)):
        run_id = f"thesis_greedy_t5r_f2_{name}"
        label = f"Greedy · T5/F2 · N2918 · K≤62 · {name.replace('_', ' ')}"
        live_manifest(run_id, label, "running")
        directory = OUT / name
        command = [*common, "--maximum-wait-seconds", str(waiting), "--output", str(directory),
                   "--live-snapshot", str(LIVE / f"{run_id}.json")]
        before = time.time(); code = subprocess.run(command, cwd=ROOT).returncode
        results.append({"id": name, "exit_code": code, "wall_seconds": time.time()-before})
        live_manifest(run_id, label, "complete" if code == 0 else "failed")
        atomic_json(OUT / "controller.json", {"status": "running", "completed": results})
        if code: break
    atomic_json(OUT / "controller.json", {"status": "complete" if all(r["exit_code"] == 0 for r in results) else "failed", "runs": results})


if __name__ == "__main__": main()
