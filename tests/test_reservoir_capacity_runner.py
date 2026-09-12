from dataclasses import replace
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
from time import perf_counter

import pytest
from test_reservoir_capacity_phases import physical_small
from test_reservoir_hybrid import enumerate_plans
from ropeway_skip_stop_optimization.optimization.ddd.reservoir_cp_sat_certificate import (
    write_reservoir_cp_checkpoint,
)
from ropeway_skip_stop_optimization.optimization.ddd.reservoir_arc_flow_problem import (
    DddReservoirOperatingMode,
)
from ropeway_skip_stop_optimization.optimization.ddd.reservoir_capacity.network import (
    build_network,
)
from ropeway_skip_stop_optimization.optimization.ddd.reservoir_capacity.model import (
    build_model,
)
from ropeway_skip_stop_optimization.optimization.ddd.reservoir_hybrid.domain import (
    load_reference,
)

ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.parametrize("method", ["phase_arc_flow", "all_stop_bound", "cp_sat"])
def test_supervised_runner(tmp_path, method):
    p = physical_small()
    seed = next(
        s
        for s in enumerate_plans(p)
        if s.ride_counts
        and all("skip" not in o for tr in s.trips for o in tr.route_option_ids)
    )
    if method == "all_stop_bound":
        p = replace(p, operating_mode=DddReservoirOperatingMode.ALL_STOP)
    ref = tmp_path / "seed.json"
    write_reservoir_cp_checkpoint(ref, p, seed)
    out = tmp_path / method
    cmd = [
        sys.executable,
        str(ROOT / "benchmarks/run_reservoir_capacity_arc_flow.py"),
        "--method",
        method,
        "--reference",
        str(ref),
        "--time-limit",
        "15",
        "--threads",
        "1",
        "--output-dir",
        str(out),
    ]
    subprocess.run(cmd, check=True, timeout=20)
    assert not (out / "failure.json").exists(), (out / "process.log").read_text()
    r = json.loads((out / "result.json").read_text())
    assert r["reference_metrics"]["served"] == 1
    assert (out / "supervisor.json").exists()
    if method == "phase_arc_flow":
        assert r["global_lower_bound"] is None
    if method == "all_stop_bound":
        assert r["global_lower_bound"] == 0


def test_campaign_budget_and_fixed_repetition():
    spec = importlib.util.spec_from_file_location(
        "capacity_campaign", ROOT / "benchmarks/run_reservoir_capacity_campaign.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    jobs = module.schedule()
    assert sum(x[3] for x in jobs) + 300 + 540 == 3600
    assert jobs[-2:] == [
        ("R2", "cp_sat", 1, 300, None),
        ("R2", "phase_arc_flow", 1, 300, None),
    ]


def test_historical_max50_positive_passenger_replay():
    path = (
        ROOT / "benchmarks/output/reservoir_demand_probe_20260911_v2/seed_1/best.json"
    )
    if not path.exists():
        pytest.skip("private historical artifact not distributed")
    d, seed = load_reference(path)
    deadline = perf_counter() + 90
    n = build_network(d.problem, [seed], deadline=deadline)
    b = build_model(n, reference=seed, deadline=deadline)
    try:
        assert seed.ride_counts
        assert b.reference_values(seed)
    finally:
        b.model.dispose()


def test_cp_full_service_infeasible_is_not_original_domain_infeasible():
    from ropeway_skip_stop_optimization.optimization.ddd.cp_sat_integrated import (
        DddIntegratedCpSatConfig,
    )
    from ropeway_skip_stop_optimization.optimization.ddd.reservoir_cp_sat import (
        DddReservoirCpSatOptimizer,
        DddReservoirCpObjective,
    )

    p = physical_small(release=4)
    r = DddReservoirCpSatOptimizer(
        DddIntegratedCpSatConfig(total_time_limit_seconds=5, num_workers=1),
        DddReservoirCpObjective.UNSERVED,
    ).solve(p, require_full_service=True)
    assert r["solver_status"] == "INFEASIBLE"
    assert r["validated_upper_bound"] == 1
    assert r["cp_lower_bound"] == 1
    assert not r["full_service_witness"]
