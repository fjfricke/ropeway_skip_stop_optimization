"""Small solver-free tests; safe while the sequential benchmark is running."""

from dataclasses import replace
from itertools import product
from types import SimpleNamespace as NS

import pytest

from ropeway_skip_stop_optimization.optimization.ean.models import EanDemandGroup
from ropeway_skip_stop_optimization.optimization.ddd.reservoir_capacity.formulation import (
    ReservoirPhaseFormulationConfig as Config,
)
from ropeway_skip_stop_optimization.optimization.ddd.reservoir_capacity.network import (
    PhaseArc,
)
from ropeway_skip_stop_optimization.optimization.ddd.reservoir_capacity.passenger_structure import (
    prepare_passengers,
    PassengerGroup,
)
from ropeway_skip_stop_optimization.optimization.ddd.reservoir_capacity.passenger_certificate import (
    assign_released,
)
from ropeway_skip_stop_optimization.optimization.ddd.reservoir_capacity.resource_structure import (
    prepare_resources,
    dominates,
)


def tiny_network():
    options = tuple(NS(id=s, station_id=s, from_state_id=s) for s in ("A", "B", "C"))
    arcs = []
    for shift in (0, 10):
        seq = [
            ("A", "ready", 0),
            ("B", "entry", 1),
            ("B", "platform", 2),
            ("B", "ready", 3),
            ("C", "entry", 4),
            ("C", "platform", 5),
        ]
        for i, kind in enumerate(("exit", "arrive", "ready", "exit", "arrive")):
            u, v = seq[i], seq[i + 1]
            arcs.append(
                PhaseArc(
                    len(arcs),
                    (u[0], u[1], u[2] + shift),
                    (v[0], v[1], v[2] + shift),
                    kind,
                    u[0],
                )
            )
    groups = (
        EanDemandGroup("early", "A", "C", 0, 2),
        EanDemandGroup("late", "A", "C", 0.000009, 1),
    )
    p = NS(
        cycle_states=("A", "B", "C"),
        cabin_capacity=2,
        demand_groups=groups,
        resolved_core=NS(route_options=options, passenger_service_end_tick=20),
    )
    return NS(arcs=tuple(arcs), problem=p)


def test_group_support_and_aggregation():
    n = tiny_network()
    legacy = prepare_passengers(n, Config())
    shared = prepare_passengers(n, Config(passenger_encoding="od_flow"))
    assert len(legacy.variables) == 15
    assert len(shared.variables) == 11
    assert len({g.class_id for g in shared.groups}) == 1
    assert shared.groups[1].boarding == (5,)
    assert legacy.fingerprint != shared.fingerprint
    assert (
        shared.fingerprint
        == prepare_passengers(n, Config(passenger_encoding="od_flow")).fingerprint
    )


def test_chain_projection_retains_boundary_and_capacity():
    n = tiny_network()
    st = prepare_passengers(
        n, Config(passenger_encoding="od_flow", passenger_network="contracted")
    )
    assert st.removed_equalities > 0
    proj = dict(st.projection)
    assert proj["g", "early", 0] == ("g", "early", 0)
    assert len(st.loads) == 10
    for g in st.groups:
        assert all(
            proj["od", g.class_id, a] == ("od", g.class_id, a) for a in g.alighting
        )


def test_queue_algebra_on_known_boardings():
    st = prepare_passengers(tiny_network(), Config(passenger_encoding="od_queue"))
    values = {v.key: 0 for v in st.variables}
    for key, prev, released, boarding in st.queue_steps:
        if boarding:
            values[boarding[0]] = 1
        values[key] = (
            (values[prev] if prev else 0) + released - sum(values[b] for b in boarding)
        )
    assert all(values[k] >= 0 for k in values)
    assert values[st.queue_steps[-1][0]] == 1
    for row in st.rows:
        if row.family == "demand_queue":
            assert sum(c * values[k] for k, c in row.terms) == row.rhs


def test_different_destinations_not_aggregated():
    n = tiny_network()
    n.problem.demand_groups += (EanDemandGroup("other", "A", "B", 0, 1),)
    st = prepare_passengers(n, Config(passenger_encoding="od_queue"))
    assert len({g.class_id for g in st.groups}) == 2


def test_future_group_contract_is_rejected():
    class Extended(EanDemandGroup):
        pass

    n = tiny_network()
    n.problem.demand_groups = (Extended("x", "A", "C", 0, 1),)
    with pytest.raises(ValueError, match="group contract"):
        prepare_passengers(n, Config(passenger_encoding="od_queue"))


def test_queue_lift_all_small_prefixes():
    groups = (
        PassengerGroup("g0", "c", 2, 0, "A", "B", (), (), ()),
        PassengerGroup("g1", "c", 1, 2, "A", "B", (), (), ()),
    )
    for counts in product(range(4), repeat=4):
        feasible = all(sum(counts[: t + 1]) <= (2 if t < 2 else 3) for t in range(4))
        events = [(t, 0, t, n) for t, n in enumerate(counts)]
        if feasible:
            lifted = assign_released(groups, events)
            assert sum(lifted.values()) == sum(counts)
            assert sum(v for (*_, g), v in lifted.items() if g == "g0") <= 2
        else:
            with pytest.raises(ValueError, match="released"):
                assign_released(groups, events)


