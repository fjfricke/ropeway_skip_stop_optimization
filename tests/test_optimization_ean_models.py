from __future__ import annotations

import pytest

from ropeway_skip_stop_optimization.optimization.ean import (
    EanActivationReference,
    EanCabinStart,
    EanCabinStartKind,
    EanConfig,
    EanTimeReference,
    HeadwayCandidate,
    HeadwayCheckpointDefinition,
    HeadwayCheckpointKind,
    HeadwayPair,
    Passenger,
    RideCandidate,
    SkipStopTiming,
    StationEanConfig,
    StationWaitingMode,
    SwitchVisitDefinition,
)


def test_ean_config_validates_station_configs_and_model_end() -> None:
    config = EanConfig(
        horizon_seconds=600.0,
        tail_seconds=120.0,
        cabin_capacity=8,
        station_configs=(
            StationEanConfig(station_id="M", waiting_mode=StationWaitingMode.NO_WAITING),
            StationEanConfig(
                station_id="R",
                waiting_mode=StationWaitingMode.STATION_FIFO_BUFFER,
                fifo_capacity=4,
            ),
        ),
    )

    config.validate()

    assert config.model_end_seconds == 720.0


def test_station_fifo_capacity_is_required_only_for_fifo_waiting() -> None:
    StationEanConfig(
        station_id="M",
        waiting_mode=StationWaitingMode.STATION_FIFO_BUFFER,
        fifo_capacity=2,
    ).validate()

    with pytest.raises(ValueError, match="positive fifo_capacity"):
        StationEanConfig(
            station_id="M",
            waiting_mode=StationWaitingMode.STATION_FIFO_BUFFER,
        ).validate()

    with pytest.raises(ValueError, match="only valid"):
        StationEanConfig(
            station_id="M",
            waiting_mode=StationWaitingMode.END_OF_PLATFORM_WAIT,
            fifo_capacity=2,
        ).validate()


def test_skip_stop_timing_validates_positive_durations() -> None:
    timing = SkipStopTiming(
        switch_id="sw_m_entry_lr",
        station_id="M",
        entry_to_platform_entry_seconds=3.0,
        min_platform_entry_to_platform_exit_seconds=8.0,
        platform_exit_to_exit_switch_seconds=3.0,
        skip_entry_to_exit_switch_seconds=4.0,
        rope_to_next_switch_seconds=30.0,
    )

    timing.validate()

    with pytest.raises(ValueError, match="skip_entry_to_exit_switch_seconds"):
        SkipStopTiming(
            switch_id="sw_m_entry_lr",
            station_id="M",
            entry_to_platform_entry_seconds=3.0,
            min_platform_entry_to_platform_exit_seconds=8.0,
            platform_exit_to_exit_switch_seconds=3.0,
            skip_entry_to_exit_switch_seconds=0.0,
            rope_to_next_switch_seconds=30.0,
        ).validate()


def test_core_ean_records_validate() -> None:
    EanCabinStart(
        cabin_id=0,
        first_switch_id="sw_l_entry",
        kind=EanCabinStartKind.FIXED,
        time_seconds=0.0,
    ).validate()
    SwitchVisitDefinition(
        cabin_id=0,
        visit_index=3,
        switch_id="sw_m_entry_lr",
    ).validate()
    HeadwayCheckpointDefinition(
        id="platform_entry::M::sw_m_entry_lr",
        kind=HeadwayCheckpointKind.PLATFORM_ENTRY,
        switch_id="sw_m_entry_lr",
        station_id="M",
        headway_seconds=2.5,
        applies_to_serve=True,
        applies_to_skip=False,
        waiting_modes=(StationWaitingMode.NO_WAITING,),
    ).validate()
    HeadwayCandidate(
        id="candidate::0::3::platform_entry::M::sw_m_entry_lr",
        checkpoint_id="platform_entry::M::sw_m_entry_lr",
        cabin_id=0,
        visit_index=3,
        time_reference=EanTimeReference.PLATFORM_ENTRY_TIME,
        activation_reference=EanActivationReference.SERVE,
    ).validate()
    HeadwayPair(
        id="pair::a::b",
        checkpoint_id="platform_entry::M::sw_m_entry_lr",
        first_candidate_id="a",
        second_candidate_id="b",
        headway_seconds=2.5,
    ).validate()


def test_headway_checkpoint_must_apply_to_a_path() -> None:
    with pytest.raises(ValueError, match="serve and/or skip"):
        HeadwayCheckpointDefinition(
            id="exit_switch::M::sw_m_entry_lr",
            kind=HeadwayCheckpointKind.EXIT_SWITCH,
            switch_id="sw_m_entry_lr",
            station_id="M",
            headway_seconds=2.5,
            applies_to_serve=False,
            applies_to_skip=False,
            waiting_modes=(StationWaitingMode.NO_WAITING,),
        ).validate()


def test_passenger_and_ride_candidate_validate() -> None:
    Passenger(
        id="p0",
        origin_station_id="L",
        destination_station_id="R",
        release_time_seconds=15.0,
    ).validate()
    RideCandidate(
        id="ride::p0::c0::1::3",
        passenger_id="p0",
        cabin_id=0,
        board_visit_index=1,
        alight_visit_index=3,
    ).validate()

    with pytest.raises(ValueError, match="origin and destination"):
        Passenger(
            id="p0",
            origin_station_id="L",
            destination_station_id="L",
            release_time_seconds=15.0,
        ).validate()

    with pytest.raises(ValueError, match="before"):
        RideCandidate(
            id="ride::p0::c0::3::3",
            passenger_id="p0",
            cabin_id=0,
            board_visit_index=3,
            alight_visit_index=3,
        ).validate()
