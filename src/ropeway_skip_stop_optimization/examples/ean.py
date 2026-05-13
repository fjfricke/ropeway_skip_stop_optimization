from __future__ import annotations

from typing import Protocol, runtime_checkable

from ropeway_skip_stop_optimization.models import Scenario
from ropeway_skip_stop_optimization.optimization.ean import EanBuildArtifactBuilder, EanConfig


@runtime_checkable
class EanScenarioExample(Protocol):
    """Scenario example capability for EAN artifact generation."""

    def build_ean_config(self, scenario: Scenario) -> EanConfig:
        """Build the EAN configuration for this physical scenario example."""
        ...

    def build_ean_artifact_builder(
        self,
        scenario: Scenario,
        config: EanConfig,
    ) -> EanBuildArtifactBuilder:
        """Build the EAN artifact builder for this physical scenario example."""
        ...
