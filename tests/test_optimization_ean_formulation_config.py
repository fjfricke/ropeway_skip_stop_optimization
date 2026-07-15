from __future__ import annotations

import pytest

from ropeway_skip_stop_optimization.optimization.ean import (
    EanFormulationConfig,
    EanHorizonFormulation,
    EanOptimizationConfig,
    EanStopSkipTimingFormulation,
    EanTimeBoundFormulation,
)


def test_ean_configuration_parses_independent_and_categorical_selections() -> None:
    config = EanOptimizationConfig.from_selection(
        "candidate_horizon_pruning,"
        "horizon_exact_time_activation,"
        "time_bounds_derived_visit_bounds,"
        "stop_skip_timing_affine"
    )

    assert config.enable_candidate_horizon_pruning
    assert not config.enable_single_ring_dominated_ride_pruning
    assert config.formulation == EanFormulationConfig(
        horizon=EanHorizonFormulation.EXACT_TIME_ACTIVATION,
        time_bounds=EanTimeBoundFormulation.DERIVED_VISIT_BOUNDS,
        stop_skip_timing=EanStopSkipTimingFormulation.AFFINE,
    )
    assert config.selection_label() == (
        "candidate_horizon_pruning,"
        "horizon_exact_time_activation,"
        "time_bounds_derived_visit_bounds,"
        "stop_skip_timing_affine"
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

    with pytest.raises(ValueError, match="at most one EAN stop/skip timing"):
        EanOptimizationConfig.from_selection(
            "stop_skip_timing_big_m,stop_skip_timing_affine"
        )


def test_ean_configuration_all_and_none_keep_legacy_formulation_defaults() -> None:
    assert EanOptimizationConfig.from_selection("all").formulation == EanFormulationConfig()
    assert EanOptimizationConfig.from_selection("none").formulation == EanFormulationConfig()


def test_ean_configuration_all_accepts_formulation_override() -> None:
    config = EanOptimizationConfig.from_selection("all,stop_skip_timing_affine")

    assert config.enabled_names()
    assert config.formulation.stop_skip_timing is EanStopSkipTimingFormulation.AFFINE


def test_ean_configuration_rejects_all_with_none() -> None:
    with pytest.raises(ValueError, match="cannot combine"):
        EanOptimizationConfig.from_selection("all,none")
