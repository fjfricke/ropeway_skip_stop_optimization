"""Passenger candidates that are safe for optimized initial placement."""

from ropeway_skip_stop_optimization.optimization.ean.builders.passenger_builder import (
    EanPassengerCandidateBuilder,
)
from ropeway_skip_stop_optimization.optimization.ean.models import EanFleetMode
from ropeway_skip_stop_optimization.optimization.ean.optimization_config import (
    EanOptimizationConfig,
)


def oip_passenger_candidate_builder() -> EanPassengerCandidateBuilder:
    """Build candidates without reductions that assume a fixed initial state."""
    optimization_config = EanOptimizationConfig().resolved_for_fleet_mode(
        EanFleetMode.OPTIMIZED_INITIAL_PLACEMENT
    )
    return EanPassengerCandidateBuilder(optimization_config=optimization_config)
