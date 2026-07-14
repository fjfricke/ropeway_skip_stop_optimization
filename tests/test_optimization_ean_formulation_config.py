from __future__ import annotations

import pytest

from ropeway_skip_stop_optimization.optimization.ean import (
    EanFormulationConfig,
    EanHorizonFormulation,
    EanOptimizationConfig,
    EanTimeBoundFormulation,
)


def test_ean_configuration_parses_independent_and_categorical_selections() -> None:
    config = EanOptimizationConfig.from_selection(
        "candidate_horizon_pruning,"
        "horizon_exact_time_activation,"
        "time_bounds_derived_visit_bounds"
    )

    assert config.enable_candidate_horizon_pruning
    assert not config.enable_single_ring_dominated_ride_pruning
    assert config.formulation == EanFormulationConfig(
        horizon=EanHorizonFormulation.EXACT_TIME_ACTIVATION,
        time_bounds=EanTimeBoundFormulation.DERIVED_VISIT_BOUNDS,
    )
    assert config.selection_label() == (
        "candidate_horizon_pruning,"
        "horizon_exact_time_activation,"
        "time_bounds_derived_visit_bounds"
    )


def test_ean_configuration_rejects_multiple_values_in_one_category() -> None:
    with pytest.raises(ValueError, match="at most one EAN horizon"):
        EanOptimizationConfig.from_selection(
            "horizon_legacy,horizon_exact_time_activation"
        )

    with pytest.raises(ValueError, match="at most one EAN time-bound"):
        EanOptimizationConfig.from_selection(
            "time_bounds_legacy_plus_10,time_bounds_derived_visit_bounds"
        )


def test_ean_configuration_all_and_none_keep_legacy_formulation_defaults() -> None:
    assert EanOptimizationConfig.from_selection("all").formulation == EanFormulationConfig()
    assert EanOptimizationConfig.from_selection("none").formulation == EanFormulationConfig()

