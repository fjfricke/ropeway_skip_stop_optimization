from __future__ import annotations

import math
from dataclasses import dataclass, field, replace

from ropeway_skip_stop_optimization.models import HeadwayRouteBehavior, Scenario
from ropeway_skip_stop_optimization.optimization.ean.artifact import EanBuildArtifact
from ropeway_skip_stop_optimization.optimization.ean.builders.network_artifact_builder import (
    NetworkEanBuildArtifactBuilder,
)
from ropeway_skip_stop_optimization.optimization.ean.models import (
    EanConfig,
    EanFleetCardinalityMode,
    EanFleetConfig,
    EanFleetMode,
)
from ropeway_skip_stop_optimization.optimization.ean.packing_capacity import (
    EanInitialPlacementPackingBound,
    EanInitialPlacementPackingBoundBuilder,
)
from ropeway_skip_stop_optimization.optimization.ean.periodic_route import (
    EanPeriodicRouteCapacityBound,
    EanPeriodicRouteCapacityBoundBuilder,
)


@dataclass(frozen=True)
class EanPreparedRing:
    """Reusable physical data and analytic bounds for capacity probes."""

    seed_artifact: EanBuildArtifact
    packing_bound: EanInitialPlacementPackingBound
    canonical_all_stop_lower_bound: int
    periodic_route_bound: EanPeriodicRouteCapacityBound | None
    certified_lower_bound: int

    def validate(self) -> None:
        self.seed_artifact.validate()
        self.packing_bound.validate()
        if not (
            0
            < self.canonical_all_stop_lower_bound
            <= self.certified_lower_bound
            <= self.packing_bound.packing_upper_bound
        ):
            raise ValueError("prepared ring has inconsistent capacity bounds")
        if self.periodic_route_bound is not None:
            self.periodic_route_bound.validate_for_artifact(self.seed_artifact)
        expected_lower_bound = max(
            self.canonical_all_stop_lower_bound,
            min(
                self.packing_bound.packing_upper_bound,
                self.periodic_route_bound.fleet_lower_bound,
            )
            if self.periodic_route_bound is not None
            else 0,
        )
        if self.certified_lower_bound != expected_lower_bound:
            raise ValueError("prepared ring has an unsupported certified lower bound")


@dataclass(frozen=True)
class EanPreparedRingBuilder:
    packing_bound_builder: EanInitialPlacementPackingBoundBuilder = field(
        default_factory=EanInitialPlacementPackingBoundBuilder
    )
    periodic_route_bound_builder: EanPeriodicRouteCapacityBoundBuilder = field(
        default_factory=EanPeriodicRouteCapacityBoundBuilder
    )

    def build(
        self,
        *,
        scenario: Scenario,
        config: EanConfig,
        artifact_builder: NetworkEanBuildArtifactBuilder,
    ) -> EanPreparedRing:
        network = artifact_builder.network_builder.build(
            scenario,
            artifact_builder.pattern_definition,
        )
        packing_bound = self.packing_bound_builder.build_for_network(
            scenario=scenario,
            config=config,
            network=network,
            pattern_id=artifact_builder.pattern_definition.id,
        )
        seed_artifact = replace(
            artifact_builder,
            fleet_config=EanFleetConfig(
                mode=EanFleetMode.OPTIMIZED_INITIAL_PLACEMENT,
                available_fleet_count=1,
                cardinality_mode=EanFleetCardinalityMode.EXACT,
            ),
        ).build(scenario, config)
        all_stop = min(
            packing_bound.packing_upper_bound,
            canonical_all_stop_fleet_count(seed_artifact),
        )
        periodic = self.periodic_route_bound_builder.build_optional(seed_artifact)
        periodic_lower = (
            min(packing_bound.packing_upper_bound, periodic.fleet_lower_bound)
            if periodic is not None
            else 0
        )
        prepared = EanPreparedRing(
            seed_artifact=seed_artifact,
            packing_bound=packing_bound,
            canonical_all_stop_lower_bound=all_stop,
            periodic_route_bound=periodic,
            certified_lower_bound=max(all_stop, periodic_lower),
        )
        prepared.validate()
        return prepared


def canonical_all_stop_fleet_count(artifact: EanBuildArtifact) -> int:
    timing_by_switch_id = {timing.switch_id: timing for timing in artifact.timings}
    cycle_seconds = sum(
        timing.entry_to_platform_entry_seconds
        + timing.min_platform_entry_to_platform_exit_seconds
        + timing.platform_exit_to_exit_switch_seconds
        + timing.rope_to_next_switch_seconds
        for timing in timing_by_switch_id.values()
    )
    service = HeadwayRouteBehavior.SERVICE
    headways = tuple(
        artifact.headway_rule_for_checkpoint(checkpoint).required_seconds(
            service,
            service,
        )
        for checkpoint in artifact.headway_checkpoints
        if checkpoint.applies_to_serve
    )
    if not headways:
        raise ValueError("all-stop lower bound needs a serving headway")
    return max(1, math.floor((cycle_seconds + 1e-9) / max(headways)))
