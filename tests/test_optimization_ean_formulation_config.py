from __future__ import annotations

import pytest

from ropeway_skip_stop_optimization.optimization.ean import (
    EanBoardTimeFormulation,
    EanFormulationConfig,
    EanHorizonFormulation,
    EanOptimizationConfig,
    EanSlotActivationFormulation,
    EanStopSkipTimingFormulation,
    EanTimeBoundFormulation,
)


def test_ean_configuration_parses_independent_and_categorical_selections() -> None:
    config = EanOptimizationConfig.from_selection(
        "candidate_horizon_pruning,"
        "horizon_exact_time_activation,"
        "time_bounds_derived_visit_bounds,"
        "stop_skip_timing_affine,"
        "slot_activation_first_slot,"
        "board_time_projected_journey_time"
    )

    assert config.enable_candidate_horizon_pruning
    assert not config.enable_single_ring_dominated_ride_pruning
    assert config.formulation == EanFormulationConfig(
        horizon=EanHorizonFormulation.EXACT_TIME_ACTIVATION,
        time_bounds=EanTimeBoundFormulation.DERIVED_VISIT_BOUNDS,
        stop_skip_timing=EanStopSkipTimingFormulation.AFFINE,
        slot_activation=EanSlotActivationFormulation.FIRST_SLOT_IMPLICATIONS,
        board_time=EanBoardTimeFormulation.PROJECTED_JOURNEY_TIME,
    )
    assert config.selection_label() == (
        "candidate_horizon_pruning,"
        "horizon_exact_time_activation,"
        "time_bounds_derived_visit_bounds,"
        "stop_skip_timing_affine,"
        "slot_activation_first_slot,"
        "board_time_projected_journey_time"
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

    with pytest.raises(ValueError, match="at most one EAN slot-activation"):
        EanOptimizationConfig.from_selection(
            "slot_activation_per_slot,slot_activation_first_slot"
        )

    with pytest.raises(ValueError, match="at most one EAN board-time"):
        EanOptimizationConfig.from_selection(
            "board_time_explicit,board_time_projected_journey_time"
        )


def test_ean_configuration_all_and_none_keep_legacy_formulation_defaults() -> None:
    assert EanOptimizationConfig.from_selection("all").formulation == EanFormulationConfig()
    assert EanOptimizationConfig.from_selection("none").formulation == EanFormulationConfig()


def test_ean_configuration_all_accepts_formulation_override() -> None:
    config = EanOptimizationConfig.from_selection(
        "all,stop_skip_timing_affine,slot_activation_first_slot,board_time_projected_journey_time"
    )

    assert config.enabled_names()
    assert config.formulation.stop_skip_timing is EanStopSkipTimingFormulation.AFFINE
    assert config.formulation.slot_activation is EanSlotActivationFormulation.FIRST_SLOT_IMPLICATIONS
    assert config.formulation.board_time is EanBoardTimeFormulation.PROJECTED_JOURNEY_TIME


def test_ean_configuration_rejects_all_with_none() -> None:
    with pytest.raises(ValueError, match="cannot combine"):
        EanOptimizationConfig.from_selection("all,none")
