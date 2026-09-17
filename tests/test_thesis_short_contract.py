from copy import deepcopy
import hashlib
import importlib.util
import json
from pathlib import Path
import sys
from types import SimpleNamespace

import pytest

from ropeway_skip_stop_optimization.benchmarking.thesis_contract import (
    THESIS_CONTRACT_ID, ThesisWindows,
)
from ropeway_skip_stop_optimization.benchmarking.thesis_reruns import (
    exact_reference_capacity, journey_jobs,
)
from ropeway_skip_stop_optimization.benchmarking.thesis_cases import (
    ExperimentCaseSpec, ThesisDemandFamily, ThesisDemandProfile, ThesisGeometry,
    ThesisObjective, ThesisTopology, prepare_fixed_k_experiment,
)
from ropeway_skip_stop_optimization.benchmarking.oip_pattern_waiting import (
    prepare_oip_pattern_waiting_pilot,
)


def _runner(name):
    path = Path(__file__).resolve().parents[1] / "benchmarks" / f"{name}.py"
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_journey_matrix_has_five_step_grid_and_fresh_reference_dependencies():
    jobs = journey_jobs()
    assert len({job["id"] for job in jobs}) == len(jobs) == 128
    assert len([j for j in jobs if j["kind"] == "reference"]) == 24
    assert {j["k"] for j in jobs if j["kind"] == "relative"} == {10, 15, 20, 25, 30}
    assert {j["k"] for j in jobs if j["kind"] == "constant"} == {20, 25, 30}
    references = {j["id"] for j in jobs if j["kind"] == "reference"}
    for job in jobs:
        if job["kind"] != "reference":
            assert job["reference_id"] in references
            assert job["demand"] is None
            assert job["status"] == "pending_reference"
        if job["kind"] == "constant":
            assert job["reference_k"] == 31


def test_old_or_unproved_references_are_rejected():
    result = dict(run=dict(
        cabins=20, proof_scope="FIXED_K_BALANCED_START_ALL_STOP_AND_NESTED_DEMAND",
        capacity_proven=True, proven_feasible_demand=100, proven_infeasible_demand=101,
        probes=[dict(demand=n, outcome=outcome, case=dict(
            thesis_contract_id=THESIS_CONTRACT_ID, continuation_tick=300_000_000,
            problem_fingerprint=f"physical-domain-for-{n}",
        )) for n, outcome in ((100, "feasible"), (101, "infeasible"))],
    ))
    assert exact_reference_capacity(result, k=20) == 100
    for change in ("old_contract", "unknown", "other_k"):
        wrong = deepcopy(result)
        if change == "old_contract":
            wrong["run"]["probes"][0]["case"].pop("thesis_contract_id")
        elif change == "unknown":
            wrong["run"]["probes"][1]["outcome"] = "unknown"
        else:
            wrong["run"]["cabins"] = 25
        with pytest.raises(ValueError):
            exact_reference_capacity(wrong, k=20)


def test_both_adapters_share_windows_and_entry_exit_resources_without_solver():
    spec = ExperimentCaseSpec(
        ThesisTopology.T5R, ThesisGeometry.G500, ThesisDemandFamily.F2,
        ThesisDemandProfile.P0, ThesisObjective.JOURNEY_TIME, 20,
        release_resolution_seconds=15, maximum_wait_seconds=0,
    )
    config, fixed, manifest = prepare_fixed_k_experiment(
        spec, cabins=2, time_limit_seconds=10, workers=1, seed=0,
    )
    oip = prepare_oip_pattern_waiting_pilot(
        maximum_wait_seconds=0, cabin_count=2, demand_total=20,
    )
    windows = ThesisWindows(732)
    assert manifest["demand_window_tick"] == 1_464_000_000
    assert config.horizon_seconds == oip.passenger_horizon_seconds == windows.service_horizon_seconds
    assert fixed.problem.artifact.config.operational_end_seconds == oip.operation_seconds == 2664
    assert config.tail_seconds == 300
    assert fixed.problem.artifact.config.horizon_seconds == 2364
    assert fixed.problem.start_policy.value == "balanced_reference"
    assert oip.domain.exact_k
    fixed_groups = fixed.problem.passenger_build.demand_groups
    assert max(g.release_time_seconds for g in fixed_groups) < 1464
    assert sum(g.count for g in fixed_groups) == 20
    for artifact in (fixed.problem.artifact, oip.domain.artifact):
        kinds = {c.kind.value for c in artifact.headway_checkpoints}
        assert {"entry_switch", "exit_switch"} <= kinds


