"""Bounded historical projection and fixed-movement passenger-optimum checks."""

import argparse
from dataclasses import asdict
import hashlib
import json
from pathlib import Path
import sys
from time import perf_counter

from run_reservoir_compact_campaign import VARIANTS
from ropeway_skip_stop_optimization.benchmarking.process_supervisor import supervise
from ropeway_skip_stop_optimization.optimization.ddd.cp_sat_certificate import (
    atomic_json,
)
from ropeway_skip_stop_optimization.optimization.ddd.cp_sat_integrated import (
    DddIntegratedCpSatConfig,
)
from ropeway_skip_stop_optimization.optimization.ddd.reservoir_cp_sat import (
    DddReservoirCpSatOptimizer,
    DddReservoirCpObjective,
)
from ropeway_skip_stop_optimization.optimization.ddd.reservoir_capacity.formulation import (
    ReservoirPhaseFormulationConfig as Config,
)
from ropeway_skip_stop_optimization.optimization.ddd.reservoir_capacity.network import (
    build_network,
)
from ropeway_skip_stop_optimization.optimization.ddd.reservoir_capacity.model import (
    build_model,
    solve,
)
from ropeway_skip_stop_optimization.optimization.ddd.reservoir_hybrid.domain import (
    load_reference,
)
from ropeway_skip_stop_optimization.optimization.ddd.reservoir_cp_sat_certificate import (
    validate_reservoir_cp_plan,
)

ROOT = Path(__file__).resolve().parents[1]
CONFIGS = VARIANTS | {
    "combined": Config(
        passenger_encoding="od_queue",
        passenger_integrality="boarding",
        passenger_network="contracted",
        resource_encoding="maximal",
        conflict_cuts="local_cliques",
    )
}


def worker(a):
    domain, seed = load_reference(a.reference)
    p = domain.problem
    original = validate_reservoir_cp_plan(p, seed)
    if a.profile == "cp_reference":
        r = DddReservoirCpSatOptimizer(
            DddIntegratedCpSatConfig(total_time_limit_seconds=60, num_workers=12),
            DddReservoirCpObjective.UNSERVED,
        ).solve(p, primal_seed=seed, fixed_plan=seed)
        if r["solver_status"] != "OPTIMAL":
            raise RuntimeError(
                "independent fixed-movement capacity optimum not established"
            )
        optimum = r["validated_upper_bound"]
        if optimum != int(optimum):
            raise ValueError("noninteger fixed-movement capacity optimum")
        atomic_json(
            a.output_dir / "result.json",
            dict(
                passed=True,
                capacity_optimum=int(optimum),
                original=asdict(original),
            ),
        )
        return
    deadline = perf_counter() + 175
    network = build_network(p, [seed], deadline=deadline)
    b = build_model(
        network, reference=seed, formulation=CONFIGS[a.profile], deadline=deadline
    )
    try:
        values = b.reference_values(seed)
        # Preserve the exact original group assignment as an explicit projection
        # witness, even where OD queue has multiple possible disaggregations.
        for v in b.model.getVars():
            if not v.LB - 1e-8 <= values[v.index] <= v.UB + 1e-8:
                raise ValueError("reference outside variable bounds")
        for v in b.x.values():
            v.LB = v.UB = values[v.index]
        _, r = solve(
            b,
            deadline=deadline,
            threads=12,
            reference=seed,
            soft_memory_gb=24 * 1024**3 / 1e9,
        )
        if r["status"] != 2 or r["validated_upper_bound"] != a.expected:
            raise RuntimeError(
                f"fixed movement capacity mismatch: {r['status']}, {r['validated_upper_bound']} != {a.expected}"
            )
        r.update(passed=True, original=asdict(original), projection_witness=True)
        atomic_json(a.output_dir / "result.json", r)
    finally:
        b.model.dispose()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--reference", type=Path)
    parser.add_argument("--profile")
    parser.add_argument("--expected", type=int)
    parser.add_argument("--worker", action="store_true")
    parser.add_argument("--correctness-evidence", type=Path)
    a = parser.parse_args()
    if a.worker:
        worker(a)
        return
    if a.correctness_evidence is None:
        raise RuntimeError("--correctness-evidence is required for historical gate")
    correctness = a.correctness_evidence
    if (
        not correctness.exists()
        or json.loads(correctness.read_text()).get("state") != "passed"
    ):
        raise RuntimeError("native correctness tests have not passed")
    source_before = {
        str(p.relative_to(ROOT)): hashlib.sha256(p.read_bytes()).hexdigest()
        for p in (ROOT / "src").rglob("*.py")
    }
    a.output_dir.mkdir(parents=True, exist_ok=False)
    references = {
        "R0": ROOT
        / "benchmarks/output/reservoir_capacity_campaign_20260911_v1/prepare/R0_ss.json",
        "R2": ROOT
        / "benchmarks/output/reservoir_capacity_campaign_20260911_v1/prepare/R2_ss.json",
        "waiting": ROOT
        / "benchmarks/output/reservoir_demand_probe_20260911_v2/seed_1/best.json",
    }
    wait_data = json.loads(references["waiting"].read_text())
    if not any(t for tr in wait_data["plan"]["trips"] for t in tr["wait_ticks"]):
        raise RuntimeError("historical waiting reference has no positive waiting")
    records = []
    for name, reference in references.items():
        if not reference.exists():
            raise RuntimeError(f"missing required historical reference {name}")
        expected = None
        for profile in ("cp_reference", *CONFIGS):
            out = a.output_dir / f"{name}_{profile}"
            out.mkdir()
            command = [
                sys.executable,
                str(Path(__file__).resolve()),
                "--worker",
                "--output-dir",
                str(out.resolve()),
                "--reference",
                str(reference),
                "--profile",
                profile,
            ]
            if expected is not None:
                command += ["--expected", str(expected)]
            supervise(command, out, seconds=180, memory_bytes=24 * 1024**3)
            path = out / "result.json"
            if not path.exists():
                raise RuntimeError(f"replay failed: {out}")
            r = json.loads(path.read_text())
            if not r.get("passed"):
                raise RuntimeError(f"replay gate failed: {out}")
            if profile == "cp_reference":
                expected = r["capacity_optimum"]
            records.append(
                dict(
                    case=name,
                    profile=profile,
                    capacity_optimum=expected,
                    result=str(path),
                )
            )
            atomic_json(a.output_dir / "progress.json", records)
    hashes = {
        str(p.relative_to(ROOT)): hashlib.sha256(p.read_bytes()).hexdigest()
        for folder in (ROOT / "src",)
        for p in folder.rglob("*.py")
    }
    if hashes != source_before:
        raise RuntimeError("sources changed during historical replay checks")
    atomic_json(
        a.output_dir / "gate.json",
        dict(passed=True, replays=records, source_hashes=hashes),
    )


if __name__ == "__main__":
    main()