def test_same_tick_shared_demand_and_negative():
    groups = (PassengerGroup("g", "c", 1, 2, "A", "B", (), (), ()),)
    assert sum(assign_released(groups, [(2, 0, 1, 1)]).values()) == 1
    for events in ([(1, 0, 1, 1)], [(2, 0, 1, 1), (2, 1, 2, 1)], [(2, 0, 1, -1)]):
        with pytest.raises(ValueError):
            assign_released(groups, events)


def resource_arcs():
    return tuple(
        PhaseArc(i, None, None, "test", None, resources)
        for i, resources in enumerate(
            (
                (("r1", 0, 2), ("r3", 0, 2)),
                (("r1", 0, 2), ("r2", 0, 2)),
                (("r2", 0, 2), ("r3", 0, 2)),
            )
        )
    )


def test_cross_resource_triangle_proof():
    st = prepare_resources(resource_arcs(), Config(conflict_cuts="local_cliques"))
    assert st.cliques[0][0] == (0, 1, 2)
    assert all(sum(0.5 * c for _, c in r.terms) <= 1 for r in st.rows)
    assert sum([0.5] * 3) > 1
    for i, j in product(range(2), repeat=2):
        for k in range(2):
            v = (i, j, k)
            feasible = all(sum(v[a] * c for a, c in r.terms) <= 1 for r in st.rows)
            if feasible:
                assert sum(v) <= 1


def test_half_open_and_duplicate_resource_coefficients():
    arcs = (
        PhaseArc(0, None, None, "x", None, (("r", 0, 2), ("r", 1, 2))),
        PhaseArc(1, None, None, "x", None, (("r", 2, 3),)),
    )
    st = prepare_resources(arcs, Config(resource_encoding="maximal"))
    assert any(r.terms == ((0, 2),) for r in st.rows)
    assert not st.cliques
    assert not dominates(((0, 1),), ((0, 2),))


def test_resource_dominance_and_bounded_optional_cuts():
    arcs = resource_arcs()
    st = prepare_resources(
        arcs,
        Config(
            resource_encoding="maximal",
            conflict_cuts="local_cliques",
            conflict_work_limit=0,
        ),
    )
    assert not st.cliques and st.truncated
    assert len(st.retained) == 3
    for old, new in st.implied_by:
        assert new in st.retained
        assert dominates(st.rows[new].terms, st.rows[old].terms)


def test_config_validation():
    Config().validate("cp_sat")
    with pytest.raises(ValueError):
        Config(passenger_encoding="od_queue").validate("cp_sat")
    with pytest.raises(ValueError):
        Config(passenger_integrality="relax_everything").validate()
    with pytest.raises(ValueError):
        replace(Config(), conflict_work_limit=-1).validate()


def test_resource_reduction_random_small_coefficients():
    import random

    rng = random.Random(27)
    for _ in range(25):
        arcs = []
        for aid in range(4):
            uses = []
            for rid in ("r", "s"):
                for _ in range(rng.randrange(3)):
                    start = rng.randrange(4)
                    uses.append((rid, start, start + rng.randrange(1, 4)))
            arcs.append(PhaseArc(aid, None, None, "test", None, tuple(uses)))
        st = prepare_resources(arcs, Config(resource_encoding="maximal"))
        for values in product((0, 0.25, 0.5, 0.75, 1), repeat=4):
            full = all(sum(c * values[a] for a, c in r.terms) <= 1 for r in st.rows)
            reduced = all(
                sum(c * values[a] for a, c in st.rows[i].terms) <= 1
                for i in st.retained
            )
            assert full == reduced


@pytest.mark.parametrize("encoding", ("legacy", "od_flow", "od_queue"))
@pytest.mark.parametrize("contraction", ("legacy", "contracted"))
def test_projected_integer_flow_satisfies_prepared_algebra(encoding, contraction):
    from collections import Counter
    from ropeway_skip_stop_optimization.optimization.ddd.reservoir_capacity.passenger_structure import (
        group_flow_key,
    )

    st = prepare_passengers(
        tiny_network(),
        Config(passenger_encoding=encoding, passenger_network=contraction),
    )
    projection = dict(st.projection)
    raw = dict.fromkeys(projection, 0)
    # Two early persons on the first path, one late person on the second.
    for g in st.groups:
        selected = range(5) if g.id == "early" else range(5, 10)
        n = 2 if g.id == "early" else 1
        for aid in selected:
            raw[group_flow_key(g, aid, encoding)] += n
    for key, previous, released, boarding in st.queue_steps:
        raw[key] = (
            (raw[previous] if previous else 0)
            + released
            - sum(raw[k] for k in boarding)
        )
    values = {}
    for key, rep in projection.items():
        if rep in values:
            assert values[rep] == raw[key]
        values[rep] = raw[key]
    for v in st.variables:
        assert 0 <= values[v.key] <= v.upper
    for row in st.rows:
        lhs = sum(c * values[k] for k, c in row.terms)
        assert lhs == row.rhs if row.sense == "=" else lhs <= row.rhs
    for _, terms in st.loads:
        assert sum(c * values[k] for k, c in terms) <= 2
    assert sum(values[k] for k in st.alighting) == 3
    assert all(v == 1 for v in Counter(st.alighting).values())
