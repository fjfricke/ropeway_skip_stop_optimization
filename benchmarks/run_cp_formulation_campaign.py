"""Sequential, frozen two-case formulation ablation with a hard wall-clock cap."""

from __future__ import annotations

import argparse
from dataclasses import asdict, replace
import datetime
import hashlib
import json
import os
from pathlib import Path
import runpy
import shutil
import signal
import subprocess
import sys
import tarfile
import time

ROOT = Path(__file__).resolve().parents[1]
ENGINE = Path(
    "/Users/felix/Applications/CPLEX_Studio222/cpoptimizer/bin/arm64_osx/cpoptimizer"
)
EXAMPLE = "five_station_circle_cw_half_skip_no_wait_headway_b_v0"


def stamp():
    return datetime.datetime.now().astimezone().isoformat()


def dump(path, value):
    path = Path(path)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(value, indent=2, default=str))
    tmp.replace(path)


def single(spec):
    from ropeway_skip_stop_optimization.optimization.ddd.cp_formulation import (
        DddCpFormulationConfig,
    )
    from ropeway_skip_stop_optimization.optimization.ddd.cp_sat_integrated import (
        DddIntegratedCpSatConfig,
    )

    form = DddCpFormulationConfig(**spec["formulation"])
    out, inputs = Path(spec["output"]), Path(spec["inputs"])
    started = time.monotonic()
    if spec["case"] == "R":
        from ropeway_skip_stop_optimization.benchmarking.ddd_reservoir_arc_flow import (
            DddReservoirArcFlowRunConfig,
        )

        physical = DddReservoirArcFlowRunConfig(
            EXAMPLE,
            available_fleet_count=50,
            warmup_seconds=300,
            service_seconds=1200,
            recovery_seconds=300,
            waiting_max_seconds=1200.0,
            waiting_step_seconds=1e-6,
        )
        if spec["backend"] == "cp_sat":
            from ropeway_skip_stop_optimization.benchmarking.ddd_reservoir_cp_sat import (
                DddReservoirCpSatRunConfig,
                run_ddd_reservoir_cp_sat,
            )

            result = run_ddd_reservoir_cp_sat(
                DddReservoirCpSatRunConfig(
                    physical,
                    out,
                    solver=DddIntegratedCpSatConfig(
                        total_time_limit_seconds=spec["seconds"],
                        num_workers=12,
                        seed=spec["seed"],
                        log_search_progress=True,
                        formulation=form,
                    ),
                    resume_checkpoint=inputs / "R_seed.json",
                )
            )
        else:
            from ropeway_skip_stop_optimization.benchmarking.ddd_reservoir_ibm_cp import (
                DddReservoirIbmCpRunConfig,
                run_ddd_reservoir_ibm_cp,
            )
            from ropeway_skip_stop_optimization.optimization.ddd.reservoir_ibm_cp import (
                DddReservoirIbmCpConfig,
            )

            result = run_ddd_reservoir_ibm_cp(
                DddReservoirIbmCpRunConfig(
                    physical,
                    out,
                    solver=DddReservoirIbmCpConfig(
                        total_time_limit_seconds=spec["seconds"],
                        num_workers=12,
                        seed=spec["seed"],
                        executable=Path(spec["engine"]),
                        formulation=form,
                    ),
                    resume_checkpoint=inputs / "R_seed.json",
                )
            )
        seed = (
            json.loads((inputs / "R_seed.json").read_text())["metrics"][
                "journey_time_tick"
            ]
            / 1e6
        )
        lower_floor = 0.0
        from ropeway_skip_stop_optimization.benchmarking.ddd_reservoir_arc_flow import (
            prepare_ddd_reservoir_arc_flow_run,
        )
        from ropeway_skip_stop_optimization.optimization.ddd.reservoir_cp_sat_problem import (
            DddReservoirCpSatProblem,
        )
        from ropeway_skip_stop_optimization.optimization.ddd.cp_formulation import (
            prepare_cp_structure,
        )

        p = replace(
            DddReservoirCpSatProblem.from_arc_flow(
                prepare_ddd_reservoir_arc_flow_run(physical).problem
            ),
            dispatch_step_seconds=1e-6,
        )
        lower_floor = (
            prepare_cp_structure(
                p.movement,
                p.passenger_build,
                {k: p.visit_states for k in range(50)},
                reservoir=p,
            ).analytical_lower_bound
            / 1e6
        )
        ub, lb = result["validated_upper_bound"], result.get("cp_lower_bound")
    else:
        from ropeway_skip_stop_optimization.optimization.ddd.fixed_timetable_capacity import (
            NestedDemand,
        )
        from ropeway_skip_stop_optimization.optimization.ddd.cp_sat_certificate import (
            read_ddd_cp_sat_checkpoint,
            validate_ddd_cp_sat_domain,
        )
        from ropeway_skip_stop_optimization.optimization.ddd.cp_sat_capacity import (
            DddCpSatCapacityOptimizer,
        )

        p = runpy.run_path(
            str(ROOT / "benchmarks/run_fixed_start_capacity_campaign.py")
        )["prepare"](39, True).problem
        p = NestedDemand(p.passenger_build.demand_groups).apply(p, 3074)
        primal = read_ddd_cp_sat_checkpoint(
            inputs / "C_seed.json", problem=p, manifest=validate_ddd_cp_sat_domain(p)
        )
        seed = sum(primal.unserved_counts.values())
        out.mkdir(exist_ok=False)
        dump(out / "domain.json", validate_ddd_cp_sat_domain(p))
        shutil.copy2(inputs / "C_seed.json", out / "seed.json")
        prepare = time.monotonic() - started
        config = DddIntegratedCpSatConfig(
            total_time_limit_seconds=max(1e-6, spec["seconds"] - prepare),
            num_workers=12,
            seed=spec["seed"],
            checkpoint_path=out / "incumbent.json",
            log_search_progress=True,
            formulation=form,
        )
        dump(out / "config.json", asdict(config))
        with (
            (out / "events.jsonl").open("w") as events,
            (out / "solver.log").open("w") as log,
        ):

            def event(e):
                events.write(
                    json.dumps(
                        {**e, "runner_elapsed_seconds": time.monotonic() - started}
                    )
                    + "\n"
                )
                events.flush()

            def logging(line):
                log.write(line if line.endswith("\n") else line + "\n")
                log.flush()

            result = DddCpSatCapacityOptimizer(config).solve(
                p, primal_seed=primal, event_callback=event, log_callback=logging
            )
        result.update(
            prepare_seconds=prepare,
            end_to_end_seconds=time.monotonic() - started,
            seed_upper_bound=seed,
        )
        dump(out / "result.json", result)
        ub, lb = result["unserved_upper_bound"], result["unserved_lower_bound"]
        lower_floor = 0
    if result.get("error") or result["solver_status"] in (
        "ERROR",
        "MODEL_INVALID",
        "INFEASIBLE",
        "Infeasible",
    ):
        raise RuntimeError(
            "backend error: " + str(result.get("error", result["solver_status"]))
        )
    first = None
    last = None
    adopted = None
    improvements = 0
    for line in (out / "events.jsonl").read_text().splitlines():
        e = json.loads(line)
        if e["kind"] not in ("incumbent", "cp_incumbent"):
            continue
        score = e.get("unserved", e.get("objective_raw", e.get("objective_tick")))
        if score is None:
            continue
        if spec["case"] == "R":
            score /= 1e6
        elapsed = e.get("runner_elapsed_seconds", e["elapsed_seconds"])
        if score <= seed and adopted is None:
            adopted = elapsed
        if score < seed:
            first = elapsed if first is None else first
            last = elapsed
            improvements += 1
    text = (out / "solver.log").read_text()
    presolve = None
    import re

    match = re.search(r"Presolved optimization model.*?\n#Variables: ([\d\x27]+)", text)
    if match:
        presolve = int(match.group(1).replace("'", ""))
    summary = dict(
        spec=spec,
        status=result["solver_status"],
        ub=ub,
        raw_reported_lb=lb,
        analytical_lb=lower_floor,
        comparable_lb=max(lower_floor, lb or 0),
        seed_cost=seed,
        seed_adopted_seconds=adopted,
        first_improvement_seconds=first,
        last_improvement_seconds=last,
        improvement_events=improvements,
        seconds=result.get("end_to_end_seconds", result.get("total_seconds")),
        presolved_variables=presolve,
        problem_fingerprint=result["problem_fingerprint"],
        model_fingerprint=result.get("model_fingerprint"),
        solver_version=result.get("solver_version"),
        build_seconds=result.get("build_seconds"),
        hint_seconds=result.get("hint_seconds"),
        solve_seconds=result.get("solve_seconds"),
        validation_seconds=result.get("validation_seconds"),
    )
    import ortools

    summary.update(
        model_stats=result.get("model_stats"),
        preprocessing_seconds=result.get("model_stats", {}).get(
            "preprocessing_seconds", 0
        ),
        prepare_seconds=result.get("prepare_seconds"),
        model_build_seconds=result.get("model_build_seconds"),
        child_total_seconds=time.monotonic() - started,
        engine=spec["engine"] if spec["backend"] == "ibm" else sys.executable,
        solver_version=result.get("solver_version")
        or (ortools.__version__ if spec["backend"] == "cp_sat" else None),
    )
    dump(out / "summary.json", summary)


