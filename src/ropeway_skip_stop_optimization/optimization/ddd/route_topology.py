from __future__ import annotations

from ropeway_skip_stop_optimization.optimization.ddd.models import (
    DddMovementProblem,
    DddRouteDecision,
    DddRouteOption,
)


def deterministic_route_state_ids(
    movement_problem: DddMovementProblem,
    *,
    start_state_id: str,
    max_visit_count: int,
    error_context: str,
) -> tuple[str, ...]:
    """Follow a fixed sequence of target states through a route network."""
    states = [start_state_id]
    for _ in range(max_visit_count):
        options = movement_problem.route_options_by_state_id.get(states[-1], ())
        if not options:
            raise ValueError(f"{error_context} state has no route option")
        targets = {option.to_state_id for option in options}
        if len(targets) != 1:
            raise ValueError(f"{error_context} requires deterministic route targets")
        states.append(next(iter(targets)))
    return tuple(states)


def unique_stop_route_option(
    movement_problem: DddMovementProblem,
    state_id: str,
    *,
    error_context: str,
) -> DddRouteOption:
    """Return the sole STOP option at a state or reject ambiguous topology."""
    options = tuple(
        option
        for option in movement_problem.route_options_by_state_id[state_id]
        if option.decision is DddRouteDecision.STOP
    )
    if len(options) != 1:
        raise ValueError(f"{error_context} requires one STOP option per state")
    return options[0]
