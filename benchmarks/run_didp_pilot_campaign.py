"""Sequential, cold CABS/CP-SAT campaign with a hard 30-minute envelope."""

import argparse
import hashlib
import importlib.metadata
import json
from pathlib import Path
import pickle
import shutil
import subprocess
import sys
from time import perf_counter

from ropeway_skip_stop_optimization.benchmarking.ddd_fixed_k_didp import (
    prepare_small,
    prepare_large,
)
from ropeway_skip_stop_optimization.optimization.ddd.didp.optimizer import (
    DddDidpConfig,
    DddDidpOptimizer,
    supervise,
)
from ropeway_skip_stop_optimization.optimization.ddd.cp_sat_certificate import (
    atomic_json,
    read_ddd_cp_sat_checkpoint,
    validate_ddd_cp_sat_domain,
)

ROOT = Path(__file__).resolve().parents[1]
REFERENCES = {
    38: ROOT
    / "benchmarks/output/pattern_search_20260910/seeds/k38_waiting_n3074/incumbent.json",
    39: ROOT / "benchmarks/output/pattern_search_followup_20260910/run/incumbent.json",
}


def _cp_local(problem, seconds, threads, seed, folder, emit):
    from ropeway_skip_stop_optimization.optimization.ddd.cp_sat_capacity import (
        DddCpSatCapacityOptimizer,
    )
    from ropeway_skip_stop_optimization.optimization.ddd.cp_sat_integrated import (
        DddIntegratedCpSatConfig,
    )

    result = DddCpSatCapacityOptimizer(
        DddIntegratedCpSatConfig(
            total_time_limit_seconds=seconds,
            num_workers=threads,
            seed=seed,
            checkpoint_path=folder / "incumbent.json",
            checkpoint_interval_seconds=1,
        )
    ).solve(problem, event_callback=emit)
    result.update(
        native_incumbent=result.get("incumbent"),
        native_unserved=result.get("unserved_upper_bound"),
    )
    return result


def sources():
    paths = [
        *ROOT.glob("src/**/*.py"),
        *ROOT.glob("benchmarks/*.py"),
        ROOT / "pyproject.toml",
        ROOT / "uv.lock",
        ROOT / "tests/test_ddd_didp.py",
    ]
    return {
        str(p.relative_to(ROOT)): hashlib.sha256(p.read_bytes()).hexdigest()
        for p in sorted(paths)
    }


