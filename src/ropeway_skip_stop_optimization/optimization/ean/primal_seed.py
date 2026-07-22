from __future__ import annotations

from dataclasses import dataclass

from ropeway_skip_stop_optimization.optimization.ean.fleet import EanFleetPlan
from ropeway_skip_stop_optimization.optimization.ean.passenger_plan import (
    EanPassengerServicePlan,
)
from ropeway_skip_stop_optimization.optimization.ean.plan import EanMovementPlan


@dataclass(frozen=True)
class EanPrimalSeed:
    """Solver-independent primal data that may be installed as a MIP start."""

    fleet_plan: EanFleetPlan | None
    movement_plan: EanMovementPlan
    passenger_plan: EanPassengerServicePlan | None = None
