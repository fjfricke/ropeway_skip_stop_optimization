import importlib.util
import json
from pathlib import Path

import pytest

RUNNER = Path(__file__).parents[1] / "benchmarks/run_oip_nowait_formulation_comparison.py"


def load_runner():
    spec = importlib.util.spec_from_file_location("oip_nowait_comparison", RUNNER)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_calibration_gate_requires_every_proof(tmp_path):
    module = load_runner()
    path = tmp_path / "references.json"
    path.write_text(json.dumps({"evidence": [
        {"family": "f2", "capacity_proven": True, "load_120": 100},
    ]}))
    with pytest.raises(ValueError, match="f3, f0"):
        module.load_calibration(path, ("f2", "f3", "f0"))


def test_manifest_uses_proven_120_percent_loads_and_frozen_order(tmp_path):
    module = load_runner()
    path = tmp_path / "references.json"
    path.write_text(json.dumps({"evidence": [
        {"family": family, "capacity_proven": True, "load_120": value}
        for family, value in (("f2", 2266), ("f3", 5000), ("f0", 7000))
    ]}))
    loads = module.load_calibration(path, ("f2", "f3", "f0"))
    args = type("Args", (), {
        "output": tmp_path / "campaign",
        "calibration": path,
        "reference_time_limit_seconds": 300,
        "trial_time_limit_seconds": 300,
        "workers": 12,
        "seed": 0,
        "memory_limit_gib": 32,
        "families": ["f2", "f3", "f0"],
    })()
    manifest = module.new_manifest(args, loads)
    assert [(item["family"], item["formulation"]) for item in manifest["trials"]] == list(module.ORDER)
    assert [item["demand_total"] for item in manifest["trials"][:2]] == [2266, 2266]
    assert all(item["objective"] == "served" for item in manifest["trials"])


def test_partial_campaign_requires_and_builds_only_selected_families(tmp_path):
    module = load_runner()
    path = tmp_path / "references.json"
    path.write_text(json.dumps({"evidence": [
        {"family": "f2", "capacity_proven": True, "load_120": 2266},
        {"family": "f3", "capacity_proven": True, "load_120": 5430},
        {"family": "f0", "capacity_proven": False, "load_120": None},
    ]}))
    loads = module.load_calibration(path, ("f2", "f3"))
    args = type("Args", (), {
        "output": tmp_path / "campaign", "calibration": path,
        "reference_time_limit_seconds": 300, "trial_time_limit_seconds": 300,
        "workers": 12, "seed": 0, "memory_limit_gib": 32,
        "families": ["f2", "f3"],
    })()
    manifest = module.new_manifest(args, loads)
    assert manifest["families"] == ["f2", "f3"]
    assert [(trial["family"], trial["formulation"])
            for trial in manifest["trials"]] == [
        ("f2", "ean"), ("f2", "nowait_templates"),
        ("f3", "nowait_templates"), ("f3", "ean"),
    ]
    assert loads == {"f2": 2266, "f3": 5430}
    assert manifest["reference_runs"] == {
        "f2": {"status": "planned", "demand_total": 2266},
        "f3": {"status": "planned", "demand_total": 5430},
    }


def test_templates_only_has_exactly_two_trials(tmp_path):
    from types import SimpleNamespace
    module = load_runner()
    args = SimpleNamespace(output=tmp_path, calibration=tmp_path / "references.json",
        families=["f2", "f3"], formulations=["nowait_templates"],
        reference_time_limit_seconds=300, trial_time_limit_seconds=900,
        workers=12, seed=0, memory_limit_gib=32)
    manifest = module.new_manifest(args, {"f2":2266, "f3":5430})
    assert [(t["family"],t["formulation"]) for t in manifest["trials"]] == [
        ("f2","nowait_templates"), ("f3","nowait_templates")]
    assert manifest["configuration"]["trial_time_limit_seconds"] == 900