def test_journey_manifest_build_only_never_invokes_solver(tmp_path, monkeypatch):
    runner = _runner("run_thesis_revised_journey_campaign")
    monkeypatch.setattr(runner.subprocess, "run", lambda *a, **k: pytest.fail("solver launched"))
    monkeypatch.setattr(sys, "argv", ["runner", "--output-dir", str(tmp_path / "study"), "--build-only"])
    runner.main()
    manifest = json.loads((tmp_path / "study/campaign.json").read_text())
    assert manifest["status"] == "prepared"
    assert manifest["execution_started_unix"] is None
    assert len(manifest["jobs"]) == 128


def test_oip_thesis_requires_new_calibration_and_never_defaults_old_loads(tmp_path, monkeypatch):
    runner = _runner("run_oip_thesis_pattern_campaigns")
    monkeypatch.setattr(runner.subprocess, "run", lambda *a, **k: pytest.fail("solver launched"))
    monkeypatch.setattr(sys, "argv", ["runner", "--output", str(tmp_path / "suite"), "--build-only"])
    runner.main()
    suite = json.loads((tmp_path / "suite/suite.json").read_text())
    assert suite["status"] == "pending_calibration"
    assert suite["reference_kind"] == "regular_all_stop_free_common_phase"
    assert all(c["demand_total"] is None for c in suite["cases"])
    old = tmp_path / "old.json"
    old.write_text(json.dumps({"contract_id": "45_minute_reservoir", "cases": []}))
    with pytest.raises(ValueError, match="new short"):
        runner.calibrated_cases(old)


def test_oip_resume_rejects_physical_or_source_changes():
    runner = _runner("run_oip_pattern_screening")
    frozen = dict(configuration_fingerprint="same-args", frozen_identity=dict(domain="new", source_digest="abc"))
    runner._validate_resume(deepcopy(frozen), frozen)
    for identity in (None, dict(domain="old", source_digest="abc"), dict(domain="new", source_digest="def")):
        old = dict(configuration_fingerprint="same-args", frozen_identity=identity)
        with pytest.raises(ValueError, match="changed"):
            runner._validate_resume(old, frozen)


def test_oip_resume_does_not_renew_an_expired_budget(tmp_path, monkeypatch):
    runner = _runner("run_oip_pattern_screening")
    manifest = dict(
        configuration_fingerprint="fixed", frozen_identity={"domain": "same"},
        status="partial", trials=[], refinements=[], execution_started_unix=10,
        deadline_unix=20, trial_count=0, refinement_count=0, resume_count=0,
    )
    path = tmp_path / "campaign.json"
    path.write_text(json.dumps(manifest))
    monkeypatch.setattr(runner, "parse_args", lambda: SimpleNamespace(
        output=tmp_path, frontend_root=None, wall_limit_seconds=100,
        resume=True, build_only=False, screening_only=True,
        refinement_candidates_per_k=0,
    ))
    monkeypatch.setattr(runner, "freeze_campaign", lambda *args: deepcopy(manifest))
    monkeypatch.setattr(runner.time, "time", lambda: 500)
    runner.main()
    assert json.loads(path.read_text())["deadline_unix"] == 20