def specs():
    profiles = [
        "legacy",
        "hints",
        "temporal",
        "passenger_links",
        "journey_bounds",
        "strengthened",
    ]

    def base(case, backend, profile, resource="legacy", movement="legacy"):
        return dict(
            case=case,
            backend=backend,
            formulation=dict(
                profile=profile, resource_encoding=resource, movement_encoding=movement
            ),
        )

    result = [base("R", "cp_sat", p) for p in profiles]
    result += [base("C", "cp_sat", p) for p in profiles if p != "journey_bounds"]
    result += [
        base("R", "ibm", p, movement=m)
        for p, m in [
            ("legacy", "legacy"),
            ("strengthened", "legacy"),
            ("strengthened", "native_visits"),
        ]
    ]
    result += [
        base("R", "cp_sat", "strengthened", resource=r)
        for r in ["compact_fixed", "merged_exit"]
    ]
    return result


def rank(r):
    return (
        r["ub"],
        -r["comparable_lb"],
        r["first_improvement_seconds"]
        if r["first_improvement_seconds"] is not None
        else float("inf"),
    )


def confirmation_verdict(candidate, reference, case):
    """Both independent seeds must support the same direction of recommendation."""
    comparisons = []
    for seed in (1, 2):
        left = next((r for r in candidate if r["spec"]["seed"] == seed), None)
        right = next((r for r in reference if r["spec"]["seed"] == seed), None)
        if left is None or right is None:
            return {"status": "pending", "comparisons": comparisons}
        if left["problem_fingerprint"] != right["problem_fingerprint"]:
            raise ValueError("confirmation domains differ")
        gain = right["ub"] - left["ub"]

        def gap(r):
            return max(0, r["ub"] - r["comparable_lb"]) / max(1, abs(r["ub"]))

        gap_gain = gap(right) - gap(left)
        passes = gain >= 0 and (
            (gain > 0 and gain >= (0.001 * right["ub"] if case == "R" else 10))
            or gap_gain >= 0.01
        )
        comparisons.append(
            dict(seed=seed, ub_gain=gain, gap_gain=gap_gain, passes=passes)
        )
    return {
        "status": "confirmed"
        if all(c["passes"] for c in comparisons)
        else "inconclusive",
        "comparisons": comparisons,
    }


