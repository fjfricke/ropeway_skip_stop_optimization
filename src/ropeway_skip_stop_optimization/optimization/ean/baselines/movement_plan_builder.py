from __future__ import annotations

from abc import ABC, abstractmethod

from ropeway_skip_stop_optimization.optimization.ean.artifact import EanBuildArtifact
from ropeway_skip_stop_optimization.optimization.ean.plan import EanMovementPlan


class EanMovementPlanBuilder(ABC):
    @abstractmethod
    def build(self, artifact: EanBuildArtifact) -> EanMovementPlan:
        """Build a concrete EAN movement plan from a build artifact."""
