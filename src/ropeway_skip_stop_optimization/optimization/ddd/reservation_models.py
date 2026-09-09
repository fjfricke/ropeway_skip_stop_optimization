from __future__ import annotations

import math
from dataclasses import dataclass
from enum import StrEnum

from .fixed_k_certificate import DddValidatedFixedKPlan


class DddReservationAttemptStatus(StrEnum):
    FEASIBLE = "FEASIBLE"
    NO_CANDIDATE = "NO_CANDIDATE"
    NO_FEASIBLE_REPAIR_FOUND = "NO_FEASIBLE_REPAIR_FOUND"
    BUDGET_EXHAUSTED = "BUDGET_EXHAUSTED"


@dataclass(frozen=True, slots=True)
class DddReservationInsertionConfig:
    total_time_limit_seconds: float = 30.0
    # Repair search budget; independent acceptance checks are measured separately.
    attempt_time_limit_seconds: float = 0.25
    maximum_affected_cabins: int = 4
    beam_width: int = 8
    wait_candidate_limit: int = 12
    lookahead_visits: int = 3
    accept_improvements: bool = False

    def validate(self):
        for value in (self.total_time_limit_seconds, self.attempt_time_limit_seconds):
            if not math.isfinite(value) or value <= 0:
                raise ValueError("reservation time limits must be positive and finite")
        for value in (
            self.maximum_affected_cabins,
            self.beam_width,
            self.wait_candidate_limit,
            self.lookahead_visits,
        ):
            if type(value) is not int or value <= 0:
                raise ValueError("reservation search limits must be positive integers")


@dataclass(frozen=True, slots=True)
class DddServiceInsertionIntent:
    candidate_id: str
    count: int

    def __post_init__(self):
        if not self.candidate_id or type(self.count) is not int or self.count <= 0:
            raise ValueError(
                "service insertion requires a candidate and positive integer count"
            )


@dataclass(frozen=True, slots=True)
class DddReservationAttemptResult:
    intent: DddServiceInsertionIntent
    status: DddReservationAttemptStatus
    elapsed_seconds: float
    affected_cabins: tuple[int, ...]
    pair_checks: int
    labels: int
    reason: str
    objective: float | None = None
    different_movement: bool = False
    repair_seconds: float = 0.0
    passenger_seconds: float = 0.0
    validation_seconds: float = 0.0


@dataclass(frozen=True, slots=True)
class DddReservationInsertionResult:
    initial_plan: DddValidatedFixedKPlan
    best_plan: DddValidatedFixedKPlan
    attempts: tuple[DddReservationAttemptResult, ...]
    elapsed_seconds: float
    termination_reason: str
    distinct_movements: int
    finalist_plans: tuple[DddValidatedFixedKPlan, ...] = ()
