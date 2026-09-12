from dataclasses import replace
import json
from types import SimpleNamespace

import pytest

from test_optimization_ddd_reservoir_arc_flow import _problem
from ropeway_skip_stop_optimization.benchmarking.ddd_reservoir_arc_flow import (
    DddReservoirArcFlowRunConfig,
)
from ropeway_skip_stop_optimization.benchmarking.ddd_reservoir_cp_sat import (
    DddReservoirCpSatRunConfig,
    run_ddd_reservoir_cp_sat,
    all_stop_reservoir_movement,
)
from ropeway_skip_stop_optimization.optimization.ddd.cp_sat_integrated import (
    DddIntegratedCpSatConfig,
)
from ropeway_skip_stop_optimization.optimization.ddd.reservoir_cp_sat_problem import (
    DddReservoirCpSatProblem,
)
from ropeway_skip_stop_optimization.optimization.ddd.reservoir_cp_sat_certificate import (
    validate_reservoir_cp_plan,
)


def test_analytic_all_stop_backbone_needs_no_expanded_network():
    source = _problem(fleet=3)
    p = DddReservoirCpSatProblem.from_arc_flow(source)
    plan = all_stop_reservoir_movement(p, source)
    checked = validate_reservoir_cp_plan(p, plan)
    assert checked.used_fleet == 2 and all(
        o.endswith("stop") for t in plan.trips for o in t.route_option_ids
    )


def test_runner_writes_valid_results_progress_and_resume_without_overwriting(
    tmp_path, monkeypatch
):
    source = _problem(fleet=2)
    monkeypatch.setattr(
        "ropeway_skip_stop_optimization.benchmarking.ddd_reservoir_cp_sat.prepare_ddd_reservoir_arc_flow_run",
        lambda config: SimpleNamespace(problem=source, all_stop_maximum_cabin_count=2),
    )
    c = DddReservoirCpSatRunConfig(
        DddReservoirArcFlowRunConfig("tiny"),
        tmp_path / "first",
        DddIntegratedCpSatConfig(total_time_limit_seconds=5),
        seed_time_limit_seconds=1,
    )
    r = run_ddd_reservoir_cp_sat(c)
    assert r["proven_optimal"] and r["metrics"]["unserved"] == 0
    assert r["seed_upper_bound"] >= r["validated_upper_bound"]
    raw = json.loads((c.output_dir / "incumbent.json").read_text())
    assert raw["problem_fingerprint"] == r["problem_fingerprint"]
    assert (c.output_dir / "events.jsonl").read_text().strip()
    resumed = run_ddd_reservoir_cp_sat(
        replace(
            c,
            output_dir=tmp_path / "second",
            resume_checkpoint=c.output_dir / "incumbent.json",
        )
    )
    assert resumed["validated_upper_bound"] == r["validated_upper_bound"]
    with pytest.raises(FileExistsError):
        run_ddd_reservoir_cp_sat(c)
