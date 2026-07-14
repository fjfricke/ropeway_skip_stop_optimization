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

    def selection_names(self) -> tuple[str, ...]:
        names: list[str] = []
        if self.horizon is not EanHorizonFormulation.LEGACY:
            names.append(self.horizon.value)
        if self.time_bounds is not EanTimeBoundFormulation.LEGACY_PLUS_10:
            names.append(self.time_bounds.value)
        return tuple(names)


ALL_EAN_FORMULATION_SELECTION_NAMES: tuple[str, ...] = (
    *(value.value for value in EanHorizonFormulation),
    *(value.value for value in EanTimeBoundFormulation),
)
