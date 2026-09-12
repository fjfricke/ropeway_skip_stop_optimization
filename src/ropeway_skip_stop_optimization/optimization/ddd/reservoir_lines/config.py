from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
import math

from ..time_ticks import ddd_seconds_to_tick, ddd_tick_to_seconds


class ReservoirLineVariant(StrEnum):
    DISPATCH_DOMAINS = "dispatch_domains"
    INTERVALS = "intervals"
    PATH_SELECTION = "path_selection"


class ReservoirLineMode(StrEnum):
    FEASIBILITY = "feasibility"
    EXACT_SERVICE = "exact_service"
    OPTIMISTIC_SERVICE = "optimistic_service"


class ReservoirLineCatalogProfile(StrEnum):
    SMALL = "small"
    RELEVANT = "relevant"


@dataclass(frozen=True)
class ReservoirLineConfig:
    dispatch_window_end_seconds: float
    variant: ReservoirLineVariant = ReservoirLineVariant.DISPATCH_DOMAINS
    mode: ReservoirLineMode = ReservoirLineMode.EXACT_SERVICE
    catalog_profile: ReservoirLineCatalogProfile = ReservoirLineCatalogProfile.SMALL
    maximum_cabins: int | None = None
    fixed_cabins: int | None = None
    fixed_pattern_sequence: tuple[str, ...] = ()
    time_limit_seconds: float = 60.0
    workers: int = 12
    memory_limit_gib: float = 24.0
    seed: int = 0
    log_search_progress: bool = False
    presolve: bool = True

    @property
    def dispatch_window_end_tick(self) -> int:
        return ddd_seconds_to_tick(self.dispatch_window_end_seconds)

    def validate(self, available_fleet_count: int) -> None:
        if self.variant not in (
            ReservoirLineVariant.DISPATCH_DOMAINS,
            ReservoirLineVariant.INTERVALS,
        ):
            raise ValueError(
                f"reservoir line variant {self.variant.value!r} is not implemented"
            )
        if not isinstance(self.mode, ReservoirLineMode):
            raise ValueError("invalid reservoir line solve mode")
        if not isinstance(self.catalog_profile, ReservoirLineCatalogProfile):
            raise ValueError("invalid reservoir line catalog profile")
        if (
            not math.isfinite(self.dispatch_window_end_seconds)
            or self.dispatch_window_end_seconds < 0
            or abs(
                self.dispatch_window_end_seconds
                - ddd_tick_to_seconds(self.dispatch_window_end_tick)
            )
            > 1e-10
        ):
            raise ValueError(
                "dispatch window end must be finite, nonnegative, and on the tick grid"
            )
        limit = (
            available_fleet_count
            if self.maximum_cabins is None
            else self.maximum_cabins
        )
        if type(limit) is not int or not 1 <= limit <= available_fleet_count:
            raise ValueError("maximum cabins must lie within the available fleet")
        if self.fixed_cabins is not None and (
            type(self.fixed_cabins) is not int or not 0 <= self.fixed_cabins <= limit
        ):
            raise ValueError("fixed cabins must lie between zero and maximum cabins")
        if self.fixed_pattern_sequence and len(self.fixed_pattern_sequence) > limit:
            raise ValueError("fixed pattern sequence exceeds maximum cabins")
        if any(not isinstance(item, str) or not item for item in self.fixed_pattern_sequence):
            raise ValueError("fixed pattern sequence entries must be nonempty strings")
        if not math.isfinite(self.time_limit_seconds) or self.time_limit_seconds <= 0:
            raise ValueError("time limit must be finite and positive")
        if type(self.workers) is not int or self.workers <= 0:
            raise ValueError("workers must be a positive integer")
        if not math.isfinite(self.memory_limit_gib) or self.memory_limit_gib <= 0:
            raise ValueError("memory limit must be finite and positive")
        if type(self.seed) is not int:
            raise ValueError("seed must be an integer")
        if type(self.presolve) is not bool:
            raise ValueError("presolve must be boolean")
