from __future__ import annotations

from dataclasses import dataclass
import math

from ropeway_skip_stop_optimization.optimization.ddd.models import (
    DddFixedStart,
    DddMovementProblem,
    DddMovementState,
    DddResource,
    DddResourceUsage,
    DddRouteDecision,
    DddRouteOption,
)
from ropeway_skip_stop_optimization.optimization.ean.artifact import EanBuildArtifact
from ropeway_skip_stop_optimization.optimization.ean.models import (
    EanCabinStartKind,
    EanFleetMode,
    HeadwayCheckpointDefinition,
    HeadwayCheckpointKind,
    SkipStopTiming,
    StationWaitingMode,
)
from ropeway_skip_stop_optimization.optimization.ean.network import (
    EanMovementEffect,
    EanPassengerBehavior,
    EanRouteOption,
)
from ropeway_skip_stop_optimization.models import HeadwayRouteBehavior


@dataclass(frozen=True)
class EanArtifactToDddMovementProblemAdapter:
    tolerance_seconds: float = 1e-9

    def build(self, artifact: EanBuildArtifact) -> DddMovementProblem:
        artifact.validate()
        if self.tolerance_seconds < 0:
            raise ValueError("DDD adapter tolerance_seconds must be nonnegative")
        if artifact.fleet_mode is not EanFleetMode.FIXED_STARTS:
            raise ValueError("DDD reference oracle supports fixed starts only")
        if artifact.movement_network is None:
            raise ValueError("DDD reference oracle requires movement-network provenance")
        if len(artifact.circulation_pattern_ids) != 1:
            raise ValueError("DDD reference oracle requires exactly one circulation pattern")
        unsupported_waiting = tuple(
            station
            for station in artifact.config.station_configs
            if station.waiting_mode is not StationWaitingMode.NO_WAITING
        )
        if unsupported_waiting:
            details = ", ".join(
                f"{station.station_id}={station.waiting_mode.value}"
                for station in unsupported_waiting
            )
            raise ValueError(
                "DDD reference oracle does not yet support station waiting: "
                f"{details}"
            )
        if any(start.kind is not EanCabinStartKind.FIXED for start in artifact.cabin_starts):
            raise ValueError("DDD reference oracle requires exact fixed start times")

        network = artifact.movement_network
        pattern = network.pattern(artifact.circulation_pattern_ids[0])
        station_config_by_id = {
            station.station_id: station for station in artifact.config.station_configs
        }
        options_by_id = {option.id: option for option in network.route_options}
        timing_by_state_id = {timing.switch_id: timing for timing in artifact.timings}
        checkpoints_by_state_id: dict[str, list[HeadwayCheckpointDefinition]] = {}
        for checkpoint in artifact.headway_checkpoints:
            station_config = station_config_by_id[checkpoint.station_id]
            if station_config.waiting_mode not in checkpoint.waiting_modes:
                raise ValueError(
                    f"DDD checkpoint {checkpoint.id!r} does not apply to configured "
                    f"waiting mode {station_config.waiting_mode.value!r}"
                )
            checkpoints_by_state_id.setdefault(checkpoint.switch_id, []).append(checkpoint)

        allowed_option_ids = {
            option_id
            for position_options in pattern.route_option_ids_by_position
            for option_id in position_options
        }
        route_options = tuple(
            self._route_option(
                options_by_id[option_id],
                timing_by_state_id,
                checkpoints_by_state_id,
                artifact,
            )
            for option_id in sorted(allowed_option_ids)
        )
        resource_ids = {
            usage.resource_id
            for option in route_options
            for usage in option.resource_usages
        }
        checkpoint_by_id = {
            checkpoint.id: checkpoint for checkpoint in artifact.headway_checkpoints
        }
        resources = tuple(
            DddResource(
                id=resource_id,
                headway_seconds=artifact.headway_rule_for_checkpoint(
                    checkpoint_by_id[resource_id]
                ).minimum_seconds,
                maximum_headway_seconds=artifact.headway_rule_for_checkpoint(
                    checkpoint_by_id[resource_id]
                ).maximum_seconds,
            )
            for resource_id in sorted(resource_ids)
        )
        visit_count_by_cabin_id: dict[int, int] = {}
        for visit in artifact.switch_visits:
            visit_count_by_cabin_id[visit.cabin_id] = (
                visit_count_by_cabin_id.get(visit.cabin_id, 0) + 1
            )
        starts = tuple(
            DddFixedStart(
                cabin_id=start.cabin_id,
                state_id=start.first_switch_id,
                time_seconds=start.time_seconds,
                max_visit_count=visit_count_by_cabin_id[start.cabin_id],
            )
            for start in sorted(artifact.cabin_starts, key=lambda item: item.cabin_id)
        )
        problem = DddMovementProblem(
            scenario_id=artifact.scenario_id,
            passenger_service_end_seconds=artifact.config.passenger_service_end_seconds,
            operational_end_seconds=artifact.config.operational_end_seconds,
            states=tuple(DddMovementState(state.id) for state in network.states),
            starts=starts,
            route_options=route_options,
            resources=resources,
        )
        problem.validate()
        return problem

    def _route_option(
        self,
        option: EanRouteOption,
        timing_by_state_id: dict[str, SkipStopTiming],
        checkpoints_by_state_id: dict[str, list[HeadwayCheckpointDefinition]],
        artifact: EanBuildArtifact,
    ) -> DddRouteOption:
        if option.movement_effect is not EanMovementEffect.CONTINUE:
            raise ValueError(
                "DDD reference oracle does not yet support movement effect "
                f"{option.movement_effect.value!r}"
            )
        if not math.isclose(
            option.minimum_seconds,
            option.maximum_seconds,
            rel_tol=0.0,
            abs_tol=self.tolerance_seconds,
        ):
            raise ValueError("DDD reference oracle requires exact route durations")
        timing = timing_by_state_id[option.from_state_id]
        if option.passenger_behavior is EanPassengerBehavior.SERVICE:
            decision = DddRouteDecision.STOP
            platform_entry = timing.entry_to_platform_entry_seconds
            platform_exit = (
                platform_entry + timing.min_platform_entry_to_platform_exit_seconds
            )
            exit_switch = platform_exit + timing.platform_exit_to_exit_switch_seconds
        elif option.passenger_behavior is EanPassengerBehavior.SKIP:
            decision = DddRouteDecision.SKIP
            platform_entry = None
            platform_exit = None
            exit_switch = timing.skip_entry_to_exit_switch_seconds
        else:
            raise ValueError("DDD reference oracle encountered unknown passenger behavior")
        expected_duration = exit_switch + timing.rope_to_next_switch_seconds
        if not math.isclose(
            option.minimum_seconds,
            expected_duration,
            rel_tol=0.0,
            abs_tol=self.tolerance_seconds,
        ):
            raise ValueError(
                f"DDD route duration mismatch for {option.id!r}: "
                f"network={option.minimum_seconds}, timing={expected_duration}"
            )

        compatibility_resource_ids = {
            usage.resource_id
            for usage in option.resource_usages
            if usage.checkpoint_kind is not None
        }
        usages: list[DddResourceUsage] = []
        for checkpoint in sorted(
            checkpoints_by_state_id.get(option.from_state_id, ()),
            key=lambda item: item.id,
        ):
            applies = (
                checkpoint.applies_to_serve
                if decision is DddRouteDecision.STOP
                else checkpoint.applies_to_skip
            )
            if not applies:
                continue
            if checkpoint.id not in compatibility_resource_ids:
                raise ValueError(
                    f"DDD route {option.id!r} is missing checkpoint resource "
                    f"{checkpoint.id!r}"
                )
            offset = _checkpoint_offset(
                checkpoint.kind,
                decision=decision,
                platform_entry=platform_entry,
                platform_exit=platform_exit,
                exit_switch=exit_switch,
            )
            usages.append(
                DddResourceUsage(
                    resource_id=checkpoint.id,
                    leader_clear_offset_seconds=offset,
                    follower_enter_offset_seconds=offset,
                    separation_after_seconds=(
                        artifact.headway_rule_for_checkpoint(
                            checkpoint
                        ).required_seconds(
                            _headway_behavior(decision),
                            _headway_behavior(decision),
                        )
                    ),
                )
            )
        return DddRouteOption(
            id=option.id,
            from_state_id=option.from_state_id,
            to_state_id=option.to_state_id,
            station_id=option.station_id,
            decision=decision,
            duration_seconds=expected_duration,
            platform_entry_offset_seconds=platform_entry,
            platform_exit_offset_seconds=platform_exit,
            exit_switch_offset_seconds=exit_switch,
            resource_usages=tuple(usages),
        )


def _checkpoint_offset(
    kind: HeadwayCheckpointKind,
    *,
    decision: DddRouteDecision,
    platform_entry: float | None,
    platform_exit: float | None,
    exit_switch: float,
) -> float:
    if kind is HeadwayCheckpointKind.PLATFORM_ENTRY:
        if decision is not DddRouteDecision.STOP or platform_entry is None:
            raise ValueError("platform-entry checkpoint requires a STOP route")
        return platform_entry
    if kind is HeadwayCheckpointKind.PLATFORM_EXIT:
        if decision is not DddRouteDecision.STOP or platform_exit is None:
            raise ValueError("platform-exit checkpoint requires a STOP route")
        return platform_exit
    if kind in (
        HeadwayCheckpointKind.EXIT_SWITCH,
        HeadwayCheckpointKind.SERVICE_MECHANISM,
    ):
        return exit_switch
    raise ValueError(f"unsupported DDD checkpoint kind: {kind}")


def _headway_behavior(decision: DddRouteDecision) -> HeadwayRouteBehavior:
    return (
        HeadwayRouteBehavior.SERVICE
        if decision is DddRouteDecision.STOP
        else HeadwayRouteBehavior.BYPASS
    )
