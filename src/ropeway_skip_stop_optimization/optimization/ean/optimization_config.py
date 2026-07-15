from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Iterable

from ropeway_skip_stop_optimization.optimization.ean.formulation_config import (
    ALL_EAN_FORMULATION_SELECTION_NAMES,
    EanFormulationConfig,
    EanHorizonFormulation,
    EanStopSkipTimingFormulation,
    EanTimeBoundFormulation,
)


class EanOptimizationName(StrEnum):
    CANDIDATE_HORIZON_PRUNING = "candidate_horizon_pruning"
    SINGLE_RING_DOMINATED_RIDE_PRUNING = "single_ring_dominated_ride_pruning"
    SLOT_TIME_RELAXATION_STRENGTHENING = "slot_time_relaxation_strengthening"
    TIGHT_BIG_M_BOUNDS = "tight_big_m_bounds"


ALL_EAN_OPTIMIZATION_NAMES: tuple[EanOptimizationName, ...] = tuple(EanOptimizationName)
ALL_EAN_SELECTION_NAMES: tuple[str, ...] = (
    *(name.value for name in ALL_EAN_OPTIMIZATION_NAMES),
    *ALL_EAN_FORMULATION_SELECTION_NAMES,
)
DEFAULT_EAN_OPTIMIZATION_NAMES: tuple[EanOptimizationName, ...] = (
    EanOptimizationName.CANDIDATE_HORIZON_PRUNING,
    EanOptimizationName.SINGLE_RING_DOMINATED_RIDE_PRUNING,
    EanOptimizationName.SLOT_TIME_RELAXATION_STRENGTHENING,
)


@dataclass(frozen=True)
class EanOptimizationConfig:
    """Independent reductions plus mutually exclusive formulation choices.

    `from_selection` preserves one CLI list: optimization names are freely
    combinable, while at most one value from each formulation category may
    occur. Omitted formulation categories use their legacy defaults.
    """

    enable_candidate_horizon_pruning: bool = True
    enable_single_ring_dominated_ride_pruning: bool = True
    enable_slot_time_relaxation_strengthening: bool = True
    enable_tight_big_m_bounds: bool = False
    formulation: EanFormulationConfig = EanFormulationConfig()

    @classmethod
    def all(cls) -> EanOptimizationConfig:
        return cls()

    @classmethod
    def none(cls) -> EanOptimizationConfig:
        return cls(
            enable_candidate_horizon_pruning=False,
            enable_single_ring_dominated_ride_pruning=False,
            enable_slot_time_relaxation_strengthening=False,
            enable_tight_big_m_bounds=False,
            formulation=EanFormulationConfig(),
        )

    @classmethod
    def from_enabled_names(
        cls,
        names: Iterable[EanOptimizationName | str],
        *,
        formulation: EanFormulationConfig | None = None,
    ) -> EanOptimizationConfig:
        enabled = {EanOptimizationName(name) for name in names}
        return cls(
            enable_candidate_horizon_pruning=EanOptimizationName.CANDIDATE_HORIZON_PRUNING in enabled,
            enable_single_ring_dominated_ride_pruning=(
                EanOptimizationName.SINGLE_RING_DOMINATED_RIDE_PRUNING in enabled
            ),
            enable_slot_time_relaxation_strengthening=(
                EanOptimizationName.SLOT_TIME_RELAXATION_STRENGTHENING in enabled
            ),
            enable_tight_big_m_bounds=EanOptimizationName.TIGHT_BIG_M_BOUNDS in enabled,
            formulation=formulation or EanFormulationConfig(),
        )

    @classmethod
    def from_selection(cls, selection: str) -> EanOptimizationConfig:
        normalized = selection.strip()
        names = [item.strip() for item in normalized.split(",") if item.strip()]
        if not names:
            raise ValueError("EAN optimization selection must be 'all', 'none', or a comma-separated list")
        keywords = {"all", "none"}
        unknown = sorted(set(names) - set(ALL_EAN_SELECTION_NAMES) - keywords)
        if unknown:
            raise ValueError(f"unknown EAN configuration selections: {', '.join(unknown)}")
        if "all" in names and "none" in names:
            raise ValueError("EAN configuration selection cannot combine 'all' and 'none'")

        horizon_values = [EanHorizonFormulation(name) for name in names if name in EanHorizonFormulation]
        time_bound_values = [EanTimeBoundFormulation(name) for name in names if name in EanTimeBoundFormulation]
        stop_skip_timing_values = [
            EanStopSkipTimingFormulation(name)
            for name in names
            if name in EanStopSkipTimingFormulation
        ]
        if len(horizon_values) > 1:
            raise ValueError("select at most one EAN horizon formulation")
        if len(time_bound_values) > 1:
            raise ValueError("select at most one EAN time-bound formulation")
        if len(stop_skip_timing_values) > 1:
            raise ValueError("select at most one EAN stop/skip timing formulation")

        formulation = EanFormulationConfig(
            horizon=horizon_values[0] if horizon_values else EanHorizonFormulation.LEGACY,
            time_bounds=(
                time_bound_values[0]
                if time_bound_values
                else EanTimeBoundFormulation.LEGACY_PLUS_10
            ),
            stop_skip_timing=(
                stop_skip_timing_values[0]
                if stop_skip_timing_values
                else EanStopSkipTimingFormulation.BIG_M
            ),
        )
        optimization_names: list[EanOptimizationName | str] = []
        if "all" in names:
            optimization_names.extend(DEFAULT_EAN_OPTIMIZATION_NAMES)
        optimization_names.extend(name for name in names if name in EanOptimizationName)
        return cls.from_enabled_names(optimization_names, formulation=formulation)

    def enabled_names(self) -> tuple[EanOptimizationName, ...]:
        names: list[EanOptimizationName] = []
        if self.enable_candidate_horizon_pruning:
            names.append(EanOptimizationName.CANDIDATE_HORIZON_PRUNING)
        if self.enable_single_ring_dominated_ride_pruning:
            names.append(EanOptimizationName.SINGLE_RING_DOMINATED_RIDE_PRUNING)
        if self.enable_slot_time_relaxation_strengthening:
            names.append(EanOptimizationName.SLOT_TIME_RELAXATION_STRENGTHENING)
        if self.enable_tight_big_m_bounds:
            names.append(EanOptimizationName.TIGHT_BIG_M_BOUNDS)
        return tuple(names)

    def selection_label(self) -> str:
        enabled = self.enabled_names()
        formulation_names = self.formulation.selection_names()
        if enabled == DEFAULT_EAN_OPTIMIZATION_NAMES and not formulation_names:
            return "all"
        if not enabled and not formulation_names:
            return "none"
        return ",".join((*[name.value for name in enabled], *formulation_names))
