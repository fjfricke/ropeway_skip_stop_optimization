from __future__ import annotations

from typing import Protocol, runtime_checkable

from ropeway_skip_stop_optimization.mapping import DiscretizationConfig
from ropeway_skip_stop_optimization.models import Scenario


@runtime_checkable
class DiscreteScenarioExample(Protocol):
    """Scenario example capability for discrete-time artifact generation."""

    def build_discretization_config(self, scenario: Scenario) -> DiscretizationConfig:
        """Build the discretization config for this physical scenario example."""
        ...
