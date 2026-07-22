from __future__ import annotations

from dataclasses import dataclass

from ropeway_skip_stop_optimization.optimization.ean.builders.ring_switch_visit_builder import (
    RingSwitchVisitBuilder,
)
from ropeway_skip_stop_optimization.optimization.ean.builders.switch_visit_builder import (
    SwitchVisitBuilder,
)
from ropeway_skip_stop_optimization.optimization.ean.models import (
    EanCabinStart,
    EanConfig,
    SkipStopTiming,
    SwitchVisitBuildResult,
)
from ropeway_skip_stop_optimization.optimization.ean.network import EanCirculationPattern


@dataclass(frozen=True)
class NetworkVisitBuilder(SwitchVisitBuilder):
    """Build fixed visits from a deterministic network circulation pattern.

    Stage one deliberately shares the proven cyclic visit-counting kernel with
    the compatibility builder. Route decisions are introduced only in the
    later dynamic-routing stage.
    """

    pattern: EanCirculationPattern
    safety_visit_margin: int = 1
    selectable_initial_phase_count: int = 0

    def build(
        self,
        config: EanConfig,
        cabin_starts: tuple[EanCabinStart, ...],
        timings: tuple[SkipStopTiming, ...],
    ) -> SwitchVisitBuildResult:
        self.pattern.validate()
        return RingSwitchVisitBuilder(
            switch_cycle=self.pattern.state_ids,
            safety_visit_margin=self.safety_visit_margin,
            selectable_initial_phase_count=self.selectable_initial_phase_count,
        ).build(config=config, cabin_starts=cabin_starts, timings=timings)
