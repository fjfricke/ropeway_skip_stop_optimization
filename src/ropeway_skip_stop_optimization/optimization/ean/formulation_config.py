from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

HORIZON_ACTIVATION_EPSILON_SECONDS = 1e-4


class EanHorizonFormulation(StrEnum):
    """Operational meaning of visits around the configured model end.

    `LEGACY` preserves the historical behavior in which every generated safety
    visit receives normal route and headway decisions.

    `CONSERVATIVE_FREE_SUFFIX` keeps every visit whose conservative earliest
    switch time is at or before the operational horizon. The first later visit
    is timing-only boundary context. This can constrain a freely optimized
    finite continuation beyond the horizon.

    `EXACT_TIME_ACTIVATION` decides from optimized event times which visits and
    checkpoint occurrences belong to the finite operational horizon. A visit
    entering by the horizon remains modeled through its route clearance, while
    later visits receive no route decision.
    """

    LEGACY = "horizon_legacy"
    CONSERVATIVE_FREE_SUFFIX = "horizon_conservative_free_suffix"
    EXACT_TIME_ACTIVATION = "horizon_exact_time_activation"


class EanTimeBoundFormulation(StrEnum):
    """Finite bounds used for EAN switch, exit, and waiting variables.

    `LEGACY_PLUS_10` gives every time variable one global upper bound: the
    longest generated no-wait cabin chain plus ten seconds. For the longest
    chain this leaves only ten seconds of cumulative waiting, so it is retained
    as a reproducible historical baseline rather than the finite-horizon
    contract.

    `DERIVED_VISIT_BOUNDS` propagates per-visit earliest and latest times.
    Waiting uses a station-specific physical limit when configured and
    otherwise one operational horizon as a terminal occupancy cap. This avoids
    coupling feasible waiting to faster skip decisions.
    """

    LEGACY_PLUS_10 = "time_bounds_legacy_plus_10"
    DERIVED_VISIT_BOUNDS = "time_bounds_derived_visit_bounds"


class EanStopSkipTimingFormulation(StrEnum):
    """Linear formulation of active visit stop/skip timing.

    `BIG_M` preserves the historical four timing implications.

    `AFFINE` uses one exact affine equality for every unconditionally active
    visit. Under exact horizon activation, the equality is enabled by the
    visit-activation binary.
    """

    BIG_M = "stop_skip_timing_big_m"
    AFFINE = "stop_skip_timing_affine"


class EanSlotActivationFormulation(StrEnum):
    """Placement of candidate-level constraints for unary passenger slots.

    `PER_SLOT_IMPLICATIONS` preserves the historical formulation, which repeats
    candidate-level stop and time implications for every interchangeable slot.

    `FIRST_SLOT_IMPLICATIONS` attaches those implications only to the first
    unary slot. Every later slot is at most the first slot, so this removes
    rows implied even in the LP relaxation. It also omits the zero-release
    implication and, when slot-time strengthening is enabled, lower-bound rows
    that are algebraically implied by existing variable bounds and the retained
    minimum-trip-duration row.
    """

    PER_SLOT_IMPLICATIONS = "slot_activation_per_slot"
    FIRST_SLOT_IMPLICATIONS = "slot_activation_first_slot"


class EanBoardTimeFormulation(StrEnum):
    """Representation of selected boarding times in passenger objectives.

    `AUTO` resolves to the formulation appropriate for the passenger
    objective: projected boarding time for journey time and explicit boarding
    time for waiting time. It is an internal default, not a CLI selection.

    `EXPLICIT` keeps one selected boarding-time variable per passenger slot.
    It is required for the waiting-time objective.

    `PROJECTED_JOURNEY_TIME` removes those variables for the journey-time
    objective through the exact Fourier--Motzkin projection of their
    linearization and minimum-trip-time constraints.
    """

    AUTO = "board_time_auto"
    EXPLICIT = "board_time_explicit"
    PROJECTED_JOURNEY_TIME = "board_time_projected_journey_time"


@dataclass(frozen=True)
class EanFormulationConfig:
    """Mutually exclusive EAN formulation choices.

    These choices are separate from independently combinable exact reductions.
    Exactly one value is selected per category. Horizon values intentionally
    define different finite-horizon semantics and must not be described as
    performance-only optimizations.
    """

    horizon: EanHorizonFormulation = EanHorizonFormulation.LEGACY
    time_bounds: EanTimeBoundFormulation = EanTimeBoundFormulation.LEGACY_PLUS_10
    stop_skip_timing: EanStopSkipTimingFormulation = EanStopSkipTimingFormulation.AFFINE
    slot_activation: EanSlotActivationFormulation = EanSlotActivationFormulation.FIRST_SLOT_IMPLICATIONS
    board_time: EanBoardTimeFormulation = EanBoardTimeFormulation.AUTO

    def selection_names(self) -> tuple[str, ...]:
        names: list[str] = []
        if self.horizon is not EanHorizonFormulation.LEGACY:
            names.append(self.horizon.value)
        if self.time_bounds is not EanTimeBoundFormulation.LEGACY_PLUS_10:
            names.append(self.time_bounds.value)
        if self.stop_skip_timing is not EanStopSkipTimingFormulation.AFFINE:
            names.append(self.stop_skip_timing.value)
        if self.slot_activation is not EanSlotActivationFormulation.FIRST_SLOT_IMPLICATIONS:
            names.append(self.slot_activation.value)
        if self.board_time is not EanBoardTimeFormulation.AUTO:
            names.append(self.board_time.value)
        return tuple(names)


ALL_EAN_FORMULATION_SELECTION_NAMES: tuple[str, ...] = (
    *(value.value for value in EanHorizonFormulation),
    *(value.value for value in EanTimeBoundFormulation),
    *(value.value for value in EanStopSkipTimingFormulation),
    *(value.value for value in EanSlotActivationFormulation),
    *(
        value.value
        for value in EanBoardTimeFormulation
        if value is not EanBoardTimeFormulation.AUTO
    ),
)
