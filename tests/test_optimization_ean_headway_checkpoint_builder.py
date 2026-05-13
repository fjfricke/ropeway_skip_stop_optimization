from __future__ import annotations

import pytest

from ropeway_skip_stop_optimization.optimization.ean import (
    HeadwayCheckpointKind,
    SkipStopHeadwayCheckpointBuilder,
    SkipStopTiming,
    StationEanConfig,
    StationWaitingMode,
)


def test_skip_stop_headway_checkpoint_builder_omits_platform_exit_for_no_waiting() -> None:
    builder = _builder()

    checkpoints = builder.build(
        timings=(_timing("sw_a", "A"),),
        station_configs=(StationEanConfig(station_id="A", waiting_mode=StationWaitingMode.NO_WAITING),),
    )

    assert tuple(checkpoint.id for checkpoint in checkpoints) == (
        "platform_entry::sw_a",
        "exit_switch::sw_a",
    )
    assert tuple(checkpoint.kind for checkpoint in checkpoints) == (
        HeadwayCheckpointKind.PLATFORM_ENTRY,
        HeadwayCheckpointKind.EXIT_SWITCH,
    )
    assert checkpoints[0].headway_seconds == 2.5
    assert checkpoints[0].applies_to_serve is True
    assert checkpoints[0].applies_to_skip is False
    assert checkpoints[0].waiting_modes == (StationWaitingMode.NO_WAITING,)
    assert checkpoints[1].headway_seconds == 3.5
    assert checkpoints[1].applies_to_serve is True
    assert checkpoints[1].applies_to_skip is True


def test_skip_stop_headway_checkpoint_builder_adds_platform_exit_for_end_waiting() -> None:
    builder = _builder()

    checkpoints = builder.build(
        timings=(_timing("sw_b", "B"),),
        station_configs=(StationEanConfig(station_id="B", waiting_mode=StationWaitingMode.END_OF_PLATFORM_WAIT),),
    )

    assert tuple(checkpoint.id for checkpoint in checkpoints) == (
        "platform_entry::sw_b",
        "platform_exit::sw_b",
        "exit_switch::sw_b",
    )
    assert tuple(checkpoint.kind for checkpoint in checkpoints) == (
        HeadwayCheckpointKind.PLATFORM_ENTRY,
        HeadwayCheckpointKind.PLATFORM_EXIT,
        HeadwayCheckpointKind.EXIT_SWITCH,
    )
    assert {checkpoint.waiting_modes for checkpoint in checkpoints} == {
        (StationWaitingMode.END_OF_PLATFORM_WAIT,)
    }


def test_skip_stop_headway_checkpoint_builder_marks_disabled_skip_at_exit() -> None:
    builder = _builder()

    checkpoints = builder.build(
        timings=(_timing("sw_a", "A", skip_allowed=False),),
        station_configs=(StationEanConfig(station_id="A", waiting_mode=StationWaitingMode.NO_WAITING),),
    )

    assert checkpoints[1].id == "exit_switch::sw_a"
    assert checkpoints[1].applies_to_serve is True
    assert checkpoints[1].applies_to_skip is False


def test_skip_stop_headway_checkpoint_builder_adds_platform_exit_for_fifo_buffer() -> None:
    builder = _builder()

    checkpoints = builder.build(
        timings=(_timing("sw_c", "C"),),
        station_configs=(
            StationEanConfig(
                station_id="C",
                waiting_mode=StationWaitingMode.STATION_FIFO_BUFFER,
                fifo_capacity=3,
            ),
        ),
    )

    assert tuple(checkpoint.id for checkpoint in checkpoints) == (
        "platform_entry::sw_c",
        "platform_exit::sw_c",
        "exit_switch::sw_c",
    )
    assert all(checkpoint.station_id == "C" for checkpoint in checkpoints)
    assert {checkpoint.waiting_modes for checkpoint in checkpoints} == {
        (StationWaitingMode.STATION_FIFO_BUFFER,)
    }


