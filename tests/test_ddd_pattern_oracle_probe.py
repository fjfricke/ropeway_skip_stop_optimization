from dataclasses import replace
import pytest
from test_ddd_capacity_experiment import fixture
from test_optimization_ddd_cp_sat_integrated import tiny_problem
from ropeway_skip_stop_optimization.optimization.ddd.pattern_search import (
    PatternTimingOracle,
)
from ropeway_skip_stop_optimization.optimization.ddd.pattern_oracle_probe import (
    FixedPatternCpSatProbe,
    PatternProbeConfig,
)
from ropeway_skip_stop_optimization.optimization.ddd.pattern_mip import (
    FixedPatternMipProbe,
)
from ropeway_skip_stop_optimization.optimization.ddd.reference import (
    DddReferenceTrajectoryGenerator,
    DddReferenceSolution,
)
from ropeway_skip_stop_optimization.optimization.ean.models import EanDemandGroup


def compare(p, pattern, seed=None):
    c = PatternProbeConfig(seconds=10, workers=1)
    cp = FixedPatternCpSatProbe(c).solve(p, pattern, seed=seed)
    mip = FixedPatternMipProbe(c).solve(p, pattern, seed=seed)
    assert cp["pattern_upper_bound"] == mip["pattern_upper_bound"]
    assert cp["status"] == mip["status"] == "OPTIMAL"
    assert (
        cp["pattern_lower_bound"]
        == mip["pattern_lower_bound"]
        == cp["pattern_upper_bound"]
    )
    return cp, mip


def test_all_tiny_no_wait_patterns_match_between_backends():
    p, s = fixture()
    oracle = PatternTimingOracle(p, workers=1)
    for t in (
        DddReferenceTrajectoryGenerator()
        .generate(p.resolved_trajectory_problem.structural_movement_problem)
        .by_cabin_id[0]
    ):
        compare(p, oracle.pattern_from(DddReferenceSolution((t,))))


def test_matching_seed_full_cp_hints_and_worse_pattern_no_cutoff():
    p, s = fixture()
    oracle = PatternTimingOracle(p, workers=1)
    pattern = oracle.pattern_from(s)
    result = oracle.evaluate(pattern, budget=5)
    seed = result.incumbent
    cp, mip = compare(p, pattern, seed)
    assert cp["model_stats"]["hinted_variables"] == cp["model_stats"]["variables"]
    assert mip["model_stats"]["hinted_variables"] == mip["model_stats"]["variables"]
    bad = replace(
        pattern,
        choices=tuple(
            (c, v, oracle.options[c, v]["skip"]) for c, v, o in pattern.choices
        ),
    )
    cp, mip = compare(p, bad, seed)
    assert cp["pattern_upper_bound"] == 2
    assert not any(e["kind"] == "initial" for e in mip["events"])


@pytest.mark.parametrize("starts", [(0,), (0, 35)])
def test_waiting_release_capacity_and_headways(starts):
    _, p = tiny_problem(
        horizon=100,
        starts=starts,
        maximum_wait=20,
        groups=(EanDemandGroup("ab", "A", "B", 30, 3),),
    )
    oracle = PatternTimingOracle(p, workers=1)
    generated = DddReferenceTrajectoryGenerator().generate(
        p.resolved_trajectory_problem.structural_movement_problem
    )
    ts = tuple(
        next(
            t for t in trajectories if all(v.decision.value == "stop" for v in t.visits)
        )
        for trajectories in generated.by_cabin_id.values()
    )
    cp, mip = compare(p, oracle.pattern_from(DddReferenceSolution(ts)))
    assert cp["pattern_upper_bound"] == (1 if len(starts) == 1 else 0)


def test_conflicting_fixed_starts_infeasible_in_both_backends():
    _, p = tiny_problem(
        horizon=65, starts=(0, 0), groups=(EanDemandGroup("ab", "A", "B", 0, 2),)
    )
    oracle = PatternTimingOracle(p, workers=1)
    from ropeway_skip_stop_optimization.optimization.ddd.pattern_search import (
        StopPattern,
    )

    pattern = StopPattern(
        oracle.domain_id,
        tuple((c, v, opts["stop"]) for (c, v), opts in sorted(oracle.options.items())),
    )
    for backend in (FixedPatternCpSatProbe, FixedPatternMipProbe):
        r = backend(PatternProbeConfig(seconds=10, workers=1)).solve(p, pattern)
        assert r["status"] == "INFEASIBLE" and r["incumbent"] is None


