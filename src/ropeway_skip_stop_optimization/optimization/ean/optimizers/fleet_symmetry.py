from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any

from ropeway_skip_stop_optimization.optimization.ean.artifact import (
    EanBuildArtifact,
)
from ropeway_skip_stop_optimization.optimization.ean.models import (
    EanFleetCardinalityMode,
    HeadwayCheckpointKind,
    SkipStopTiming,
    SwitchVisitDefinition,
)


VisitKey = tuple[int, int]


@dataclass(frozen=True)
class EanFleetSymmetryBreaker:
    """Exact cabin-label canonicalization at the OIP service boundary."""

    enable_full_initial_state_order: bool = True
    enable_inactive_variable_canonicalization: bool = True

    def add_constraints(
        self,
        *,
        model: Any,
        artifact: EanBuildArtifact,
        cabin_active: dict[int, Any],
        station_selected: dict[VisitKey, Any],
        rope_selected: dict[VisitKey, Any],
        switch_time: dict[VisitKey, Any],
        exit_switch_time: dict[VisitKey, Any],
        wait_time: dict[VisitKey, Any],
        stop: dict[VisitKey, Any],
        visits_by_cabin_id: dict[int, tuple[SwitchVisitDefinition, ...]],
        timing_by_switch_id: dict[str, SkipStopTiming],
        big_m: float,
    ) -> None:
        parameters = artifact.initial_placement_parameters
        if parameters is None:
            raise ValueError("OIP symmetry breaking needs fleet parameters")
        cabin_ids = sorted(cabin_active)
        exact_fleet = (
            artifact.fleet_cardinality_mode is EanFleetCardinalityMode.EXACT
        )

        if not exact_fleet:
            self._add_active_prefix(model, cabin_ids, cabin_active)

        if self.enable_full_initial_state_order:
            self._add_initial_category_order(
                model=model,
                cabin_ids=cabin_ids,
                cabin_active=cabin_active,
                station_selected=station_selected,
                rope_selected=rope_selected,
                visits_by_cabin_id=visits_by_cabin_id,
                phase_count=parameters.initial_phase_visit_count,
            )
            self._add_initial_station_order(
                model=model,
                cabin_ids=cabin_ids,
                station_selected=station_selected,
                switch_time=switch_time,
                phase_count=parameters.initial_phase_visit_count,
                big_m=big_m,
            )
            self._add_initial_platform_entry_order(
                model=model,
                artifact=artifact,
                cabin_ids=cabin_ids,
                station_selected=station_selected,
                rope_selected=rope_selected,
                switch_time=switch_time,
                stop=stop,
                visits_by_cabin_id=visits_by_cabin_id,
                timing_by_switch_id=timing_by_switch_id,
                phase_count=parameters.initial_phase_visit_count,
                big_m=big_m,
            )
        else:
            self._add_legacy_phase_order(
                model=model,
                cabin_ids=cabin_ids,
                cabin_active=cabin_active,
                station_selected=station_selected,
                rope_selected=rope_selected,
                visits_by_cabin_id=visits_by_cabin_id,
                phase_count=parameters.initial_phase_visit_count,
            )

        if (
            self.enable_inactive_variable_canonicalization
            and not exact_fleet
        ):
            self._canonicalize_inactive_operational_variables(
                model=model,
                cabin_active=cabin_active,
                switch_time=switch_time,
                exit_switch_time=exit_switch_time,
                wait_time=wait_time,
            )

    @staticmethod
    def _add_active_prefix(
        model: Any,
        cabin_ids: list[int],
        cabin_active: dict[int, Any],
    ) -> None:
        for previous_id, current_id in zip(cabin_ids, cabin_ids[1:]):
            model.addConstr(
                cabin_active[current_id] <= cabin_active[previous_id],
                name=f"cabin_activation_symmetry_{current_id}",
            )

    @staticmethod
    def _add_initial_category_order(
        *,
        model: Any,
        cabin_ids: list[int],
        cabin_active: dict[int, Any],
        station_selected: dict[VisitKey, Any],
        rope_selected: dict[VisitKey, Any],
        visits_by_cabin_id: dict[int, tuple[SwitchVisitDefinition, ...]],
        phase_count: int,
    ) -> None:
        category_count = 2 * phase_count
        category = {
            cabin_id: sum(
                (
                    2 * phase_index * station_selected[(cabin_id, visit.visit_index)]
                    + (2 * phase_index + 1)
                    * rope_selected[(cabin_id, visit.visit_index)]
                )
                for phase_index, visit in enumerate(
                    visits_by_cabin_id[cabin_id][:phase_count]
                )
            )
            for cabin_id in cabin_ids
        }
        for previous_id, current_id in zip(cabin_ids, cabin_ids[1:]):
            model.addConstr(
                category[previous_id]
                <= category[current_id]
                + category_count
                * (2 - cabin_active[previous_id] - cabin_active[current_id]),
                name=f"initial_state_category_symmetry_{current_id}",
            )

    @staticmethod
    def _add_legacy_phase_order(
        *,
        model: Any,
        cabin_ids: list[int],
        cabin_active: dict[int, Any],
        station_selected: dict[VisitKey, Any],
        rope_selected: dict[VisitKey, Any],
        visits_by_cabin_id: dict[int, tuple[SwitchVisitDefinition, ...]],
        phase_count: int,
    ) -> None:
        phase = {
            cabin_id: sum(
                visit.visit_index
                * (
                    station_selected[(cabin_id, visit.visit_index)]
                    + rope_selected[(cabin_id, visit.visit_index)]
                )
                for visit in visits_by_cabin_id[cabin_id][:phase_count]
            )
            for cabin_id in cabin_ids
        }
        for previous_id, current_id in zip(cabin_ids, cabin_ids[1:]):
            model.addConstr(
                phase[previous_id]
                <= phase[current_id]
                + phase_count
                * (2 - cabin_active[previous_id] - cabin_active[current_id]),
                name=f"initial_phase_symmetry_{current_id}",
            )

    @staticmethod
    def _add_initial_platform_entry_order(
        *,
        model: Any,
        artifact: EanBuildArtifact,
        cabin_ids: list[int],
        station_selected: dict[VisitKey, Any],
        rope_selected: dict[VisitKey, Any],
        switch_time: dict[VisitKey, Any],
        stop: dict[VisitKey, Any],
        visits_by_cabin_id: dict[int, tuple[SwitchVisitDefinition, ...]],
        timing_by_switch_id: dict[str, SkipStopTiming],
        phase_count: int,
        big_m: float,
    ) -> None:
        entry_headway_by_switch_id = {
            checkpoint.switch_id: checkpoint.headway_seconds
            for checkpoint in artifact.headway_checkpoints
            if checkpoint.kind is HeadwayCheckpointKind.PLATFORM_ENTRY
        }
        for phase_index in range(phase_count):
            reference_visit = visits_by_cabin_id[cabin_ids[0]][phase_index]
            timing = timing_by_switch_id[reference_visit.switch_id]
            headway = entry_headway_by_switch_id[reference_visit.switch_id]
            for leader_position, leader_id in enumerate(cabin_ids):
                leader_visit = visits_by_cabin_id[leader_id][phase_index]
                leader_key = (leader_id, leader_visit.visit_index)
                leader_selected = (
                    station_selected[leader_key] + rope_selected[leader_key]
                )
                leader_entry = (
                    switch_time[leader_key]
                    + timing.entry_to_platform_entry_seconds
                )
                for follower_id in cabin_ids[leader_position + 1 :]:
                    follower_visit = visits_by_cabin_id[follower_id][phase_index]
                    follower_key = (follower_id, follower_visit.visit_index)
                    follower_selected = (
                        station_selected[follower_key] + rope_selected[follower_key]
                    )
                    follower_entry = (
                        switch_time[follower_key]
                        + timing.entry_to_platform_entry_seconds
                    )
                    model.addConstr(
                        leader_entry + headway
                        <= follower_entry
                        + big_m
                        * (
                            4
                            - leader_selected
                            - follower_selected
                            - stop[leader_key]
                            - stop[follower_key]
                        ),
                        name=(
                            f"initial_platform_entry_order_"
                            f"{reference_visit.switch_id}_{leader_id}_{follower_id}"
                        ),
                    )

    @staticmethod
    def _add_initial_station_order(
        *,
        model: Any,
        cabin_ids: list[int],
        station_selected: dict[VisitKey, Any],
        switch_time: dict[VisitKey, Any],
        phase_count: int,
        big_m: float,
    ) -> None:
        for phase_index in range(phase_count):
            for leader_id, follower_id in zip(cabin_ids, cabin_ids[1:]):
                leader_key = (leader_id, phase_index)
                follower_key = (follower_id, phase_index)
                model.addConstr(
                    switch_time[leader_key]
                    <= switch_time[follower_key]
                    + big_m
                    * (
                        2
                        - station_selected[leader_key]
                        - station_selected[follower_key]
                    ),
                    name=(
                        f"initial_station_order_"
                        f"{phase_index}_{leader_id}_{follower_id}"
                    ),
                )

    @staticmethod
    def _canonicalize_inactive_operational_variables(
        *,
        model: Any,
        cabin_active: dict[int, Any],
        switch_time: dict[VisitKey, Any],
        exit_switch_time: dict[VisitKey, Any],
        wait_time: dict[VisitKey, Any],
    ) -> None:
        for variables, label in (
            (switch_time, "switch_time"),
            (exit_switch_time, "exit_switch_time"),
            (wait_time, "wait_time"),
        ):
            for key, variable in variables.items():
                lower = float(variable.LB)
                upper = float(variable.UB)
                if not math.isfinite(lower) or not math.isfinite(upper):
                    raise ValueError(
                        f"inactive {label} canonicalization needs finite bounds"
                    )
                if upper <= lower:
                    continue
                active = cabin_active[key[0]]
                model.addConstr(
                    variable <= lower + (upper - lower) * active,
                    name=f"inactive_{label}_{key[0]}_{key[1]}",
                )