def test_oip_calibrated_case_index_checks_load_ratio_and_reference_hash(tmp_path):
    runner = _runner("run_oip_thesis_pattern_campaigns")
    rows = []
    for family in ("f0", "f2", "f3"):
        result = tmp_path / f"{family}.json"
        result.write_text(json.dumps(dict(
            contract_id=THESIS_CONTRACT_ID, reference_kind=runner.REFERENCE_KIND,
            family=family, capacity_proven=True,
            proven_feasible_demand=101, proven_infeasible_demand=102,
        )))
        rows.append(dict(family=family, demand_total=112,
                         load_numerator=11, load_denominator=10,
                         reference_result=result.name,
                         reference_sha256=hashlib.sha256(result.read_bytes()).hexdigest()))
    payload = dict(contract_id=THESIS_CONTRACT_ID,
                   reference_kind=runner.REFERENCE_KIND, cases=rows)
    index = tmp_path / "index.json"
    index.write_text(json.dumps(payload))
    assert [row["family"] for row in runner.calibrated_cases(index)] == ["f2", "f3", "f0"]
    payload["cases"][0]["demand_total"] = 111
    index.write_text(json.dumps(payload))
    with pytest.raises(ValueError, match="declared load ratio"):
        runner.calibrated_cases(index)
    payload["cases"][0]["demand_total"] = 112
    index.write_text(json.dumps(payload))
    (tmp_path / "f0.json").write_text("{}")
    with pytest.raises(ValueError, match="content has changed"):
        runner.calibrated_cases(index)


def test_oip_thesis_suite_forwards_screening_only(tmp_path, monkeypatch):
    runner = _runner("run_oip_thesis_pattern_campaigns")
    evidence = []
    for family in runner.THESIS_FAMILIES:
        result = tmp_path / f"{family}.json"
        result.write_text(json.dumps(dict(
            contract_id=THESIS_CONTRACT_ID,
            reference_kind=runner.REFERENCE_KIND,
            family=family,
            capacity_proven=True,
            proven_feasible_demand=100,
            proven_infeasible_demand=101,
        )))
        evidence.append(dict(
            family=family,
            demand_total=100,
            load_numerator=1,
            load_denominator=1,
            reference_result=result.name,
            reference_sha256=hashlib.sha256(result.read_bytes()).hexdigest(),
        ))
    index = tmp_path / "index.json"
    index.write_text(json.dumps(dict(
        contract_id=THESIS_CONTRACT_ID,
        reference_kind=runner.REFERENCE_KIND,
        cases=evidence,
    )))
    commands = []
    monkeypatch.setattr(runner.subprocess, "run", lambda command, **kwargs: commands.append(command) or SimpleNamespace(returncode=0))
    monkeypatch.setattr(sys, "argv", [
        "runner", "--output", str(tmp_path / "suite"),
        "--calibrated-cases", str(index), "--build-only", "--screening-only",
    ])
    runner.main()
    assert len(commands) == 3
    assert all("--screening-only" in command for command in commands)
    assert all(command[command.index("--k-values") + 1:command.index("--k-values") + 4] == ["40", "50", "62"] for command in commands)


def test_fixed_start_calibration_does_not_build_or_report_a_reservoir(tmp_path, monkeypatch):
    runner = _runner("run_thesis_experiment")
    args = runner.parser().parse_args([
        "--topology", "t5r", "--geometry", "g500", "--demand-family", "f2",
        "--objective", "journey_time", "--demand", "100", "--cabins", "20",
        "--method", "all_stop_phase", "--capacity-search",
        "--output-dir", str(tmp_path),
    ])
    monkeypatch.setattr(runner, "prepare_experiment_case", lambda *a, **kw: pytest.fail("reservoir built"))
    monkeypatch.setattr(runner, "_source_identity", lambda: {"test": True})
    case = {"thesis_contract_id": THESIS_CONTRACT_ID, "cabins": 20}
    monkeypatch.setattr(runner, "search_fixed_k_all_stop_capacity", lambda *a, **kw: {
        "probes": [{"case": case}], "proof_scope": "fixed_start_test",
    })
    runner.worker(args)
    result = json.loads((tmp_path / "result.json").read_text())
    assert result["case"] == case
    assert "problem_fingerprint" not in result  # Each demand probe has its own.
