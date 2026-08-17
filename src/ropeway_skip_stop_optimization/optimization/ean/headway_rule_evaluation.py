from __future__ import annotations

from dataclasses import dataclass

from ropeway_skip_stop_optimization.models import (
    HeadwayRouteBehavior,
    HeadwayRule,
)


@dataclass(frozen=True)
class EanHeadwayPairEvaluation:
    forward_required_seconds: float
    reverse_required_seconds: float
    forward_margin_seconds: float
    reverse_margin_seconds: float

    @property
    def violation_seconds(self) -> float:
        return min(-self.forward_margin_seconds, -self.reverse_margin_seconds)

    def is_violated(self, *, tolerance_seconds: float) -> bool:
        return (
            self.forward_margin_seconds < -tolerance_seconds
            and self.reverse_margin_seconds < -tolerance_seconds
        )


def evaluate_headway_pair(
    *,
    rule: HeadwayRule,
    first_is_service: bool,
    second_is_service: bool,
    forward_gap_seconds: float,
    reverse_gap_seconds: float,
) -> EanHeadwayPairEvaluation:
    first = _behavior(first_is_service)
    second = _behavior(second_is_service)
    forward_required = rule.required_seconds(first, second)
    reverse_required = rule.required_seconds(second, first)
    return EanHeadwayPairEvaluation(
        forward_required_seconds=forward_required,
        reverse_required_seconds=reverse_required,
        forward_margin_seconds=forward_gap_seconds - forward_required,
        reverse_margin_seconds=reverse_gap_seconds - reverse_required,
    )


def _behavior(service: bool) -> HeadwayRouteBehavior:
    return HeadwayRouteBehavior.SERVICE if service else HeadwayRouteBehavior.BYPASS
