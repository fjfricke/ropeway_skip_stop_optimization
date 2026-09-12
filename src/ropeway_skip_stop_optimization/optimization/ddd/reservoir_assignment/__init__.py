"""Demand-led service assignment followed by exact reservoir timing."""

from .assignment import (
    ReservoirServiceAssignment,
    ReservoirServiceTrip,
    assignment_from_plan,
    assignment_from_payload,
    assignment_to_payload,
    canonicalize_reservoir_plan,
    validate_service_assignment,
)
from .conflicts import (
    ReservoirAssignmentConflict,
    ReservoirConflictConfig,
    assignment_violates_conflict,
    conflict_from_payload,
    conflict_to_payload,
    extract_assignment_conflict,
    replay_assignment_conflict,
)
from .master import ReservoirAssignmentMasterConfig, solve_assignment_master
from .pipeline import ReservoirAssignmentPipelineConfig, solve_assignment_pipeline
from .timing import (
    ReservoirAssignmentTimingConfig,
    ReservoirPassengerFixing,
    ReservoirTimingAssumption,
    build_assignment_timing_model,
    solve_assignment_timing,
)

__all__ = [
    "ReservoirAssignmentMasterConfig",
    "ReservoirAssignmentConflict",
    "ReservoirAssignmentPipelineConfig",
    "ReservoirAssignmentTimingConfig",
    "ReservoirPassengerFixing",
    "ReservoirTimingAssumption",
    "ReservoirConflictConfig",
    "ReservoirServiceAssignment",
    "ReservoirServiceTrip",
    "assignment_from_plan",
    "assignment_from_payload",
    "assignment_to_payload",
    "assignment_violates_conflict",
    "build_assignment_timing_model",
    "canonicalize_reservoir_plan",
    "conflict_from_payload",
    "conflict_to_payload",
    "extract_assignment_conflict",
    "replay_assignment_conflict",
    "solve_assignment_master",
    "solve_assignment_pipeline",
    "solve_assignment_timing",
    "validate_service_assignment",
]
