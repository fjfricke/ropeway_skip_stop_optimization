"""A reusable reference is evidence, not an unchecked incumbent number."""
from dataclasses import dataclass
import json
from types import SimpleNamespace as NS
import pytest
from ropeway_skip_stop_optimization.benchmarking import thesis_reference_reuse as reuse


@dataclass
class Spec:
    demand_total: int = 100
    fingerprint: str = "domain"


def test_upper_reference_requires_matching_native_infeasibility(tmp_path):
    (tmp_path / "result.json").write_text(json.dumps({"method": "all_stop_phase", "case_fingerprint": "domain", "run": {
        "proof_scope": "REGULAR_NO_WAIT_ALL_STOP_COMMON_PHASE_AND_NESTED_DEMAND", "config": {"cabins": 2},
        "proven_infeasible_demand": 20, "probes": [{"demand": 20, "outcome": "unknown", "solver_status": "UNKNOWN"}]}}))
    with pytest.raises(ValueError, match="native infeasibility"):
        reuse.load_capacity_reference(tmp_path, Spec(), NS(cabins=2))


def test_waiting_reference_rejected_even_if_full_service_and_regular_dispatch(tmp_path, monkeypatch):
    (tmp_path / "result.json").write_text(json.dumps({"method": "all_stop_phase", "case_fingerprint": "domain", "run": {
        "proof_scope": "REGULAR_NO_WAIT_ALL_STOP_COMMON_PHASE_AND_NESTED_DEMAND", "config": {"cabins": 2}, "proven_feasible_demand": 10}}))
    monkeypatch.setattr(reuse, "prepare_experiment_case", lambda _: NS(problem=object()))
    plan = NS(trips=[NS(wait_ticks=(0, 1)), NS(wait_ticks=(0, 0))], ride_counts={"ride": 10})
    monkeypatch.setattr(reuse, "read_reservoir_cp_checkpoint", lambda *_: plan)
    with pytest.raises(ValueError, match="Waiting"):
        reuse.load_capacity_reference(tmp_path, Spec(), NS(cabins=2))
