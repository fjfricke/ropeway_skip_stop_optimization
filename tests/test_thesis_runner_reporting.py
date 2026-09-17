"""Prevent misleading thesis summaries and accidental seeded comparisons."""
import json

import pytest

from benchmarks.export_thesis_frontend import _run_summary
from benchmarks.run_thesis_g500_calibration import validate_reusable_reference
from ropeway_skip_stop_optimization.benchmarking.thesis_cases import (
    ExperimentCaseSpec, ThesisTopology, ThesisGeometry, ThesisDemandFamily,
    ThesisDemandProfile, ThesisObjective, prepare_fixed_k_experiment,
)
from ropeway_skip_stop_optimization.benchmarking.ddd_fixed_k_arc_flow import (
    run_ddd_fixed_k_arc_flow,
)


CASE = dict(topology="t5r", geometry="g500", demand_family="f2",
            demand_profile="p0", objective="journey_time", demand_total=10)


def test_unvalidated_solver_objective_is_not_a_frontend_incumbent(tmp_path):
    summary = _run_summary(tmp_path, {"run": {"status": "optimal", "objective_value": 123}},
                           CASE, {"method": "labelled_arc_flow"})
    assert summary["validated"] is False
    assert summary["journeyTime"] is None


def test_export_keeps_zero_service_and_exposes_the_actual_seed(tmp_path):
    result = {"run": {"independent_validation_status": "feasible",
                      "independent_validation_objective": 0,
                      "seed_kind": "all_stop", "primal_seed_objective_value": 4}}
    summary = _run_summary(tmp_path, result, CASE, {"method": "labelled_arc_flow"})
    assert summary["journeyTime"] == 0
    assert summary["primalSeedKind"] == "all_stop"
    evolution = {"run": {"best": {
        "movement": {"feasible": True},
        "passengers": {"plan": {}, "served": 0, "unserved": 10},
    }}}
    summary = _run_summary(tmp_path, evolution, {**CASE, "objective": "unserved"},
                           {"method": "evolution"})
    assert summary["validated"] is True
    assert summary["served"] == 0


def test_reuse_rejects_an_identically_named_but_different_reference(tmp_path):
    (tmp_path / "case_spec.json").write_text(json.dumps({**CASE, "geometry": "g800"}))
    (tmp_path / "arguments.json").write_text("{}")
    (tmp_path / "result.json").write_text("{}")
    with pytest.raises(ValueError, match="geometry"):
        validate_reusable_reference(tmp_path, topology="t5r", objective="journey_time",
                                    cabins=10, resolution=30, maximum_demand=10)


def test_thesis_arc_flow_solves_without_automatic_primal_start(monkeypatch):
    pytest.importorskip("gurobipy")
    spec = ExperimentCaseSpec(ThesisTopology.T5R, ThesisGeometry.G500,
                              ThesisDemandFamily.F2, ThesisDemandProfile.P0,
                              ThesisObjective.JOURNEY_TIME, 4)
    config, prepared, _ = prepare_fixed_k_experiment(
        spec, cabins=1, time_limit_seconds=20, workers=1, seed=0,
    )
    assert config.use_primal_start is False

    def unexpected(*args, **kwargs):
        raise AssertionError("automatic seed solver/factory was called")

    module = "ropeway_skip_stop_optimization.benchmarking.ddd_fixed_k_arc_flow"
    monkeypatch.setattr(module + ".DddFixedKSeedCoordinator.solve", unexpected)
    monkeypatch.setattr(module + ".DddFixedKPrimalSeedFactory.build", unexpected)
    result = run_ddd_fixed_k_arc_flow(config, prepared_run=prepared).to_payload()
    assert result["seed_status"] == "disabled"
    assert result["seed_kind"] is None
    assert result["primal_seed_objective_value"] is None
    assert result["independent_validation_status"] == "feasible"
    assert result["validated_passenger_plan"] is not None


def test_better_fixed_timetable_assignment_is_not_a_model_error(monkeypatch):
    from dataclasses import replace
    from ropeway_skip_stop_optimization.benchmarking import ddd_fixed_k_arc_flow as module
    spec = ExperimentCaseSpec(ThesisTopology.T5R, ThesisGeometry.G500,
                              ThesisDemandFamily.F2, ThesisDemandProfile.P0,
                              ThesisObjective.JOURNEY_TIME, 4)
    config, prepared, _ = prepare_fixed_k_experiment(spec, cabins=1, time_limit_seconds=20, workers=1, seed=0)
    original = module.DddFixedKArcFlowOptimizer.solve

    def poor_assignment(self, *args, **kwargs):
        result = original(self, *args, **kwargs)
        return replace(result, objective_value=result.objective_value + 100, validated_upper_bound=result.objective_value + 100)

    monkeypatch.setattr(module.DddFixedKArcFlowOptimizer, "solve", poor_assignment)
    result = run_ddd_fixed_k_arc_flow(config, prepared_run=prepared).to_payload()
    assert result["validated_upper_bound"] == pytest.approx(result["independent_validation_objective"])
    assert sum(result["validated_passenger_plan"]["unserved_counts_by_demand_group_id"].values()) == 0
