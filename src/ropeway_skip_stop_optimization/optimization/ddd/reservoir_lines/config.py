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


class ReservoirLinePreparation(StrEnum):
    LEGACY_EAGER = "legacy_eager"
    ENCODING_SPECIFIC = "encoding_specific"


class ReservoirLineFormulation(StrEnum):
    LEGACY_TEMPLATES = "legacy_templates"
    SHARED_ROUNDS = "shared_rounds"
    SHARED_RIDES = "shared_rides"
    SHARED_EVENTS = "shared_events"


class ReservoirLineCatalogProfile(StrEnum):
    SMALL = "small"
    OD_ENDPOINTS_V1 = "od_endpoints_v1"
    RELEVANT = "relevant"


@dataclass(frozen=True)
class ReservoirLineConfig:
    dispatch_window_end_seconds: float
    passenger_service_start_seconds: float | None = None
    variant: ReservoirLineVariant = ReservoirLineVariant.INTERVALS
    preparation: ReservoirLinePreparation = ReservoirLinePreparation.ENCODING_SPECIFIC
    formulation: ReservoirLineFormulation = ReservoirLineFormulation.SHARED_ROUNDS
    mode: ReservoirLineMode = ReservoirLineMode.EXACT_SERVICE
    catalog_profile: ReservoirLineCatalogProfile = ReservoirLineCatalogProfile.SMALL
    maximum_cabins: int | None = None
    fixed_cabins: int | None = None
    fixed_pattern_sequence: tuple[str, ...] = ()
    fixed_pattern_counts: tuple[tuple[str, int], ...] = ()
    fixed_service_class_counts: tuple[tuple[str, int], ...] = ()
    time_limit_seconds: float = 60.0
    workers: int = 12
    memory_limit_gib: float = 24.0
    seed: int = 0
    log_search_progress: bool = False
    presolve: bool = True

    @property
    def dispatch_window_end_tick(self) -> int:
        return ddd_seconds_to_tick(self.dispatch_window_end_seconds)

    @property
    def service_start_tick(self) -> int:
        """Start of passenger service after the fleet-dispatch phase."""
        return ddd_seconds_to_tick(
            self.dispatch_window_end_seconds
            if self.passenger_service_start_seconds is None
            else self.passenger_service_start_seconds
        )

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
        if not isinstance(self.preparation, ReservoirLinePreparation):
            raise ValueError("invalid reservoir line preparation mode")
        if not isinstance(self.formulation, ReservoirLineFormulation):
            raise ValueError("invalid reservoir line formulation")
        if self.formulation is ReservoirLineFormulation.SHARED_EVENTS:
            raise ValueError("shared_events formulation is not implemented")
        if (
            self.formulation is not ReservoirLineFormulation.LEGACY_TEMPLATES
            and self.variant is not ReservoirLineVariant.INTERVALS
            and not (
                self.variant is ReservoirLineVariant.DISPATCH_DOMAINS
                and self.fixed_cabins is not None
                and (
                    (
                        self.fixed_pattern_sequence
                        and len(self.fixed_pattern_sequence) == self.fixed_cabins
                    )
                    or (
                        self.fixed_pattern_counts
                        and sum(count for _, count in self.fixed_pattern_counts)
                        == self.fixed_cabins
                    )
                )
            )
        ):
            raise ValueError(
                "shared line formulations require intervals encoding unless a "
                "complete fixed pattern sequence enables lazy dispatch domains"
            )
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
        if self.passenger_service_start_seconds is not None and (
            not math.isfinite(self.passenger_service_start_seconds)
            or self.passenger_service_start_seconds < 0
            or abs(
                self.passenger_service_start_seconds
                - ddd_tick_to_seconds(self.service_start_tick)
            )
            > 1e-10
        ):
            raise ValueError(
                "passenger service start must be nonnegative and on the tick grid"
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
        if self.fixed_pattern_counts:
            if self.fixed_pattern_sequence or self.fixed_service_class_counts:
                raise ValueError(
                    "fixed pattern counts conflict with fixed sequence or service classes"
                )
            ids = [item[0] for item in self.fixed_pattern_counts]
            if len(ids) != len(set(ids)):
                raise ValueError("fixed pattern IDs must be unique")
            if any(
                not isinstance(item, tuple)
                or len(item) != 2
                or not isinstance(item[0], str)
                or not item[0]
                or type(item[1]) is not int
                or item[1] <= 0
                for item in self.fixed_pattern_counts
            ):
                raise ValueError(
                    "fixed pattern counts require nonempty IDs and positive counts"
                )
            total = sum(item[1] for item in self.fixed_pattern_counts)
            if total > limit:
                raise ValueError("fixed pattern counts exceed maximum cabins")
            if self.fixed_cabins is not None and self.fixed_cabins != total:
                raise ValueError("fixed cabin count differs from fixed pattern total")
        if self.fixed_service_class_counts:
            if self.mode is not ReservoirLineMode.FEASIBILITY:
                raise ValueError("fixed service classes require feasibility mode")
            if self.fixed_pattern_sequence or self.fixed_pattern_counts:
                raise ValueError(
                    "fixed service classes conflict with fixed pattern choices"
                )
            ids = [item[0] for item in self.fixed_service_class_counts]
            if len(ids) != len(set(ids)):
                raise ValueError("fixed service class IDs must be unique")
            if any(
                not isinstance(item, tuple)
                or len(item) != 2
                or not isinstance(item[0], str)
                or not item[0]
                or type(item[1]) is not int
                or item[1] <= 0
                for item in self.fixed_service_class_counts
            ):
                raise ValueError(
                    "fixed service classes require nonempty IDs and positive counts"
                )
            total = sum(item[1] for item in self.fixed_service_class_counts)
            if total > limit:
                raise ValueError("fixed service classes exceed maximum cabins")
            if self.fixed_cabins is not None and self.fixed_cabins != total:
                raise ValueError(
                    "fixed cabin count differs from fixed service class total"
                )
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
