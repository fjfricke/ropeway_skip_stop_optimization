from __future__ import annotations

from dataclasses import dataclass
from itertools import combinations

from ..models import DddRouteDecision, DddRouteOption
from ..reservoir_cp_sat_problem import DddReservoirCpSatProblem
from ..route_topology import unique_stop_route_option
from .config import ReservoirLineCatalogProfile


@dataclass(frozen=True)
class LinePattern:
    id: str
    stop_station_ids: frozenset[str]


def line_patterns(
    problem: DddReservoirCpSatProblem,
    profile: ReservoirLineCatalogProfile,
) -> tuple[LinePattern, ...]:
    """Return deterministic stop masks; every mask serves at least one OD pair."""
    stations = tuple(
        unique_stop_route_option(
            problem.movement, state, error_context="reservoir lines"
        ).station_id
        for state in problem.cycle_states
    )
    all_stops = frozenset(stations)
    if problem.operating_mode.value == "all_stop":
        return (LinePattern("all_stop", all_stops),)

    demanded_pairs = {
        frozenset((g.origin_station_id, g.destination_station_id))
        for g in problem.demand_groups
        if g.count and g.origin_station_id != g.destination_station_id
    }
    masks: set[frozenset[str]] = {all_stops}
    if profile in (
        ReservoirLineCatalogProfile.SMALL,
        ReservoirLineCatalogProfile.OD_ENDPOINTS_V1,
    ):
        masks.update(demanded_pairs)
    else:
        # Single-station masks cannot carry a direct OD passenger. Retain every
        # larger mask that covers at least one demanded pair.
        for size in range(2, len(stations) + 1):
            for values in combinations(stations, size):
                mask = frozenset(values)
                if any(pair <= mask for pair in demanded_pairs):
                    masks.add(mask)

    def key(mask: frozenset[str]):
        return (-len(mask), tuple(station for station in stations if station in mask))

    result = []
    for mask in sorted(masks, key=key):
        ident = "all_stop" if mask == all_stops else "stop_" + "_".join(
            station for station in stations if station in mask
        )
        result.append(LinePattern(ident, mask))
    return tuple(result)


def option_for_pattern(
    problem: DddReservoirCpSatProblem,
    state_id: str,
    pattern: LinePattern,
) -> DddRouteOption:
    options = problem.resolved_core.route_options_by_state_id[state_id]
    station = options[0].station_id
    decision = (
        DddRouteDecision.STOP
        if station in pattern.stop_station_ids
        else DddRouteDecision.SKIP
    )
    matching = tuple(o for o in options if o.decision is decision)
    if len(matching) != 1:
        raise ValueError(
            f"line pattern requires one {decision.value} option at state {state_id!r}"
        )
    return matching[0]
