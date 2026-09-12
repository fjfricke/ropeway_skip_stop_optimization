"""Freeze six historical patterns and compare continuous 300s CP/MIP probes."""

import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tarfile
from time import perf_counter
import traceback

from ropeway_skip_stop_optimization.benchmarking.ddd_fixed_k_arc_flow import (
    DddFixedKArcFlowRunConfig,
    prepare_ddd_fixed_k_arc_flow_run,
)
from ropeway_skip_stop_optimization.benchmarking.ddd_cp_sat_waiting import (
    with_exit_waiting,
)
from ropeway_skip_stop_optimization.benchmarking.pattern_search import (
    EXAMPLE,
    independent_assignment,
)
from ropeway_skip_stop_optimization.optimization.ddd.fixed_k import (
    DddFixedKOperatingMode,
    DddFixedKStartPolicy,
)
from ropeway_skip_stop_optimization.optimization.ddd.fixed_timetable_capacity import (
    NestedDemand,
)
from ropeway_skip_stop_optimization.optimization.ddd.cp_sat_certificate import (
    atomic_json,
    read_ddd_cp_sat_checkpoint,
    write_ddd_cp_sat_checkpoint,
    validate_ddd_cp_sat_domain,
    solution_from_cp_sat_payload,
)
from ropeway_skip_stop_optimization.optimization.ddd.pattern_search import (
    StopPattern,
    PatternTimingOracle,
)
from ropeway_skip_stop_optimization.optimization.ddd.pattern_oracle_probe import (
    FixedPatternCpSatProbe,
    PatternProbeConfig,
)
from ropeway_skip_stop_optimization.optimization.ddd.pattern_mip import (
    FixedPatternMipProbe,
)

ROOT = Path(__file__).resolve().parents[1]


def prepare(k):
    prepared = prepare_ddd_fixed_k_arc_flow_run(
        DddFixedKArcFlowRunConfig(
            EXAMPLE,
            k,
            DddFixedKOperatingMode.SKIP_STOP,
            start_policy=DddFixedKStartPolicy.BALANCED_REFERENCE,
            cp_seed_time_limit_seconds=0,
        )
    )
    prepared = with_exit_waiting(prepared, maximum_seconds=1200, step_seconds=1e-6)
    return prepared, NestedDemand(prepared.problem.passenger_build.demand_groups).apply(
        prepared.problem, 3074
    )


def worker(args):
    folder = args.output_dir / "runs" / f"k{args.cabins}_{args.pattern}_{args.backend}"
    folder.mkdir(parents=True, exist_ok=False)
    before = perf_counter()
    prepared, problem = prepare(args.cabins)
    manifest = validate_ddd_cp_sat_domain(problem)
    data = json.loads((args.output_dir / "patterns.json").read_text())[
        str(args.cabins)
    ][args.pattern]
    pattern = StopPattern(data["domain_id"], tuple(tuple(x) for x in data["choices"]))
    seed = read_ddd_cp_sat_checkpoint(
        args.output_dir / f"seeds/k{args.cabins}.json",
        problem=problem,
        manifest=manifest,
    )
    atomic_json(
        folder / "config.json",
        dict(
            cabins=args.cabins,
            pattern=args.pattern,
            pattern_id=pattern.id,
            backend=args.backend,
            seconds=args.seconds,
            workers=args.workers,
            seed=0,
            started_utc=datetime.now(timezone.utc).isoformat(),
            preparation_seconds=perf_counter() - before,
            matching_seed=pattern.matches(seed.solution),
            historical=data["historical"],
        ),
    )
    atomic_json(folder / "domain.json", manifest)
    with (
        (folder / "events.jsonl").open("w") as events,
        (folder / "cp_solver.log").open("w") as log,
    ):

        def event(e):
            events.write(json.dumps(e) + "\n")
            events.flush()

        def line(s):
            log.write(s if s.endswith("\n") else s + "\n")
            log.flush()

        def checkpoint(inc):
            write_ddd_cp_sat_checkpoint(
                folder / "incumbent.json",
                problem=problem,
                manifest=manifest,
                incumbent=inc,
            )

        try:
            config = PatternProbeConfig(seconds=args.seconds, workers=args.workers)
            if args.backend == "cp_sat":
                result = FixedPatternCpSatProbe(config).solve(
                    problem,
                    pattern,
                    seed=seed,
                    event_callback=event,
                    log_callback=line,
                    checkpoint=checkpoint,
                )
            else:
                result = FixedPatternMipProbe(config).solve(
                    problem,
                    pattern,
                    seed=seed,
                    event_callback=event,
                    log_file=folder / "gurobi.log",
                    checkpoint=checkpoint,
                )
            atomic_json(folder / "result.json", result)
            if result["incumbent"]:
                post = independent_assignment(
                    problem,
                    prepared.scenario,
                    solution_from_cp_sat_payload(problem, result["incumbent"]),
                )
                atomic_json(folder / "independent_assignment.json", post)
                if (
                    post.get("unserved_upper_bound", float("inf"))
                    > result["pattern_upper_bound"]
                ):
                    raise RuntimeError(
                        "independent assignment failed to confirm service"
                    )
            atomic_json(
                folder / "completion.json",
                dict(status="complete", wall_seconds=perf_counter() - before),
            )
        except Exception:
            atomic_json(
                folder / "completion.json",
                dict(
                    status="failed",
                    error=traceback.format_exc(),
                    wall_seconds=perf_counter() - before,
                ),
            )
            raise


