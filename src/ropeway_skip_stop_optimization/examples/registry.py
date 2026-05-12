from __future__ import annotations

from ropeway_skip_stop_optimization.examples.base import ScenarioExample
from ropeway_skip_stop_optimization.examples.three_station import ThreeStationExample


EXAMPLES: dict[str, ScenarioExample] = {
    ThreeStationExample.metadata.id: ThreeStationExample(),
}


def get_example(example_id: str) -> ScenarioExample:
    try:
        return EXAMPLES[example_id]
    except KeyError as exc:
        known = ", ".join(sorted(EXAMPLES))
        raise ValueError(f"Unknown example id {example_id!r}. Known examples: {known}") from exc