def test_boundary_resource_block_is_not_dropped():
    from ropeway_skip_stop_optimization.optimization.ddd.reference import (
        DddReferenceResourceOccurrence,
    )
    from ropeway_skip_stop_optimization.optimization.ddd.fixed_k import (
        DddFixedKBoundaryContext,
    )

    p, s = fixture()
    occurrence = s.trajectories[0].visits[0].resource_occurrences[0]
    resource = occurrence.resource_id
    p = replace(
        p,
        boundary_context=DddFixedKBoundaryContext(
            resource_occurrences=(
                DddReferenceResourceOccurrence(
                    resource_id=resource,
                    cabin_id=0,
                    visit_index=0,
                    leader_clear_time_seconds=occurrence.follower_enter_time_seconds
                    + 5,
                    follower_enter_time_seconds=occurrence.follower_enter_time_seconds,
                    boundary_only=False,
                ),
            )
        ),
    )
    oracle = PatternTimingOracle(p, workers=1)
    pattern = oracle.pattern_from(s)
    for backend in (FixedPatternCpSatProbe, FixedPatternMipProbe):
        r = backend(PatternProbeConfig(seconds=10, workers=1)).solve(p, pattern)
        assert r["status"] == "INFEASIBLE"


def test_one_microsecond_wait_and_release_boundary_match():
    _, p = tiny_problem(
        horizon=65,
        maximum_wait=1e-6,
        waiting_step=1e-6,
        groups=(
            EanDemandGroup("reachable", "A", "B", 22.090910, 2),
            EanDemandGroup("too_late", "A", "B", 22.090911, 2),
        ),
    )
    oracle = PatternTimingOracle(p, workers=1)
    trajectories = (
        DddReferenceTrajectoryGenerator()
        .generate(p.resolved_trajectory_problem.structural_movement_problem)
        .by_cabin_id[0]
    )
    t = next(
        t for t in trajectories if all(v.decision.value == "stop" for v in t.visits)
    )
    cp, mip = compare(p, oracle.pattern_from(DddReferenceSolution((t,))))
    assert cp["pattern_upper_bound"] == 2
    assert cp["incumbent"]["unserved_counts"]["too_late"] == 2


def test_operational_tail_does_not_extend_passenger_service():
    _, p = tiny_problem(
        horizon=65,
        tail=60,
        maximum_wait=20,
        groups=(
            EanDemandGroup("after_service", "A", "B", 70, 2),
            EanDemandGroup("early", "A", "B", 0, 2),
        ),
    )
    oracle = PatternTimingOracle(p, workers=1)
    trajectories = (
        DddReferenceTrajectoryGenerator()
        .generate(p.resolved_trajectory_problem.structural_movement_problem)
        .by_cabin_id[0]
    )
    t = next(
        t for t in trajectories if all(v.decision.value == "stop" for v in t.visits)
    )
    cp, mip = compare(p, oracle.pattern_from(DddReferenceSolution((t,))))
    assert cp["pattern_upper_bound"] == 2


def test_time_only_hint_does_not_import_incumbent_cutoff_or_change_model():
    p, s = fixture()
    oracle = PatternTimingOracle(p, workers=1)
    original = oracle.pattern_from(s)
    seed = oracle.evaluate(original, budget=5).incumbent
    bad = replace(
        original,
        choices=tuple(
            (c, v, oracle.options[c, v]["skip"]) for c, v, o in original.choices
        ),
    )
    probe = FixedPatternCpSatProbe(PatternProbeConfig(seconds=10, workers=1))
    plain = probe.solve(p, bad)
    certificates = []
    hinted = probe.solve(p, bad, time_hint=seed, certificate_callback=certificates.append)
    assert certificates
    assert all(bad.matches(inc.solution) for inc in certificates)
    assert plain["pattern_upper_bound"] == hinted["pattern_upper_bound"] == 2
    assert plain["model_fingerprint"] == hinted["model_fingerprint"]
    assert hinted["model_stats"]["hint_scope"] == "TIMES_ONLY"
    assert not any(e["kind"] == "initial" for e in hinted["events"])
    with pytest.raises(ValueError):
        probe.solve(p, bad, seed=seed, time_hint=seed)
