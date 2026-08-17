from __future__ import annotations

import math

import pytest

from ropeway_skip_stop_optimization.optimization.ddd.network_refinement_model import (
    DddNetworkTimeRefinementStatus,
)
from ropeway_skip_stop_optimization.optimization.ddd.termination_policy import (
    DddRoundTerminationPolicy,
)


def _decide(**overrides: object):
    arguments: dict[str, object] = {
        "cp_sat_exact_infeasible": False,
        "has_incumbent": True,
        "refinement_stalled": False,
        "time_split_count": 0,
        "new_prefix_cut_count": 0,
        "new_resource_row_count": 0,
        "new_aggregate_support_cut_count": 0,
        "trajectory_pool_added_option_count": 0,
        "lower_bound": 1.0,
        "upper_bound": 2.0,
    }
    arguments.update(overrides)
    return DddRoundTerminationPolicy(bound_tolerance=1e-9).decide(
        **arguments  # type: ignore[arg-type]
    )


def test_exact_infeasibility_without_incumbent_has_priority() -> None:
    decision = _decide(
        cp_sat_exact_infeasible=True,
        has_incumbent=False,
        time_split_count=1,
    )

    assert decision.status is DddNetworkTimeRefinementStatus.EXACT_INFEASIBLE
    assert math.isinf(decision.upper_bound)
    assert decision.clear_primal_evaluation


def test_exact_infeasibility_with_incumbent_is_internal_error() -> None:
    decision = _decide(cp_sat_exact_infeasible=True, upper_bound=5.0)

    assert decision.status is DddNetworkTimeRefinementStatus.INVALID_INTERNAL
    assert decision.upper_bound == 5.0
    assert decision.clear_primal_evaluation


def test_stalled_round_terminates_only_without_core_refinement() -> None:
    stalled = _decide(refinement_stalled=True)
    continuing = _decide(refinement_stalled=True, new_resource_row_count=1)

    assert stalled.status is DddNetworkTimeRefinementStatus.REFINEMENT_STALLED
    assert not continuing.should_terminate


def test_closed_bound_gap_is_optimal() -> None:
    decision = _decide(lower_bound=2.0, upper_bound=2.0)

    assert decision.status is DddNetworkTimeRefinementStatus.OPTIMAL


def test_missing_incumbent_without_refinement_is_unknown() -> None:
    decision = _decide(has_incumbent=False)

    assert decision.status is DddNetworkTimeRefinementStatus.UNKNOWN_NO_INCUMBENT


def test_new_trajectory_column_keeps_rounds_running() -> None:
    decision = _decide(trajectory_pool_added_option_count=1)

    assert not decision.should_terminate


def test_negative_refinement_count_is_rejected() -> None:
    with pytest.raises(ValueError, match="counts"):
        _decide(new_prefix_cut_count=-1)