def main():
    parser = argparse.ArgumentParser(allow_abbrev=False)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    output = args.output_dir.resolve()
    output.mkdir(parents=True, exist_ok=False)
    for path in REFERENCES.values():
        if not path.is_file():
            raise FileNotFoundError(f"Required historical replay: {path}")
    preflight_started = perf_counter()
    check = subprocess.run(
        [
            sys.executable,
            "-m",
            "pytest",
            "-q",
            "tests/test_ddd_didp.py",
            "tests/test_optimization_ddd_cp_sat_passenger.py",
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
    )
    (output / "correctness.txt").write_text(check.stdout + check.stderr)
    atomic_json(
        output / "correctness.json",
        dict(
            passed=check.returncode == 0,
            seconds=perf_counter() - preflight_started,
            returncode=check.returncode,
        ),
    )
    if check.returncode:
        raise RuntimeError("Correctness gate failed; no performance jobs started")
    started = perf_counter()
    deadline = started + 1800
    frozen = output / "frozen"
    frozen.mkdir()
    source_hashes = sources()
    for relative in source_hashes:
        destination = frozen / "sources" / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(ROOT / relative, destination)
    atomic_json(frozen / "sources.json", source_hashes)
    atomic_json(
        frozen / "versions.json",
        dict(
            python=sys.version,
            executable=sys.executable,
            didppy=importlib.metadata.version("didppy"),
            ortools=importlib.metadata.version("ortools"),
            cabs=dict(initial_beam_size=1, max_beam_size=None, keep_all_layers=True),
            memory_limit_gib=8,
            historical_warmstart=False,
            cp_formulation="legacy",
        ),
    )
    cases = {}
    references = {}
    for k in (2, 4):
        for waiting in (False, True):
            name = f"k{k}_" + ("waiting" if waiting else "no_wait")
            _, problem = prepare_small(k, waiting=2 if waiting else 0)
            cases[name] = problem
    for k in (38, 39):
        _, problem = prepare_large(k)
        name = f"k{k}_waiting"
        cases[name] = problem
        reference = read_ddd_cp_sat_checkpoint(
            REFERENCES[k], problem=problem, manifest=validate_ddd_cp_sat_domain(problem)
        )
        references[name] = sum(reference.unserved_counts.values())
        if references[name] != {38: 315, 39: 1402}[k]:
            raise ValueError("Historical reference changed")
        shutil.copy2(REFERENCES[k], frozen / f"{name}_reference.json")
    for name, problem in cases.items():
        (frozen / f"{name}.pickle").write_bytes(pickle.dumps(problem))
        atomic_json(frozen / f"{name}.json", validate_ddd_cp_sat_domain(problem))
    jobs = []
    for k in (2, 4):
        for waiting in ("no_wait", "waiting"):
            for solver in ("didp", "cp_sat"):
                jobs.append((f"k{k}_{waiting}", solver, 60, 1, 0))
    for k in (38, 39):
        for solver in ("didp", "cp_sat"):
            jobs.append((f"k{k}_waiting", solver, 180, 12, 0))
    for solver in ("cp_sat", "didp"):
        jobs.append(("k39_waiting", solver, 180, 12, 1))
    records = []
    for case, solver, budget, threads, repeat in jobs:
        name = f"{case}_{solver}_repeat{repeat}"
        if perf_counter() + budget + 2 > deadline:
            records.append(dict(name=name, skipped="remaining campaign budget"))
            continue
        if threads == 12 and not any(
            r.get("solver") == "didp"
            and r.get("case", "").endswith("waiting")
            and r.get("threads") == 1
            and r.get("native_unserved") is not None
            for r in records
        ):
            records.append(
                dict(name=name, skipped="No native complete small Waiting plan")
            )
            continue
        if sources() != source_hashes:
            raise RuntimeError("Sources changed during the frozen campaign")
        folder = output / name
        folder.mkdir()
        problem = cases[case]
        atomic_json(
            folder / "config.json",
            dict(
                case=case,
                solver=solver,
                seconds=budget,
                threads=threads,
                seed=repeat if solver == "cp_sat" else None,
                repeat=repeat,
                hints=False,
                objective_cutoff=False,
            ),
        )
        print("START", name, flush=True)

        def event(item):
            with (folder / "events.jsonl").open("a") as stream:
                stream.write(json.dumps(item) + "\n")

        trial_start = perf_counter()
        if solver == "didp":
            result = DddDidpOptimizer(DddDidpConfig(budget, threads, 8, folder)).solve(
                problem, event_callback=event
            )
        else:
            result = supervise(
                _cp_local,
                (problem, budget, threads, repeat, folder),
                seconds=budget,
                memory_gib=8,
                event_callback=event,
            )
            if (folder / "incumbent.json").exists():
                checked = read_ddd_cp_sat_checkpoint(
                    folder / "incumbent.json",
                    problem=problem,
                    manifest=validate_ddd_cp_sat_domain(problem),
                )
                result.update(
                    native_incumbent=checked.to_payload(),
                    native_unserved=sum(checked.unserved_counts.values()),
                )
        result.update(
            case=case,
            solver=solver,
            threads=threads,
            repeat=repeat,
            reference_unserved=references.get(case),
            total_seconds=perf_counter() - trial_start,
        )
        atomic_json(folder / "result.json", result)
        record = {
            key: result.get(key)
            for key in (
                "case",
                "solver",
                "threads",
                "repeat",
                "solver_status",
                "native_unserved",
                "unserved_lower_bound",
                "reference_unserved",
                "total_seconds",
                "peak_rss_bytes",
                "model_stats",
                "build_seconds",
                "generated",
                "expanded",
            )
        }
        record["name"] = name
        records.append(record)
        atomic_json(
            output / "summary.json",
            dict(
                records=records,
                elapsed_seconds=perf_counter() - started,
                hard_budget_seconds=1800,
                source_hashes=str(frozen / "sources.json"),
            ),
        )
        print("DONE", json.dumps(record), flush=True)
    atomic_json(
        output / "summary.json",
        dict(
            records=records,
            elapsed_seconds=perf_counter() - started,
            hard_budget_seconds=1800,
            complete=True,
            source_hashes=str(frozen / "sources.json"),
        ),
    )


if __name__ == "__main__":
    main()
