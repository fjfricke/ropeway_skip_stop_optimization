from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any, Mapping


class OptimizationEventKind(StrEnum):
    CAMPAIGN_STARTED = "campaign_started"
    CAMPAIGN_COMPLETED = "campaign_completed"
    TRIAL_QUEUED = "trial_queued"
    TRIAL_STARTED = "trial_started"
    TRIAL_COMPLETED = "trial_completed"
    TRIAL_FAILED = "trial_failed"
    STAGE_STARTED = "stage_started"
    STAGE_COMPLETED = "stage_completed"
    SOLVER_SAMPLE = "solver_sample"
    CG_ROUND_COMPLETED = "cg_round_completed"
    INCUMBENT_VALIDATED = "incumbent_validated"
    CHECKPOINT_WRITTEN = "checkpoint_written"
    HEARTBEAT = "heartbeat"


@dataclass(frozen=True, slots=True)
class OptimizationProgressEvent:
    sequence: int
    kind: OptimizationEventKind
    campaign_id: str
    timestamp_utc: str = field(
        default_factory=lambda: datetime.now(UTC).isoformat()
    )
    policy_id: str | None = None
    available_fleet_count: int | None = None
    trial_fingerprint: str | None = None
    stage: str | None = None
    round_index: int | None = None
    global_certified_lower_bound: float | None = None
    global_validated_upper_bound: float | None = None
    global_relative_gap: float | None = None
    local_solver_incumbent: float | None = None
    local_solver_bound: float | None = None
    local_solver_gap: float | None = None
    elapsed_seconds: float | None = None
    payload: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.sequence < 1:
            raise ValueError("event sequence must be positive")
        if not self.campaign_id:
            raise ValueError("campaign_id must not be empty")
        if self.available_fleet_count is not None and self.available_fleet_count < 0:
            raise ValueError("available_fleet_count must be non-negative")

    def to_dict(self) -> dict[str, Any]:
        value = asdict(self)
        value["kind"] = self.kind.value
        return value

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> OptimizationProgressEvent:
        return cls(
            sequence=int(value["sequence"]),
            kind=OptimizationEventKind(str(value["kind"])),
            campaign_id=str(value["campaign_id"]),
            timestamp_utc=str(value["timestamp_utc"]),
            policy_id=_optional_str(value.get("policy_id")),
            available_fleet_count=_optional_int(value.get("available_fleet_count")),
            trial_fingerprint=_optional_str(value.get("trial_fingerprint")),
            stage=_optional_str(value.get("stage")),
            round_index=_optional_int(value.get("round_index")),
            global_certified_lower_bound=_optional_float(
                value.get("global_certified_lower_bound")
            ),
            global_validated_upper_bound=_optional_float(
                value.get("global_validated_upper_bound")
            ),
            global_relative_gap=_optional_float(value.get("global_relative_gap")),
            local_solver_incumbent=_optional_float(
                value.get("local_solver_incumbent")
            ),
            local_solver_bound=_optional_float(value.get("local_solver_bound")),
            local_solver_gap=_optional_float(value.get("local_solver_gap")),
            elapsed_seconds=_optional_float(value.get("elapsed_seconds")),
            payload=dict(value.get("payload", {})),
        )


def _optional_str(value: object) -> str | None:
    return None if value is None else str(value)


def _optional_int(value: object) -> int | None:
    return None if value is None else int(value)


def _optional_float(value: object) -> float | None:
    return None if value is None else float(value)
