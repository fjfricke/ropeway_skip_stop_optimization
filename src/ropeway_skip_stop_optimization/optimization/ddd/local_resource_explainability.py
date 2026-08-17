from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from ropeway_skip_stop_optimization.optimization.ddd.cp_sat_primal import (
    DddCpSatPrimalOracle,
    DddCpSatPrimalStatus,
)
from ropeway_skip_stop_optimization.optimization.ddd.network_time_space import (
    DddNetworkTimeProblem,
)
from ropeway_skip_stop_optimization.optimization.ddd.time_refinement import (
    DddRecoveredSchedule,
)
from ropeway_skip_stop_optimization.optimization.ddd.timed_flow_cover import (
    DddCpSatTimedFlowSupport,
    DddTimedArcFlowCount,
    DddTimedFlowCoverCut,
    DddTimedFlowRegion,
    DddTimedFlowThresholdLiteral,
)


class DddCpSatLocalExplainabilityClass(StrEnum):
    """Smallest tested physical scope that proves a rejected support impossible."""

    SINGLE_RESOURCE = "single_resource"
    RESOURCE_GROUP = "resource_group"
    GLOBAL = "global"
    UNRESOLVED = "unresolved"


@dataclass(frozen=True)
class DddTimedFlowResourceWindow:
    """Diagnostic time envelope induced by one core literal on one resource."""

    literal_id: str
    route_option_id: str
    station_id: str
    resource_id: str
    minimum_flow: int
    entry_lower_tick: int
    entry_upper_tick: int
    blocked_until_lower_tick: int
    blocked_until_upper_tick: int


@dataclass(frozen=True)
class DddCpSatLocalResourceProbe:
    resource_ids: tuple[str, ...]
    status: DddCpSatPrimalStatus
    wall_seconds: float
    conflict_count: int
    branch_count: int
    core_literal_count: int
    infeasible_core: tuple[DddTimedFlowThresholdLiteral, ...]
    all_core_literals_touch_enabled_resources: bool


@dataclass(frozen=True)
class DddCpSatLocalExplainabilityObservation:
    round_index: int
    classification: DddCpSatLocalExplainabilityClass
    explaining_resource_ids: tuple[str, ...]
    full_support: DddCpSatTimedFlowSupport
    core_cut: DddTimedFlowCoverCut
    station_ids: tuple[str, ...]
    resource_windows: tuple[DddTimedFlowResourceWindow, ...]
    probes: tuple[DddCpSatLocalResourceProbe, ...]

    @property
    def probe_seconds(self) -> float:
        return sum(probe.wall_seconds for probe in self.probes)


@dataclass(frozen=True)
class DddCpSatLocalCutCoverage:
    round_index: int
    cut_id: str
    excluded_observed_support_count: int
    excluded_other_support_count: int


@dataclass(frozen=True)
class DddCpSatLocalExplainabilityReport:
    observation_count: int
    single_resource_count: int
    resource_group_count: int
    global_count: int
    unresolved_count: int
    resource_touching_core_count: int
    total_probe_seconds: float
    unique_station_ids: tuple[str, ...]
    unique_resource_ids: tuple[str, ...]
    cut_coverage: tuple[DddCpSatLocalCutCoverage, ...]


