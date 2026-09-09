"""Membership of the closed operational horizon, independent of feasibility tolerances."""

from __future__ import annotations

import math


FINITE_EVENT_ENTRY_CONTRACT = "closed_event_entry_horizon_v1"


def is_within_closed_horizon(event_time: float, horizon: float) -> bool:
    """Include H itself, but never extend H by the headway/timing tolerance.

    Four floating-point ULPs only absorb arithmetic roundoff (e.g. exit minus
    wait). They are not a physical time allowance or a solver feasibility
    tolerance. On the project's horizons this is far below one microsecond,
    so canonical DDD tick events have exactly their integer classification.
    Native continuous-time EAN events are not rounded to a tick grid.
    """
    if not math.isfinite(event_time) or not math.isfinite(horizon):
        raise ValueError("horizon membership requires finite event and horizon times")
    return event_time <= horizon or event_time - horizon <= 4 * math.ulp(horizon)
