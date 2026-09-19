import importlib.util
from pathlib import Path
from types import SimpleNamespace

import pytest
from test_oip_pattern_waiting import _small_domain

from ropeway_skip_stop_optimization.optimization.oip.cp_sat import (
    OipCpSatConfig,
    cannot_beat_reference,
    solve_oip_cp_sat,
)


def runner():
    path = Path(__file__).parents[1] / "benchmarks/run_oip_fixed_mix_campaign.py"
    spec = importlib.util.spec_from_file_location("fixed_mixes", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.mark.parametrize(
    "bound,expected",
    [
        (0, False),
        (3099, False),
        (3100, True),
        (3101, True),
        (3099.999999, False),
        (float("nan"), False),
    ],
)
def test_reference_bound_is_conservative(bound, expected):
    assert cannot_beat_reference(7500, bound, 4400) is expected


def test_manifest_and_commands(tmp_path):
    m = runner()
    args = SimpleNamespace(
        output=tmp_path,
        calibration=tmp_path / "references.json",
        families=["f2", "f3", "f0"],
        formulations=["nowait_templates"],
        reuse_reference_root=None,
        trial_time_limit_seconds=300,
        reference_time_limit_seconds=300,
        workers=12,
        seed=0,
        memory_limit_gib=32,
    )
    manifest = m.manifest_for(args, {"f2": 2266, "f3": 5430, "f0": 7606})
    assert len(manifest["trials"]) == 15
    for t in manifest["trials"]:
        assert sum(t["fixed_type_counts"].values()) == 62
        cmd = m.mixture_command(t, tmp_path / "ref", tmp_path / "trial", args)
        assert "--start-checkpoint" not in cmd
        assert ("--stop-if-cannot-beat-reference" in cmd) == (
            t["fixed_type_counts"]["all_stop"] != 62
        )
    assert manifest["trials"][0]["fixed_type_counts"] == {
        "all_stop": 62,
        "bd": 0,
        "ce": 0,
    }


def test_bound_callback_stops_without_infeasibility_claim():
    domain = _small_domain(0)
    total = sum(d.count for d in domain.scenario.demands)
    result = solve_oip_cp_sat(
        domain,
        OipCpSatConfig(
            time_limit_seconds=5,
            workers=1,
            type_catalog="all_stop_alternating",
            formulation="nowait_templates",
            objective="served",
            stop_at_reference_served=total,
        ),
    )
    assert result.termination_reason == "cannot_beat_reference"
    assert result.solver_status not in ("INFEASIBLE", "MODEL_INVALID")
    assert result.reference_served_cutoff == total