@dataclass(frozen=True)
class DddCpSatLocalResourceAnalyzer:
    """Re-probe an infeasible timed support under local resource relaxations.

    Every probe retains all route, timing, horizon, and support assumptions, but
    removes no-overlap constraints outside the selected resource scope.  Hence
    local infeasibility is a valid proof for the complete physical model;
    feasibility or UNKNOWN only means that this particular local probe does not
    explain the original conflict.
    """

    time_limit_seconds: float = 0.5
    num_workers: int = 8

    def analyze(
        self,
        problem: DddNetworkTimeProblem,
        *,
        round_index: int,
        full_support: DddCpSatTimedFlowSupport,
        core: tuple[DddTimedFlowThresholdLiteral, ...],
        hint_schedules: tuple[DddRecoveredSchedule, ...] = (),
    ) -> DddCpSatLocalExplainabilityObservation:
        if self.time_limit_seconds <= 0:
            raise ValueError("DDD local explainability time limit must be positive")
        if self.num_workers <= 0:
            raise ValueError("DDD local explainability worker count must be positive")
        full_support.validate()
        cut = DddTimedFlowCoverCut.from_core(core)
        core_support = ddd_timed_flow_core_support(cut)
        resource_ids = cut.resource_ids
        oracle = DddCpSatPrimalOracle(
            time_limit_seconds=self.time_limit_seconds,
            num_workers=self.num_workers,
            max_candidate_count=1,
        )
        probes: list[DddCpSatLocalResourceProbe] = []
        single_explanations: list[str] = []
        for resource_id in resource_ids:
            probe = _run_probe(
                oracle,
                problem,
                resource_ids=(resource_id,),
                support=core_support,
                hint_schedules=hint_schedules,
            )
            probes.append(probe)
            if probe.status is DddCpSatPrimalStatus.INFEASIBLE:
                single_explanations.append(resource_id)

        if single_explanations:
            classification = DddCpSatLocalExplainabilityClass.SINGLE_RESOURCE
            explaining_resource_ids = tuple(single_explanations)
        elif len(resource_ids) > 1:
            group_probe = _run_probe(
                oracle,
                problem,
                resource_ids=resource_ids,
                support=core_support,
                hint_schedules=hint_schedules,
            )
            probes.append(group_probe)
            if group_probe.status is DddCpSatPrimalStatus.INFEASIBLE:
                classification = DddCpSatLocalExplainabilityClass.RESOURCE_GROUP
                explaining_resource_ids = resource_ids
            elif group_probe.status is DddCpSatPrimalStatus.FEASIBLE:
                classification = DddCpSatLocalExplainabilityClass.GLOBAL
                explaining_resource_ids = ()
            else:
                classification = DddCpSatLocalExplainabilityClass.UNRESOLVED
                explaining_resource_ids = ()
        else:
            classification = (
                DddCpSatLocalExplainabilityClass.GLOBAL
                if not probes
                or probes[0].status is DddCpSatPrimalStatus.FEASIBLE
                else DddCpSatLocalExplainabilityClass.UNRESOLVED
            )
            explaining_resource_ids = ()

        station_ids, windows = _resource_windows(problem, cut)
        return DddCpSatLocalExplainabilityObservation(
            round_index=round_index,
            classification=classification,
            explaining_resource_ids=explaining_resource_ids,
            full_support=full_support,
            core_cut=cut,
            station_ids=station_ids,
            resource_windows=windows,
            probes=tuple(probes),
        )


def ddd_timed_flow_core_support(
    cut: DddTimedFlowCoverCut,
) -> DddCpSatTimedFlowSupport:
    """Release every master decision outside an infeasible assumption core."""

    cut.validate()
    result = DddCpSatTimedFlowSupport(
        arc_flows=tuple(
            DddTimedArcFlowCount(
                region=literal.region,
                count=literal.minimum_flow,
            )
            for literal in cut.literals
        )
    )
    result.validate()
    return result


def ddd_timed_flow_cover_excludes_support(
    cut: DddTimedFlowCoverCut,
    support: DddCpSatTimedFlowSupport,
) -> bool:
    """Return whether all cut thresholds hold in a recorded timed support."""

    cut.validate()
    support.validate()
    for literal in cut.literals:
        flow = sum(
            item.count
            for item in support.arc_flows
            if _is_child_region(item.region, literal.region)
        )
        if flow < literal.minimum_flow:
            return False
    return True


def build_ddd_cp_sat_local_explainability_report(
    observations: tuple[DddCpSatLocalExplainabilityObservation, ...],
) -> DddCpSatLocalExplainabilityReport:
    coverages = tuple(
        DddCpSatLocalCutCoverage(
            round_index=observation.round_index,
            cut_id=observation.core_cut.id,
            excluded_observed_support_count=(
                excluded_count := sum(
                    ddd_timed_flow_cover_excludes_support(
                        observation.core_cut,
                        candidate.full_support,
                    )
                    for candidate in observations
                )
            ),
            excluded_other_support_count=max(0, excluded_count - 1),
        )
        for observation in observations
    )
    return DddCpSatLocalExplainabilityReport(
        observation_count=len(observations),
        single_resource_count=sum(
            observation.classification
            is DddCpSatLocalExplainabilityClass.SINGLE_RESOURCE
            for observation in observations
        ),
        resource_group_count=sum(
            observation.classification
            is DddCpSatLocalExplainabilityClass.RESOURCE_GROUP
            for observation in observations
        ),
        global_count=sum(
            observation.classification is DddCpSatLocalExplainabilityClass.GLOBAL
            for observation in observations
        ),
        unresolved_count=sum(
            observation.classification is DddCpSatLocalExplainabilityClass.UNRESOLVED
            for observation in observations
        ),
        resource_touching_core_count=sum(
            any(
                probe.status is DddCpSatPrimalStatus.INFEASIBLE
                and probe.all_core_literals_touch_enabled_resources
                for probe in observation.probes
            )
            for observation in observations
        ),
        total_probe_seconds=sum(item.probe_seconds for item in observations),
        unique_station_ids=tuple(
            sorted({station for item in observations for station in item.station_ids})
        ),
        unique_resource_ids=tuple(
            sorted(
                {
                    resource
                    for item in observations
                    for resource in item.core_cut.resource_ids
                }
            )
        ),
        cut_coverage=coverages,
    )


