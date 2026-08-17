from __future__ import annotations

from dataclasses import dataclass

from ropeway_skip_stop_optimization.models import Scenario
from ropeway_skip_stop_optimization.optimization.ean import (
    EanCabinStart,
    EanCabinStartBuilder,
    EanCirculationPattern,
    EanConfig,
    EanMovementNetwork,
)


@dataclass(frozen=True)
class KeepEverySecondCabinStartBuilder(EanCabinStartBuilder):
    base_builder: EanCabinStartBuilder

    def build(
        self,
        scenario: Scenario,
        config: EanConfig,
        network: EanMovementNetwork,
        pattern: EanCirculationPattern,
    ) -> tuple[EanCabinStart, ...]:
        starts = self.base_builder.build(
            scenario=scenario,
            config=config,
            network=network,
            pattern=pattern,
        )
        return starts[::2]
