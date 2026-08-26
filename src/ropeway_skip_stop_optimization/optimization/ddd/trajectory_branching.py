from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from hashlib import sha256
import json
import math
from typing import Iterable

from ropeway_skip_stop_optimization.optimization.ddd.models import DddRouteDecision
from ropeway_skip_stop_optimization.optimization.ddd.reference import (
    DddReferenceTrajectory,
)


class DddTrajectoryBranchPredicateKind(StrEnum):
    SERVICE_DECISION = "service_decision"
    ROUTE_OPTION = "route_option"


@dataclass(frozen=True, order=True)
class DddTrajectoryBranchPredicate:
    """A physical binary predicate with a coefficient for every trajectory.

    A missing visit evaluates to false.  Consequently, branching on the
    predicate and its complement partitions the complete trajectory universe,
    including trajectories that terminate before the selected visit.
    """

    kind: DddTrajectoryBranchPredicateKind
    cabin_id: int
    visit_index: int
    value: str

    @classmethod
    def service_decision(
        cls,
        *,
        cabin_id: int,
        visit_index: int,
        decision: DddRouteDecision,
    ) -> DddTrajectoryBranchPredicate:
        return cls(
            kind=DddTrajectoryBranchPredicateKind.SERVICE_DECISION,
            cabin_id=cabin_id,
            visit_index=visit_index,
            value=decision.value,
        )

    @classmethod
    def route_option(
        cls,
        *,
        cabin_id: int,
        visit_index: int,
        route_option_id: str,
    ) -> DddTrajectoryBranchPredicate:
        return cls(
            kind=DddTrajectoryBranchPredicateKind.ROUTE_OPTION,
            cabin_id=cabin_id,
            visit_index=visit_index,
            value=route_option_id,
        )

    def validate(self) -> None:
        if not isinstance(self.kind, DddTrajectoryBranchPredicateKind):
            raise ValueError("trajectory branch predicate kind is invalid")
        if self.cabin_id < 0:
            raise ValueError("trajectory branch predicate cabin must be nonnegative")
        if self.visit_index < 0:
            raise ValueError("trajectory branch predicate visit must be nonnegative")
        if not self.value:
            raise ValueError("trajectory branch predicate value is empty")
        if self.kind is DddTrajectoryBranchPredicateKind.SERVICE_DECISION:
            try:
                DddRouteDecision(self.value)
            except ValueError as error:
                raise ValueError(
                    "trajectory service branch value is invalid"
                ) from error

    def evaluate(self, trajectory: DddReferenceTrajectory) -> bool:
        self.validate()
        if trajectory.cabin_id != self.cabin_id:
            return False
        if self.visit_index >= len(trajectory.visits):
            return False
        visit = trajectory.visits[self.visit_index]
        if self.kind is DddTrajectoryBranchPredicateKind.SERVICE_DECISION:
            return visit.decision.value == self.value
        return visit.route_option_id == self.value

    def to_payload(self) -> dict[str, object]:
        self.validate()
        return {
            "kind": self.kind.value,
            "cabin_id": self.cabin_id,
            "visit_index": self.visit_index,
            "value": self.value,
        }

    @classmethod
    def from_payload(cls, payload: dict[str, object]) -> DddTrajectoryBranchPredicate:
        predicate = cls(
            kind=DddTrajectoryBranchPredicateKind(str(payload["kind"])),
            cabin_id=int(payload["cabin_id"]),
            visit_index=int(payload["visit_index"]),
            value=str(payload["value"]),
        )
        predicate.validate()
        return predicate


@dataclass(frozen=True, order=True)
class DddTrajectoryBranchDecision:
    predicate: DddTrajectoryBranchPredicate
    required: bool

    def validate(self) -> None:
        self.predicate.validate()
        if not isinstance(self.required, bool):
            raise ValueError("trajectory branch decision required flag is invalid")

    def allows(self, trajectory: DddReferenceTrajectory) -> bool:
        if trajectory.cabin_id != self.predicate.cabin_id:
            return True
        return self.predicate.evaluate(trajectory) is self.required

    @property
    def complement(self) -> DddTrajectoryBranchDecision:
        return DddTrajectoryBranchDecision(
            predicate=self.predicate,
            required=not self.required,
        )

    def to_payload(self) -> dict[str, object]:
        self.validate()
        return {
            "predicate": self.predicate.to_payload(),
            "required": self.required,
        }

    @classmethod
    def from_payload(cls, payload: dict[str, object]) -> DddTrajectoryBranchDecision:
        predicate_payload = payload["predicate"]
        if not isinstance(predicate_payload, dict):
            raise ValueError("trajectory branch predicate payload is invalid")
        required = payload["required"]
        if not isinstance(required, bool):
            raise ValueError("trajectory branch decision required flag is invalid")
        decision = cls(
            predicate=DddTrajectoryBranchPredicate.from_payload(predicate_payload),
            required=required,
        )
        decision.validate()
        return decision


