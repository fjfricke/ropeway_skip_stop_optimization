"""Separate finite-horizon validity from exported-tail and continuation claims."""

from __future__ import annotations

from dataclasses import dataclass

from .artifact import EanBuildArtifact
from .formulation_config import EanHorizonFormulation
from .headway_separator import EanHeadwayViolation, separate_all_headway_violations
from .horizon_contract import FINITE_EVENT_ENTRY_CONTRACT, is_within_closed_horizon
from .plan import EanMovementPlan
from .validation import validate_ean_movement_plan_against_artifact
from ...validation.result import ValidationReport


@dataclass(frozen=True)
class EanHorizonAudit:
    finite_validation: ValidationReport
    exported_headway_violations: tuple[EanHeadwayViolation, ...]
    visits_clearing_after_horizon: int
    contract: str = FINITE_EVENT_ENTRY_CONTRACT
    continuation_status: str = "NOT_PROVEN"


def audit_ean_exact_horizon(
    artifact: EanBuildArtifact,
    plan: EanMovementPlan,
    *,
    tolerance_seconds: float = 1e-5,
) -> EanHorizonAudit:
    """Audit existing events only; never construct or certify future movement.

    The exported-tail diagnostic includes resource entries after H, without
    making them part of the original optimization domain. It neither repairs
    a conflict nor proves that every possible continuation must conflict.
    """
    if plan.horizon_formulation is not EanHorizonFormulation.EXACT_TIME_ACTIVATION:
        raise ValueError("horizon audit requires exact event-time activation")
    return EanHorizonAudit(
        finite_validation=validate_ean_movement_plan_against_artifact(
            artifact, plan, tolerance_seconds=tolerance_seconds
        ),
        exported_headway_violations=separate_all_headway_violations(
            artifact, plan, tolerance_seconds=tolerance_seconds,
            include_after_horizon=True,
        ),
        visits_clearing_after_horizon=sum(
            not is_within_closed_horizon(v.next_switch_time_seconds, plan.model_end_seconds)
            for t in plan.trajectories for v in t.visits
        ),
    )