def evaluate(results, winners):
    def trials(key):
        spec = winners.get(key)
        return (
            []
            if spec is None
            else [
                r
                for r in results
                if r["spec"]["phase"] == "confirm"
                and all(
                    r["spec"][k] == spec[k] for k in ("case", "backend", "formulation")
                )
            ]
        )

    return {
        "R_cp_sat_over_ibm": confirmation_verdict(
            trials("R_cp_sat"), trials("R_ibm"), "R"
        ),
        "R_ibm_over_cp_sat": confirmation_verdict(
            trials("R_ibm"), trials("R_cp_sat"), "R"
        ),
        "C_new_over_legacy": confirmation_verdict(
            trials("C_cp_sat_new"), trials("C_cp_sat"), "C"
        ),
    }


def campaign(out, wall_seconds, wait_for_pids=()):
    out.mkdir(parents=True, exist_ok=False)
    # A prerequisite campaign owns the machine until its supervisor exits.
    # Queue time is recorded separately; no solver/model builds run while queued.
    queued = time.monotonic()
    while True:
        alive = []
        for pid in wait_for_pids:
            try:
                os.kill(pid, 0)
            except ProcessLookupError:
                continue
            alive.append(pid)
        if not alive:
            break
        dump(
            out / "status.json",
            dict(state="queued", waiting_for_pids=alive, at=stamp()),
        )
        time.sleep(5)
    queue_seconds = time.monotonic() - queued
    started = time.monotonic()
    deadline = started + wall_seconds
    inputs = out / "inputs"
    inputs.mkdir()
    for name, source in [
        (
            "R_seed.json",
            "ddd_reservoir_cp_sat/waiting_max50_8h_12workers_20260910/validated_seed.json",
        ),
        ("C_seed.json", "fixed_start_capacity_20260910/k39_waiting_n3074/seed.json"),
    ]:
        shutil.copy2(ROOT / "benchmarks/output" / source, inputs / name)
    files = (
        sorted((ROOT / "src").rglob("*.py"))
        + sorted((ROOT / "benchmarks").glob("*.py"))
        + [ROOT / "pyproject.toml", ROOT / "uv.lock"]
    )
    hashes = {
        str(p.relative_to(ROOT)): hashlib.sha256(p.read_bytes()).hexdigest()
        for p in files
    }
    dump(out / "source_hashes.json", hashes)
    with tarfile.open(out / "source_snapshot.tar.gz", "w:gz") as tar:
        for p in files:
            tar.add(p, arcname=str(p.relative_to(ROOT)))
    dump(
        out / "launch.json",
        dict(
            started=stamp(),
            queue_seconds=queue_seconds,
            pid=os.getpid(),
            wall_seconds=wall_seconds,
            engine=str(ENGINE),
            engine_sha256=hashlib.sha256(ENGINE.read_bytes()).hexdigest(),
            input_hashes={
                p.name: hashlib.sha256(p.read_bytes()).hexdigest()
                for p in inputs.iterdir()
            },
            screening=specs(),
        ),
    )
    results = []
    failures = []
    index = 0

    def run(base, seconds, seed, phase):
        nonlocal index
        if deadline - time.monotonic() < seconds + 45:
            return None
        for path, digest in hashes.items():
            if hashlib.sha256((ROOT / path).read_bytes()).hexdigest() != digest:
                raise RuntimeError("Source changed during frozen campaign: " + path)
        index += 1
        name = f"{index:02d}_{phase}_{base['case']}_{base['backend']}_{base['formulation']['profile']}_{base['formulation']['resource_encoding']}_{base['formulation']['movement_encoding']}_s{seed}"
        spec = {
            **base,
            "seconds": seconds,
            "seed": seed,
            "output": str(out / name),
            "inputs": str(inputs),
            "engine": str(ENGINE),
            "phase": phase,
        }
        path = out / (name + ".spec.json")
        dump(path, spec)
        dump(
            out / "status.json",
            dict(
                state="running",
                trial=name,
                completed=len(results),
                failures=failures,
                at=stamp(),
            ),
        )
        with (out / (name + ".terminal.log")).open("w") as log:
            child = subprocess.Popen(
                [sys.executable, str(Path(__file__).resolve()), "--single", str(path)],
                cwd=ROOT,
                env={**os.environ, "PYTHONPATH": str(ROOT / "src")},
                stdout=log,
                stderr=subprocess.STDOUT,
                start_new_session=True,
            )
            try:
                code = child.wait(
                    timeout=min(seconds + 60, max(1, deadline - time.monotonic() - 10))
                )
            except subprocess.TimeoutExpired:
                os.killpg(child.pid, signal.SIGTERM)
                try:
                    child.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    os.killpg(child.pid, signal.SIGKILL)
                    child.wait()
                code = -1
        summary = Path(spec["output"]) / "summary.json"
        if code or not summary.exists():
            failures.append(dict(trial=name, exit_code=code))
            dump(out / "failures.json", failures)
            return None
        r = json.loads(summary.read_text())
        same_case = [v for v in results if v["spec"]["case"] == r["spec"]["case"]]
        if any(
            v["problem_fingerprint"] != r["problem_fingerprint"]
            or v["seed_cost"] != r["seed_cost"]
            for v in same_case
        ):
            raise ValueError("campaign domain or seed changed")
        results.append(r)
        dump(out / "results.json", results)
        return r

    try:
        for s in specs():
            run(s, 180, 0, "screen")
        winners = {}
        for case, backend, new in [
            ("R", "cp_sat", False),
            ("R", "ibm", False),
            ("C", "cp_sat", True),
            ("C", "cp_sat", False),
        ]:
            key = f"{case}_{backend}" + ("_new" if new else "")
            candidates = [
                r
                for r in results
                if r["spec"]["case"] == case
                and r["spec"]["backend"] == backend
                and (r["spec"]["formulation"]["profile"] != "legacy" if new else True)
            ]
            if case == "C" and not new:
                candidates = [
                    r
                    for r in candidates
                    if r["spec"]["formulation"]["profile"] == "legacy"
                ]
            if candidates:
                winners[key] = min(candidates, key=rank)["spec"]
        dump(out / "selected.json", winners)
        for seed in [1, 2]:
            for key in ["R_cp_sat", "R_ibm", "C_cp_sat_new", "C_cp_sat"]:
                if key in winners:
                    run(
                        {
                            k: winners[key][k]
                            for k in ["case", "backend", "formulation"]
                        },
                        300,
                        seed,
                        "confirm",
                    )
        verdicts = evaluate(results, winners)
        dump(out / "evaluation.json", verdicts)
        rows = [
            "# CP formulation campaign",
            "",
            f"Completed {stamp()}. {len(results)} valid trials, {len(failures)} failed trials.",
            "",
            "| Phase | Case | Backend | Profile / encoding | Seed | UB | Comparable LB | Seconds |",
            "|---|---|---|---|---:|---:|---:|---:|",
        ]
        for r in results:
            s = r["spec"]
            f = s["formulation"]
            rows.append(
                f"| {s['phase']} | {s['case']} | {s['backend']} | {f['profile']} / {f['resource_encoding']} / {f['movement_encoding']} | {s['seed']} | {r['ub']:.6f} | {r['comparable_lb']:.6f} | {r['seconds']:.2f} |"
            )
        rows += [
            "",
            "R is journey time in passenger-seconds; C is unserved persons. These are different domains/objectives. Comparable R bounds include the same analytical floor for every profile. No default profile is changed. Failed or incomplete trials are not evidence of an optimum.",
        ]
        rows += ["", "Confirmation (both additional seeds required):", ""]
        rows += [f"- {key}: {value['status']}." for key, value in verdicts.items()]
        (out / "comparison.md").write_text("\n".join(rows) + "\n")
        dump(
            out / "status.json",
            dict(
                state="completed" if len(results) == 24 else "incomplete",
                completed=len(results),
                failures=failures,
                seconds=time.monotonic() - started,
                at=stamp(),
            ),
        )
    except Exception as e:
        dump(out / "status.json", dict(state="error", error=str(e), at=stamp()))
        raise


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--single", type=Path)
    p.add_argument("--output-dir", type=Path)
    p.add_argument("--wall-seconds", type=float, default=7200)
    p.add_argument("--wait-for-pid", type=int, action="append", default=[])
    a = p.parse_args()
    if a.single:
        single(json.loads(a.single.read_text()))
    else:
        if a.output_dir is None:
            p.error("--output-dir required")
        campaign(a.output_dir.resolve(), min(a.wall_seconds, 7200), a.wait_for_pid)


if __name__ == "__main__":
    main()
