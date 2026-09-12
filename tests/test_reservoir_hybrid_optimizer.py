import json

import pytest
from test_reservoir_hybrid import small, enumerate_plans
from ropeway_skip_stop_optimization.optimization.ddd.reservoir_hybrid.optimizer import (
    ReservoirHybridConfig,
    ReservoirHybridOptimizer,
)
from ropeway_skip_stop_optimization.optimization.ddd.reservoir_hybrid.certificates import (
    GlobalReservoirBound,
    read_global_bound_result,
)
from ropeway_skip_stop_optimization.optimization.ddd.reservoir_cp_sat_certificate import (
    validate_reservoir_cp_plan,
)


def test_coordinator_improves_late_plan_without_promoting_local_bounds():
    p = small()
    plan = next(
        s
        for s in enumerate_plans(p)
        if s.ride_counts
        and validate_reservoir_cp_plan(p, s).journey_time_tick > 2_000_000
    )
    bound = GlobalReservoirBound(p.fingerprint, 2, "tiny_analytic", "analytical_only")
    result_plan, result = ReservoirHybridOptimizer(
        ReservoirHybridConfig(time_limit=5, workers=1)
    ).solve(p, primal_seed=plan, initial_bound=bound)
    assert result["validated_upper_bound"] == 2
    assert result["certified_lower_bound"] == 2
    assert validate_reservoir_cp_plan(p, result_plan).journey_time_tick == 2_000_000
    assert any(e["kind"] == "improvement" for e in result["events"])
    assert all(e["certified_lower_bound"] == 2 for e in result["events"])


def test_bound_import_ignores_unfinished_round_and_rejects_local(tmp_path):
    p = small()
    path = tmp_path / "result.json"
    content = {
        "problem_fingerprint": p.fingerprint,
        "rounds": [
            {
                "status": 2,
                "raw_lp_bound": 2,
                "model_fingerprint": "model",
                "objective_scope": "single_use_reservoir_global",
            },
            {
                "status": 9,
                "raw_lp_bound": 100,
                "model_fingerprint": "unfinished",
                "objective_scope": "single_use_reservoir_global",
            },
        ],
    }
    path.write_text(json.dumps(content))
    assert read_global_bound_result(path, p).value == 2
    content["rounds"][0]["objective_scope"] = "local_repair_only"
    path.write_text(json.dumps(content))
    with pytest.raises(ValueError, match="no completed"):
        read_global_bound_result(path, p)


def test_hybrid_budget_validation():
    with pytest.raises(ValueError):
        ReservoirHybridConfig(time_limit=float("inf"))
    with pytest.raises(ValueError):
        ReservoirHybridConfig(bound_fraction=0.5)
