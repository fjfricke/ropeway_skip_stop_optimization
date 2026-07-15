from __future__ import annotations

from typing import Any


def add_affine_stop_skip_timing_constraint(
    *,
    model: Any,
    switch_time: Any,
    exit_switch_time: Any,
    wait_time: Any,
    stop: Any,
    active: Any,
    service_seconds: float,
    skip_seconds: float,
    name: str,
) -> None:
    """Add the exact active-visit affine stop/skip timing relation."""
    affine_exit_time = (
        switch_time
        + skip_seconds
        + (service_seconds - skip_seconds) * stop
        + wait_time
    )
    if isinstance(active, int | float):
        if float(active) >= 0.5:
            model.addConstr(exit_switch_time == affine_exit_time, name=name)
        return
    model.addGenConstrIndicator(
        active,
        True,
        exit_switch_time == affine_exit_time,
        name=name,
    )
