from __future__ import annotations

from dataclasses import dataclass, field, replace
from enum import StrEnum
from typing import Iterable

from ropeway_skip_stop_optimization.optimization.ean.formulation_config import (
    ALL_EAN_FORMULATION_SELECTION_NAMES,
    EanBoardTimeFormulation,
    EanFormulationConfig,
    EanHorizonFormulation,
    EanSlotActivationFormulation,
    EanStopSkipTimingFormulation,
    EanTimeBoundFormulation,
)
from ropeway_skip_stop_optimization.optimization.ean.models import EanFleetMode


class EanOptimizationName(StrEnum):
    CANDIDATE_HORIZON_PRUNING = "candidate_horizon_pruning"
    SINGLE_RING_DOMINATED_RIDE_PRUNING = "single_ring_dominated_ride_pruning"
    SLOT_TIME_RELAXATION_STRENGTHENING = "slot_time_relaxation_strengthening"
    TIGHT_BIG_M_BOUNDS = "tight_big_m_bounds"
    FIXED_START_HEADWAY_PRECEDENCE = "fixed_start_headway_precedence"
    SHARED_MERGE_HEADWAY_ORDER = "shared_merge_headway_order"
    DIAGNOSTIC_RELAX_MERGE_HEADWAYS = "diagnostic_relax_merge_headways"
    OIP_FULL_INITIAL_STATE_SYMMETRY = "oip_full_initial_state_symmetry"
    OIP_INITIAL_HEADWAY_PRECEDENCE = "oip_initial_headway_precedence"
    OIP_INACTIVE_VARIABLE_CANONICALIZATION = (
        "oip_inactive_variable_canonicalization"
    )


class EanOptimizationSelectionOrigin(StrEnum):
    AUTO = "auto"
    EXPLICIT = "explicit"


ALL_EAN_OPTIMIZATION_NAMES: tuple[EanOptimizationName, ...] = tuple(EanOptimizationName)
ALL_EAN_SELECTION_NAMES: tuple[str, ...] = (
    *(name.value for name in ALL_EAN_OPTIMIZATION_NAMES),
    *ALL_EAN_FORMULATION_SELECTION_NAMES,
)
DEFAULT_EAN_OPTIMIZATION_NAMES: tuple[EanOptimizationName, ...] = (
    EanOptimizationName.CANDIDATE_HORIZON_PRUNING,
    EanOptimizationName.SINGLE_RING_DOMINATED_RIDE_PRUNING,
    EanOptimizationName.SLOT_TIME_RELAXATION_STRENGTHENING,
    EanOptimizationName.OIP_FULL_INITIAL_STATE_SYMMETRY,
    EanOptimizationName.OIP_INITIAL_HEADWAY_PRECEDENCE,
    EanOptimizationName.OIP_INACTIVE_VARIABLE_CANONICALIZATION,
)


