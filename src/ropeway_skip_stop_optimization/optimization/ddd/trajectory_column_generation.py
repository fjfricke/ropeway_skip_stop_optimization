from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
import math


class DddTrajectoryOptimizerMode(StrEnum):
    """Trajectory backend used alongside the anonymous DDD master."""

    OFF = "off"
    RESTRICTED_PRIMAL = "restricted_primal"


class DddTrajectoryBoundStatus(StrEnum):
    """Strength of the mathematical certificate produced by the backend."""

    PRIMAL_POOL_ONLY = "primal_pool_only"
    TRAJECTORY_RELAXATION_BOUND = "trajectory_relaxation_bound"
    FULL_ROOT_LP_CERTIFIED = "full_root_lp_certified"
    BRANCH_PRICE_CERTIFIED = "branch_price_certified"


class DddTrajectoryWaitingDomain(StrEnum):
    NO_WAIT = "no_wait"
    BOUNDED_WAIT = "bounded_wait"


@dataclass(frozen=True)
class DddTrajectoryReducedCost:
    cabin_id: int
    minimum_reduced_cost: float
    exact: bool

    def __post_init__(self) -> None:
        if self.cabin_id < 0:
            raise ValueError("trajectory pricing cabin_id must be nonnegative")
        if not math.isfinite(self.minimum_reduced_cost):
            raise ValueError("trajectory reduced cost must be finite")


@dataclass(frozen=True)
class DddTrajectoryPricingCertificate:
    """Proof-safe reduced-cost correction for a trajectory RMP LP.

    A restricted-master value alone is not a lower bound.  The correction is
    exposed only when every required cabin pricing problem was solved exactly
    over the same waiting domain as the target problem.
    """

    restricted_master_lp_value: float
    expected_cabin_ids: tuple[int, ...]
    reduced_costs: tuple[DddTrajectoryReducedCost, ...]
    instance_fingerprint: str
    objective_fingerprint: str
    master_fingerprint: str
    dual_fingerprint: str
    row_pool_fingerprint: str
    pricing_waiting_domain: DddTrajectoryWaitingDomain
    target_waiting_domain: DddTrajectoryWaitingDomain
    row_separation_complete: bool = False
    tolerance: float = 1e-9

    def __post_init__(self) -> None:
        if not math.isfinite(self.restricted_master_lp_value):
            raise ValueError("trajectory RMP LP value must be finite")
        fingerprints = (
            self.instance_fingerprint,
            self.objective_fingerprint,
            self.master_fingerprint,
            self.dual_fingerprint,
            self.row_pool_fingerprint,
        )
        if any(not value.strip() for value in fingerprints):
            raise ValueError("trajectory pricing certificate fingerprints are required")
        if self.tolerance < 0 or not math.isfinite(self.tolerance):
            raise ValueError(
                "trajectory pricing tolerance must be finite and nonnegative"
            )
        expected = tuple(sorted(self.expected_cabin_ids))
        if not expected or len(expected) != len(set(expected)) or expected[0] < 0:
            raise ValueError("expected trajectory pricing cabin IDs must be unique")
        actual = tuple(sorted(item.cabin_id for item in self.reduced_costs))
        if len(actual) != len(set(actual)):
            raise ValueError("trajectory pricing contains duplicate cabin results")
        if actual != expected:
            raise ValueError("trajectory pricing does not cover the expected cabins")

    @property
    def pricing_complete(self) -> bool:
        return self.pricing_waiting_domain is self.target_waiting_domain and all(
            item.exact for item in self.reduced_costs
        )

    @property
    def certified_lower_bound(self) -> float | None:
        if not self.pricing_complete:
            return None
        return self.restricted_master_lp_value + sum(
            min(0.0, item.minimum_reduced_cost) for item in self.reduced_costs
        )

    @property
    def bound_status(self) -> DddTrajectoryBoundStatus:
        if not self.pricing_complete:
            return DddTrajectoryBoundStatus.PRIMAL_POOL_ONLY
        converged = all(
            item.minimum_reduced_cost >= -self.tolerance for item in self.reduced_costs
        )
        if converged and self.row_separation_complete:
            return DddTrajectoryBoundStatus.FULL_ROOT_LP_CERTIFIED
        return DddTrajectoryBoundStatus.TRAJECTORY_RELAXATION_BOUND
