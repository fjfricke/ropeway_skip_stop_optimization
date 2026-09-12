"""Run the bounded passenger-fixing and conflict-transfer diagnosis."""

import argparse
from dataclasses import asdict
from datetime import datetime
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import time

import gurobipy as gp
from ortools import __version__ as ortools_version
import psutil

from ropeway_skip_stop_optimization.optimization.ddd.cp_sat_certificate import (
    atomic_json,
)
from ropeway_skip_stop_optimization.optimization.ddd.reservoir_assignment import (
    assignment_from_payload,
    assignment_from_plan,
    assignment_to_payload,
    assignment_violates_conflict,
    conflict_from_payload,
    validate_service_assignment,
)
from ropeway_skip_stop_optimization.optimization.ddd.reservoir_cp_sat_certificate import (
    validate_reservoir_cp_plan,
)
from ropeway_skip_stop_optimization.optimization.ddd.reservoir_hybrid.domain import (
    load_reference,
)


def _file_hash(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _source_hash(root):
    paths = (
        root / "src/ropeway_skip_stop_optimization/optimization/ddd/reservoir_assignment/assignment.py",
        root / "src/ropeway_skip_stop_optimization/optimization/ddd/reservoir_assignment/master.py",
        root / "src/ropeway_skip_stop_optimization/optimization/ddd/reservoir_assignment/timing.py",
        root / "src/ropeway_skip_stop_optimization/optimization/ddd/reservoir_assignment/conflicts.py",
        root / "benchmarks/run_reservoir_assignment_timing.py",
        root / "benchmarks/run_reservoir_assignment_conflict_diagnosis.py",
    )
    digest = hashlib.sha256()
    for path in paths:
        digest.update(str(path.relative_to(root)).encode())
        digest.update(path.read_bytes())
    return digest.hexdigest()


def _assignment_metrics(assignment):
    waits = [value for trip in assignment.trips for value in trip.witness_wait_ticks]
    return {
        "target_served": assignment.target_served,
        "used_fleet": len(assignment.trips),
        "positive_rides": sum(1 for value in assignment.ride_counts.values() if value),
        "positive_waits": sum(1 for value in waits if value),
        "total_wait_ticks": sum(waits),
    }


def _process_rss(process):
    try:
        parent = psutil.Process(process.pid)
        members = [parent, *parent.children(recursive=True)]
    except psutil.Error:
        return 0
    total = 0
    for member in members:
        try:
            total += member.memory_info().rss
        except psutil.Error:
            pass
    return total


def _stop_tree(process):
    try:
        parent = psutil.Process(process.pid)
        members = parent.children(recursive=True)
    except psutil.Error:
        members = []
    for member in reversed(members):
        try:
            member.terminate()
        except psutil.Error:
            pass
    process.terminate()
    try:
        process.wait(timeout=5)
    except subprocess.TimeoutExpired:
        for member in reversed(members):
            try:
                member.kill()
            except psutil.Error:
                pass
        process.kill()
        process.wait()


def _run_child(command, log_path, deadline, memory_bytes, allowance):
    started = time.time()
    peak = 0
    reason = None
    with log_path.open("w") as log:
        process = subprocess.Popen(command, stdout=log, stderr=subprocess.STDOUT)
        while process.poll() is None:
            peak = max(peak, _process_rss(process))
            if peak > memory_bytes:
                reason = "memory_limit"
                _stop_tree(process)
                break
            if time.time() >= min(deadline, started + allowance):
                reason = "deadline"
                _stop_tree(process)
                break
            time.sleep(0.2)
    return {
        "return_code": process.returncode,
        "wall_seconds": time.time() - started,
        "peak_rss_bytes": peak,
        "termination_reason": reason,
    }


def _result_summary(path):
    if not path.exists():
        return None
    result = json.loads(path.read_text())
    metrics = result.get("metrics") or {}
    return {
        key: result.get(key)
        for key in (
            "status",
            "proved_infeasible",
            "has_valid_plan",
            "build_seconds",
            "solve_seconds",
            "total_seconds",
            "passenger_fixing",
        )
    } | {
        "served": metrics.get("served"),
        "unserved": metrics.get("unserved"),
        "core_size": result.get("core_size"),
        "initial_core_size": result.get("initial_core_size"),
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__, allow_abbrev=False)
    parser.add_argument("--reference-checkpoint", required=True, type=Path)
    parser.add_argument("--assignment-input", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--case-seconds", type=float, default=120)
    parser.add_argument("--master-seconds", type=float, default=180)
    parser.add_argument("--transfer-timing-seconds", type=float, default=420)
    parser.add_argument("--total-seconds", type=float, default=2400)
    parser.add_argument("--threads", type=int, default=12)
    parser.add_argument("--memory-gib", type=float, default=24)
    parser.add_argument("--seed", type=int, default=0)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=False)
    started = time.time()
    deadline = started + args.total_seconds
    root = Path(__file__).resolve().parents[1]
    runner = Path(__file__).with_name("run_reservoir_assignment_timing.py")
    domain, reference_plan = load_reference(args.reference_checkpoint)
    reference_metrics = validate_reservoir_cp_plan(domain.problem, reference_plan)
    reference_assignment = assignment_from_plan(domain.problem, reference_plan)
    difficult_payload = json.loads(args.assignment_input.read_text())
    difficult_assignment = assignment_from_payload(difficult_payload)
    validate_service_assignment(domain.problem, difficult_assignment)
    frozen = args.output / "frozen"
    frozen.mkdir()
    reference_assignment_path = frozen / "reference_assignment.json"
    difficult_assignment_path = frozen / "difficult_assignment.json"
    atomic_json(reference_assignment_path, assignment_to_payload(reference_assignment))
    atomic_json(difficult_assignment_path, difficult_payload)
    atomic_json(frozen / "domain.json", domain.problem.manifest)
    report = {
        "schema": "reservoir_assignment_conflict_diagnosis_v1",
        "started_at": datetime.now().astimezone().isoformat(),
        "deadline_epoch": deadline,
        "input_hashes": {
            "reference": _file_hash(args.reference_checkpoint),
            "assignment": _file_hash(args.assignment_input),
            "sources": _source_hash(root),
        },
        "versions": {
            "python": sys.version,
            "ortools": ortools_version,
            "gurobi": ".".join(map(str, gp.gurobi.version())),
        },
        "reference_metrics": asdict(reference_metrics),
        "assignments": {
            "reference": _assignment_metrics(reference_assignment),
            "difficult": _assignment_metrics(difficult_assignment),
        },
        "cases": [],
        "conflict": None,
        "transfer": None,
    }
    atomic_json(args.output / "campaign.json", report)
    cases = (
        ("T0_reference_free_exact", reference_assignment_path, False, "exact"),
        ("T1_difficult_fixed_exact", difficult_assignment_path, True, "exact"),
        ("T2_difficult_free_commitments", difficult_assignment_path, False, "commitments"),
        ("T3_difficult_fixed_reassign", difficult_assignment_path, True, "reassign"),
        ("T4_difficult_free_reassign", difficult_assignment_path, False, "reassign"),
    )
    memory_bytes = int(args.memory_gib * 1024**3)
    for name, assignment_path, fixed_routes, passenger_fixing in cases:
        if time.time() + 30 >= deadline:
            report.setdefault("pending", []).append(name)
            continue
        output = args.output / name
        command = [
            sys.executable,
            str(runner),
            "--stage", "timing",
            "--reference-checkpoint", str(args.reference_checkpoint),
            "--assignment-input", str(assignment_path),
            "--output", str(output),
            "--timing-seconds", str(args.case_seconds),
            "--threads", str(args.threads),
            "--seed", str(args.seed),
            "--memory-gib", str(args.memory_gib),
            "--no-witness-hints",
            "--passenger-fixing", passenger_fixing,
        ]
        if not fixed_routes:
            command.append("--free-nonservice-routes")
        entry = {"name": name, "command": command, "started_at": time.time()}
        entry.update(
            _run_child(
                command,
                args.output / f"{name}.log",
                deadline,
                memory_bytes,
                args.case_seconds + 30,
            )
        )
        entry["result"] = _result_summary(output / "result.json")
        report["cases"].append(entry)
        atomic_json(args.output / "campaign.json", report)

    infeasible = {
        entry["name"]: entry
        for entry in report["cases"]
        if entry.get("result", {}).get("status") == "INFEASIBLE"
    }
    priority = (
        "T4_difficult_free_reassign",
        "T3_difficult_fixed_reassign",
        "T2_difficult_free_commitments",
        "T1_difficult_fixed_exact",
    )
    selected = next((name for name in priority if name in infeasible), None)
    conflict_path = None
    if selected and time.time() + 30 < deadline:
        case = next(item for item in cases if item[0] == selected)
        _, assignment_path, fixed_routes, passenger_fixing = case
        output = args.output / "conflict"
        command = [
            sys.executable,
            str(runner),
            "--stage", "conflict",
            "--reference-checkpoint", str(args.reference_checkpoint),
            "--assignment-input", str(assignment_path),
            "--output", str(output),
            "--seed", str(args.seed),
            "--threads", "1",
            "--memory-gib", str(args.memory_gib),
            "--no-witness-hints",
            "--passenger-fixing", passenger_fixing,
            "--conflict-seconds", "180",
            "--conflict-deletion-seconds", "300",
            "--conflict-replay-seconds", "120",
            "--conflict-deletion-slice-seconds", "15",
        ]
        if not fixed_routes:
            command.append("--free-nonservice-routes")
        conflict_entry = {"source_case": selected, "command": command}
        conflict_entry.update(
            _run_child(
                command,
                args.output / "conflict.log",
                deadline,
                memory_bytes,
                630,
            )
        )
        conflict_entry["result"] = _result_summary(output / "result.json")
        conflict_path = output / "conflict.json"
        if conflict_path.exists():
            conflict = conflict_from_payload(json.loads(conflict_path.read_text()))
            conflict_entry["difficult_assignment_violates"] = (
                assignment_violates_conflict(
                    domain.problem, difficult_assignment, conflict
                )
            )
            conflict_entry["reference_assignment_violates"] = (
                assignment_violates_conflict(
                    domain.problem, reference_assignment, conflict
                )
            )
        report["conflict"] = conflict_entry
        atomic_json(args.output / "campaign.json", report)

    transferable = (
        conflict_path is not None
        and report["conflict"].get("difficult_assignment_violates") is True
        and report["conflict"].get("reference_assignment_violates") is False
    )
    if transferable and time.time() + 30 < deadline:
        master_output = args.output / "transfer_master"
        master_command = [
            sys.executable,
            str(runner),
            "--stage", "master",
            "--reference-checkpoint", str(args.reference_checkpoint),
            "--conflict-input", str(conflict_path),
            "--output", str(master_output),
            "--additional-served", "10",
            "--master-seconds", str(args.master_seconds),
            "--threads", str(args.threads),
            "--seed", str(args.seed),
            "--memory-gib", str(args.memory_gib),
        ]
        transfer = {"master_command": master_command}
        transfer["master_process"] = _run_child(
            master_command,
            args.output / "transfer_master.log",
            deadline,
            memory_bytes,
            args.master_seconds + 30,
        )
        transfer["master_result"] = _result_summary(master_output / "result.json")
        new_assignment = master_output / "assignment.json"
        if new_assignment.exists() and time.time() + 30 < deadline:
            timing_output = args.output / "transfer_timing"
            timing_command = [
                sys.executable,
                str(runner),
                "--stage", "timing",
                "--reference-checkpoint", str(args.reference_checkpoint),
                "--assignment-input", str(new_assignment),
                "--output", str(timing_output),
                "--timing-seconds", str(args.transfer_timing_seconds),
                "--threads", str(args.threads),
                "--seed", str(args.seed),
                "--memory-gib", str(args.memory_gib),
                "--no-witness-hints",
                "--free-nonservice-routes",
                "--passenger-fixing", "exact",
            ]
            transfer["timing_command"] = timing_command
            transfer["timing_process"] = _run_child(
                timing_command,
                args.output / "transfer_timing.log",
                deadline,
                memory_bytes,
                args.transfer_timing_seconds + 30,
            )
            transfer["timing_result"] = _result_summary(
                timing_output / "result.json"
            )
        report["transfer"] = transfer

    report["finished_at"] = datetime.now().astimezone().isoformat()
    report["wall_seconds"] = time.time() - started
    atomic_json(args.output / "campaign.json", report)
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
