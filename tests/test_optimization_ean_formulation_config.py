from __future__ import annotations

import pytest

from ropeway_skip_stop_optimization.optimization.ean import (
    EanBoardTimeFormulation,
    EanFormulationConfig,
    EanFleetMode,
    EanHorizonFormulation,
    EanOptimizationConfig,
    EanPassengerObjective,
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
        "board_time_projected_journey_time"
    )


def test_fixed_start_headway_precedence_is_independent_and_rejects_oip() -> None:
    config = EanOptimizationConfig.from_selection(
        "fixed_start_headway_precedence"
    )

    assert config.enable_fixed_start_headway_precedence
    assert config.selection_label() == "fixed_start_headway_precedence"
    with pytest.raises(NotImplementedError, match="fixed_start_headway_precedence"):
        config.resolved_for_fleet_mode(
            EanFleetMode.OPTIMIZED_INITIAL_PLACEMENT
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


def test_ean_configuration_all_and_none_use_current_formulation_defaults() -> None:
    default_formulation = EanFormulationConfig(
        stop_skip_timing=EanStopSkipTimingFormulation.AFFINE,
        slot_activation=EanSlotActivationFormulation.FIRST_SLOT_IMPLICATIONS,
        board_time=EanBoardTimeFormulation.AUTO,
    )

    assert EanOptimizationConfig.from_selection("all").formulation == default_formulation
    assert EanOptimizationConfig.from_selection("none").formulation == default_formulation
    assert EanOptimizationConfig.from_selection("all").selection_label() == "all"
    assert EanOptimizationConfig.from_selection("none").selection_label() == "none"
    resolved_oip = EanOptimizationConfig.from_selection("all").resolved_for_fleet_mode(
        EanFleetMode.OPTIMIZED_INITIAL_PLACEMENT
    )
    assert not resolved_oip.enable_candidate_horizon_pruning
    assert not resolved_oip.enable_single_ring_dominated_ride_pruning
    assert resolved_oip.enable_slot_time_relaxation_strengthening


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


def test_ean_configuration_resolves_board_time_by_objective_without_overriding_explicit_selection() -> None:
    automatic = EanOptimizationConfig.from_selection("all")

    assert (
        automatic.resolved_for_passenger_objective(
            EanPassengerObjective.JOURNEY_TIME
        ).formulation.board_time
        is EanBoardTimeFormulation.PROJECTED_JOURNEY_TIME
    )
    assert (
        automatic.resolved_for_passenger_objective(
            EanPassengerObjective.WAITING_TIME
        ).formulation.board_time
        is EanBoardTimeFormulation.EXPLICIT
    )

    explicit = EanOptimizationConfig.from_selection("all,board_time_explicit")
    assert (
        explicit.resolved_for_passenger_objective(
            EanPassengerObjective.JOURNEY_TIME
        ).formulation.board_time
        is EanBoardTimeFormulation.EXPLICIT
    )
