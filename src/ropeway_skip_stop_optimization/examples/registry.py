from __future__ import annotations

from ropeway_skip_stop_optimization.examples.base import ScenarioExample
from ropeway_skip_stop_optimization.examples.artificial_headway_cases import (
    FiveStationCircleCwFullSkipNoWaitHeadwayBExample,
    FiveStationCircleCwFullSkipWaitHeadwayBExample,
    FiveStationCircleCwHalfSkipNoWaitHeadwayBExample,
    artificial_physical_headway_examples,
)
from ropeway_skip_stop_optimization.examples.circular_skip_stop import (
    FiveStationOptimizedInitialPlacementAllStopSkipWaitExample,
    FiveStationOptimizedInitialPlacementNoSkipNoWaitExample,
    FiveStationOptimizedInitialPlacementDoubleAllStopSkipWaitExample,
    FiveStationOptimizedInitialPlacementSkipNoWaitExample,
    FiveStationCircleCwFullNoSkipNoWaitExample,
    FiveStationCircleCwFullSkipNoWaitExample,
    FiveStationCircleCwHalfNoSkipNoWaitExample,
    FiveStationCircleCwHalfSkipNoWaitExample,
    FiveStationCircleCwHalfSkipWaitExample,
)
from ropeway_skip_stop_optimization.examples.linear_skip_stop import (
    FiveStationExample,
    FiveStationHalfNoSkipNoWaitExample,
    FiveStationNoWaitExample,
)
from ropeway_skip_stop_optimization.examples.three_station import (
    ThreeStationOptimizedInitialPlacementExample,
    ThreeStationExample,
    ThreeStationFullNoSkipNoWaitExample,
    ThreeStationHalfNoSkipNoWaitExample,
)
from ropeway_skip_stop_optimization.examples.thesis_cases import thesis_ring_examples


EXAMPLES: dict[str, ScenarioExample] = {
    ThreeStationExample.metadata.id: ThreeStationExample(),
    ThreeStationFullNoSkipNoWaitExample.metadata.id: ThreeStationFullNoSkipNoWaitExample(),
    ThreeStationHalfNoSkipNoWaitExample.metadata.id: ThreeStationHalfNoSkipNoWaitExample(),
    ThreeStationOptimizedInitialPlacementExample.metadata.id: ThreeStationOptimizedInitialPlacementExample(),
    FiveStationExample.metadata.id: FiveStationExample(),
    FiveStationNoWaitExample.metadata.id: FiveStationNoWaitExample(),
    FiveStationHalfNoSkipNoWaitExample.metadata.id: FiveStationHalfNoSkipNoWaitExample(),
    FiveStationCircleCwFullNoSkipNoWaitExample.metadata.id: FiveStationCircleCwFullNoSkipNoWaitExample(),
    FiveStationCircleCwFullSkipNoWaitExample.metadata.id: FiveStationCircleCwFullSkipNoWaitExample(),
    FiveStationCircleCwFullSkipNoWaitHeadwayBExample.metadata.id: FiveStationCircleCwFullSkipNoWaitHeadwayBExample(),
    FiveStationCircleCwFullSkipWaitHeadwayBExample.metadata.id: FiveStationCircleCwFullSkipWaitHeadwayBExample(),
    FiveStationCircleCwHalfSkipNoWaitHeadwayBExample.metadata.id: FiveStationCircleCwHalfSkipNoWaitHeadwayBExample(),
    FiveStationCircleCwHalfNoSkipNoWaitExample.metadata.id: FiveStationCircleCwHalfNoSkipNoWaitExample(),
    FiveStationCircleCwHalfSkipNoWaitExample.metadata.id: FiveStationCircleCwHalfSkipNoWaitExample(),
    FiveStationCircleCwHalfSkipWaitExample.metadata.id: FiveStationCircleCwHalfSkipWaitExample(),
    FiveStationOptimizedInitialPlacementSkipNoWaitExample.metadata.id: FiveStationOptimizedInitialPlacementSkipNoWaitExample(),
    FiveStationOptimizedInitialPlacementNoSkipNoWaitExample.metadata.id: FiveStationOptimizedInitialPlacementNoSkipNoWaitExample(),
    FiveStationOptimizedInitialPlacementDoubleAllStopSkipWaitExample.metadata.id: FiveStationOptimizedInitialPlacementDoubleAllStopSkipWaitExample(),
    FiveStationOptimizedInitialPlacementAllStopSkipWaitExample.metadata.id: FiveStationOptimizedInitialPlacementAllStopSkipWaitExample(),
    **{
        example.metadata.id: example
        for example in artificial_physical_headway_examples()
    },
    **{example.metadata.id: example for example in thesis_ring_examples()},
}


def get_example(example_id: str) -> ScenarioExample:
    try:
        return EXAMPLES[example_id]
    except KeyError as exc:
        known = ", ".join(sorted(EXAMPLES))
        raise ValueError(f"Unknown example id {example_id!r}. Known examples: {known}") from exc