@dataclass(frozen=True)
class DddTrajectoryBranchDomain:
    decisions: tuple[DddTrajectoryBranchDecision, ...] = ()

    def __post_init__(self) -> None:
        normalized = tuple(sorted(self.decisions))
        if normalized != self.decisions:
            object.__setattr__(self, "decisions", normalized)
        self.validate()

    def validate(self) -> None:
        for decision in self.decisions:
            decision.validate()
        if len(set(self.decisions)) != len(self.decisions):
            raise ValueError("trajectory branch domain contains duplicate decisions")
        required_by_predicate: dict[DddTrajectoryBranchPredicate, bool] = {}
        for decision in self.decisions:
            previous = required_by_predicate.get(decision.predicate)
            if previous is not None and previous is not decision.required:
                raise ValueError("trajectory branch domain is contradictory")
            required_by_predicate[decision.predicate] = decision.required

    @property
    def fingerprint(self) -> str:
        return sha256(
            json.dumps(
                self.to_payload(),
                sort_keys=True,
                separators=(",", ":"),
            ).encode()
        ).hexdigest()

    def allows(self, trajectory: DddReferenceTrajectory) -> bool:
        return all(decision.allows(trajectory) for decision in self.decisions)

    def filter(
        self, trajectories: Iterable[DddReferenceTrajectory]
    ) -> tuple[DddReferenceTrajectory, ...]:
        return tuple(item for item in trajectories if self.allows(item))

    def child(
        self,
        predicate: DddTrajectoryBranchPredicate,
        *,
        required: bool,
    ) -> DddTrajectoryBranchDomain:
        decision = DddTrajectoryBranchDecision(
            predicate=predicate,
            required=required,
        )
        decision.validate()
        return DddTrajectoryBranchDomain((*self.decisions, decision))

    def decisions_for_cabin(
        self, cabin_id: int
    ) -> tuple[DddTrajectoryBranchDecision, ...]:
        if cabin_id < 0:
            raise ValueError("trajectory branch cabin must be nonnegative")
        return tuple(
            item for item in self.decisions if item.predicate.cabin_id == cabin_id
        )

    def to_payload(self) -> dict[str, object]:
        return {"decisions": [item.to_payload() for item in self.decisions]}

    @classmethod
    def from_payload(cls, payload: dict[str, object]) -> DddTrajectoryBranchDomain:
        raw = payload.get("decisions")
        if not isinstance(raw, list):
            raise ValueError("trajectory branch domain decisions are invalid")
        decisions = []
        for item in raw:
            if not isinstance(item, dict):
                raise ValueError("trajectory branch decision payload is invalid")
            decisions.append(DddTrajectoryBranchDecision.from_payload(item))
        return cls(tuple(decisions))


@dataclass(frozen=True)
class DddTrajectoryBranchCandidate:
    predicate: DddTrajectoryBranchPredicate
    true_mass: float
    false_mass: float

    def __post_init__(self) -> None:
        self.predicate.validate()
        if any(
            not math.isfinite(value) or value < 0
            for value in (self.true_mass, self.false_mass)
        ):
            raise ValueError("trajectory branch candidate mass is invalid")

    @property
    def score(self) -> float:
        return min(self.true_mass, self.false_mass)

    @property
    def preferred_required(self) -> bool:
        return self.true_mass >= self.false_mass


@dataclass(frozen=True)
class DddTrajectoryBranchCandidateEvaluator:
    tolerance: float = 1e-7

    def evaluate(
        self,
        *,
        trajectory_by_option_id: dict[str, DddReferenceTrajectory],
        option_values_by_id: dict[str, float],
        domain: DddTrajectoryBranchDomain = DddTrajectoryBranchDomain(),
    ) -> tuple[DddTrajectoryBranchCandidate, ...]:
        if self.tolerance < 0 or not math.isfinite(self.tolerance):
            raise ValueError("trajectory branching tolerance is invalid")
        unknown = set(option_values_by_id) - set(trajectory_by_option_id)
        if unknown:
            raise ValueError("trajectory branching values reference unknown options")

        values = {
            option_id: value
            for option_id, value in option_values_by_id.items()
            if value > self.tolerance
        }
        if any(not math.isfinite(value) or value < 0 for value in values.values()):
            raise ValueError("trajectory branching option value is invalid")

        by_cabin: dict[int, list[tuple[DddReferenceTrajectory, float]]] = {}
        for option_id, value in values.items():
            trajectory = trajectory_by_option_id[option_id]
            if not domain.allows(trajectory):
                raise ValueError("trajectory branching LP violates its branch domain")
            by_cabin.setdefault(trajectory.cabin_id, []).append((trajectory, value))

        candidates: list[DddTrajectoryBranchCandidate] = []
        for cabin_id, weighted in sorted(by_cabin.items()):
            total_mass = sum(value for _, value in weighted)
            maximum_visit_count = max(len(item.visits) for item, _ in weighted)
            for visit_index in range(maximum_visit_count):
                predicate = DddTrajectoryBranchPredicate.service_decision(
                    cabin_id=cabin_id,
                    visit_index=visit_index,
                    decision=DddRouteDecision.STOP,
                )
                true_mass = sum(
                    value for item, value in weighted if predicate.evaluate(item)
                )
                false_mass = total_mass - true_mass
                if (
                    true_mass > self.tolerance
                    and false_mass > self.tolerance
                ):
                    candidates.append(
                        DddTrajectoryBranchCandidate(
                            predicate=predicate,
                            true_mass=true_mass,
                            false_mass=false_mass,
                        )
                    )

        return tuple(
            sorted(
                candidates,
                key=lambda item: (
                    -item.score,
                    item.predicate,
                ),
            )
        )
