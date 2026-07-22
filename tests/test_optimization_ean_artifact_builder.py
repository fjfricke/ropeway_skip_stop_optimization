from __future__ import annotations

import pytest

from ropeway_skip_stop_optimization.examples.three_station import build_three_station_scenario
from ropeway_skip_stop_optimization.examples.three_station_ean import (
    build_three_station_ean_config,
    build_three_station_ean_pattern_definition,
)
from ropeway_skip_stop_optimization.optimization.ean import (
    EanBuildProgressKind,
    EanBuildStage,
    EanCabinStartKind,
    EanCirculationPatternDefinition,
    network_ean_builder_for_pattern,
    StationWaitingMode,
)


def test_ring_ean_build_artifact_builder_builds_three_station_artifact() -> None:
    scenario = build_three_station_scenario()
    config = build_three_station_ean_config(scenario)
    pattern_definition = build_three_station_ean_pattern_definition()

    artifact = network_ean_builder_for_pattern(
        pattern_definition=pattern_definition
    ).build(scenario, config)

    artifact.validate()
    assert artifact.scenario_id == scenario.id
    assert artifact.circulation_state_ids == pattern_definition.state_node_ids
    assert tuple(timing.switch_id for timing in artifact.timings) == (
        pattern_definition.state_node_ids
    )
    assert {start.cabin_id for start in artifact.cabin_starts} == {0, 1, 2, 3}
    assert artifact.switch_visits
    assert artifact.switch_transitions
    assert artifact.headway_checkpoints
    assert artifact.headway_candidates
    assert artifact.headway_pairs

    timing_by_switch = {timing.switch_id: timing for timing in artifact.timings}
    assert timing_by_switch["M_entry_lr"].skip_allowed is True
    assert timing_by_switch["M_entry_rl"].skip_allowed is True
    assert timing_by_switch["L_entry_rl"].skip_allowed is False
    assert timing_by_switch["R_entry_lr"].skip_allowed is False

    starts_by_cabin = {start.cabin_id: start for start in artifact.cabin_starts}
    assert starts_by_cabin[0].first_switch_id == "M_entry_lr"
    assert starts_by_cabin[0].kind is EanCabinStartKind.FIXED
    assert starts_by_cabin[1].first_switch_id == "M_entry_rl"
    assert starts_by_cabin[1].kind is EanCabinStartKind.FIXED

    waiting_mode_by_station_id = {
        station_config.station_id: station_config.waiting_mode
        for station_config in artifact.config.station_configs
    }
    assert waiting_mode_by_station_id == {
        "L": StationWaitingMode.NO_WAITING,
        "M": StationWaitingMode.END_OF_PLATFORM_WAIT,
        "R": StationWaitingMode.NO_WAITING,
    }
    checkpoint_ids = {checkpoint.id for checkpoint in artifact.headway_checkpoints}
    assert "platform_entry::M_entry_lr" in checkpoint_ids
    assert "exit_switch::M_entry_lr" in checkpoint_ids
    assert "platform_exit::M_entry_lr" in checkpoint_ids


def test_network_ean_build_artifact_builder_rejects_duplicate_pattern_states() -> None:
    scenario = build_three_station_scenario()
    config = build_three_station_ean_config(scenario)

    with pytest.raises(ValueError, match="node ids must be nonempty and unique"):
        network_ean_builder_for_pattern(
            pattern_definition=EanCirculationPatternDefinition(
                id="duplicate_pattern",
                state_node_ids=("M_entry_lr", "M_entry_lr"),
            )
        ).build(scenario, config)


def test_ring_ean_build_artifact_reports_detailed_build_metrics() -> None:
    scenario = build_three_station_scenario()
    config = build_three_station_ean_config(scenario)
    events = []

    artifact = network_ean_builder_for_pattern(
        pattern_definition=build_three_station_ean_pattern_definition()
    ).build(scenario, config, progress_callback=events.append)

    metrics = artifact.build_metrics
    assert metrics is not None
    assert metrics.total_seconds >= sum(
        (
            metrics.timing_seconds,
            metrics.visit_seconds,
            metrics.checkpoint_seconds,
            metrics.candidate_seconds,
            metrics.pair_seconds,
            metrics.validation_seconds,
        )
    )
    assert metrics.checkpoint_count == len(artifact.headway_checkpoints)
    assert metrics.candidate_count == len(artifact.headway_candidates)
    assert metrics.pair_count == len(artifact.headway_pairs)
    assert metrics.peak_rss_bytes is None or metrics.peak_rss_bytes > 0
    assert any(
        event.stage is EanBuildStage.ARTIFACT_PAIRS
        and event.kind is EanBuildProgressKind.PROGRESS
        and event.pair_count
        for event in events
    )
