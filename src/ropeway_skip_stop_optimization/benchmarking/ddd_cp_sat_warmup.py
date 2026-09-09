"""Add empty, fully optimized operation before the original demand window."""
from dataclasses import replace
from datetime import date, datetime, timedelta
import math

from ..examples.registry import get_example
from ..optimization.ddd.artifact_adapter import EanArtifactToDddMovementProblemAdapter
from ..optimization.ddd.cp_sat_certificate import (
    validate_ddd_cp_sat_domain,
)
from ..optimization.ddd.time_ticks import ddd_seconds_to_tick, ddd_tick_to_seconds
from ..optimization.ean import EanPassengerCandidateBuilder, SparseHeadwayPairBuilder
from ..optimization.ean.builders.fixed_start_builder import ExplicitEanCabinStartBuilder
from ..optimization.ean.models import EanFleetConfig, EanFleetMode
from ..optimization.headway_resource_reduction import HeadwayResourceReductionMode
from .ddd_fixed_k_arc_flow import DddPreparedFixedKArcFlowRun


def with_empty_warmup(prepared: DddPreparedFixedKArcFlowRun, *, seconds: float
                     ) -> DddPreparedFixedKArcFlowRun:
    """Keep the t=0 snapshot; shift releases and both horizons together.

    No initial-boundary relaxation and no future route fixing is introduced.
    Existing finite seed trajectories are dropped: their continuation beyond
    the old certification horizon has not been checked.
    """
    if not math.isfinite(seconds) or seconds < 0:
        raise ValueError('warmup seconds must be finite and nonnegative')
    if not math.isclose(seconds, ddd_tick_to_seconds(ddd_seconds_to_tick(seconds)),
                        rel_tol=0, abs_tol=1e-10):
        raise ValueError('warmup must lie on the canonical tick grid')
    if seconds == 0:
        return prepared

    def shift_clock(value):
        original = datetime.combine(date(2000, 1, 1), value)
        shifted = original + timedelta(seconds=seconds)
        if shifted.date() != original.date():
            raise ValueError('warmup cannot cross the scenario calendar day')
        return shifted.time()

    problem = prepared.problem
    scenario = replace(prepared.scenario,
        service_end_time=shift_clock(prepared.scenario.service_end_time),
        demands=tuple(replace(d, arrival_time=shift_clock(d.arrival_time))
                      for d in prepared.scenario.demands))
    scenario.validate()
    config = replace(problem.artifact.config,
                     horizon_seconds=problem.artifact.config.horizon_seconds + seconds)
    example = get_example(scenario.id)
    builder = replace(example.build_ean_artifact_builder(scenario, config),
        fleet_config=EanFleetConfig(mode=EanFleetMode.FIXED_STARTS),
        start_builder=ExplicitEanCabinStartBuilder(problem.artifact.cabin_starts),
        headway_pair_builder=SparseHeadwayPairBuilder(),
        headway_resource_reduction_mode=HeadwayResourceReductionMode.DISABLED)
    artifact = builder.build(scenario, config)
    policy = problem.resolved_trajectory_problem.waiting_policy
    trajectory = EanArtifactToDddMovementProblemAdapter(
        waiting_step_seconds=policy.step_seconds or 1e-6).build_trajectory_problem(artifact)
    updated = replace(problem, artifact=artifact, trajectory_problem=trajectory,
        passenger_build=EanPassengerCandidateBuilder().build(scenario, artifact))
    if artifact.cabin_starts != problem.artifact.cabin_starts:
        raise ValueError('warmup changed the physical initial snapshot')
    old, new = problem.passenger_build.demand_groups, updated.passenger_build.demand_groups
    if tuple(replace(g, release_time_seconds=g.release_time_seconds + seconds) for g in old) != new:
        raise ValueError('warmup changed demand beyond shifting its release')
    validate_ddd_cp_sat_domain(updated)
    return replace(prepared, scenario=scenario, problem=updated, seed_trajectories=())