@dataclass(frozen=True)
class EanOptimizationConfig:
    """Independent reductions plus mutually exclusive formulation choices.

    `from_selection` preserves one CLI list: optimization names are freely
    combinable, while at most one value from each formulation category may
    occur. Omitted formulation categories use the current production defaults.
    """

    enable_candidate_horizon_pruning: bool = True
    enable_single_ring_dominated_ride_pruning: bool = True
    enable_slot_time_relaxation_strengthening: bool = True
    enable_tight_big_m_bounds: bool = False
    enable_fixed_start_headway_precedence: bool = False
    enable_shared_merge_headway_order: bool = False
    enable_diagnostic_relax_merge_headways: bool = False
    enable_oip_full_initial_state_symmetry: bool = True
    enable_oip_initial_headway_precedence: bool = True
    enable_oip_inactive_variable_canonicalization: bool = True
    formulation: EanFormulationConfig = EanFormulationConfig()
    selection_origin: EanOptimizationSelectionOrigin = field(
        default=EanOptimizationSelectionOrigin.AUTO,
        compare=False,
    )
    explicit_formulation_names: frozenset[str] = field(
        default_factory=frozenset,
        compare=False,
    )

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
            enable_fixed_start_headway_precedence=False,
            enable_shared_merge_headway_order=False,
            enable_diagnostic_relax_merge_headways=False,
            enable_oip_full_initial_state_symmetry=False,
            enable_oip_initial_headway_precedence=False,
            enable_oip_inactive_variable_canonicalization=False,
            formulation=EanFormulationConfig(),
            selection_origin=EanOptimizationSelectionOrigin.EXPLICIT,
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
            enable_fixed_start_headway_precedence=(
                EanOptimizationName.FIXED_START_HEADWAY_PRECEDENCE in enabled
            ),
            enable_shared_merge_headway_order=(
                EanOptimizationName.SHARED_MERGE_HEADWAY_ORDER in enabled
            ),
            enable_diagnostic_relax_merge_headways=(
                EanOptimizationName.DIAGNOSTIC_RELAX_MERGE_HEADWAYS in enabled
            ),
            enable_oip_full_initial_state_symmetry=(
                EanOptimizationName.OIP_FULL_INITIAL_STATE_SYMMETRY in enabled
            ),
            enable_oip_initial_headway_precedence=(
                EanOptimizationName.OIP_INITIAL_HEADWAY_PRECEDENCE in enabled
            ),
            enable_oip_inactive_variable_canonicalization=(
                EanOptimizationName.OIP_INACTIVE_VARIABLE_CANONICALIZATION
                in enabled
            ),
            formulation=formulation or EanFormulationConfig(),
            selection_origin=EanOptimizationSelectionOrigin.EXPLICIT,
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
        if names == ["all"]:
            # The CLI default is the objective/fleet-aware production default,
            # not an explicit request to force every fixed-start reduction.
            return cls.all()

        horizon_values = [EanHorizonFormulation(name) for name in names if name in EanHorizonFormulation]
        time_bound_values = [EanTimeBoundFormulation(name) for name in names if name in EanTimeBoundFormulation]
        stop_skip_timing_values = [
            EanStopSkipTimingFormulation(name)
            for name in names
            if name in EanStopSkipTimingFormulation
        ]
        slot_activation_values = [
            EanSlotActivationFormulation(name)
            for name in names
            if name in EanSlotActivationFormulation
        ]
        board_time_values = [
            EanBoardTimeFormulation(name)
            for name in names
            if name in {
                EanBoardTimeFormulation.EXPLICIT,
                EanBoardTimeFormulation.PROJECTED_JOURNEY_TIME,
            }
        ]
        if len(horizon_values) > 1:
            raise ValueError("select at most one EAN horizon formulation")
        if len(time_bound_values) > 1:
            raise ValueError("select at most one EAN time-bound formulation")
        if len(stop_skip_timing_values) > 1:
            raise ValueError("select at most one EAN stop/skip timing formulation")
        if len(slot_activation_values) > 1:
            raise ValueError("select at most one EAN slot-activation formulation")
        if len(board_time_values) > 1:
            raise ValueError("select at most one EAN board-time formulation")

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
                else EanStopSkipTimingFormulation.AFFINE
            ),
            slot_activation=(
                slot_activation_values[0]
                if slot_activation_values
                else EanSlotActivationFormulation.FIRST_SLOT_IMPLICATIONS
            ),
            board_time=(
                board_time_values[0]
                if board_time_values
                else EanBoardTimeFormulation.AUTO
            ),
        )
        optimization_names: list[EanOptimizationName | str] = []
        if "all" in names:
            optimization_names.extend(DEFAULT_EAN_OPTIMIZATION_NAMES)
        optimization_names.extend(name for name in names if name in EanOptimizationName)
        return replace(
            cls.from_enabled_names(optimization_names, formulation=formulation),
            explicit_formulation_names=frozenset(
                name for name in names if name in ALL_EAN_FORMULATION_SELECTION_NAMES
            ),
        )

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
        if self.enable_fixed_start_headway_precedence:
            names.append(EanOptimizationName.FIXED_START_HEADWAY_PRECEDENCE)
        if self.enable_shared_merge_headway_order:
            names.append(EanOptimizationName.SHARED_MERGE_HEADWAY_ORDER)
        if self.enable_diagnostic_relax_merge_headways:
            names.append(
                EanOptimizationName.DIAGNOSTIC_RELAX_MERGE_HEADWAYS
            )
        if self.enable_oip_full_initial_state_symmetry:
            names.append(EanOptimizationName.OIP_FULL_INITIAL_STATE_SYMMETRY)
        if self.enable_oip_initial_headway_precedence:
            names.append(EanOptimizationName.OIP_INITIAL_HEADWAY_PRECEDENCE)
        if self.enable_oip_inactive_variable_canonicalization:
            names.append(
                EanOptimizationName.OIP_INACTIVE_VARIABLE_CANONICALIZATION
            )
        return tuple(names)

    def selection_label(self) -> str:
        enabled = self.enabled_names()
        formulation_names = self.formulation.selection_names()
        if enabled == DEFAULT_EAN_OPTIMIZATION_NAMES and not formulation_names:
            return "all"
        if not enabled and not formulation_names:
            return "none"
        return ",".join((*[name.value for name in enabled], *formulation_names))

    def resolved_for_passenger_objective(self, objective: str) -> EanOptimizationConfig:
        """Resolve the objective-aware boarding-time production default.

        The projected representation is exact only for journey time because
        selected boarding time is absent from that objective. Explicit user
        selections always take precedence over this automatic choice.
        """

        if self.formulation.board_time is not EanBoardTimeFormulation.AUTO:
            return self
        board_time = (
            EanBoardTimeFormulation.PROJECTED_JOURNEY_TIME
            if objective == "journey_time"
            else EanBoardTimeFormulation.EXPLICIT
        )
        return replace(
            self,
            formulation=replace(self.formulation, board_time=board_time),
        )

    def resolved_for_fleet_mode(
        self,
        fleet_mode: EanFleetMode,
    ) -> EanOptimizationConfig:
        if (
            self.enable_shared_merge_headway_order
            and self.enable_diagnostic_relax_merge_headways
        ):
            raise ValueError(
                "diagnostic_relax_merge_headways cannot be combined with "
                "shared_merge_headway_order"
            )
        if fleet_mode is EanFleetMode.FIXED_STARTS:
            return self
        if fleet_mode is not EanFleetMode.OPTIMIZED_INITIAL_PLACEMENT:
            raise ValueError(f"unsupported EAN fleet mode: {fleet_mode}")

        if (
            self.enable_oip_initial_headway_precedence
            and not self.enable_oip_full_initial_state_symmetry
        ):
            raise ValueError(
                "oip_initial_headway_precedence requires "
                "oip_full_initial_state_symmetry"
            )

        unsupported = []
        if self.enable_candidate_horizon_pruning:
            unsupported.append(EanOptimizationName.CANDIDATE_HORIZON_PRUNING.value)
        if self.enable_single_ring_dominated_ride_pruning:
            unsupported.append(
                EanOptimizationName.SINGLE_RING_DOMINATED_RIDE_PRUNING.value
            )
        if self.enable_tight_big_m_bounds:
            unsupported.append(EanOptimizationName.TIGHT_BIG_M_BOUNDS.value)
        if self.enable_fixed_start_headway_precedence:
            unsupported.append(
                EanOptimizationName.FIXED_START_HEADWAY_PRECEDENCE.value
            )
        if self.enable_shared_merge_headway_order:
            unsupported.append(
                EanOptimizationName.SHARED_MERGE_HEADWAY_ORDER.value
            )
        if self.enable_diagnostic_relax_merge_headways:
            unsupported.append(
                EanOptimizationName.DIAGNOSTIC_RELAX_MERGE_HEADWAYS.value
            )
        if (
            self.selection_origin is EanOptimizationSelectionOrigin.EXPLICIT
            and unsupported
        ):
            raise NotImplementedError(
                "optimized initial placement does not yet implement "
                + ", ".join(unsupported)
                + "; horizon pruning must minimize over boundary states, ring "
                "dominance must be proven per selected boundary trajectory, "
                "and time/headway reductions need state-specific safe bounds"
            )

        explicit_formulations = self.explicit_formulation_names
        if (
            EanHorizonFormulation.EXACT_TIME_ACTIVATION.value
            not in explicit_formulations
            and any(
                name in explicit_formulations
                for name in EanHorizonFormulation
            )
        ):
            raise NotImplementedError(
                "optimized initial placement currently requires "
                "horizon_exact_time_activation"
            )
        if any(name in explicit_formulations for name in EanTimeBoundFormulation):
            if (
                EanTimeBoundFormulation.INITIAL_PLACEMENT_SAFE.value
                not in explicit_formulations
            ):
                raise NotImplementedError(
                    "optimized initial placement requires boundary-state time "
                    "bounds; derived fixed-start bounds can later be adapted "
                    "per selected initial state"
                )

        return replace(
            self,
            enable_candidate_horizon_pruning=False,
            enable_single_ring_dominated_ride_pruning=False,
            enable_tight_big_m_bounds=False,
            enable_fixed_start_headway_precedence=False,
            enable_shared_merge_headway_order=False,
            enable_diagnostic_relax_merge_headways=False,
            formulation=replace(
                self.formulation,
                horizon=EanHorizonFormulation.EXACT_TIME_ACTIVATION,
                time_bounds=EanTimeBoundFormulation.INITIAL_PLACEMENT_SAFE,
            ),
        )
