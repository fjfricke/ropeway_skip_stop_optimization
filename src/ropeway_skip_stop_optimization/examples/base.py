from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass

from ropeway_skip_stop_optimization.models import Scenario


@dataclass(frozen=True)
class ScenarioExampleMetadata:
    id: str
    label: str
    description: str
    tags: tuple[str, ...] = ()


class ScenarioExample(ABC):
    metadata: ScenarioExampleMetadata

    @abstractmethod
    def build_scenario(self) -> Scenario:
        raise NotImplementedError
