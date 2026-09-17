"""Experiment preparation and process-tree supervision for native engines."""

from __future__ import annotations

import json
import os
import signal
import subprocess
import sys
import time
from dataclasses import replace

from ..optimization.ddd.cp_sat_certificate import (
    atomic_json,
    read_ddd_cp_sat_checkpoint,
    validate_ddd_cp_sat_domain,
)
from ..optimization.ddd.fixed_k import DddFixedKOperatingMode, DddFixedKStartPolicy
from ..optimization.ddd.fixed_timetable_capacity import NestedDemand
from ..optimization.ddd.native_solvers import NativeSolverConfig, solve_native
from ..optimization.ddd.native_solvers.optimizer import save_plan, validate_plan
from ..optimization.ddd.reservoir_cp_sat_certificate import read_reservoir_cp_checkpoint
from ..optimization.ddd.reservoir_cp_sat_problem import DddReservoirCpSatProblem


def prepare_input(args):
    if args.operation == "reservoir":
        from ..optimization.ddd.reservoir_arc_flow_problem import (
            DddReservoirOperatingMode,
        )
        from .ddd_reservoir_arc_flow import (
            DddReservoirArcFlowRunConfig,
            prepare_ddd_reservoir_arc_flow_run,
        )

        physical = DddReservoirArcFlowRunConfig(
            args.example,
            args.max_cabins,
            entry_state_id=args.entry_state,
            warmup_seconds=args.warmup_seconds,
            service_seconds=args.service_seconds,
            recovery_seconds=args.recovery_seconds,
            waiting_max_seconds=args.maximum_wait_seconds,
            waiting_step_seconds=args.waiting_step_seconds,
            operating_mode=DddReservoirOperatingMode(args.mode),
        )
        p = DddReservoirCpSatProblem.from_arc_flow(
            prepare_ddd_reservoir_arc_flow_run(physical).problem
        )
        p = replace(p, dispatch_step_seconds=args.dispatch_step_seconds)
        if args.demand is not None:
            p = replace(
                p, demand_groups=NestedDemand(p.demand_groups).groups(args.demand)
            )
        seed = (
            read_reservoir_cp_checkpoint(args.resume_checkpoint, p)
            if args.resume_checkpoint
            else None
        )
    else:
        from .ddd_cp_sat_waiting import with_exit_waiting
        from .ddd_cp_sat_warmup import with_empty_warmup
        from .ddd_fixed_k_arc_flow import (
            DddFixedKArcFlowRunConfig,
            prepare_ddd_fixed_k_arc_flow_run,
        )

        prepared = prepare_ddd_fixed_k_arc_flow_run(
            DddFixedKArcFlowRunConfig(
                args.example,
                args.cabins,
                DddFixedKOperatingMode(args.mode),
                start_policy=DddFixedKStartPolicy(args.start_policy),
                cp_seed_time_limit_seconds=0,
            )
        )
        if args.maximum_wait_seconds:
            prepared = with_exit_waiting(
                prepared,
                maximum_seconds=args.maximum_wait_seconds,
                step_seconds=args.waiting_step_seconds,
            )
        if args.warmup_seconds:
            prepared = with_empty_warmup(prepared, seconds=args.warmup_seconds)
        p = prepared.problem
        if args.demand is not None:
            p = NestedDemand(p.passenger_build.demand_groups).apply(p, args.demand)
        seed = (
            read_ddd_cp_sat_checkpoint(
                args.resume_checkpoint,
                problem=p,
                manifest=validate_ddd_cp_sat_domain(p),
            )
            if args.resume_checkpoint
            else None
        )
    return p, seed


