from __future__ import annotations

from dataclasses import dataclass

from ropeway_skip_stop_optimization.optimization.ddd.models import (
    DddMovementProblem,
    DddRouteDecision,
)
from ropeway_skip_stop_optimization.optimization.ddd.reference import (
    DddReferenceSolution,
    validate_ddd_reference_solution,
)
from ropeway_skip_stop_optimization.optimization.ddd.time_ticks import (
    ddd_seconds_to_tick,
    ddd_tick_to_seconds,
)
from ropeway_skip_stop_optimization.optimization.ean.artifact import EanBuildArtifact
from ropeway_skip_stop_optimization.optimization.ean.formulation_config import (
    EanHorizonFormulation,
)
from ropeway_skip_stop_optimization.optimization.ean.models import EanFleetMode
from ropeway_skip_stop_optimization.optimization.ean.plan import (
    EanCabinTrajectory,
    EanCabinVisit,
    EanMovementPlan,
    EanRouteDecision,
)


@dataclass(frozen=True)
class DddReferenceToEanMovementPlanAdapter:
    tolerance_seconds: float = 1e-9

    def build(
        self,
        *,
        problem: DddMovementProblem,
        solution: DddReferenceSolution,
        artifact: EanBuildArtifact,
    ) -> EanMovementPlan:
        if artifact.scenario_id != problem.scenario_id:
            raise ValueError("DDD problem and EAN artifact scenario ids differ")
        if artifact.fleet_mode is not EanFleetMode.FIXED_STARTS:
            raise ValueError("DDD reference plan conversion supports fixed starts only")
        if (
            ddd_seconds_to_tick(artifact.config.passenger_service_end_seconds)
            != problem.passenger_service_end_tick
            or ddd_seconds_to_tick(artifact.config.operational_end_seconds)
            != problem.operational_end_tick
        ):
            raise ValueError("DDD problem and EAN artifact horizons differ")
        artifact_cabin_ids = {start.cabin_id for start in artifact.cabin_starts}
        problem_cabin_ids = {start.cabin_id for start in problem.starts}
        if artifact_cabin_ids != problem_cabin_ids:
            raise ValueError("DDD problem and EAN artifact fixed starts differ")
        validate_ddd_reference_solution(
            problem,
            solution,
            tolerance_seconds=self.tolerance_seconds,
        )
        options_by_id = {option.id: option for option in problem.route_options}
        trajectories: list[EanCabinTrajectory] = []
        for trajectory in sorted(solution.trajectories, key=lambda item: item.cabin_id):
            visits: list[EanCabinVisit] = []
            for reference_visit in trajectory.visits:
                option = options_by_id[reference_visit.route_option_id]
                is_stop = option.decision is DddRouteDecision.STOP
                visits.append(
                    EanCabinVisit(
                        cabin_id=trajectory.cabin_id,
                        visit_index=reference_visit.visit_index,
                        switch_id=reference_visit.state_id,
                        station_id=option.station_id,
                        decision=(
                            EanRouteDecision.STOP
                            if is_stop
                            else EanRouteDecision.SKIP
                        ),
                        switch_time_seconds=reference_visit.switch_time_seconds,
                        platform_entry_time_seconds=(
                            ddd_tick_to_seconds(
                                ddd_seconds_to_tick(
                                    reference_visit.switch_time_seconds
                                )
                                + ddd_seconds_to_tick(
                                    option.platform_entry_offset_seconds
                                )
                            )
                            if option.platform_entry_offset_seconds is not None
                            else None
                        ),
                        platform_exit_time_seconds=(
                            ddd_tick_to_seconds(
                                ddd_seconds_to_tick(
                                    reference_visit.switch_time_seconds
                                )
                                + ddd_seconds_to_tick(
                                    option.platform_exit_offset_seconds
                                )
                            )
                            if option.platform_exit_offset_seconds is not None
                            else None
                        ),
                        exit_switch_time_seconds=ddd_tick_to_seconds(
                            ddd_seconds_to_tick(
                                reference_visit.switch_time_seconds
                            )
                            + option.exit_switch_offset_tick
                        ),
                        next_switch_time_seconds=(
                            reference_visit.next_switch_time_seconds
                        ),
                        wait_seconds=0.0,
                    )
                )
            trajectories.append(
                EanCabinTrajectory(
                    cabin_id=trajectory.cabin_id,
                    visits=tuple(visits),
                )
            )
        plan = EanMovementPlan(
            scenario_id=artifact.scenario_id,
            horizon_seconds=artifact.config.horizon_seconds,
            model_end_seconds=artifact.config.model_end_seconds,
            trajectories=tuple(trajectories),
            horizon_formulation=EanHorizonFormulation.EXACT_TIME_ACTIVATION,
            fleet_mode=EanFleetMode.FIXED_STARTS,
        )
        plan.validate()
        return plan