def report(output, report_md=None):
    rows = []
    for f in sorted((output / "runs").glob("*")):
        c = (
            json.loads((f / "config.json").read_text())
            if (f / "config.json").exists()
            else {}
        )
        if not c:
            continue
        r = (
            json.loads((f / "result.json").read_text())
            if (f / "result.json").exists()
            else None
        )
        done = (
            json.loads((f / "completion.json").read_text())
            if (f / "completion.json").exists()
            else None
        )
        rows.append(dict(config=c, result=r, completion=done))
    lines = [
        "# Diagnose: festes Muster, freies Timing",
        "",
        "Sechs eingefrorene Muster, zwei Solver, jeweils ein zusammenhängender Lauf bis 300 s einschließlich Modellbau. Zeiten und Warten bleiben auf demselben 1-µs-Gitter; Ziel ist die Zahl unbedienter Personen. Alle Bounds gelten ausschließlich für das jeweilige Muster.",
        "",
        "| K | Muster | Solver | Status | U | lokales LB | Bau s | Erste native Lösung s | Gesamt s |",
        "|---|---|---|---|---:|---:|---:|---:|---:|",
    ]

    def fmt(v):
        return "—" if v is None else f"{v:.2f}" if isinstance(v, float) else str(v)

    summaries = []
    for row in rows:
        c, r, done = row["config"], row["result"], row["completion"]
        state = "RUNNING" if done is None else done["status"]
        if r:
            state = r["status"]
        lines.append(
            "| "
            + " | ".join(
                map(
                    str,
                    [
                        c["cabins"],
                        c["pattern"],
                        c["backend"],
                        state,
                        fmt(r.get("pattern_upper_bound")) if r else "—",
                        fmt(r.get("pattern_lower_bound")) if r else "—",
                        fmt(r.get("build_seconds")) if r else "—",
                        fmt(r.get("first_native_feasible_seconds")) if r else "—",
                        fmt(r.get("total_seconds")) if r else "—",
                    ],
                )
            )
            + " |"
        )
        if not r:
            continue
        milestones = []
        for t in (5, 30, 60, 300):
            seen = [e for e in r["events"] if e["elapsed_seconds"] <= t]
            us = [
                e["unserved"]
                for e in seen
                if e["kind"] in ("initial", "solver_incumbent")
            ]
            lbs = [
                e["lower_bound"]
                for e in seen
                if e["kind"] == "bound" and e["lower_bound"] is not None
            ]
            upper = min(us, default=None)
            lower = max(lbs, default=None)
            if r["total_seconds"] <= t:
                upper = r["pattern_upper_bound"]
                lower = r["pattern_lower_bound"]
            milestones.append(dict(seconds=t, upper=upper, lower=lower))
        summaries.append(
            dict(
                cabins=c["cabins"],
                pattern=c["pattern"],
                backend=c["backend"],
                milestones=milestones,
            )
        )
    lines += [
        "",
        "## Messpunkte im selben Lauf",
        "",
        "| K / Muster / Solver | 5 s U / LB | 30 s U / LB | 60 s U / LB | 300 s U / LB |",
        "|---|---:|---:|---:|---:|",
    ]
    for s in summaries:
        lines.append(
            "| "
            + f"{s['cabins']} / {s['pattern']} / {s['backend']}"
            + " | "
            + " | ".join(
                f"{fmt(m['upper'])} / {fmt(m['lower'])}" for m in s["milestones"]
            )
            + " |"
        )
    lines += [
        "",
        "Eine Startlösung zählt ab ihrer Prüfung als bekanntes U. „Erste native Lösung“ misst separat, wann der Solver selbst ein validiertes Ergebnis liefert. Bei geänderten Mustern wird ein nicht passender Ausgangsfahrplan weder als Lösung noch als Zielfunktionsschranke übernommen. Beide Solver bekommen bei passenden Mustern auch die deterministisch abgeleiteten Hilfsvariablen als Startwerte.",
        "",
        "CP-SAT verwendet die bisherige physikalische Formulierung mit fixierten Routen. Gurobi baut nur die gewählten Routen, ganzzahlige Ereigniszeiten/Wartezeiten und optionale paarweise Ressourcenreihenfolgen auf. Unmögliche Besuche werden anhand frühester Ankunftszeiten entfernt; es wird keine Ressourcenreihenfolge aus dem Seed fixiert. Der Vergleich betrifft somit zwei Formulierungen desselben Teilproblems, nicht ausschließlich den Solverwechsel.",
        "",
        "Vorgegebene Muster: Originale aus den gemeinsamen Kampagnenseeds; K38 eine UNKNOWN- und eine INFEASIBLE-Änderung aus dem Screening; K39 die zwei damals FEASIBLE-Änderungen. Auswahl vor dem Vergleich eingefroren, kein nachträgliches Aussuchen guter Resultate.",
        "",
        f"Ergebnisse: `{output}`. Pro Lauf: Domain, Konfiguration, Ereignisse, native Logs, Checkpoint, Ergebnis und unabhängige EAN/Gurobi-Passagierprüfung. `summary.json` enthält die Messpunkte und Rohresultate. `patterns.json` enthält die exakten Muster.",
        "",
        "Code: `optimization/ddd/pattern_oracle_probe.py`, `optimization/ddd/pattern_mip.py`, `benchmarks/run_pattern_oracle_diagnostic.py`. Der vorherige VNS-Lauf ist pausiert; dessen Ergebnisse sind unter `pattern_search_20260910_v2` erhalten.",
    ]
    text = "\n".join(lines) + "\n"
    (output / "comparison.md").write_text(text)
    if report_md:
        report_md.write_text(text)
    atomic_json(output / "summary.json", dict(rows=rows, milestones=summaries))


