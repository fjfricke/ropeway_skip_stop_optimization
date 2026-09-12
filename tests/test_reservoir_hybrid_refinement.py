from time import perf_counter

from test_reservoir_hybrid import small, enumerate_plans
from ropeway_skip_stop_optimization.optimization.ddd.reservoir_hybrid.arrival_curves import (
    ArrivalIntervalPartition,
)
from ropeway_skip_stop_optimization.optimization.ddd.reservoir_hybrid.bound_domain import (
    prepare_bound,
)
from ropeway_skip_stop_optimization.optimization.ddd.reservoir_hybrid.bound_model import (
    ReservoirArrivalBoundBuilder,
    ReservoirArrivalBoundOptimizer,
)
from ropeway_skip_stop_optimization.optimization.ddd.reservoir_hybrid.refinement import (
    refinement_projection,
    ReservoirBoundRefiner,
)


def test_child_arcs_project_and_all_original_plans_survive():
    p = small()
    coarse = ArrivalIntervalPartition.build(p, 3_000_000)
    parent = prepare_bound(p, coarse)
    child = prepare_bound(p, coarse.refine([1_000_000, 2_000_000]))
    assert len(refinement_projection(parent, child)) == len(child.arcs)
    bounds = []
    for prepared in (parent, child):
        built = ReservoirArrivalBoundBuilder().build(
            prepared, "movement_capacity", journey_encoding="time_moments"
        )
        try:
            for plan in enumerate_plans(p):
                built.project(plan)
            bound, _ = ReservoirArrivalBoundOptimizer().solve(
                built, deadline=perf_counter() + 5, threads=1
            )
            bounds.append(bound.value)
        finally:
            built.model.dispose()
    assert bounds[1] >= bounds[0] - 1e-6


def test_refiner_bounded_round_count_and_never_claims_primal_search():
    p = small()
    plan = next(s for s in enumerate_plans(p) if s.ride_counts)
    result = ReservoirBoundRefiner().solve(
        p, plan, time_limit=5, max_rounds=2, workers=1
    )
    assert len(result["rounds"]) <= 2
    assert result["certified_lower_bound"] <= result["validated_upper_bound"] + 1e-6
