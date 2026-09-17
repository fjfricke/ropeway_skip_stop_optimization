from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from hashlib import sha256
import json


class EvolutionEngine(StrEnum):
    GA = "ga"
    NSGA2 = "nsga2"
    TPE = "tpe"
    RANDOM = "random"


class OperatorProfile(StrEnum):
    LOCAL = "local"
    LOCAL_BLOCK = "local_block"
    MIXED_GLOBAL = "mixed_global"


@dataclass(frozen=True, slots=True)
class LineGenome:
    pattern_ids: tuple[str, ...]
    phase_tick: int
    extra_gap_ticks: tuple[int, ...]

    @property
    def fleet_size(self) -> int:
        return len(self.pattern_ids)

    @property
    def identity(self) -> str:
        return sha256(json.dumps({
            "patterns": self.pattern_ids,
            "phase": self.phase_tick,
            "extra_gaps": self.extra_gap_ticks,
        }, sort_keys=True).encode()).hexdigest()

    def validate(
        self,
        *,
        maximum_cabins: int,
        minimum_gap_tick: int,
        window_tick: int,
        dispatch_step_tick: int = 1,
    ) -> None:
        if not 0 <= self.fleet_size <= maximum_cabins:
            raise ValueError("evolution fleet size lies outside its domain")
        if type(self.phase_tick) is not int or self.phase_tick < 0:
            raise ValueError("evolution phase must be a nonnegative integer tick")
        if len(self.extra_gap_ticks) != max(0, self.fleet_size - 1):
            raise ValueError("evolution gap vector has the wrong length")
        if any(type(x) is not int or x < 0 for x in self.extra_gap_ticks):
            raise ValueError("evolution extra gaps must be nonnegative integer ticks")
        if (
            self.phase_tick % dispatch_step_tick
            or any(x % dispatch_step_tick for x in self.extra_gap_ticks)
        ):
            raise ValueError("evolution dispatch values must lie on the dispatch grid")
        last = self.phase_tick + max(0, self.fleet_size - 1) * minimum_gap_tick + sum(self.extra_gap_ticks)
        if self.fleet_size and last > window_tick:
            raise ValueError("evolution dispatch sequence exceeds its window")

    def dispatch_ticks(self, minimum_gap_tick: int) -> tuple[int, ...]:
        if not self.pattern_ids:
            return ()
        result = [self.phase_tick]
        for extra in self.extra_gap_ticks:
            result.append(result[-1] + minimum_gap_tick + extra)
        return tuple(result)


@dataclass(frozen=True, slots=True)
class ConflictWitness:
    resource_id: str
    first_cabin_id: int
    second_cabin_id: int
    overlap_ticks: int


@dataclass(frozen=True, slots=True)
class MovementEvaluation:
    genome: LineGenome
    feasible: bool
    plan: object | None
    conflicts: tuple[ConflictWitness, ...]
    total_overlap_ticks: int
    optimistic_od_coverage: int
    decode_seconds: float
    reason: str | None = None
    # A collision-bearing timetable is search input, never a certificate.
    relaxed_timetable: object | None = None


@dataclass(frozen=True, slots=True)
class PassengerEvaluation:
    plan: object
    served: int
    unserved: int
    proven_optimal: bool
    native_served_upper_bound: int | None
    ride_counts: tuple[tuple[str, int], ...]
    build_seconds: float
    solve_seconds: float
    validation_seconds: float
    status: str
    journey_time_tick: int | None = None


@dataclass(frozen=True, slots=True)
class PassengerPotential:
    """Assignment with inter-cabin collisions ignored; no valid-plan claim."""
    assigned: int
    unassigned: int
    proven_optimal: bool
    native_assigned_upper_bound: int | None
    build_seconds: float
    solve_seconds: float
    validation_seconds: float
    status: str


@dataclass(frozen=True, slots=True)
class CandidateEvaluation:
    movement: MovementEvaluation
    passengers: PassengerEvaluation | None
    cached: bool = False
    potential: PassengerPotential | None = None
    decoder: dict | None = None
    repair: dict | None = None

    @property
    def valid_served(self) -> int | None:
        return None if self.passengers is None else self.passengers.served
