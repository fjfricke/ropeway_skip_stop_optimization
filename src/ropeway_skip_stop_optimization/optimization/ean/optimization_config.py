from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Iterable


class EanOptimizationName(StrEnum):
    CANDIDATE_HORIZON_PRUNING = "candidate_horizon_pruning"
    SINGLE_RING_DOMINATED_RIDE_PRUNING = "single_ring_dominated_ride_pruning"
    SLOT_TIME_RELAXATION_STRENGTHENING = "slot_time_relaxation_strengthening"


ALL_EAN_OPTIMIZATION_NAMES: tuple[EanOptimizationName, ...] = tuple(EanOptimizationName)


@dataclass(frozen=True)
class EanOptimizationConfig:
    enable_candidate_horizon_pruning: bool = True
    enable_single_ring_dominated_ride_pruning: bool = True
    enable_slot_time_relaxation_strengthening: bool = True

    @classmethod
    def all(cls) -> EanOptimizationConfig:
        return cls()

    @classmethod
    def none(cls) -> EanOptimizationConfig:
        return cls(
            enable_candidate_horizon_pruning=False,
            enable_single_ring_dominated_ride_pruning=False,
            enable_slot_time_relaxation_strengthening=False,
        )

    @classmethod
    def from_enabled_names(cls, names: Iterable[EanOptimizationName | str]) -> EanOptimizationConfig:
        enabled = {EanOptimizationName(name) for name in names}
        return cls(
            enable_candidate_horizon_pruning=EanOptimizationName.CANDIDATE_HORIZON_PRUNING in enabled,
            enable_single_ring_dominated_ride_pruning=(
                EanOptimizationName.SINGLE_RING_DOMINATED_RIDE_PRUNING in enabled
            ),
            enable_slot_time_relaxation_strengthening=(
                EanOptimizationName.SLOT_TIME_RELAXATION_STRENGTHENING in enabled
            ),
        )

    @classmethod
    def from_selection(cls, selection: str) -> EanOptimizationConfig:
        normalized = selection.strip()
        if normalized == "all":
            return cls.all()
        if normalized == "none":
            return cls.none()
        names = [item.strip() for item in normalized.split(",") if item.strip()]
        if not names:
            raise ValueError("EAN optimization selection must be 'all', 'none', or a comma-separated list")
        return cls.from_enabled_names(names)

    def enabled_names(self) -> tuple[EanOptimizationName, ...]:
        names: list[EanOptimizationName] = []
        if self.enable_candidate_horizon_pruning:
            names.append(EanOptimizationName.CANDIDATE_HORIZON_PRUNING)
        if self.enable_single_ring_dominated_ride_pruning:
            names.append(EanOptimizationName.SINGLE_RING_DOMINATED_RIDE_PRUNING)
        if self.enable_slot_time_relaxation_strengthening:
            names.append(EanOptimizationName.SLOT_TIME_RELAXATION_STRENGTHENING)
        return tuple(names)

    def selection_label(self) -> str:
        enabled = self.enabled_names()
        if enabled == ALL_EAN_OPTIMIZATION_NAMES:
            return "all"
        if not enabled:
            return "none"
        return ",".join(name.value for name in enabled)
