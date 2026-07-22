from __future__ import annotations

from abc import ABC, abstractmethod

from ropeway_skip_stop_optimization.models import Scenario
from ropeway_skip_stop_optimization.optimization.ean.artifact import EanBuildArtifact
from ropeway_skip_stop_optimization.optimization.ean.build_profile import (
    EanBuildProgressCallback,
)
from ropeway_skip_stop_optimization.optimization.ean.models import EanConfig


class EanBuildArtifactBuilder(ABC):
    @abstractmethod
    def build(
        self,
        scenario: Scenario,
        config: EanConfig,
        *,
        progress_callback: EanBuildProgressCallback | None = None,
    ) -> EanBuildArtifact:
        """Build an EAN artifact from a physical scenario and EAN config."""
