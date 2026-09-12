"""Frozen K39 VNS follow-up after the controlled time-hint experiment."""

import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tarfile
import time

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--worker", action="store_true")
    args = parser.parse_args()
    out = args.output_dir.resolve()
    if args.worker:
        from ropeway_skip_stop_optimization.benchmarking.pattern_search import (
            PatternBenchmarkConfig,
            run_pattern_benchmark,
        )

        run_pattern_benchmark(
            PatternBenchmarkConfig(
                39,
                seconds=1800,
                oracle_seconds=10,
                refine_seconds=30,
                retry_unknown=False,
            ),
            output=out / "run",
            seed_path=out / "seed.json",
        )
        return
    out.mkdir(parents=True, exist_ok=False)
    prior = ROOT / "benchmarks/output/pattern_time_hint_ablation_20260910"
    runtime = out / "runtime"
    runtime.mkdir()
    with tarfile.open(prior / "source.tar.gz") as archive:
        archive.extractall(runtime, filter="data")
    for name in (
        "benchmarks/run_pattern_search_followup.py",
        "src/ropeway_skip_stop_optimization/benchmarking/pattern_search.py",
        "src/ropeway_skip_stop_optimization/optimization/ddd/pattern_search.py",
    ):
        shutil.copy2(ROOT / name, runtime / name)
    shutil.copy2(
        prior / "runs/variant1_time_hint_seed0/incumbent.json", out / "seed.json"
    )
    files = sorted(p for p in runtime.rglob("*") if p.is_file())
    hashes = {
        str(p.relative_to(runtime)): hashlib.sha256(p.read_bytes()).hexdigest()
        for p in files
    }
    (out / "source_manifest.json").write_text(json.dumps(hashes, indent=2))
    with tarfile.open(out / "source.tar.gz", "w:gz") as archive:
        for p in files:
            archive.add(p, arcname=str(p.relative_to(runtime)))
    (out / "protocol.json").write_text(
        json.dumps(
            dict(
                cabins=39,
                demand=3074,
                seconds=1800,
                workers=12,
                seed=0,
                oracle_seconds=10,
                refine_seconds=30,
                retry_unknown=False,
                seed_source=str(prior / "runs/variant1_time_hint_seed0/incumbent.json"),
                queued_after=str(prior),
                proof_scope="HEURISTIC_FIXED_K",
            ),
            indent=2,
        )
    )
    print("QUEUED: waiting for hint ablation completion", flush=True)
    supervisor = json.loads(Path(str(prior) + "_process.json").read_text())["pid"]
    while not (prior / "completion.json").exists():
        os.kill(supervisor, 0)
        time.sleep(10)
    print(
        "START K39 VNS: 1800 s, 10 s new patterns, 30 s improving patterns", flush=True
    )
    result = subprocess.run(
        [
            sys.executable,
            str(runtime / "benchmarks/run_pattern_search_followup.py"),
            "--worker",
            "--output-dir",
            str(out),
        ],
        cwd=runtime,
        env={**os.environ, "PYTHONPATH": str(runtime / "src")},
    )
    (out / "completion.json").write_text(
        json.dumps(
            dict(
                status="complete" if result.returncode == 0 else "failed",
                returncode=result.returncode,
            ),
            indent=2,
        )
    )
    raise SystemExit(result.returncode)


if __name__ == "__main__":
    main()
