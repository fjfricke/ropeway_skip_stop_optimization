from __future__ import annotations

from abc import ABC, abstractmethod

from ropeway_skip_stop_optimization.optimization.ean.models import (
    EanCabinStart,
    EanConfig,
    SkipStopTiming,
    SwitchVisitBuildResult,
)


class SwitchVisitBuilder(ABC):
    @abstractmethod
    def build(
        self,
        config: EanConfig,
        cabin_starts: tuple[EanCabinStart, ...],
        timings: tuple[SkipStopTiming, ...],
    ) -> SwitchVisitBuildResult:
        """Build switch visits without creating solver variables."""