def run_existing_cp(
    problem, seed, objective, seconds, workers, random_seed, output, emit
):
    from ..optimization.ddd.cp_sat_capacity import DddCpSatCapacityOptimizer
    from ..optimization.ddd.cp_sat_integrated import (
        DddIntegratedCpSatConfig,
        DddIntegratedCpSatOptimizer,
    )
    from ..optimization.ddd.reservoir_cp_sat import (
        DddReservoirCpObjective,
        DddReservoirCpSatOptimizer,
    )

    config = DddIntegratedCpSatConfig(
        total_time_limit_seconds=seconds,
        num_workers=workers,
        seed=random_seed,
        checkpoint_path=output / "best.json",
        checkpoint_interval_seconds=1,
        log_search_progress=True,
    )
    reference = None
    if seed is not None:
        seed, m = validate_plan(problem, seed)
        reference = m["unserved" if objective == "unserved" else "journey_time_tick"]
        save_plan(problem, seed, output / "best.json")
    if isinstance(problem, DddReservoirCpSatProblem):
        raw = DddReservoirCpSatOptimizer(
            config, DddReservoirCpObjective(objective)
        ).solve(problem, primal_seed=seed, event_callback=emit)
        scale = 1 if objective == "unserved" else 1000000
        ub = raw["validated_upper_bound"]
        lb = raw["cp_lower_bound"]
        result = {
            "validated_upper_bound": None if ub is None else round(ub * scale),
            "lower_bound": None if lb is None else __import__("math").floor(lb * scale),
            "status": raw["solver_status"],
            "proven_optimal": raw["proven_optimal"],
            "stats": raw["model_stats"],
        }
    elif objective == "unserved":
        raw = DddCpSatCapacityOptimizer(config).solve(
            problem, primal_seed=seed, event_callback=emit
        )
        result = {
            "validated_upper_bound": raw.get("unserved_upper_bound"),
            "lower_bound": raw.get("unserved_lower_bound"),
            "status": raw.get("solver_status"),
            "proven_optimal": raw["proven_optimal"],
            "stats": raw.get("model_stats"),
        }
    else:
        result_object = DddIntegratedCpSatOptimizer(config).solve(
            problem, primal_seed=seed, event_callback=emit
        )
        raw = result_object.to_payload()
        result = {
            "validated_upper_bound": None
            if result_object.incumbent is None
            else result_object.incumbent.objective_tick,
            "lower_bound": result_object.cp_best_bound_tick,
            "status": result_object.solver_status,
            "proven_optimal": result_object.proven_optimal,
            "stats": result_object.model_stats,
        }
    atomic_json(output / "cp_raw_result.json", raw)
    result.update(
        backend="cp_sat",
        objective=objective,
        reference_objective=reference,
        units="persons" if objective == "unserved" else "person_ticks",
        events=raw.get("events", []),
        raw_lower_bound=raw.get("raw_cp_bound", raw.get("raw_cp_best_bound_tick")),
        proof_scope="FULL_DOMAIN",
        model_fingerprint=raw.get("model_fingerprint"),
        actual_worker_configuration=workers,
        repetition_is_seed=True,
    )
    # Native solution counts/events stay in cp_raw_result; a fallback reference
    # is never inferred to be a native solution merely from the final UB.
    return result


def _signal_owned_process_tree(process, sig):
    """Handle macOS group-signal denial and the exit-at-deadline race."""
    if process.poll() is not None:
        return
    try:
        os.killpg(process.pid, sig)
        return
    except ProcessLookupError:
        return
    except PermissionError:
        # The child can have exited between poll and killpg. If it remains,
        # signal our concrete child and its descendants rather than the group.
        if process.poll() is not None:
            return
    import psutil

    try:
        descendants = psutil.Process(process.pid).children(recursive=True)
    except psutil.NoSuchProcess:
        descendants = []
    for child in reversed(descendants):
        try:
            child.send_signal(sig)
        except psutil.NoSuchProcess:
            pass
    process.send_signal(sig)