def test_skip_stop_headway_checkpoint_builder_handles_multiple_timings() -> None:
    builder = _builder()

    checkpoints = builder.build(
        timings=(_timing("sw_a", "A"), _timing("sw_b", "B")),
        station_configs=(
            StationEanConfig(station_id="A", waiting_mode=StationWaitingMode.NO_WAITING),
            StationEanConfig(station_id="B", waiting_mode=StationWaitingMode.END_OF_PLATFORM_WAIT),
        ),
    )

    assert tuple(checkpoint.id for checkpoint in checkpoints) == (
        "platform_entry::sw_a",
        "exit_switch::sw_a",
        "platform_entry::sw_b",
        "platform_exit::sw_b",
        "exit_switch::sw_b",
    )


def test_skip_stop_headway_checkpoint_builder_rejects_missing_references() -> None:
    builder = _builder()

    with pytest.raises(ValueError, match="without EAN config"):
        builder.build(
            timings=(_timing("sw_x", "X"),),
            station_configs=(StationEanConfig(station_id="A", waiting_mode=StationWaitingMode.NO_WAITING),),
        )

    with pytest.raises(ValueError, match="missing station headway"):
        builder.build(
            timings=(_timing("sw_x", "X"),),
            station_configs=(StationEanConfig(station_id="X", waiting_mode=StationWaitingMode.NO_WAITING),),
        )

    with pytest.raises(ValueError, match="missing exit switch headway"):
        SkipStopHeadwayCheckpointBuilder(
            station_headway_seconds_by_station_id={"A": 2.5},
            exit_switch_headway_seconds_by_switch_id={"sw_other": 3.5},
        ).build(
            timings=(_timing("sw_a", "A"),),
            station_configs=(StationEanConfig(station_id="A", waiting_mode=StationWaitingMode.NO_WAITING),),
        )


def test_skip_stop_headway_checkpoint_builder_rejects_duplicate_inputs_and_bad_headways() -> None:
    builder = _builder()

    with pytest.raises(ValueError, match="duplicate skip/stop timing"):
        builder.build(
            timings=(_timing("sw_a", "A"), _timing("sw_a", "A")),
            station_configs=(StationEanConfig(station_id="A", waiting_mode=StationWaitingMode.NO_WAITING),),
        )

    with pytest.raises(ValueError, match="duplicate station EAN config"):
        builder.build(
            timings=(_timing("sw_a", "A"),),
            station_configs=(
                StationEanConfig(station_id="A", waiting_mode=StationWaitingMode.NO_WAITING),
                StationEanConfig(station_id="A", waiting_mode=StationWaitingMode.NO_WAITING),
            ),
        )

    with pytest.raises(ValueError, match="station headway seconds must be positive"):
        SkipStopHeadwayCheckpointBuilder(
            station_headway_seconds_by_station_id={"A": 0.0},
            exit_switch_headway_seconds_by_switch_id={"sw_a": 3.5},
        ).build(
            timings=(_timing("sw_a", "A"),),
            station_configs=(StationEanConfig(station_id="A", waiting_mode=StationWaitingMode.NO_WAITING),),
        )


def _builder() -> SkipStopHeadwayCheckpointBuilder:
    return SkipStopHeadwayCheckpointBuilder(
        station_headway_seconds_by_station_id={"A": 2.5, "B": 2.75, "C": 3.0},
        exit_switch_headway_seconds_by_switch_id={"sw_a": 3.5, "sw_b": 3.75, "sw_c": 4.0},
    )


def _timing(switch_id: str, station_id: str, skip_allowed: bool = True) -> SkipStopTiming:
    return SkipStopTiming(
        switch_id=switch_id,
        station_id=station_id,
        entry_to_platform_entry_seconds=2.0,
        min_platform_entry_to_platform_exit_seconds=5.0,
        platform_exit_to_exit_switch_seconds=3.0,
        skip_entry_to_exit_switch_seconds=4.0,
        rope_to_next_switch_seconds=10.0,
        skip_allowed=skip_allowed,
    )
