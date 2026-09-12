import importlib.util
import json
from pathlib import Path
import sys
import time

import pytest

from test_reservoir_hybrid import small, enumerate_plans
from ropeway_skip_stop_optimization.benchmarking.ddd_reservoir_hybrid import (
    DddReservoirHybridRunConfig,
    run_ddd_reservoir_hybrid,
)
from ropeway_skip_stop_optimization.optimization.ddd.reservoir_cp_sat_certificate import (
    write_reservoir_cp_checkpoint,
)


def test_runner_size_failure_preserves_checked_reference(tmp_path):
    p = small()
    plan = next(s for s in enumerate_plans(p) if s.ride_counts)
    path = tmp_path / "seed.json"
    write_reservoir_cp_checkpoint(path, p, plan)
    out = tmp_path / "result"
    config = DddReservoirHybridRunConfig(path, out, max_variables=1)
    result = run_ddd_reservoir_hybrid(config)
    assert result["status"] == "model_size_limit"
    assert result["validated_upper_bound"] > 0
    assert result["certified_lower_bound"] <= result["validated_upper_bound"]
    assert sum(result["partial_variable_families"].values()) == 1
    assert json.loads((out / "result.json").read_text()) == result
    with pytest.raises(FileExistsError):
        run_ddd_reservoir_hybrid(config)


def test_runner_without_size_caps_builds_and_certifies(tmp_path):
    p = small()
    plan = next(s for s in enumerate_plans(p) if s.ride_counts)
    path = tmp_path / "seed.json"
    write_reservoir_cp_checkpoint(path, p, plan)
    result = run_ddd_reservoir_hybrid(
        DddReservoirHybridRunConfig(
            path,
            tmp_path / "result",
            max_variables=None,
            max_rows=None,
            num_workers=1,
        )
    )
    assert result["status"] == 2
    assert result["variables"] > 1
    assert result["certified_lower_bound"] <= result["validated_upper_bound"]


@pytest.mark.parametrize(
    "phase,lifecycle", [("unknown", "single_use"), ("bound", "reusable")]
)
def test_unimplemented_phases_rejected(phase, lifecycle):
    with pytest.raises(ValueError, match="gated"):
        DddReservoirHybridRunConfig(
            Path("missing"), Path("unused"), phase=phase, lifecycle=lifecycle
        ).validate()


@pytest.mark.parametrize(
    "memory_limit,reason", [(4 * 1024**3, "wall_time_limit"), (1, "rss_limit")]
)
def test_parent_terminates_worker_without_fabricating_bound(
    tmp_path, memory_limit, reason
):
    path = (
        Path(__file__).resolve().parents[1]
        / "benchmarks/run_reservoir_hybrid_gate_campaign.py"
    )
    spec = importlib.util.spec_from_file_location("hybrid_campaign_test", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    result = module.run_case(
        [sys.executable, "-c", "import time; time.sleep(30)"],
        tmp_path / "worker.log",
        time.monotonic() + 0.5,
        memory_limit,
    )
    assert result["termination_reason"] == reason
    assert result["actual_seconds"] < 5
    assert result["return_code"] != 0
    assert "certified_lower_bound" not in result