def _macos_memory_free_percent() -> float | None:
    """Return Apple's pressure-aware free percentage when the command exists."""
    if sys.platform != "darwin":
        return None
    try:
        completed = subprocess.run(
            ["memory_pressure", "-Q"],
            capture_output=True,
            check=False,
            text=True,
            timeout=1,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    for line in completed.stdout.splitlines():
        prefix = "System-wide memory free percentage:"
        if line.startswith(prefix):
            try:
                return float(line.removeprefix(prefix).strip().removesuffix("%"))
            except ValueError:
                return None
    return None


def supervise(
    command,
    output,
    *,
    seconds,
    memory_bytes=8 * 1024**3,
    global_deadline=None,
    checkpoint_callback=None,
    env=None,
    system_memory_pressure_seconds=None,
):
    """Hard civil/awake deadlines and RSS for the complete isolated process tree."""
    import psutil

    started, civil = time.monotonic(), time.time()
    deadline = min(civil + seconds, global_deadline or float("inf"))
    peak, cpu, threads = 0, {}, 0
    minimum_available = None
    minimum_pressure_free_percent = None
    initial_swap = psutil.swap_memory().used
    peak_swap = initial_swap
    critical_since = None
    next_pressure_sample = 0.0
    reason, last_checkpoint = None, None
    with (output / "process.log").open("w") as stream:
        process = subprocess.Popen(
            command,
            stdout=stream,
            stderr=subprocess.STDOUT,
            start_new_session=True,
            env=env,
        )
        while process.poll() is None:
            checkpoint = output / "best.json"
            if checkpoint_callback and checkpoint.is_file():
                stamp = checkpoint.stat().st_mtime_ns
                if stamp != last_checkpoint:
                    try:
                        checkpoint_callback(checkpoint, time.monotonic() - started)
                    except Exception as exc:  # noqa: BLE001 - preserve diagnostics across optional native engine failures
                        reason = "INVALID_CHECKPOINT"
                        atomic_json(
                            output / "validation_error.json",
                            {"error": f"{type(exc).__name__}: {exc}"},
                        )
                    last_checkpoint = stamp
            try:
                parent = psutil.Process(process.pid)
                tree = [parent, *parent.children(recursive=True)]
                rss, thread_count = 0, 0
                for p in tree:
                    try:
                        rss += p.memory_info().rss
                        c = p.cpu_times()
                        cpu[p.pid] = c.user + c.system
                        thread_count += p.num_threads()
                    except psutil.Error:
                        pass
                peak, threads = max(peak, rss), max(threads, thread_count)
                if rss > memory_bytes:
                    reason = "MEMORY_LIMIT"
            except psutil.Error:
                pass
            elapsed = time.monotonic() - started
            memory = psutil.virtual_memory()
            swap = psutil.swap_memory().used
            peak_swap = max(peak_swap, swap)
            minimum_available = (
                memory.available
                if minimum_available is None
                else min(minimum_available, memory.available)
            )
            if system_memory_pressure_seconds is not None and elapsed >= next_pressure_sample:
                pressure_free = _macos_memory_free_percent()
                next_pressure_sample = elapsed + 1.0
                if pressure_free is not None:
                    minimum_pressure_free_percent = (
                        pressure_free
                        if minimum_pressure_free_percent is None
                        else min(minimum_pressure_free_percent, pressure_free)
                    )
                critical = (
                    pressure_free is not None and pressure_free <= 5.0
                ) or memory.available <= max(512 * 1024**2, int(memory.total * 0.02))
                if critical:
                    critical_since = critical_since or elapsed
                    if elapsed - critical_since >= system_memory_pressure_seconds:
                        reason = "SYSTEM_MEMORY_PRESSURE"
                else:
                    critical_since = None
            civil_elapsed = time.time() - civil
            if civil_elapsed - elapsed > 5:
                reason = "SUSPEND_DETECTED"
            if time.time() >= deadline or elapsed >= seconds:
                reason = reason or "WALL_DEADLINE"
            if reason:
                _signal_owned_process_tree(process, signal.SIGTERM)
                try:
                    process.wait(timeout=min(1, max(0.01, deadline - time.time())))
                except subprocess.TimeoutExpired:
                    _signal_owned_process_tree(process, signal.SIGKILL)
                break
            time.sleep(min(0.1, max(0.001, deadline - time.time())))
        process.wait()
    metrics = {
        "exit_code": process.returncode,
        "supervisor_reason": reason,
        "civil_wall_seconds": time.time() - civil,
        "awake_wall_seconds": time.monotonic() - started,
        "peak_process_tree_rss_bytes": peak,
        "sampled_process_tree_cpu_seconds": sum(cpu.values()),
        "peak_sampled_thread_count": threads,
        "minimum_system_available_bytes": minimum_available,
        "minimum_macos_memory_free_percent": minimum_pressure_free_percent,
        "initial_swap_used_bytes": initial_swap,
        "peak_swap_used_bytes": peak_swap,
        "final_swap_used_bytes": psutil.swap_memory().used,
        "system_memory_pressure_grace_seconds": system_memory_pressure_seconds,
    }
    atomic_json(output / "supervisor.json", metrics)
    return metrics


def worker(problem, seed, args, *, started=None):
    started = started or time.monotonic()
    output = args.output_dir
    with (output / "events.jsonl").open("w") as stream:

        def emit(event):
            item = {**event, "runner_elapsed_seconds": time.monotonic() - started}
            stream.write(json.dumps(item, default=str) + "\n")
            stream.flush()

        remaining = args.time_limit - (time.monotonic() - started) - 2
        if remaining <= 0:
            raise TimeoutError("preparation exhausted run budget")
        if args.backend == "cp_sat":
            result = run_existing_cp(
                problem,
                seed,
                args.objective,
                remaining,
                args.num_workers,
                args.seed,
                output,
                emit,
            )
        else:
            config = NativeSolverConfig(
                args.backend,
                args.objective,
                remaining,
                args.num_workers,
                args.seed,
                output / "best.json",
                args.build_only,
            )
            result, _ = solve_native(
                problem, config, primal_seed=seed, event_callback=emit
            )
    result["runner_total_seconds"] = time.monotonic() - started
    atomic_json(output / "result.json", result)
    return result


def assess_campaign(cases):
    """Published acceptance thresholds, independently for each original domain."""
    indexed = {(c.get("case"), c["backend"], c.get("repetition")): c for c in cases}
    results = []
    for case in ("R", "C"):
        for backend in ("hexaly", "z3"):
            confirmations = []
            for repetition in (1, 2):
                new = indexed.get((case, backend, repetition), {})
                base = indexed.get((case, "cp_sat", repetition), {})
                if any(
                    c.get("status") in (None, "ERROR", "NOT_STARTED")
                    or c.get("validated_upper_bound") is None
                    for c in (new, base)
                ):
                    confirmations.append(
                        {"repetition": repetition, "outcome": "unavailable"}
                    )
                    continue
                ub, reference = (
                    new["validated_upper_bound"],
                    base["validated_upper_bound"],
                )
                better_ub = (
                    ub < reference and ub * 1000 <= reference * 999
                    if case == "R"
                    else ub <= reference - 10
                )
                better_gap = ub <= reference and new["gap"] <= base["gap"] - 0.01
                confirmations.append(
                    {
                        "repetition": repetition,
                        "outcome": "confirmed"
                        if better_ub or better_gap
                        else "inconclusive",
                        "incumbent_gain": better_ub,
                        "gap_gain": better_gap,
                    }
                )
            results.append(
                {
                    "case": case,
                    "backend": backend,
                    "recommended": all(
                        c["outcome"] == "confirmed" for c in confirmations
                    ),
                    "confirmations": confirmations,
                }
            )
    return results