def _run_probe(
    oracle: DddCpSatPrimalOracle,
    problem: DddNetworkTimeProblem,
    *,
    resource_ids: tuple[str, ...],
    support: DddCpSatTimedFlowSupport,
    hint_schedules: tuple[DddRecoveredSchedule, ...],
) -> DddCpSatLocalResourceProbe:
    result = oracle.solve(
        problem,
        hint_schedules=hint_schedules,
        timed_flow_support=support,
        enabled_resource_ids=resource_ids,
    )
    enabled = set(resource_ids)
    core = result.timed_flow_infeasible_core
    return DddCpSatLocalResourceProbe(
        resource_ids=resource_ids,
        status=result.status,
        wall_seconds=result.wall_seconds,
        conflict_count=result.conflict_count,
        branch_count=result.branch_count,
        core_literal_count=len(core),
        infeasible_core=core,
        all_core_literals_touch_enabled_resources=(
            bool(core)
            and all(
                enabled.intersection(literal.region.resource_ids) for literal in core
            )
        ),
    )


def _resource_windows(
    problem: DddNetworkTimeProblem,
    cut: DddTimedFlowCoverCut,
) -> tuple[tuple[str, ...], tuple[DddTimedFlowResourceWindow, ...]]:
    movement = problem.movement_problem
    options_by_id = {option.id: option for option in movement.route_options}
    resources_by_id = movement.resources_by_id
    windows: list[DddTimedFlowResourceWindow] = []
    station_ids: set[str] = set()
    for literal in cut.literals:
        option = options_by_id[literal.region.route_option_id]
        station_ids.add(option.station_id)
        for usage in option.resource_usages:
            if usage.resource_id not in cut.resource_ids:
                continue
            resource = resources_by_id[usage.resource_id]
            windows.append(
                DddTimedFlowResourceWindow(
                    literal_id=literal.id,
                    route_option_id=option.id,
                    station_id=option.station_id,
                    resource_id=usage.resource_id,
                    minimum_flow=literal.minimum_flow,
                    entry_lower_tick=(
                        literal.region.source_lower_tick
                        + usage.follower_enter_offset_tick
                    ),
                    entry_upper_tick=(
                        literal.region.source_upper_tick
                        + usage.follower_enter_offset_tick
                    ),
                    blocked_until_lower_tick=(
                        literal.region.source_lower_tick
                        + usage.leader_clear_offset_tick
                        + usage.separation_after_tick(resource.minimum_headway_tick)
                    ),
                    blocked_until_upper_tick=(
                        literal.region.source_upper_tick
                        + usage.leader_clear_offset_tick
                        + usage.separation_after_tick(resource.minimum_headway_tick)
                    ),
                )
            )
    return tuple(sorted(station_ids)), tuple(
        sorted(
            windows,
            key=lambda item: (
                item.resource_id,
                item.entry_lower_tick,
                item.entry_upper_tick,
                item.literal_id,
            ),
        )
    )


def _is_child_region(
    child: DddTimedFlowRegion,
    parent: DddTimedFlowRegion,
) -> bool:
    return (
        child.visit_index == parent.visit_index
        and child.route_option_id == parent.route_option_id
        and child.cabin_id == parent.cabin_id
        and parent.source_lower_tick <= child.source_lower_tick
        and child.source_upper_tick <= parent.source_upper_tick
        and parent.target_lower_tick <= child.target_lower_tick
        and child.target_upper_tick <= parent.target_upper_tick
        and child.timing_scope is parent.timing_scope
    )
