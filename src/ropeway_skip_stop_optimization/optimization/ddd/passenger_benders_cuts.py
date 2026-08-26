from __future__ import annotations

from dataclasses import dataclass, replace
from hashlib import sha256
import json
import math
from typing import Mapping


@dataclass(frozen=True, slots=True)
class DddPassengerBendersCut:
    id: str
    constant: float
    coefficients: tuple[tuple[str, float], ...]
    source_objective: float
    source_movement_signature: str
    kind: str = "lp_dual_optimality"
    globally_valid: bool = True
    proof_provenance: str = (
        "dual feasible solution of normalized fixed-movement Passenger LP"
    )

    def evaluate(self, movement_values: Mapping[str, float]) -> float:
        return self.constant + sum(
            coefficient * movement_values.get(arc_id, 0.0)
            for arc_id, coefficient in self.coefficients
        )

    def violation(
        self,
        movement_values: Mapping[str, float],
        theta_value: float,
    ) -> float:
        return self.evaluate(movement_values) - theta_value

    def validate(self) -> None:
        if not self.id or not self.source_movement_signature:
            raise ValueError("Passenger Benders cut needs stable provenance")
        if not math.isfinite(self.constant) or not math.isfinite(
            self.source_objective
        ):
            raise ValueError("Passenger Benders cut values must be finite")
        arc_ids = tuple(arc_id for arc_id, _ in self.coefficients)
        if tuple(sorted(arc_ids)) != arc_ids or len(set(arc_ids)) != len(arc_ids):
            raise ValueError("Passenger Benders cut coefficients are not canonical")
        if any(not math.isfinite(value) for _, value in self.coefficients):
            raise ValueError("Passenger Benders cut coefficients must be finite")
        if self.id != _cut_fingerprint(self):
            raise ValueError("Passenger Benders cut fingerprint is inconsistent")

    def to_payload(self) -> dict[str, object]:
        return {
            "id": self.id,
            "constant": self.constant,
            "coefficients": [list(item) for item in self.coefficients],
            "source_objective": self.source_objective,
            "source_movement_signature": self.source_movement_signature,
            "kind": self.kind,
            "globally_valid": self.globally_valid,
            "proof_provenance": self.proof_provenance,
        }

    @classmethod
    def from_payload(cls, payload: Mapping[str, object]) -> DddPassengerBendersCut:
        result = cls(
            id=str(payload["id"]),
            constant=float(payload["constant"]),
            coefficients=tuple(
                (str(item[0]), float(item[1]))
                for item in payload["coefficients"]
            ),
            source_objective=float(payload["source_objective"]),
            source_movement_signature=str(
                payload["source_movement_signature"]
            ),
            kind=str(payload["kind"]),
            globally_valid=bool(payload["globally_valid"]),
            proof_provenance=str(payload["proof_provenance"]),
        )
        result.validate()
        return result


@dataclass(slots=True)
class DddPassengerBendersCutPool:
    violation_tolerance: float = 1e-6
    _cuts_by_id: dict[str, DddPassengerBendersCut] | None = None

    def __post_init__(self) -> None:
        if self.violation_tolerance <= 0:
            raise ValueError("Passenger cut-pool tolerance must be positive")
        if self._cuts_by_id is None:
            self._cuts_by_id = {}

    @property
    def cuts(self) -> tuple[DddPassengerBendersCut, ...]:
        assert self._cuts_by_id is not None
        return tuple(self._cuts_by_id.values())

    def add_if_violated(
        self,
        cut: DddPassengerBendersCut,
        movement_values: Mapping[str, float],
        theta_value: float,
    ) -> bool:
        if cut.violation(movement_values, theta_value) <= self.violation_tolerance:
            return False
        return self.add(cut)

    def add(self, cut: DddPassengerBendersCut) -> bool:
        cut.validate()
        if not cut.globally_valid:
            raise ValueError("Passenger cut pool accepts only globally valid cuts")
        assert self._cuts_by_id is not None
        if cut.id in self._cuts_by_id:
            return False
        self._cuts_by_id[cut.id] = cut
        return True


def build_ddd_passenger_benders_cut(
    *,
    constant: float,
    coefficients: Mapping[str, float],
    source_objective: float,
    source_movement_signature: str,
    zero_tolerance: float = 1e-10,
) -> DddPassengerBendersCut:
    sparse = tuple(
        sorted(
            (arc_id, value)
            for arc_id, value in coefficients.items()
            if abs(value) > zero_tolerance
        )
    )
    incomplete = DddPassengerBendersCut(
        id="",
        constant=constant,
        coefficients=sparse,
        source_objective=source_objective,
        source_movement_signature=source_movement_signature,
    )
    result = replace(incomplete, id=_cut_fingerprint(incomplete))
    result.validate()
    return result


def ddd_movement_vector_signature(values: Mapping[str, float]) -> str:
    payload = tuple(
        (arc_id, round(float(value), 12))
        for arc_id, value in sorted(values.items())
    )
    return sha256(
        json.dumps(payload, separators=(",", ":")).encode()
    ).hexdigest()


def _cut_fingerprint(cut: DddPassengerBendersCut) -> str:
    payload = {
        "constant": cut.constant,
        "coefficients": cut.coefficients,
        "kind": cut.kind,
        "globally_valid": cut.globally_valid,
        "proof_provenance": cut.proof_provenance,
    }
    return sha256(
        json.dumps(payload, separators=(",", ":"), sort_keys=True).encode()
    ).hexdigest()
