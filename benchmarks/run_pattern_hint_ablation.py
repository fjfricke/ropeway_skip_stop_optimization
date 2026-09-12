"""Paired time-hint ablation on the two historical K39 patterns."""

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
import traceback

from run_pattern_oracle_diagnostic import prepare
from ropeway_skip_stop_optimization.benchmarking.pattern_search import (
    independent_assignment,
)
from ropeway_skip_stop_optimization.optimization.ddd.cp_sat_certificate import (
    atomic_json,
    read_ddd_cp_sat_checkpoint,
    write_ddd_cp_sat_checkpoint,
    validate_ddd_cp_sat_domain,
    solution_from_cp_sat_payload,
)
from ropeway_skip_stop_optimization.optimization.ddd.pattern_search import StopPattern
from ropeway_skip_stop_optimization.optimization.ddd.pattern_oracle_probe import (
    FixedPatternCpSatProbe,
    PatternProbeConfig,
)

ROOT = Path(__file__).resolve().parents[1]


def report(out, doc=None):
    manifest = json.loads((out / "experiment.json").read_text())
    rows = []
    for job in manifest["jobs"]:
        folder = out / "runs" / job["name"]
        result = (
            json.loads((folder / "result.json").read_text())
            if (folder / "result.json").exists()
            else None
        )
        completion = (
            json.loads((folder / "completion.json").read_text())
            if (folder / "completion.json").exists()
            else None
        )
        rows.append(dict(**job, result=result, completion=completion))
    checks = []
    for pattern in ("variant1", "variant2"):
        for seed in (0, 1):
            pair = [
                r
                for r in rows
                if r["pattern"] == pattern and r["seed"] == seed and r["result"]
            ]
            if len(pair) == 2:
                a, b = [r["result"] for r in pair]
                equal = (
                    a["model_fingerprint"] == b["model_fingerprint"]
                    and a["pattern_id"] == b["pattern_id"]
                    and a["domain_manifest"] == b["domain_manifest"]
                )
                if not equal:
                    raise RuntimeError("paired models differ beyond hints")
                checks.append(dict(pattern=pattern, seed=seed, identical_model=True))
    lines = [
        "# K39: isolierter Vergleich von Zeit-Hints",
        "",
        "Zwei historische Muster × mit/ohne Zeit-Hints × Solver-Seeds 0/1. Jeweils 300 s einschließlich Aufbau, zwölf Worker, sequenziell. Bei Seed 1 ist die Methodenreihenfolge umgekehrt. Startwerte sind keine fixierten Zeiten; keine Ausgangslösung oder Objective-Schranke wird übernommen.",
        "",
        "| Muster | Seed | Zeit-Hint | Status | Unbedient | lokales LB | Erste native Lösung s | Gesamt s |",
        "|---|---:|---|---|---:|---:|---:|---:|",
    ]

    def fmt(x):
        return "—" if x is None else f"{x:.2f}" if isinstance(x, float) else str(x)

    for row in rows:
        r = row["result"]
        c = row["completion"]
        state = (
            r["status"]
            if r
            else c["status"]
            if c
            else "RUNNING"
            if (out / "runs" / row["name"] / "config.json").exists()
            else "PENDING"
        )
        fields = [row["pattern"], row["seed"], row["mode"], state] + [
            fmt(r.get(k)) if r else "—"
            for k in (
                "pattern_upper_bound",
                "pattern_lower_bound",
                "first_native_feasible_seconds",
                "total_seconds",
            )
        ]
        lines.append("| " + " | ".join(map(str, fields)) + " |")
    lines += [
        "",
        f"Abgeschlossene, auf identische Modellstruktur geprüfte Paare: {len(checks)}/4. Alle Bounds sind nur musterbezogen.",
        "",
        "Die Zeit-Hints stammen unverändert aus dem gespeicherten K39-Screening-Endfahrplan (U=1418). Beim damaligen Screening blieb dieser aktuelle Fahrplan vor beiden erfolgreichen Musteränderungen erhalten: Die geänderten Muster mit U=1426 wurden nicht als aktueller Zustand akzeptiert. Damit sind dies die früher verwendeten Zeitwerte.",
        "",
        "Für jedes Paar wird der Modell-Fingerprint nach Entfernen der Hint-Felder verglichen. Vollständige Domain-Manifeste und Muster-IDs müssen ebenfalls übereinstimmen. Jede Bestlösung je Musterlauf wird als vollständiges Zertifikat gespeichert; sämtliche vom Solver zurückgegebenen zulässigen Lösungen zusätzlich unter `certificates/`. Die Endzuordnung wird unabhängig mit EAN/Gurobi geprüft.",
        "",
        "Zwei Seeds liefern eine begrenzte Wiederholung, keinen statistisch abgesicherten allgemeinen Effekt. Die parallele CP-SAT-Suche ist nicht deterministisch. Die abgeschlossenen früheren 300-s-Läufe ohne Hints werden nicht anstelle neuer Kontrollläufe verwendet.",
        "",
        f"Ergebnisordner: `{out}`. `experiment.json`, `patterns.json`, `time_hint.json`, `source.tar.gz`, `source_manifest.json`; je Lauf Konfiguration, Domain, Events, Solverlog, Ergebnis, Checkpoint und vollständige Zertifikate.",
    ]
    text = "\n".join(lines) + "\n"
    (out / "comparison.md").write_text(text)
    if doc:
        doc.write_text(text)
    atomic_json(out / "summary.json", dict(rows=rows, model_identity_checks=checks))


