from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from enum import StrEnum
import math

from ropeway_skip_stop_optimization.optimization.ddd.aggregate_support import (
    DddAggregateSupportCut,
    DddAggregateSupportDistanceCut,
    DddCpSatFixedSupport,
)
from ropeway_skip_stop_optimization.optimization.ddd.cp_sat_primal import (
    DddCpSatPrimalOracle,
    DddCpSatPrimalResult,
    DddCpSatPrimalStatus,
)
from ropeway_skip_stop_optimization.optimization.ddd.lifting import (
    build_ddd_cabin_path_core_cut,
)
from ropeway_skip_stop_optimization.optimization.ddd.local_resource_explainability import (
    DddCpSatLocalExplainabilityObservation,
    DddCpSatLocalResourceAnalyzer,
)
from ropeway_skip_stop_optimization.optimization.ddd.network_time_space import (
    DddAnonymousFlowResult,
    DddLayeredTimeNetwork,
    DddNetworkTimeProblem,
    build_ddd_cp_sat_timed_flow_support,
)
from ropeway_skip_stop_optimization.optimization.ddd.prefix_budget import (
    select_ddd_prefix_cuts_within_budget,
)
from ropeway_skip_stop_optimization.optimization.ddd.reference import (
    DddReferenceSolution,
)
from ropeway_skip_stop_optimization.optimization.ddd.support_master import (
    DddSupportConflictCut,
)
from ropeway_skip_stop_optimization.optimization.ddd.time_refinement import (
    DddRecoveredSchedule,
)
from ropeway_skip_stop_optimization.optimization.ddd.time_space import (
    DddPartialTimedPath,
)
from ropeway_skip_stop_optimization.optimization.ddd.timed_flow_cover import (
    DddTimedFlowCoverCut,
)


class DddCpSatMasterCoupling(StrEnum):
    FREE_ROUTE_CHOICES = "free_route_choices"
    FIXED_AGGREGATE_SUPPORT = "fixed_aggregate_support"


DddCpSatCandidateValidator = Callable[
    [tuple[DddRecoveredSchedule, ...]], DddReferenceSolution | None
]
DddCpSatCandidateConsumer = Callable[
    [tuple[DddRecoveredSchedule, ...], DddReferenceSolution, int], None
]


@dataclass(frozen=True)
class DddCpSatRoundResult:
    status: DddCpSatPrimalStatus = DddCpSatPrimalStatus.NOT_RUN
    seconds: float = 0.0
    conflict_count: int = 0
    branch_count: int = 0
    candidate_count: int = 0
    search_complete: bool = False
    exact_infeasible: bool = False
    invalid_candidate: bool = False
    cabin_path_status: DddCpSatPrimalStatus = DddCpSatPrimalStatus.NOT_RUN
    cabin_path_seconds: float = 0.0
    cabin_path_core_cabin_ids: tuple[int, ...] = ()
    cabin_path_core_literal_count: int = 0
    cabin_path_cut_literal_count: int = 0
    cabin_path_candidate_cuts: tuple[DddSupportConflictCut, ...] = ()
    aggregate_support_cuts: tuple[DddAggregateSupportCut, ...] = ()
    aggregate_distance_cuts: tuple[DddAggregateSupportDistanceCut, ...] = ()
    timed_flow_cover_cuts: tuple[DddTimedFlowCoverCut, ...] = ()
    core_literal_count: int = 0
    timed_flow_core_literal_count: int = 0
    timed_flow_core_resource_ids: tuple[str, ...] = ()
    local_explainability: DddCpSatLocalExplainabilityObservation | None = None
    nearest_status: DddCpSatPrimalStatus = DddCpSatPrimalStatus.NOT_RUN
    nearest_seconds: float = 0.0
    nearest_distance_primal: int | None = None
    nearest_distance_lower_bound: float | None = None


