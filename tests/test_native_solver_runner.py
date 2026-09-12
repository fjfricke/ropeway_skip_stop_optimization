import sys
from unittest.mock import patch

import pytest

pytest.importorskip("psutil")

from ropeway_skip_stop_optimization.benchmarking.native_solvers import supervise


def test_deadline_stops_child_without_claiming_solver_infeasibility(tmp_path):
    result = supervise(
        [sys.executable, "-c", "import time; time.sleep(30)"], tmp_path, seconds=0.3
    )
    assert result["supervisor_reason"] == "WALL_DEADLINE"
    assert result["civil_wall_seconds"] < 2
    assert result["exit_code"] != 0
    assert "proven_optimal" not in result


def test_failed_checkpoint_validation_stops_process(tmp_path):
    (tmp_path / "best.json").write_text("{}")

    def reject(path, elapsed):
        raise ValueError("invalid certificate fixture")

    result = supervise(
        [sys.executable, "-c", "import time; time.sleep(30)"],
        tmp_path,
        seconds=2,
        checkpoint_callback=reject,
    )
    assert result["supervisor_reason"] == "INVALID_CHECKPOINT"
    assert (tmp_path / "validation_error.json").is_file()


def test_group_signal_denied_still_stops_owned_child(tmp_path):
    with patch("os.killpg", side_effect=PermissionError("group signal denied")):
        result = supervise(
            [sys.executable, "-c", "import time; time.sleep(30)"],
            tmp_path,
            seconds=0.2,
        )
    assert result["supervisor_reason"] == "WALL_DEADLINE"
    assert result["civil_wall_seconds"] < 2
    assert result["exit_code"] != 0


def test_memory_limit_is_not_an_unsat_proof(tmp_path):
    result = supervise(
        [sys.executable, "-c", "import time; time.sleep(30)"],
        tmp_path,
        seconds=2,
        memory_bytes=1,
    )
    assert result["supervisor_reason"] == "MEMORY_LIMIT"
    assert result["peak_process_tree_rss_bytes"] > 0


def test_recommendation_requires_both_additional_repetitions():
    from ropeway_skip_stop_optimization.benchmarking.native_solvers import (
        assess_campaign,
    )

    cases = []
    for r in (1, 2):
        cases.extend(
            [
                {
                    "case": "C",
                    "backend": "cp_sat",
                    "repetition": r,
                    "status": "FEASIBLE",
                    "validated_upper_bound": 100,
                    "gap": 0.5,
                },
                {
                    "case": "C",
                    "backend": "z3",
                    "repetition": r,
                    "status": "UNKNOWN",
                    "validated_upper_bound": 90,
                    "gap": 0.5,
                },
            ]
        )
    result = next(
        x for x in assess_campaign(cases) if x["case"] == "C" and x["backend"] == "z3"
    )
    assert result["recommended"]
    cases[-1]["validated_upper_bound"] = 91
    result = next(
        x for x in assess_campaign(cases) if x["case"] == "C" and x["backend"] == "z3"
    )
    assert not result["recommended"]
