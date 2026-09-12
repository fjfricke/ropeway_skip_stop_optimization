"""Read-only campaign accounting; no solver jobs."""

import importlib.util
from pathlib import Path
import sys


def module(name):
    path = Path(__file__).resolve().parents[1] / "benchmarks" / f"{name}.py"
    spec = importlib.util.spec_from_file_location(name, path)
    m = importlib.util.module_from_spec(spec)
    sys.modules[name] = m
    spec.loader.exec_module(m)
    return m


def test_budget_and_profiles():
    m = module("run_reservoir_compact_campaign")
    assert len(m.VARIANTS) == 7
    assert 2 * len(m.VARIANTS) * 120 + 4 * 300 + 12 * 60 == 3600
    assert m.VARIANTS["I"].passenger_encoding == m.VARIANTS["P1"].passenger_encoding
    assert m.VARIANTS["K"].passenger_encoding == m.VARIANTS["P1"].passenger_encoding


def test_confirmation_requires_both_seeds_and_no_seed_uptake():
    m = module("report_reservoir_compact_campaign")
    records = []
    for seed in (1, 2):
        for profile in ("L", "P1"):
            records.append(
                dict(
                    run=f"R2_{profile}_s{seed}",
                    upper=578,
                    lower=0,
                    progress=[dict(seconds=0, upper=578, lower=0)],
                )
            )
    assert not m.assess(records, "P1")["recommendation"]
    records[1]["upper"] = 568
    assert not m.assess(records, "P1")["recommendation"]
    records[3]["upper"] = 568
    assert m.assess(records, "P1")["recommendation"]
    records[3]["failure"] = {"error": "invalid certificate"}
    assert not m.assess(records, "P1")["recommendation"]


def test_confirmed_build_inclusive_reach_times():
    m = module("report_reservoir_compact_campaign")
    records = []
    for seed in (1, 2):
        for profile, seconds in (("L", 100), ("P1", 75)):
            records.append(
                dict(
                    run=f"R2_{profile}_s{seed}",
                    upper=578,
                    lower=50,
                    progress=[
                        dict(seconds=0, upper=578, lower=0),
                        dict(seconds=seconds, upper=578, lower=50),
                    ],
                )
            )
    assert m.assess(records, "P1")["recommendation"]
    records[3]["lower"] = 49
    assert not m.assess(records, "P1")["recommendation"]


def test_runner_rejects_irrelevant_flags_before_loading_reference():
    m = module("run_reservoir_capacity_arc_flow")
    args = m.parser().parse_args(
        [
            "--method",
            "cp_sat",
            "--reference",
            "missing.json",
            "--output-dir",
            "unused",
            "--passenger-encoding",
            "od_queue",
        ]
    )
    try:
        m.formulation_config(args)
    except ValueError as e:
        assert "require phase_arc_flow" in str(e)
    else:
        raise AssertionError("unsupported encoding accepted")


def test_previous_status_does_not_hide_live_frozen_worker(tmp_path, monkeypatch):
    import json
    from types import SimpleNamespace
    import pytest

    m = module("run_reservoir_compact_campaign")
    (tmp_path / "status.json").write_text(json.dumps({"state": "completed"}))
    command = str(tmp_path / "sources/benchmarks/worker.py")
    monkeypatch.setattr(
        m.psutil,
        "process_iter",
        lambda attrs: [
            SimpleNamespace(
                info={"pid": 123, "cmdline": ["python", command], "create_time": 1}
            )
        ],
    )
    with pytest.raises(RuntimeError, match="worker still alive"):
        m.check_previous_completed(tmp_path)
    monkeypatch.setattr(m.psutil, "process_iter", lambda attrs: [])
    assert m.check_previous_completed(tmp_path)["completed"]


def test_deadline_recovers_checked_checkpoint_without_claiming_improvement(tmp_path):
    import json
    import shutil
    import pytest

    reference = (
        Path(__file__).resolve().parents[1]
        / "benchmarks/output/reservoir_capacity_campaign_20260911_v1/prepare/R2_ss.json"
    )
    if not reference.exists():
        pytest.skip("private historical reference not distributed")
    for name in ("reference.json", "best.json"):
        shutil.copy2(reference, tmp_path / name)
    (tmp_path / "process.log").write_text(
        "Optimize a model with 10 rows, 20 columns and 30 nonzeros (Min)\n"
    )
    (tmp_path / "events.jsonl").write_text(
        json.dumps({"event": "restricted_bound", "lower": 0, "seconds": 50}) + "\n"
    )
    (tmp_path / "supervisor.json").write_text(
        json.dumps({"supervisor_reason": "WALL_DEADLINE", "civil_wall_seconds": 120})
    )
    m = module("run_reservoir_compact_campaign")
    result = m.summarize(tmp_path)
    assert result["upper"] == 578 and result["lower"] == 0
    assert result["variables"] == 20 and result["recovered_checkpoint"]
    assert not result["improvements"] and not result["failure"]
    assert result["status"] == "WALL_DEADLINE"
    assert (tmp_path / "recovered_result.json").exists()
    (tmp_path / "supervisor.json").write_text(
        json.dumps(
            {
                "supervisor_reason": "CONTROLLER_REPAIR_INTERRUPTION",
                "civil_wall_seconds": 20,
            }
        )
    )
    assert m.summarize(tmp_path)["failure"]["type"] == "INCOMPLETE_COMPARISON"
