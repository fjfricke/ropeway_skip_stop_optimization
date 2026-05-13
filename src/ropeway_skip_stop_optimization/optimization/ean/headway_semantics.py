from __future__ import annotations

from ropeway_skip_stop_optimization.optimization.ean.models import (
    HeadwayCheckpointDefinition,
    HeadwayCheckpointKind,
    StationEanConfig,
    StationWaitingMode,
)


POINT_HEADWAY_SEMANTICS = "point"
PLATFORM_EXIT_WAIT_OCCUPANCY_SEMANTICS = "platform_exit_wait_occupancy"


def uses_platform_exit_wait_occupancy(
    checkpoint: HeadwayCheckpointDefinition,
    station_config: StationEanConfig | None,
) -> bool:
    return (
        checkpoint.kind is HeadwayCheckpointKind.PLATFORM_EXIT
        and station_config is not None
        and station_config.waiting_mode is StationWaitingMode.END_OF_PLATFORM_WAIT
    )


def headway_semantics_label(
    checkpoint: HeadwayCheckpointDefinition,
    station_config: StationEanConfig | None,
) -> str:
    if uses_platform_exit_wait_occupancy(checkpoint, station_config):
        return PLATFORM_EXIT_WAIT_OCCUPANCY_SEMANTICS
    return POINT_HEADWAY_SEMANTICS
