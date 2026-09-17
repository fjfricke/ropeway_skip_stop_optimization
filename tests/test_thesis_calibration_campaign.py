from __future__ import annotations

import json
from pathlib import Path

from ropeway_skip_stop_optimization.benchmarking.thesis_calibration import (
    JOURNEY_REFERENCE_KIND,
    OIP_REFERENCE_KIND,
    calibration_jobs,
    result_evidence,
)


def test_calibration_manifest_contains_only_the_24_plus_3_references():
    jobs = calibration_jobs(oip_cabins=62)
    assert len(jobs) == 27
    journey = [job for job in jobs if job["group"] == "journey"]
    oip = [job for job in jobs if job["group"] == "oip"]
    assert len(journey) == 24
    assert {(job["family"], job["cabins"]) for job in journey} == {
        (family, cabins)
        for family in ("f0", "f2", "f3", "f4")
        for cabins in (10, 15, 20, 25, 30, 31)
    }
    assert all(job["reference_kind"] == JOURNEY_REFERENCE_KIND for job in journey)
    assert [(job["family"], job["cabins"]) for job in oip] == [
        ("f0", 62), ("f2", 62), ("f3", 62)
    ]
    assert all(job["reference_kind"] == OIP_REFERENCE_KIND for job in oip)


def test_reference_export_keeps_open_capacity_result_open(tmp_path: Path):
    path = tmp_path / "result.json"
    path.write_text(json.dumps({"run": {
        "capacity_proven": False,
        "proven_feasible_demand": 100,
        "proven_infeasible_demand": None,
        "proof_scope": "scope",
    }}))
    evidence = result_evidence(calibration_jobs(oip_cabins=62)[0], path)
    assert evidence["capacity_proven"] is False
    assert evidence["proven_feasible_demand"] == 100
    assert evidence["proven_infeasible_demand"] is None
