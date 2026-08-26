from __future__ import annotations

from dataclasses import dataclass
import math
from typing import Any, Mapping

from ropeway_skip_stop_optimization.optimization.ddd.fixed_k import (
    DddFixedKExperimentProfile,
    DddFixedKOperatingMode,
    DddFixedKStartPolicy,
)
from ropeway_skip_stop_optimization.optimization.ean.passenger_objective import (
    EanPassengerObjective,
)


@dataclass(frozen=True, slots=True)
class DddFixedKCampaignConfig:
    campaign_id: str
    label: str
    example_id: str
    k_values: tuple[int, ...]
    operating_modes: tuple[DddFixedKOperatingMode, ...]
    objective: EanPassengerObjective = EanPassengerObjective.JOURNEY_TIME
    start_policy: DddFixedKStartPolicy = DddFixedKStartPolicy.CANONICAL_ROPE
    profile: DddFixedKExperimentProfile = DddFixedKExperimentProfile.SCREENING
    coordinated_primal_time_limit_seconds: float = 0.0
    coordinated_primal_interval: int = 5
    coordinated_primal_workers: int = 8
    coordinated_primal_candidate_count: int = 1
    coordinated_primal_maximum_preference_count: int = 200

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> DddFixedKCampaignConfig:
        result = cls(
            campaign_id=str(value["campaign_id"]),
            label=str(value.get("label", value["campaign_id"])),
            example_id=str(value["example_id"]),
            k_values=tuple(sorted({int(item) for item in value["k_values"]})),
            operating_modes=tuple(
                DddFixedKOperatingMode(str(item))
                for item in value.get(
                    "operating_modes",
                    (
                        DddFixedKOperatingMode.ALL_STOP.value,
                        DddFixedKOperatingMode.SKIP_STOP.value,
                    ),
                )
            ),
            objective=EanPassengerObjective(
                str(value.get("objective", EanPassengerObjective.JOURNEY_TIME.value))
            ),
            start_policy=DddFixedKStartPolicy(
                str(
                    value.get(
                        "start_policy", DddFixedKStartPolicy.CANONICAL_ROPE.value
                    )
                )
            ),
            profile=DddFixedKExperimentProfile(
                str(
                    value.get(
                        "profile", DddFixedKExperimentProfile.SCREENING.value
                    )
                )
            ),
            coordinated_primal_time_limit_seconds=float(
                value.get("coordinated_primal_time_limit_seconds", 0.0)
            ),
            coordinated_primal_interval=int(
                value.get("coordinated_primal_interval", 5)
            ),
            coordinated_primal_workers=int(
                value.get("coordinated_primal_workers", 8)
            ),
            coordinated_primal_candidate_count=int(
                value.get("coordinated_primal_candidate_count", 1)
            ),
            coordinated_primal_maximum_preference_count=int(
                value.get("coordinated_primal_maximum_preference_count", 200)
            ),
        )
        result.validate()
        return result

    def validate(self) -> None:
        if not self.campaign_id or not self.example_id:
            raise ValueError("Fixed-K campaign id and example id are required")
        if not self.k_values or self.k_values[0] <= 0:
            raise ValueError("Fixed-K campaign needs positive K values")
        if not self.operating_modes or len(set(self.operating_modes)) != len(
            self.operating_modes
        ):
            raise ValueError("Fixed-K operating modes must be nonempty and unique")
        if (
            not math.isfinite(self.coordinated_primal_time_limit_seconds)
            or self.coordinated_primal_time_limit_seconds < 0
        ):
            raise ValueError("coordinated primal time limit must be nonnegative")
        if (
            self.coordinated_primal_interval <= 0
            or self.coordinated_primal_workers <= 0
            or self.coordinated_primal_candidate_count <= 0
            or self.coordinated_primal_maximum_preference_count <= 0
        ):
            raise ValueError("coordinated primal settings must be positive")


def derive_available_fleet_intervals(
    exact_k_results: Mapping[int, tuple[float, float | None]],
) -> dict[int, tuple[float, float | None]]:
    """Derive certified intervals for a fleet with at most K cabins.

    Each input tuple is ``(LB_k, UB_k)`` for exactly k active cabins.  Because
    the available-fleet problem minimizes over the exact-cardinality problems,
    both endpoints are the corresponding prefix minima.
    """

    if not exact_k_results:
        return {}
    result: dict[int, tuple[float, float | None]] = {}
    best_lower = float("inf")
    best_upper: float | None = None
    for cabin_count in sorted(exact_k_results):
        if cabin_count <= 0:
            raise ValueError("available-fleet aggregation requires positive K")
        lower, upper = exact_k_results[cabin_count]
        best_lower = min(best_lower, lower)
        if upper is not None:
            best_upper = upper if best_upper is None else min(best_upper, upper)
        result[cabin_count] = (best_lower, best_upper)
    return result


def derive_skip_stop_benefit_interval(
    *,
    all_stop_lower: float,
    all_stop_upper: float,
    skip_stop_lower: float,
    skip_stop_upper: float,
) -> tuple[float, float]:
    """Bound ``z_AS - z_SS`` for a minimization objective."""

    return (
        all_stop_lower - skip_stop_upper,
        all_stop_upper - skip_stop_lower,
    )
