"""Screen fixed patterns, then gate a paired VNS/global CP-SAT campaign."""

import argparse
import os
import hashlib
import io
import json
from pathlib import Path
import subprocess
import sys
import tarfile
import traceback
import time

from ropeway_skip_stop_optimization.benchmarking.pattern_search import (
    PatternBenchmarkConfig,
    run_pattern_benchmark,
    screening_gate,
)
from ropeway_skip_stop_optimization.optimization.ddd.cp_sat_certificate import (
    atomic_json,
)

ROOT = Path(__file__).resolve().parents[1]


def freeze(output):
    files = sorted(
        [
            *ROOT.glob("src/**/*.py"),
            *ROOT.glob("benchmarks/*.py"),
            *ROOT.glob("tests/*pattern*.py"),
            ROOT / "pyproject.toml",
            ROOT / "uv.lock",
        ]
    )
    hashes = {}
    with tarfile.open(output / "source.tar.gz", "w:gz") as archive:
        for p in files:
            data = p.read_bytes()
            name = str(p.relative_to(ROOT))
            hashes[name] = hashlib.sha256(data).hexdigest()
            info = tarfile.TarInfo(name)
            info.size = len(data)
            archive.addfile(info, io.BytesIO(data))
    runtime = output / "runtime"
    runtime.mkdir()
    with tarfile.open(output / "source.tar.gz") as archive:
        archive.extractall(runtime, filter="data")
    atomic_json(
        output / "source_manifest.json",
        dict(
            files=hashes,
            git_head=subprocess.check_output(
                ["git", "rev-parse", "HEAD"], cwd=ROOT, text=True
            ).strip(),
            git_status=subprocess.check_output(
                ["git", "status", "--short"], cwd=ROOT, text=True
            ),
            python=sys.version,
            source_sha256=hashlib.sha256(
                (output / "source.tar.gz").read_bytes()
            ).hexdigest(),
        ),
    )

    return runtime


def summarize(output):
    from ropeway_skip_stop_optimization.benchmarking.pattern_search_report import (
        build_report,
    )

    return build_report(output)


def report_until_complete(output, *, wait=False, report_md=None, archive_path=None):
    from ropeway_skip_stop_optimization.benchmarking.pattern_search_report import (
        build_report,
    )

    deadline = time.monotonic() + 10800
    previous = None
    while True:
        completed = (output / "completion.json").exists()
        signature = (
            completed,
            tuple(sorted(str(p) for p in output.glob("*/*/completion.json"))),
        )
        if signature != previous:
            report = build_report(output, report_md=report_md)
            print(
                json.dumps(
                    dict(verdict=report["verdict"], completed_runs=len(report["rows"]))
                ),
                flush=True,
            )
            previous = signature
        if completed or not wait:
            break
        if time.monotonic() >= deadline:
            raise TimeoutError("campaign report wait exceeded three hours")
        time.sleep(5)
    if completed and archive_path:
        archive_path = archive_path.resolve()
        if archive_path.exists():
            raise FileExistsError(archive_path)
        with tarfile.open(archive_path, "w:gz") as archive:
            for path in sorted(output.rglob("*")):
                if path.is_file() and "runtime" not in path.relative_to(output).parts:
                    archive.add(
                        path, arcname=str(Path(output.name) / path.relative_to(output))
                    )
        archive_path.with_suffix(archive_path.suffix + ".sha256").write_text(
            hashlib.sha256(archive_path.read_bytes()).hexdigest()
            + "  "
            + archive_path.name
            + "\n"
        )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument(
        "--stage", choices=["auto", "screen", "job", "report"], default="auto"
    )
    parser.add_argument("--wait-for-completion", action="store_true")
    parser.add_argument("--report-md", type=Path)
    parser.add_argument("--archive", type=Path)
    parser.add_argument("--cabins", type=int, choices=[38, 39], default=38)
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument("--method", choices=["vns", "cp_sat"], default="vns")
    parser.add_argument("--seconds", type=float, default=900)
    parser.add_argument("--workers", type=int, default=12)
    parser.add_argument(
        "--seed-root",
        type=Path,
        default=ROOT / "benchmarks/output/fixed_start_capacity_20260910",
    )
    args = parser.parse_args()
    output = args.output_dir.resolve()
    if args.stage == "report":
        report_until_complete(
            output,
            wait=args.wait_for_completion,
            report_md=args.report_md,
            archive_path=args.archive,
        )
        return
    if args.stage == "job":
        run_pattern_benchmark(
            PatternBenchmarkConfig(
                args.cabins, args.seed, args.workers, args.seconds, method=args.method
            ),
            output=output,
            seed_path=args.seed_root / f"k{args.cabins}_waiting_n3074/incumbent.json",
        )
        return
    output.mkdir(parents=True, exist_ok=False)
    runtime = freeze(output)
    # Freeze common seeds as well; later jobs cannot accidentally read improved seeds.
    seeds = output / "seeds"
    for k in (38, 39):
        dest = seeds / f"k{k}_waiting_n3074"
        dest.mkdir(parents=True)
        (dest / "incumbent.json").write_bytes(
            (args.seed_root / f"k{k}_waiting_n3074/incumbent.json").read_bytes()
        )

    def job(stage, k, seed, method, seconds):
        folder = output / stage / f"k{k}_{method}_seed{seed}"
        command = [
            sys.executable,
            str(runtime / "benchmarks/run_pattern_search.py"),
            "--stage",
            "job",
            "--output-dir",
            str(folder),
            "--cabins",
            str(k),
            "--seed",
            str(seed),
            "--method",
            method,
            "--seconds",
            str(seconds),
            "--workers",
            str(args.workers),
            "--seed-root",
            str(seeds),
        ]
        print("START", str(folder), flush=True)
        subprocess.run(
            command,
            check=True,
            cwd=runtime,
            env={**os.environ, "PYTHONPATH": str(runtime / "src")},
        )
        summarize(output)
        r = json.loads((folder / "result.json").read_text())
        print("DONE", str(folder), r["unserved_upper_bound"], flush=True)
        return r

    try:
        results = [job("screen", k, 0, "vns", 120) for k in (38, 39)]
        gate = screening_gate(results)
        atomic_json(output / "gate.json", gate)
        print("GATE", json.dumps(gate), flush=True)
        if not gate["passed"] or args.stage == "screen":
            atomic_json(
                output / "completion.json",
                dict(status="complete", campaign_started=False, gate=gate),
            )
            summarize(output)
            return
        for seed in (0, 1):
            for k in (38, 39):
                for method in ("vns", "cp_sat") if seed == 0 else ("cp_sat", "vns"):
                    job("campaign", k, seed, method, 900)
        atomic_json(
            output / "completion.json",
            dict(status="complete", campaign_started=True, gate=gate),
        )
        summarize(output)
    except Exception:
        atomic_json(
            output / "completion.json",
            dict(status="failed", error=traceback.format_exc()),
        )
        raise


if __name__ == "__main__":
    main()
