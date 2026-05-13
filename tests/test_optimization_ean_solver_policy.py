from __future__ import annotations

import pytest

from ropeway_skip_stop_optimization.optimization.ean import (
    EanPassengerServiceCheckpointConfig,
    GurobiSolverPolicy,
    GurobiSolverPolicyPreset,
    apply_gurobi_solver_policy,
    gurobi_solver_policy_for_preset,
)


def test_gurobi_solver_policy_presets() -> None:
    assert gurobi_solver_policy_for_preset(GurobiSolverPolicyPreset.DEFAULT) == GurobiSolverPolicy()
    assert gurobi_solver_policy_for_preset(GurobiSolverPolicyPreset.DEBUG_SHORT) == GurobiSolverPolicy(
        mip_gap=0.20,
        time_limit_seconds=60.0,
        method=3,
    )
    assert gurobi_solver_policy_for_preset(GurobiSolverPolicyPreset.QUICK_GOOD_SOLUTION) == GurobiSolverPolicy(
        mip_gap=0.10,
        method=3,
        mip_focus=1,
    )
    assert gurobi_solver_policy_for_preset(GurobiSolverPolicyPreset.PAPER_BENCHMARK) == GurobiSolverPolicy(
        mip_gap=0.01,
        method=3,
        mip_focus=2,
    )
    assert gurobi_solver_policy_for_preset(GurobiSolverPolicyPreset.EXACT_OPTIMALITY) == GurobiSolverPolicy(
        mip_gap=0.0,
        method=3,
        mip_focus=2,
    )


def test_gurobi_solver_policy_rejects_invalid_values() -> None:
    with pytest.raises(ValueError, match="mip_gap"):
        GurobiSolverPolicy(mip_gap=1.5).validate()
    with pytest.raises(ValueError, match="time_limit_seconds"):
        GurobiSolverPolicy(time_limit_seconds=0.0).validate()
    with pytest.raises(ValueError, match="mip_focus"):
        GurobiSolverPolicy(mip_focus=4).validate()


def test_ean_passenger_checkpoint_config_rejects_missing_resume_file(tmp_path) -> None:
    with pytest.raises(ValueError, match="does not exist"):
        EanPassengerServiceCheckpointConfig(read_solution_path=tmp_path / "missing.sol").validate()

    with pytest.raises(ValueError, match="must end in"):
        EanPassengerServiceCheckpointConfig(final_solution_path=tmp_path / "checkpoint.txt").validate()


def test_apply_gurobi_solver_policy_sets_only_configured_params() -> None:
    model = _FakeModel()

    apply_gurobi_solver_policy(
        model,
        GurobiSolverPolicy(
            mip_gap=0.10,
            time_limit_seconds=60.0,
            method=3,
            mip_focus=1,
        ),
    )

    assert model.Params.MIPGap == 0.10
    assert model.Params.TimeLimit == 60.0
    assert model.Params.Method == 3
    assert model.Params.MIPFocus == 1
    assert not hasattr(model.Params, "Threads")


class _FakeModel:
    def __init__(self) -> None:
        self.Params = _FakeParams()


class _FakeParams:
    pass
