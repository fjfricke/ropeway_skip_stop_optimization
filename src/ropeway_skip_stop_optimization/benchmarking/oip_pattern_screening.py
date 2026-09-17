"""Deterministic pattern allocations for the OIP fleet screening pilot."""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from enum import StrEnum
from fractions import Fraction
import hashlib
import json
from typing import Iterable


Pattern = tuple[str, ...]


class OipScreeningDemandFamily(StrEnum):
    F0 = "f0"
    F2 = "f2"
    F3 = "f3"


@dataclass(frozen=True, slots=True)
class OipPatternAllocation:
    id: str
    label: str
    family: OipScreeningDemandFamily
    weights: tuple[tuple[Pattern, Fraction], ...]

    def validate(self, station_ids: tuple[str, ...]) -> None:
        known = set(station_ids)
        if not self.id or not self.label or not self.weights:
            raise ValueError("pattern allocation needs id, label, and weights")
        total = Fraction()
        for pattern, weight in self.weights:
            if not pattern or len(pattern) != len(set(pattern)):
                raise ValueError(f"invalid pattern {pattern!r}")
            if not set(pattern) <= known:
                raise ValueError(f"pattern {pattern!r} contains an unknown station")
            if weight <= 0:
                raise ValueError("pattern weights must be positive")
            total += weight
        if total != 1:
            raise ValueError(f"pattern weights must sum to one, got {total}")


@dataclass(frozen=True, slots=True)
class MaterializedOipPatternAllocation:
    id: str
    label: str
    family: OipScreeningDemandFamily
    cabin_count: int
    counts: tuple[tuple[Pattern, int], ...]
    patterns_by_cabin_id: tuple[Pattern, ...]
    identity: str

    def validate(self) -> None:
        if self.cabin_count <= 0:
            raise ValueError("cabin_count must be positive")
        if sum(count for _, count in self.counts) != self.cabin_count:
            raise ValueError("pattern counts do not sum to cabin_count")
        if len(self.patterns_by_cabin_id) != self.cabin_count:
            raise ValueError("pattern sequence does not contain every cabin")
        if any(count <= 0 for _, count in self.counts):
            raise ValueError("materialized pattern counts must be positive")

    @property
    def composition(self) -> dict[str, int]:
        return {"+".join(pattern): count for pattern, count in self.counts}


def pattern_allocations(
    family: OipScreeningDemandFamily | str,
    station_ids: Iterable[str],
) -> tuple[OipPatternAllocation, ...]:
    family = OipScreeningDemandFamily(family)
    stations = tuple(station_ids)
    if len(stations) != 5 or len(set(stations)) != 5:
        raise ValueError("the screening catalog requires exactly five stations")
    all_stop = stations
    four_stop = tuple(
        tuple(station for station in stations if station != omitted)
        for omitted in stations
    )
    contiguous_three = tuple(
        tuple(stations[(index + offset) % 5] for offset in range(3))
        for index in range(5)
    )
    direct = tuple(
        (stations[index], stations[(index + 2) % 5]) for index in range(5)
    )
    express_three = tuple(
        (stations[index], stations[(index + 2) % 5], stations[(index + 4) % 5])
        for index in range(5)
    )

    def allocation(
        allocation_id: str,
        label: str,
        groups: tuple[tuple[tuple[Pattern, ...], Fraction], ...],
    ) -> OipPatternAllocation:
        combined: dict[Pattern, Fraction] = defaultdict(Fraction)
        order: list[Pattern] = []
        for masks, group_weight in groups:
            share = group_weight / len(masks)
            for mask in masks:
                if mask not in combined:
                    order.append(mask)
                combined[mask] += share
        result = OipPatternAllocation(
            id=allocation_id,
            label=label,
            family=family,
            weights=tuple((mask, combined[mask]) for mask in order),
        )
        result.validate(stations)
        return result

    single_all_stop = ((all_stop,), Fraction(1))
    if family is OipScreeningDemandFamily.F2:
        required = {"S1", "S2", "S3", "S4"}
        if not required <= set(stations):
            raise ValueError("F2 screening requires stations S1 through S4")
        direct_f2 = (("S1", "S3"), ("S2", "S4"))
        four_f2 = (("S1", "S2", "S3", "S4"),)
        definitions = (
            ("all_stop", "All-Stop", (single_all_stop,)),
            ("direct", "F2 direct", ((direct_f2, Fraction(1)),)),
            ("four_stop", "F2 four-stop", ((four_f2, Fraction(1)),)),
            (
                "direct_four_stop",
                "Direct + four-stop",
                ((direct_f2, Fraction(1, 2)), (four_f2, Fraction(1, 2))),
            ),
            (
                "direct_all_stop",
                "Direct + All-Stop",
                ((direct_f2, Fraction(1, 2)), (single_all_stop[0], Fraction(1, 2))),
            ),
            (
                "four_stop_all_stop",
                "Four-stop + All-Stop",
                ((four_f2, Fraction(1, 2)), (single_all_stop[0], Fraction(1, 2))),
            ),
        )
    elif family is OipScreeningDemandFamily.F0:
        definitions = (
            ("all_stop", "All-Stop", (single_all_stop,)),
            ("four_stop", "Rotating four-stop", ((four_stop, Fraction(1)),)),
            ("three_stop", "Rotating contiguous three-stop", ((contiguous_three, Fraction(1)),)),
            ("four_stop_all_stop", "Four-stop + All-Stop", ((four_stop, Fraction(1, 2)), (single_all_stop[0], Fraction(1, 2)))),
            ("three_stop_all_stop", "Three-stop + All-Stop", ((contiguous_three, Fraction(1, 2)), (single_all_stop[0], Fraction(1, 2)))),
            ("three_stop_four_stop", "Three-stop + four-stop", ((contiguous_three, Fraction(1, 2)), (four_stop, Fraction(1, 2)))),
        )
    else:
        definitions = (
            ("all_stop", "All-Stop", (single_all_stop,)),
            ("direct", "Rotating direct", ((direct, Fraction(1)),)),
            ("express_three", "Rotating express three-stop", ((express_three, Fraction(1)),)),
            (
                "direct_express_three",
                "Direct + express three-stop",
                ((direct, Fraction(1, 2)), (express_three, Fraction(1, 2))),
            ),
            ("direct_all_stop", "Direct + All-Stop", ((direct, Fraction(1, 2)), (single_all_stop[0], Fraction(1, 2)))),
            ("express_all_stop", "Express + All-Stop", ((express_three, Fraction(1, 2)), (single_all_stop[0], Fraction(1, 2)))),
        )
    return tuple(allocation(*definition) for definition in definitions)


