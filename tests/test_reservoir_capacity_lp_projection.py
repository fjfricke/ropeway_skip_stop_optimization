"""LP effects on identical networks, not inferred from zero capacity optima."""

from dataclasses import replace
import random

import gurobipy as gp
import pytest
from test_reservoir_capacity_phases import physical_small, full_calendar
from ropeway_skip_stop_optimization.optimization.ean.models import EanDemandGroup
from ropeway_skip_stop_optimization.optimization.ddd.reservoir_capacity.formulation import (
    ReservoirPhaseFormulationConfig as Config,
)
from ropeway_skip_stop_optimization.optimization.ddd.reservoir_capacity.model import (
    build_model,
)


def lp_value(net, config, weights):
    b = build_model(net, formulation=config)
    try:
        b.model.setObjective(
            b.passengers.objective
            + gp.quicksum(weights.get(aid, 0) * v for aid, v in b.x.items())
        )
        b.model.update()
        lp = b.model.relax()
        try:
            lp.Params.Threads = 1
            lp.Params.TimeLimit = 10
            lp.optimize()
            assert lp.Status == 2
            return lp.ObjVal
        finally:
            lp.dispose()
    finally:
        b.model.dispose()


@pytest.mark.parametrize("encoding", ("legacy", "od_flow", "od_queue"))
def test_substitution_integrality_and_resources_preserve_lp(encoding):
    p = physical_small()
    p = replace(
        p,
        demand_groups=(
            EanDemandGroup("a", "A", "B", 0, 3),
            EanDemandGroup("b", "A", "B", 1.5, 2),
        ),
    )
    net = full_calendar(p)
    rng = random.Random(7)
    cfg = Config(passenger_encoding=encoding)
    for _ in range(3):
        weights = {a.id: rng.randrange(-3, 4) for a in net.arcs}
        baseline = lp_value(net, cfg, weights)
        for changed in (
            replace(cfg, passenger_integrality="boarding"),
            replace(cfg, passenger_network="contracted"),
            replace(cfg, resource_encoding="maximal"),
        ):
            assert lp_value(net, changed, weights) == pytest.approx(baseline, abs=1e-6)
        assert (
            lp_value(net, replace(cfg, conflict_cuts="local_cliques"), weights)
            >= baseline - 1e-6
        )


def test_od_aggregation_does_not_exclude_legacy_lp_projection():
    p = replace(
        physical_small(waiting=True),
        demand_groups=(
            EanDemandGroup("early", "A", "B", 0, 3),
            EanDemandGroup("late", "A", "B", 1.5, 2),
        ),
    )
    net = full_calendar(p)
    rng = random.Random(17)
    for _ in range(3):
        weights = {a.id: rng.randrange(-4, 5) for a in net.arcs}
        values = {
            encoding: lp_value(net, Config(passenger_encoding=encoding), weights)
            for encoding in ("legacy", "od_flow", "od_queue")
        }
        # Summing each old class flow produces a feasible aggregate point.
        # No equality of polyhedra is inferred from these few objective probes.
        assert values["od_flow"] <= values["legacy"] + 1e-6
        assert values["od_queue"] <= values["od_flow"] + 1e-6