def campaign(args):
    out = args.output_dir
    out.mkdir(parents=True, exist_ok=False)
    runtime = out / "runtime"
    runtime.mkdir()
    archive = args.source_campaign / "source.tar.gz"
    with tarfile.open(archive) as t:
        t.extractall(runtime, filter="data")
    overlay = [
        "src/ropeway_skip_stop_optimization/optimization/ddd/pattern_oracle_probe.py",
        "src/ropeway_skip_stop_optimization/optimization/ddd/pattern_mip.py",
        "src/ropeway_skip_stop_optimization/optimization/ddd/cp_hint_completion.py",
        "benchmarks/run_pattern_oracle_diagnostic.py",
        "tests/test_ddd_pattern_oracle_probe.py",
    ]
    for file in overlay:
        shutil.copy2(ROOT / file, runtime / file)
    files = sorted(p for p in runtime.rglob("*") if p.is_file())
    atomic_json(
        out / "source_manifest.json",
        dict(
            base_source_sha256=hashlib.sha256(archive.read_bytes()).hexdigest(),
            files={
                str(p.relative_to(runtime)): hashlib.sha256(p.read_bytes()).hexdigest()
                for p in files
            },
        ),
    )
    with tarfile.open(out / "source.tar.gz", "w:gz") as t:
        for p in files:
            t.add(p, arcname=str(p.relative_to(runtime)))
    (out / "seeds").mkdir()
    patterns = {}
    for k in (38, 39):
        seed_path = args.source_campaign / f"seeds/k{k}_waiting_n3074/incumbent.json"
        shutil.copy2(seed_path, out / f"seeds/k{k}.json")
        _, problem = prepare(k)
        oracle = PatternTimingOracle(problem, workers=1)
        seed = read_ddd_cp_sat_checkpoint(
            seed_path, problem=problem, manifest=oracle.manifest
        )
        original = oracle.pattern_from(seed.solution)

        def payload(p, historical):
            return dict(
                domain_id=p.domain_id,
                choices=p.choices,
                pattern_id=p.id,
                historical=historical,
            )

        patterns[str(k)] = {
            "original": payload(original, dict(status="validated_seed"))
        }
        prior = json.loads(
            (args.source_campaign / f"screen/k{k}_vns_seed0/result.json").read_text()
        )
        seen = set()
        selected = []
        targets = ["UNKNOWN", "INFEASIBLE"] if k == 38 else ["FEASIBLE", "FEASIBLE"]
        for status in targets:
            e = next(
                e
                for e in prior["events"]
                if e.get("evaluation_kind") == "new"
                and e["status"] == status
                and e["pattern_id"] not in seen
            )
            seen.add(e["pattern_id"])
            selected.append(e)
        for i, e in enumerate(selected, 1):
            p = StopPattern(
                original.domain_id,
                tuple(tuple(x) for x in prior["patterns"][e["pattern_id"]]),
            )
            oracle.validate_pattern(p)
            patterns[str(k)][f"variant{i}"] = payload(
                p, dict(status=e["status"], upper=e["pattern_upper_bound"])
            )
    atomic_json(out / "patterns.json", patterns)
    (out / "runs").mkdir()
    failures = []
    for pattern in ("original", "variant1", "variant2"):
        for k in (38, 39):
            for backend in ("cp_sat", "gurobi"):
                print("START", k, pattern, backend, flush=True)
                command = [
                    sys.executable,
                    str(runtime / "benchmarks/run_pattern_oracle_diagnostic.py"),
                    "--stage",
                    "worker",
                    "--output-dir",
                    str(out),
                    "--cabins",
                    str(k),
                    "--pattern",
                    pattern,
                    "--backend",
                    backend,
                    "--seconds",
                    str(args.seconds),
                    "--workers",
                    str(args.workers),
                ]
                proc = subprocess.run(
                    command,
                    cwd=runtime,
                    env={**os.environ, "PYTHONPATH": str(runtime / "src")},
                )
                if proc.returncode:
                    failures.append(
                        dict(
                            cabins=k,
                            pattern=pattern,
                            backend=backend,
                            returncode=proc.returncode,
                        )
                    )
                report(out, args.report_md)
    atomic_json(
        out / "completion.json",
        dict(
            status="complete" if not failures else "completed_with_failures",
            failures=failures,
        ),
    )
    report(out, args.report_md)


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument(
        "--stage", choices=["campaign", "worker", "report"], default="campaign"
    )
    p.add_argument("--output-dir", type=Path, required=True)
    p.add_argument(
        "--source-campaign",
        type=Path,
        default=ROOT / "benchmarks/output/pattern_search_20260910_v2",
    )
    p.add_argument("--cabins", type=int, choices=[38, 39], default=38)
    p.add_argument(
        "--pattern", choices=["original", "variant1", "variant2"], default="original"
    )
    p.add_argument("--backend", choices=["cp_sat", "gurobi"], default="cp_sat")
    p.add_argument("--seconds", type=float, default=300)
    p.add_argument("--workers", type=int, default=12)
    p.add_argument("--report-md", type=Path)
    args = p.parse_args()
    args.output_dir = args.output_dir.resolve()
    if args.report_md:
        args.report_md = args.report_md.resolve()
    if args.stage == "worker":
        worker(args)
    elif args.stage == "report":
        report(args.output_dir, args.report_md)
    else:
        campaign(args)


if __name__ == "__main__":
    main()