def materialize_pattern_allocation(
    allocation: OipPatternAllocation,
    cabin_count: int,
    station_ids: Iterable[str],
) -> MaterializedOipPatternAllocation:
    stations = tuple(station_ids)
    allocation.validate(stations)
    if cabin_count <= 0:
        raise ValueError("cabin_count must be positive")
    quotas = tuple(weight * cabin_count for _, weight in allocation.weights)
    counts = [quota.numerator // quota.denominator for quota in quotas]
    missing = cabin_count - sum(counts)
    ranking = sorted(
        range(len(quotas)),
        key=lambda index: (-(quotas[index] - counts[index]), index),
    )
    for index in ranking[:missing]:
        counts[index] += 1
    positive = tuple(
        sorted(
            (
                (pattern, count)
                for (pattern, _), count in zip(allocation.weights, counts, strict=True)
                if count > 0
            ),
            key=lambda item: item[0],
        )
    )
    patterns = tuple(
        pattern for pattern, count in positive for _ in range(count)
    )
    identity = pattern_sequence_identity(patterns, family=allocation.family)
    result = MaterializedOipPatternAllocation(
        id=allocation.id,
        label=allocation.label,
        family=allocation.family,
        cabin_count=cabin_count,
        counts=positive,
        patterns_by_cabin_id=patterns,
        identity=identity,
    )
    result.validate()
    return result


def pattern_sequence_identity(
    patterns: Iterable[Pattern],
    *,
    family: OipScreeningDemandFamily | str,
) -> str:
    counts: dict[Pattern, int] = defaultdict(int)
    for pattern in patterns:
        counts[tuple(pattern)] += 1
    identity_payload = {
        "family": OipScreeningDemandFamily(family).value,
        "counts": [
            (list(pattern), count) for pattern, count in sorted(counts.items())
        ],
    }
    return hashlib.sha256(
        json.dumps(identity_payload, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def demand_fingerprint(scenario, *, horizon_seconds: float, operation_seconds: float) -> str:
    payload = {
        "demands": [
            {
                "arrival": demand.arrival_time.isoformat(),
                "origin": demand.origin,
                "destination": demand.destination,
                "count": demand.count,
            }
            for demand in scenario.demands
        ],
        "horizon_seconds": horizon_seconds,
        "operation_seconds": operation_seconds,
    }
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
