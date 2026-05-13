from __future__ import annotations

from dataclasses import dataclass

from ropeway_skip_stop_optimization.optimization.ean.artifact import EanBuildArtifact
from ropeway_skip_stop_optimization.optimization.ean.baselines.movement_plan_builder import (
    EanMovementPlanBuilder,
)
from ropeway_skip_stop_optimization.optimization.ean.models import (
    EanCabinStart,
    SkipStopTiming,
    SwitchVisitDefinition,
)
from ropeway_skip_stop_optimization.optimization.ean.plan import (
    EanCabinTrajectory,
    EanCabinVisit,
    EanMovementPlan,
    EanRouteDecision,
)


@dataclass(frozen=True)
class EarliestAllStopEanMovementPlanBuilder(EanMovementPlanBuilder):
    """Build a deterministic all-stop plan using earliest possible visit times.

    This is a baseline policy, not a feasibility repair heuristic. It does not
    add waiting to satisfy headway constraints.
    """

    def build(self, artifact: EanBuildArtifact) -> EanMovementPlan:
        artifact.validate()

        starts_by_cabin_id = _starts_by_cabin_id(artifact.cabin_starts)
        timings_by_switch_id = _timings_by_switch_id(artifact.timings)
        visits_by_cabin_id = _visits_by_cabin_id(artifact.switch_visits)

        trajectories: list[EanCabinTrajectory] = []
        for cabin_id in sorted(visits_by_cabin_id):
            if cabin_id not in starts_by_cabin_id:
                raise ValueError(f"switch visits reference cabin without start: {cabin_id!r}")
            visits = visits_by_cabin_id[cabin_id]
            start = starts_by_cabin_id[cabin_id]
            trajectories.append(
                EanCabinTrajectory(
                    cabin_id=cabin_id,
                    visits=_build_cabin_visits(
                        start=start,
                        visits=visits,
                        timings_by_switch_id=timings_by_switch_id,
                    ),
                )
            )

        plan = EanMovementPlan(
            scenario_id=artifact.scenario_id,
            horizon_seconds=artifact.config.horizon_seconds,
            model_end_seconds=artifact.config.model_end_seconds,
            trajectories=tuple(trajectories),
        )
        plan.validate()
        return plan


def _build_cabin_visits(
    start: EanCabinStart,
    visits: tuple[SwitchVisitDefinition, ...],
    timings_by_switch_id: dict[str, SkipStopTiming],
) -> tuple[EanCabinVisit, ...]:
    cabin_visits: list[EanCabinVisit] = []
    switch_time_seconds = start.time_seconds
    for visit in visits:
        timing = timings_by_switch_id[visit.switch_id]
        platform_entry_time_seconds = switch_time_seconds + timing.entry_to_platform_entry_seconds
        platform_exit_time_seconds = (
            platform_entry_time_seconds + timing.min_platform_entry_to_platform_exit_seconds
        )
        exit_switch_time_seconds = platform_exit_time_seconds + timing.platform_exit_to_exit_switch_seconds
        next_switch_time_seconds = exit_switch_time_seconds + timing.rope_to_next_switch_seconds

        cabin_visit = EanCabinVisit(
            cabin_id=visit.cabin_id,
            visit_index=visit.visit_index,
            switch_id=visit.switch_id,
            station_id=timing.station_id,
            decision=EanRouteDecision.STOP,
            switch_time_seconds=switch_time_seconds,
            platform_entry_time_seconds=platform_entry_time_seconds,
            platform_exit_time_seconds=platform_exit_time_seconds,
            exit_switch_time_seconds=exit_switch_time_seconds,
            next_switch_time_seconds=next_switch_time_seconds,
            wait_seconds=0.0,
        )
        cabin_visit.validate()
        cabin_visits.append(cabin_visit)
        switch_time_seconds = next_switch_time_seconds

    return tuple(cabin_visits)


def _starts_by_cabin_id(cabin_starts: tuple[EanCabinStart, ...]) -> dict[int, EanCabinStart]:
    result: dict[int, EanCabinStart] = {}
    duplicates: set[int] = set()
    for start in cabin_starts:
        start.validate()
        if start.cabin_id in result:
            duplicates.add(start.cabin_id)
        result[start.cabin_id] = start
    if duplicates:
        raise ValueError(f"duplicate EAN cabin starts: {duplicates}")
    return result


def _timings_by_switch_id(timings: tuple[SkipStopTiming, ...]) -> dict[str, SkipStopTiming]:
    result: dict[str, SkipStopTiming] = {}
    duplicates: set[str] = set()
    for timing in timings:
        timing.validate()
        if timing.switch_id in result:
            duplicates.add(timing.switch_id)
        result[timing.switch_id] = timing
    if duplicates:
        raise ValueError(f"duplicate EAN timings: {duplicates}")
    return result


def _visits_by_cabin_id(
    visits: tuple[SwitchVisitDefinition, ...],
) -> dict[int, tuple[SwitchVisitDefinition, ...]]:
    grouped: dict[int, list[SwitchVisitDefinition]] = {}
    for visit in visits:
        visit.validate()
        grouped.setdefault(visit.cabin_id, []).append(visit)

    result: dict[int, tuple[SwitchVisitDefinition, ...]] = {}
    for cabin_id, cabin_visits in grouped.items():
        result[cabin_id] = tuple(sorted(cabin_visits, key=lambda visit: visit.visit_index))
    return result
