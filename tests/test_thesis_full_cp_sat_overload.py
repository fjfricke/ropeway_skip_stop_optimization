from pathlib import Path

from ropeway_skip_stop_optimization.benchmarking.thesis_full_cp_sat_overload import (
    ThesisOverloadPilotConfig,
    lexicographic_score,
    prepare_pilot,
)
from ropeway_skip_stop_optimization.optimization.ddd.reservoir_cp_sat_certificate import (
    validate_reservoir_cp_plan,
)


ROOT = Path(__file__).resolve().parents[1]


def test_proven_all_stop_reference_transfers_to_nested_overload_demand(tmp_path):
    config = ThesisOverloadPilotConfig(
        reference_dir=ROOT / "results/thesis_phase_cell_capacity_references_20260916/reference_t5r_f2_r15",
        output_dir=tmp_path / "run",
    )
    prepared, plan, result = prepare_pilot(config)
    metrics = validate_reservoir_cp_plan(prepared.problem, plan)
    assert result["run"]["capacity"] == 2918
    assert sum(group.count for group in prepared.problem.demand_groups) == 3210
    assert prepared.problem.available_fleet_count == 69
    assert metrics.served == 2918
    assert metrics.unserved == 292
    assert metrics.used_fleet == 62
    assert lexicographic_score(prepared.problem, plan) < 2**53