def worker(args):
    out = args.output_dir
    name = f"{args.pattern}_{args.mode}_seed{args.seed}"
    folder = out / "runs" / name
    folder.mkdir(parents=True, exist_ok=False)
    prepared, problem = prepare(39)
    domain = validate_ddd_cp_sat_domain(problem)
    data = json.loads((out / "patterns.json").read_text())["39"][args.pattern]
    pattern = StopPattern(data["domain_id"], tuple(tuple(x) for x in data["choices"]))
    hint = read_ddd_cp_sat_checkpoint(
        out / "time_hint.json", problem=problem, manifest=domain
    )
    if pattern.matches(hint.solution):
        raise ValueError("ablation expects a different-pattern hint")
    atomic_json(
        folder / "config.json",
        dict(
            pattern=args.pattern,
            mode=args.mode,
            seed=args.seed,
            workers=12,
            seconds=300,
            hint_sha256=hashlib.sha256(
                (out / "time_hint.json").read_bytes()
            ).hexdigest(),
            started_utc=datetime.now(timezone.utc).isoformat(),
        ),
    )
    atomic_json(folder / "domain.json", domain)
    (folder / "certificates").mkdir()
    count = 0
    with (
        (folder / "events.jsonl").open("w") as events,
        (folder / "solver.log").open("w") as log,
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
                manifest=domain,
                incumbent=inc,
            )

        def certificate(inc):
            nonlocal count
            count += 1
            write_ddd_cp_sat_checkpoint(
                folder / "certificates" / f"{count:04d}.json",
                problem=problem,
                manifest=domain,
                incumbent=inc,
            )

        try:
            result = FixedPatternCpSatProbe(
                PatternProbeConfig(seconds=300, workers=12, seed=args.seed)
            ).solve(
                problem,
                pattern,
                time_hint=hint if args.mode == "time_hint" else None,
                event_callback=event,
                log_callback=line,
                checkpoint=checkpoint,
                certificate_callback=certificate,
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
                    raise RuntimeError("independent check failed")
            atomic_json(
                folder / "completion.json", dict(status="complete", certificates=count)
            )
        except Exception:
            atomic_json(
                folder / "completion.json",
                dict(status="failed", error=traceback.format_exc()),
            )
            raise


def campaign(args):
    out = args.output_dir
    out.mkdir(parents=True, exist_ok=False)
    runtime = out / "runtime"
    runtime.mkdir()
    source = ROOT / "benchmarks/output/pattern_oracle_diagnostic_20260910/source.tar.gz"
    with tarfile.open(source) as tar:
        tar.extractall(runtime, filter="data")
    for name in [
        "src/ropeway_skip_stop_optimization/optimization/ddd/pattern_oracle_probe.py",
        "benchmarks/run_pattern_hint_ablation.py",
        "tests/test_ddd_pattern_oracle_probe.py",
    ]:
        shutil.copy2(ROOT / name, runtime / name)
    files = sorted(p for p in runtime.rglob("*") if p.is_file())
    atomic_json(
        out / "source_manifest.json",
        {
            str(p.relative_to(runtime)): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in files
        },
    )
    with tarfile.open(out / "source.tar.gz", "w:gz") as tar:
        for p in files:
            tar.add(p, arcname=str(p.relative_to(runtime)))
    shutil.copy2(
        ROOT / "benchmarks/output/pattern_oracle_diagnostic_20260910/patterns.json",
        out / "patterns.json",
    )
    shutil.copy2(
        ROOT
        / "benchmarks/output/pattern_search_20260910_v2/screen/k39_vns_seed0/incumbent.json",
        out / "time_hint.json",
    )
    jobs = [
        dict(pattern=p, seed=seed, mode=mode, name=f"{p}_{mode}_seed{seed}")
        for seed in (0, 1)
        for p in ("variant1", "variant2")
        for mode in (("time_hint", "none") if seed == 0 else ("none", "time_hint"))
    ]
    atomic_json(
        out / "experiment.json",
        dict(
            jobs=jobs,
            seconds=300,
            workers=12,
            objective="unserved",
            proof_scope="FIXED_PATTERN",
        ),
    )
    (out / "runs").mkdir()
    report(out, args.report_md)
    failures = []
    for job in jobs:
        print("START", job["name"], flush=True)
        command = [
            sys.executable,
            str(runtime / "benchmarks/run_pattern_hint_ablation.py"),
            "--stage",
            "worker",
            "--output-dir",
            str(out),
            "--pattern",
            job["pattern"],
            "--mode",
            job["mode"],
            "--seed",
            str(job["seed"]),
        ]
        p = subprocess.run(
            command, cwd=runtime, env={**os.environ, "PYTHONPATH": str(runtime / "src")}
        )
        if p.returncode:
            failures.append(job)
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
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--stage", choices=["campaign", "worker", "report"], default="campaign"
    )
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--report-md", type=Path)
    parser.add_argument(
        "--pattern", choices=["variant1", "variant2"], default="variant1"
    )
    parser.add_argument("--mode", choices=["none", "time_hint"], default="time_hint")
    parser.add_argument("--seed", type=int, default=0)
    args = parser.parse_args()
    args.output_dir = args.output_dir.resolve()
    if args.report_md:
        args.report_md = args.report_md.resolve()
    if args.stage == "campaign":
        campaign(args)
    elif args.stage == "worker":
        worker(args)
    else:
        report(args.output_dir, args.report_md)


if __name__ == "__main__":
    main()
