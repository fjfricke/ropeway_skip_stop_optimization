from ropeway_skip_stop_optimization.benchmarking.thesis_study import (
    DemandLadder, confirmed_service, journey_confirmed, k_ladder, manifest_identity,
)


def test_demand_ladder_stops_after_three_unresolved_intermediate_checks():
    ladder = DemandLadder(100)
    assert ladder.advance(True) == 110
    assert ladder.advance(False) == 105
    assert ladder.advance(True) == 107
    assert ladder.advance(False) == 106
    assert ladder.advance(False) is None
    assert ladder.last_full == 105
    assert ladder.unresolved == 106  # Not a physical upper capacity bound.


def test_no_full_first_level_does_not_invent_lower_load():
    assert DemandLadder(100).advance(False) is None


def test_fleet_ladder_does_not_exceed_physical_bound():
    assert k_ladder(10, 23) == [10, 15, 23]
    assert k_ladder(10, 10) == [10]


def test_service_requires_a_complete_validated_certificate():
    assert confirmed_service({"run": {"best": {"passengers": {"served": 10, "unserved": 0}}}}) is None
    assert confirmed_service({"run": {"best": {"movement": {"feasible": True}, "passengers": {"served": 10, "unserved": 0, "plan": {}}}}}) == (10, 0)
    assert not journey_confirmed({"run": {"objective_value": 42}})
    assert journey_confirmed({"run": {"independent_validation_status": "feasible", "validated_upper_bound": 0}})


def test_resume_identity_includes_resolution_and_seed():
    assert manifest_identity({"seed": 0, "resolution": 15}) != manifest_identity({"seed": 0, "resolution": 5})
    assert manifest_identity({"seed": 0, "resolution": 15}) != manifest_identity({"seed": 1, "resolution": 15})


def test_study_resume_and_full_service_stop_with_fake_solver(tmp_path, monkeypatch):
    import json
    import sys
    from pathlib import Path
    from types import SimpleNamespace
    from benchmarks import run_thesis_study as runner
    manifest = {"schema": "thesis_study_v1", "groups": [{"id": "test", "objective": "unserved",
        "topology": "t5r", "family": "f2", "blockers": [], "k_values": [38, 39], "seeds": [0, 1],
        "demand": 10, "stage_seconds": 1, "resolution_seconds": 15, "max_demand_levels": 2,
        "catalog": "relevant", "pattern_search": "line_groups"}]}
    source = tmp_path / "manifest.json"; source.write_text(json.dumps(manifest))
    output = tmp_path / "study"; output.mkdir()
    calls = []

    def fake_run(command, **kwargs):
        calls.append(command)
        get = lambda name: command[command.index(name) + 1]
        directory = Path(get("--output-dir")); directory.mkdir()
        result = {"run": {"best": {"movement": {"feasible": True, "genome": {"pattern_ids": ["p"] * 38}},
                                    "passengers": {"served": int(get("--demand")), "unserved": 0, "plan": {}}}}}
        (directory / "result.json").write_text(json.dumps(result))
        return SimpleNamespace(returncode=0)

    monkeypatch.setattr(runner.subprocess, "run", fake_run)
    monkeypatch.setattr(sys, "argv", ["run", "--manifest", str(source), "--output-dir", str(output), "--wall-time-limit", "30", "--_worker"])
    runner.main()
    assert len(calls) == 4  # K39 is skipped immediately after full service at K38.
    assert all(call[call.index("--catalog") + 1] == "relevant" for call in calls)
    assert all(call[call.index("--pattern-search") + 1] == "line_groups" for call in calls)
    assert ["--initial-pattern-sequences" in call for call in calls] == [False, True, False, True]
    state = json.loads((output / "study.json").read_text())
    assert len(state["attempts"]) == 4
    runner.main()  # Recompute policy from saved outcomes, without solving again.
    assert len(calls) == 4


def test_launch_rejects_changed_reference_evidence(tmp_path):
    import hashlib
    import pytest
    from benchmarks.run_thesis_study import verify_evidence
    reference = tmp_path / "reference.json"; reference.write_text("original evidence")
    digest = hashlib.sha256(reference.read_bytes()).hexdigest()
    manifest = {"groups": [{"reference": {"result": str(reference), "sha256": digest}}],
                "source_resolution_evidence": str(reference), "source_resolution_sha256": digest}
    verify_evidence(manifest)
    reference.write_text("different evidence")
    with pytest.raises(ValueError, match="changed"):
        verify_evidence(manifest)