@dataclass(frozen=True)
class DddCpSatRoundSolver:
    use_primal_oracle: bool
    master_coupling: DddCpSatMasterCoupling
    use_timed_flow_covers: bool
    use_cabin_path_cuts: bool
    use_nearest_support: bool
    collect_local_explainability: bool
    retry_interval: int
    diversification_interval: int
    max_prefix_variable_count: int
    max_tracked_prefix_cabin_count: int
    max_prefix_visit_index: int

    def __post_init__(self) -> None:
        if not isinstance(self.master_coupling, DddCpSatMasterCoupling):
            raise ValueError("DDD CP-SAT master coupling is invalid")
        if (
            self.use_timed_flow_covers
            and self.master_coupling
            is not DddCpSatMasterCoupling.FIXED_AGGREGATE_SUPPORT
        ):
            raise ValueError(
                "DDD timed-flow covers require fixed aggregate master coupling"
            )
        if self.use_cabin_path_cuts and not self.use_primal_oracle:
            raise ValueError("DDD cabin-path cuts require the CP-SAT primal oracle")
        if self.collect_local_explainability and not self.use_timed_flow_covers:
            raise ValueError("DDD local CP-SAT explainability requires timed-flow covers")
        if self.retry_interval <= 0:
            raise ValueError("DDD CP-SAT retry interval must be positive")
        if self.diversification_interval < 0:
            raise ValueError("DDD CP-SAT diversification interval must be nonnegative")
        if self.diversification_interval > 0 and not self.use_primal_oracle:
            raise ValueError("DDD CP-SAT diversification requires the CP-SAT oracle")
        if self.max_prefix_variable_count <= 0:
            raise ValueError("DDD prefix variable budget must be positive")
        if self.max_tracked_prefix_cabin_count <= 0:
            raise ValueError("DDD tracked-prefix cabin budget must be positive")
        if self.max_prefix_visit_index <= 0:
            raise ValueError("DDD prefix visit budget must be positive")

    def solve(
        self,
        *,
        round_index: int,
        problem: DddNetworkTimeProblem,
        network: DddLayeredTimeNetwork,
        flow: DddAnonymousFlowResult,
        paths: tuple[DddPartialTimedPath, ...],
        existing_prefix_cuts: tuple[DddSupportConflictCut, ...],
        existing_aggregate_support_cut_ids: frozenset[str],
        existing_aggregate_distance_cut_ids: frozenset[str],
        existing_timed_flow_cover_cut_ids: frozenset[str],
        has_incumbent: bool,
        best_schedules: tuple[DddRecoveredSchedule, ...],
        excluded_schedules: tuple[tuple[DddRecoveredSchedule, ...], ...],
        primal_oracle: DddCpSatPrimalOracle,
        nearest_support_oracle: DddCpSatPrimalOracle,
        local_resource_analyzer: DddCpSatLocalResourceAnalyzer,
        validate_candidate: DddCpSatCandidateValidator,
        consume_candidate: DddCpSatCandidateConsumer,
        on_candidate_found: Callable[[int, float], None] | None = None,
        on_finished: Callable[[], None] | None = None,
    ) -> DddCpSatRoundResult:
        diversification_round = (
            self.diversification_interval > 0
            and round_index > 1
            and (round_index - 1) % self.diversification_interval == 0
        )
        should_run = self.use_primal_oracle and (
            self.master_coupling is DddCpSatMasterCoupling.FIXED_AGGREGATE_SUPPORT
            or round_index == 1
            or diversification_round
            or (not has_incumbent and (round_index - 1) % self.retry_interval == 0)
        )
        if not should_run:
            return DddCpSatRoundResult()

        fixed_support = (
            DddCpSatFixedSupport.from_paths(paths)
            if self.master_coupling
            is DddCpSatMasterCoupling.FIXED_AGGREGATE_SUPPORT
            else None
        )
        timed_flow_support = (
            build_ddd_cp_sat_timed_flow_support(
                network,
                flow,
                problem.movement_problem,
            )
            if fixed_support is not None and self.use_timed_flow_covers
            else None
        )
        cabin_path_status = DddCpSatPrimalStatus.NOT_RUN
        cabin_path_seconds = 0.0
        cabin_path_core_cabin_ids: tuple[int, ...] = ()
        cabin_path_core_literal_count = 0
        cabin_path_cut_literal_count = 0
        cabin_path_candidate_cuts: tuple[DddSupportConflictCut, ...] = ()
        cp_result: DddCpSatPrimalResult | None = None

        if self.use_cabin_path_cuts and not diversification_round:
            cabin_path_result = primal_oracle.solve(
                problem,
                hint_paths=paths,
                fixed_cabin_paths=paths,
            )
            cabin_path_status = cabin_path_result.status
            cabin_path_seconds = cabin_path_result.wall_seconds
            cabin_path_core_cabin_ids = tuple(
                sorted(
                    {
                        literal.cabin_id
                        for literal in cabin_path_result.cabin_path_infeasible_core
                    }
                )
            )
            if cabin_path_result.cabin_path_infeasible_core:
                cabin_path_core_literal_count = len(
                    cabin_path_result.cabin_path_infeasible_core
                )
                cabin_path_cut = build_ddd_cabin_path_core_cut(
                    paths,
                    cabin_path_result.cabin_path_infeasible_core,
                )
                cabin_path_cut_literal_count = len(cabin_path_cut.literals)
                admissible_cuts, _ = select_ddd_prefix_cuts_within_budget(
                    network,
                    existing_prefix_cuts,
                    (cabin_path_cut,),
                    max_new_cuts=1,
                    max_variable_count=self.max_prefix_variable_count,
                    max_cabin_count=self.max_tracked_prefix_cabin_count,
                    max_visit_index=self.max_prefix_visit_index,
                )
                if admissible_cuts:
                    cabin_path_candidate_cuts = admissible_cuts
                    cp_result = cabin_path_result
            elif cabin_path_result.status is not DddCpSatPrimalStatus.UNKNOWN:
                cp_result = cabin_path_result

        if cp_result is None:
            cp_result = primal_oracle.solve(
                problem,
                hint_paths=paths,
                fixed_support=fixed_support if timed_flow_support is None else None,
                timed_flow_support=timed_flow_support,
                excluded_schedules=(excluded_schedules if diversification_round else ()),
                candidate_callback=on_candidate_found,
            )

        common = {
            "status": cp_result.status,
            "seconds": cp_result.wall_seconds,
            "conflict_count": cp_result.conflict_count,
            "branch_count": cp_result.branch_count,
            "candidate_count": len(cp_result.candidate_schedules),
            "search_complete": cp_result.search_complete,
            "cabin_path_status": cabin_path_status,
            "cabin_path_seconds": cabin_path_seconds,
            "cabin_path_core_cabin_ids": cabin_path_core_cabin_ids,
            "cabin_path_core_literal_count": cabin_path_core_literal_count,
            "cabin_path_cut_literal_count": cabin_path_cut_literal_count,
            "cabin_path_candidate_cuts": cabin_path_candidate_cuts,
        }
        if cp_result.status is DddCpSatPrimalStatus.FEASIBLE:
            candidates = (
                cp_result.candidate_schedules
                if cp_result.candidate_schedules
                else (cp_result.schedules,)
            )
            for schedules in candidates:
                solution = validate_candidate(schedules)
                if solution is None:
                    return DddCpSatRoundResult(invalid_candidate=True, **common)
                consume_candidate(schedules, solution, len(cp_result.candidate_schedules))
            if on_finished is not None:
                on_finished()
            return DddCpSatRoundResult(**common)

        exact_infeasible = False
        aggregate_support_cuts: tuple[DddAggregateSupportCut, ...] = ()
        aggregate_distance_cuts: tuple[DddAggregateSupportDistanceCut, ...] = ()
        timed_flow_cover_cuts: tuple[DddTimedFlowCoverCut, ...] = ()
        core_literal_count = 0
        timed_flow_core_literal_count = 0
        timed_flow_core_resource_ids: tuple[str, ...] = ()
        local_explainability: DddCpSatLocalExplainabilityObservation | None = None
        nearest_status = DddCpSatPrimalStatus.NOT_RUN
        nearest_seconds = 0.0
        nearest_distance_primal: int | None = None
        nearest_distance_lower_bound: float | None = None

        if cp_result.status is DddCpSatPrimalStatus.INFEASIBLE:
            core_literal_count = len(cp_result.infeasible_core)
            timed_flow_core_literal_count = len(cp_result.timed_flow_infeasible_core)
            support_rejected = False
            if cp_result.cabin_path_infeasible_core:
                support_rejected = True
            elif cp_result.fixed_cabin_paths:
                exact_infeasible = True
            elif timed_flow_support is not None:
                if not cp_result.timed_flow_infeasible_core:
                    exact_infeasible = True
                else:
                    timed_cut = DddTimedFlowCoverCut.from_core(
                        cp_result.timed_flow_infeasible_core
                    )
                    timed_flow_core_resource_ids = timed_cut.resource_ids
                    if self.collect_local_explainability:
                        local_explainability = local_resource_analyzer.analyze(
                            problem,
                            round_index=round_index,
                            full_support=timed_flow_support,
                            core=cp_result.timed_flow_infeasible_core,
                            hint_schedules=best_schedules,
                        )
                    if timed_cut.id not in existing_timed_flow_cover_cut_ids:
                        timed_flow_cover_cuts = (timed_cut,)
                    support_rejected = True
            elif fixed_support is None or not cp_result.infeasible_core:
                exact_infeasible = True
            else:
                aggregate_cut = DddAggregateSupportCut.from_core(
                    cp_result.infeasible_core
                )
                if aggregate_cut.id not in existing_aggregate_support_cut_ids:
                    aggregate_support_cuts = (aggregate_cut,)
                support_rejected = True

            if (
                support_rejected
                and not cp_result.fixed_cabin_paths
                and self.use_nearest_support
            ):
                if fixed_support is None:
                    raise RuntimeError(
                        "DDD rejected support has no aggregate nearest center"
                    )
                nearest_result = nearest_support_oracle.solve(
                    problem,
                    hint_schedules=best_schedules,
                    nearest_support=fixed_support,
                )
                nearest_status = nearest_result.status
                nearest_seconds = nearest_result.wall_seconds
                nearest_distance_primal = nearest_result.support_distance_primal
                nearest_distance_lower_bound = (
                    nearest_result.support_distance_lower_bound
                )
                if nearest_result.status is DddCpSatPrimalStatus.INFEASIBLE:
                    exact_infeasible = True
                elif nearest_result.status is DddCpSatPrimalStatus.FEASIBLE:
                    solution = validate_candidate(nearest_result.schedules)
                    if solution is None:
                        return DddCpSatRoundResult(
                            invalid_candidate=True,
                            exact_infeasible=exact_infeasible,
                            aggregate_support_cuts=aggregate_support_cuts,
                            timed_flow_cover_cuts=timed_flow_cover_cuts,
                            core_literal_count=core_literal_count,
                            timed_flow_core_literal_count=(
                                timed_flow_core_literal_count
                            ),
                            timed_flow_core_resource_ids=(
                                timed_flow_core_resource_ids
                            ),
                            local_explainability=local_explainability,
                            nearest_status=nearest_status,
                            nearest_seconds=nearest_seconds,
                            nearest_distance_primal=nearest_distance_primal,
                            nearest_distance_lower_bound=(
                                nearest_distance_lower_bound
                            ),
                            **common,
                        )
                    consume_candidate(
                        nearest_result.schedules,
                        solution,
                        len(cp_result.candidate_schedules),
                    )
                    distance_bound = nearest_result.support_distance_lower_bound
                    if distance_bound is not None:
                        certified_distance = max(
                            0,
                            math.ceil(distance_bound - 1e-6),
                        )
                        if certified_distance > 0:
                            distance_cut = (
                                DddAggregateSupportDistanceCut.from_center(
                                    nearest_result.distance_center,
                                    minimum_distance=certified_distance,
                                )
                            )
                            if (
                                distance_cut.id
                                not in existing_aggregate_distance_cut_ids
                            ):
                                aggregate_distance_cuts = (distance_cut,)

        if on_finished is not None:
            on_finished()
        return DddCpSatRoundResult(
            exact_infeasible=exact_infeasible,
            aggregate_support_cuts=aggregate_support_cuts,
            aggregate_distance_cuts=aggregate_distance_cuts,
            timed_flow_cover_cuts=timed_flow_cover_cuts,
            core_literal_count=core_literal_count,
            timed_flow_core_literal_count=timed_flow_core_literal_count,
            timed_flow_core_resource_ids=timed_flow_core_resource_ids,
            local_explainability=local_explainability,
            nearest_status=nearest_status,
            nearest_seconds=nearest_seconds,
            nearest_distance_primal=nearest_distance_primal,
            nearest_distance_lower_bound=nearest_distance_lower_bound,
            **common,
        )
