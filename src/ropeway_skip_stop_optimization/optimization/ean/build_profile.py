from __future__ import annotations

import resource
import sys
from collections.abc import Callable
from dataclasses import dataclass
from enum import StrEnum
from time import perf_counter


class EanBuildStage(StrEnum):
    ARTIFACT_TIMINGS = "artifact_timings"
    ARTIFACT_VISITS = "artifact_visits"
    ARTIFACT_CANDIDATES = "artifact_candidates"
    ARTIFACT_PAIRS = "artifact_pairs"
    MOVEMENT_VARIABLES = "movement_variables"
    HEADWAY_CONSTRAINTS = "headway_constraints"
    PASSENGER_CANDIDATES = "passenger_candidates"
    PASSENGER_MODEL = "passenger_model"
    MIP_START = "mip_start"
    FINAL_MODEL_UPDATE = "final_model_update"
    SERIALIZATION = "serialization"


class EanBuildProgressKind(StrEnum):
    STARTED = "started"
    PROGRESS = "progress"
    FINISHED = "finished"


@dataclass(frozen=True)
class EanBuildProgressEvent:
    stage: EanBuildStage
    kind: EanBuildProgressKind
    elapsed_seconds: float
    checkpoint_count: int | None = None
    processed_checkpoint_count: int | None = None
    candidate_count: int | None = None
    visit_count: int | None = None
    pair_count: int | None = None
    fixed_pair_count: int | None = None
    disjunctive_pair_count: int | None = None
    redundant_pair_count: int | None = None
    order_variable_count: int | None = None
    order_variable_savings: int | None = None
    variable_count: int | None = None
    constraint_count: int | None = None
    nonzero_count: int | None = None
    peak_rss_bytes: int | None = None


EanBuildProgressCallback = Callable[[EanBuildProgressEvent], None]


@dataclass(frozen=True)
class EanArtifactBuildMetrics:
    timing_seconds: float
    visit_seconds: float
    checkpoint_seconds: float
    candidate_seconds: float
    pair_seconds: float
    validation_seconds: float
    total_seconds: float
    checkpoint_count: int
    candidate_count: int
    pair_count: int
    peak_rss_bytes: int | None
    original_checkpoint_count: int | None = None
    original_candidate_count: int | None = None
    original_pair_count: int | None = None
    dominated_checkpoint_count: int = 0
    dominated_candidate_count: int = 0
    dominated_pair_count: int = 0
    merged_checkpoint_count: int = 0
    merged_candidate_count: int = 0
    merged_pair_count: int = 0

    def validate(self) -> None:
        if min(
            self.timing_seconds,
            self.visit_seconds,
            self.checkpoint_seconds,
            self.candidate_seconds,
            self.pair_seconds,
            self.validation_seconds,
            self.total_seconds,
        ) < 0:
            raise ValueError("artifact build times must be nonnegative")
        if min(self.checkpoint_count, self.candidate_count, self.pair_count) < 0:
            raise ValueError("artifact build counts must be nonnegative")
        optional_counts = (
            self.original_checkpoint_count,
            self.original_candidate_count,
            self.original_pair_count,
        )
        if any(value is not None and value < 0 for value in optional_counts):
            raise ValueError("original artifact build counts must be nonnegative")
        if min(
            self.dominated_checkpoint_count,
            self.dominated_candidate_count,
            self.dominated_pair_count,
            self.merged_checkpoint_count,
            self.merged_candidate_count,
            self.merged_pair_count,
        ) < 0:
            raise ValueError("headway reduction counts must be nonnegative")
        if self.peak_rss_bytes is not None and self.peak_rss_bytes <= 0:
            raise ValueError("artifact peak RSS must be positive when available")


@dataclass(frozen=True)
class EanMovementBuildMetrics:
    variables_and_base_constraints_seconds: float
    headway_constraints_seconds: float
    final_update_seconds: float
    fixed_headway_pair_count: int = 0
    disjunctive_headway_pair_count: int = 0
    redundant_headway_pair_count: int = 0
    headway_order_family_count: int = 0
    shared_headway_pair_count: int = 0
    headway_order_variable_savings: int = 0
    singleton_headway_order_family_count: int = 0
    diagnostically_omitted_headway_checkpoint_count: int = 0
    diagnostically_omitted_headway_pair_count: int = 0

    def validate(self) -> None:
        if min(
            self.variables_and_base_constraints_seconds,
            self.headway_constraints_seconds,
            self.final_update_seconds,
        ) < 0:
            raise ValueError("movement build times must be nonnegative")
        if min(
            self.fixed_headway_pair_count,
            self.disjunctive_headway_pair_count,
            self.redundant_headway_pair_count,
            self.headway_order_family_count,
            self.shared_headway_pair_count,
            self.headway_order_variable_savings,
            self.singleton_headway_order_family_count,
            self.diagnostically_omitted_headway_checkpoint_count,
            self.diagnostically_omitted_headway_pair_count,
        ) < 0:
            raise ValueError("movement headway classification counts must be nonnegative")


def emit_build_progress(
    callback: EanBuildProgressCallback | None,
    *,
    stage: EanBuildStage,
    kind: EanBuildProgressKind,
    started: float,
    checkpoint_count: int | None = None,
    processed_checkpoint_count: int | None = None,
    candidate_count: int | None = None,
    visit_count: int | None = None,
    pair_count: int | None = None,
    fixed_pair_count: int | None = None,
    disjunctive_pair_count: int | None = None,
    redundant_pair_count: int | None = None,
    order_variable_count: int | None = None,
    order_variable_savings: int | None = None,
    variable_count: int | None = None,
    constraint_count: int | None = None,
    nonzero_count: int | None = None,
) -> None:
    if callback is None:
        return
    callback(
        EanBuildProgressEvent(
            stage=stage,
            kind=kind,
            elapsed_seconds=perf_counter() - started,
            checkpoint_count=checkpoint_count,
            processed_checkpoint_count=processed_checkpoint_count,
            candidate_count=candidate_count,
            visit_count=visit_count,
            pair_count=pair_count,
            fixed_pair_count=fixed_pair_count,
            disjunctive_pair_count=disjunctive_pair_count,
            redundant_pair_count=redundant_pair_count,
            order_variable_count=order_variable_count,
            order_variable_savings=order_variable_savings,
            variable_count=variable_count,
            constraint_count=constraint_count,
            nonzero_count=nonzero_count,
            peak_rss_bytes=peak_rss_bytes(),
        )
    )


def peak_rss_bytes() -> int | None:
    """Return process peak RSS using the platform's ``getrusage`` units."""

    try:
        value = int(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss)
    except (AttributeError, OSError, ValueError):
        return None
    if value <= 0:
        return None
    # macOS reports bytes; Linux and the BSDs exposed by our CI report KiB.
    return value if sys.platform == "darwin" else value * 1024
