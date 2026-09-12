import math
from dataclasses import dataclass
from enum import StrEnum


class ReservoirDpVariant(StrEnum):
    SYMBOLIC_VISITS = "symbolic_visits"
    PATTERN_GROUPS = "pattern_groups"


class ReservoirDpSearchMode(StrEnum):
    PRIMAL = "primal"
    DUAL = "dual"


@dataclass(frozen=True)
class ReservoirDpConfig:
    variant: ReservoirDpVariant = ReservoirDpVariant.SYMBOLIC_VISITS
    search_mode: ReservoirDpSearchMode = ReservoirDpSearchMode.PRIMAL
    time_limit_seconds: float = 60.0
    workers: int = 1
    memory_limit_gib: float = 24.0
    initial_beam_width: int = 64
    max_beam_width: int = 1024
    keep_all_layers: bool = False

    def validate(self) -> None:
        try:
            ReservoirDpVariant(self.variant)
        except ValueError as error:
            raise ValueError("unknown reservoir DP variant") from error
        try:
            ReservoirDpSearchMode(self.search_mode)
        except ValueError as error:
            raise ValueError("unknown reservoir DP search mode") from error
        if not math.isfinite(self.time_limit_seconds) or self.time_limit_seconds <= 0:
            raise ValueError("reservoir DP time limit must be positive")
        if not math.isfinite(self.memory_limit_gib) or self.memory_limit_gib <= 0:
            raise ValueError("reservoir DP memory limit must be positive")
        for label, value in (
            ("workers", self.workers),
            ("initial beam width", self.initial_beam_width),
            ("maximum beam width", self.max_beam_width),
        ):
            if type(value) is not int or value <= 0:
                raise ValueError(f"reservoir DP {label} must be a positive integer")
        if self.initial_beam_width > self.max_beam_width:
            raise ValueError("reservoir DP initial beam width exceeds maximum")
