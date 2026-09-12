from dataclasses import replace
from random import Random

import pytest

from test_ddd_capacity_experiment import fixture
from test_optimization_ddd_cp_sat_integrated import tiny_problem
from ropeway_skip_stop_optimization.optimization.ddd.pattern_search import (
    PatternTimingOracle,
    PatternNeighborhoods,
    PatternVnsOptimizer,
    PatternVnsConfig,
    unserved,
)
from ropeway_skip_stop_optimization.optimization.ddd.cp_sat_certificate import (
    validate_ddd_cp_sat_incumbent,
)
from ropeway_skip_stop_optimization.optimization.ddd.fixed_timetable_capacity import (
    FixedTimetableCapacityProbe,
)
from ropeway_skip_stop_optimization.optimization.ddd.reference import (
    DddReferenceTrajectoryGenerator,
    DddReferenceSolution,
)
from ropeway_skip_stop_optimization.optimization.ean.models import EanDemandGroup


def test_each_fixed_pattern_matches_exhaustive_no_wait_movements():
    p, _ = fixture()
    oracle = PatternTimingOracle(p, workers=1)
    generated = DddReferenceTrajectoryGenerator().generate(
        p.resolved_trajectory_problem.structural_movement_problem
    )
    for t in generated.by_cabin_id[0]:
        s = DddReferenceSolution((t,))
        pattern = oracle.pattern_from(s)
        expected = FixedTimetableCapacityProbe(5).solve(p, s)
        result = oracle.evaluate(pattern, budget=5)
        assert result.status == "OPTIMAL"
        assert unserved(result.incumbent) == expected["unserved_upper_bound"]
        assert pattern.matches(result.incumbent.solution)
        assert result.record()["proof_scope"] == "FIXED_PATTERN"
        assert oracle.evaluate(pattern, budget=5) is result


def test_worse_pattern_does_not_inherit_seed_cutoff_or_incumbent():
    p, s = fixture()
    oracle = PatternTimingOracle(p, workers=1)
    good = oracle.evaluate(oracle.pattern_from(s), budget=5).incumbent
    assert unserved(good) == 0
    pattern = oracle.pattern_from(s)
    changed = replace(
        pattern,
        choices=tuple(
            (c, v, oracle.options[c, v]["skip"]) for c, v, _ in pattern.choices
        ),
    )
    result = oracle.evaluate(changed, budget=5, hint=good)
    assert result.status == "OPTIMAL"
    assert unserved(result.incumbent) == 2
    assert changed.matches(result.incumbent.solution)


def test_unknown_is_retryable_and_not_infeasible():
    p, s = fixture()
    oracle = PatternTimingOracle(p, workers=1)
    pattern = oracle.pattern_from(s)
    result = oracle.evaluate(pattern, budget=1e-9)
    assert result.status == "UNKNOWN" and result.incumbent is None
    assert result.lower_bound is None
    result = oracle.evaluate(pattern, budget=5)
    assert result.calls == 2 and result.status == "OPTIMAL"


def test_pattern_validates_complete_domain():
    p, s = fixture()
    oracle = PatternTimingOracle(p, workers=1)
    pattern = oracle.pattern_from(s)
    for bad in (
        replace(pattern, domain_id="other"),
        replace(pattern, choices=pattern.choices[:-1]),
        replace(pattern, choices=pattern.choices + pattern.choices[:1]),
    ):
        with pytest.raises(ValueError):
            oracle.evaluate(bad)


def test_waits_remain_free_for_late_release():
    _, p = tiny_problem(
        horizon=100, maximum_wait=20, groups=(EanDemandGroup("ab", "A", "B", 30, 2),)
    )
    oracle = PatternTimingOracle(p, workers=1)
    # A no-wait all-stop seed cannot board this demand, but its pattern can.
    movements = DddReferenceTrajectoryGenerator().generate(
        p.resolved_trajectory_problem.structural_movement_problem
    )
    t = next(
        t
        for t in movements.by_cabin_id[0]
        if all(v.decision.value == "stop" for v in t.visits)
    )
    seed = validate_ddd_cp_sat_incumbent(
        p, DddReferenceSolution((t,)), {}, provenance="test"
    )
    assert (
        FixedTimetableCapacityProbe(5).solve(p, seed.solution)["unserved_upper_bound"]
        == 2
    )
    pattern = oracle.pattern_from(seed.solution)
    result = oracle.evaluate(pattern, budget=5, hint=seed)
    assert unserved(result.incumbent) == 0
    assert result.incumbent.solution != seed.solution


def test_zero_incumbent_is_only_global_optimality_claim():
    p, s = fixture()
    seed = validate_ddd_cp_sat_incumbent(p, s, {}, provenance="test")
    result = PatternVnsOptimizer(
        PatternVnsConfig(total_seconds=10, reserve_seconds=1, workers=1)
    ).solve(p, primal_seed=seed)
    assert result["proven_optimal"] and result["unserved_upper_bound"] == 0
    assert result["unserved_lower_bound"] == 0


def test_neighborhoods_are_repeatable_and_only_change_routes():
    p, s = fixture()
    oracle = PatternTimingOracle(p, workers=1)
    seed = validate_ddd_cp_sat_incumbent(p, s, {}, provenance="test")
    pattern = oracle.pattern_from(s)
    a, b = (
        PatternNeighborhoods(oracle, Random(42)),
        PatternNeighborhoods(oracle, Random(42)),
    )
    for n in (1, 2, 3):
        for _ in range(10):
            x, y = a.propose(pattern, seed, n, 2), b.propose(pattern, seed, n, 2)
            assert x == y
            if x:
                oracle.validate_pattern(x)
                assert x != pattern


def test_pattern_local_positive_bound_never_becomes_global_bound(monkeypatch):
    from ropeway_skip_stop_optimization.optimization.ddd.fixed_timetable_capacity import (
        NestedDemand,
    )

    p, s = fixture()
    p = NestedDemand(p.passenger_build.demand_groups).apply(p, 3)
    seed = validate_ddd_cp_sat_incumbent(p, s, {}, provenance="test")
    monkeypatch.setattr(PatternNeighborhoods, "propose", lambda *args: None)
    result = PatternVnsOptimizer(
        PatternVnsConfig(total_seconds=10, reserve_seconds=1, workers=1)
    ).solve(p, primal_seed=seed)
    assert result["unserved_upper_bound"] == 1
    assert result["evaluations"][0]["pattern_lower_bound"] == 1
    assert result["unserved_lower_bound"] == 0 and not result["proven_optimal"]
    assert result["status"] == "SEARCH_STALLED"
    assert (
        len([e for e in result["events"] if e["kind"] == "neighborhood_exhausted"]) == 2
    )


def test_unknown_retry_and_neighborhood_progression_with_fake_oracle(monkeypatch):
    from itertools import product
    from ropeway_skip_stop_optimization.optimization.ddd.pattern_search import (
        PatternEvaluation,
    )

    _, p = tiny_problem(horizon=130)
    oracle = PatternTimingOracle(p, workers=1)
    generated = DddReferenceTrajectoryGenerator().generate(
        p.resolved_trajectory_problem.structural_movement_problem
    )
    t = next(
        t
        for t in generated.by_cabin_id[0]
        if all(v.decision.value == "stop" for v in t.visits)
    )
    seed = validate_ddd_cp_sat_incumbent(
        p, DddReferenceSolution((t,)), {}, provenance="test"
    )
    base = oracle.pattern_from(seed.solution)
    patterns = [
        replace(
            base,
            choices=tuple(
                (c, v, o) for (c, v), o in zip(sorted(oracle.options), choices)
            ),
        )
        for choices in product(
            *(tuple(opts.values()) for _, opts in sorted(oracle.options.items()))
        )
    ]
    patterns = iter([x for x in patterns if x != base][:12])
    seen = []
    monkeypatch.setattr(
        PatternNeighborhoods,
        "propose",
        lambda self, p, i, n, w: (seen.append(n), next(patterns, None))[1],
    )

    class FakeOracle(PatternTimingOracle):
        def evaluate(self, pattern, *, budget, hint=None):
            old = self.cache.get(pattern.id)
            result = PatternEvaluation(
                pattern,
                "UNKNOWN",
                hint if pattern == base else None,
                calls=1 + (old.calls if old else 0),
            )
            self.cache[pattern.id] = result
            return result

    result = PatternVnsOptimizer(
        PatternVnsConfig(total_seconds=10, reserve_seconds=1, workers=1)
    ).solve(p, primal_seed=seed, oracle_factory=FakeOracle)
    assert {1, 2, 3}.issubset(seen)
    assert any(e.get("evaluation_kind") == "retry" for e in result["events"])
    assert max(e["calls"] for e in result["evaluations"]) == 2
    assert result["changed_valid_patterns"] == 0
    assert result["unserved_upper_bound"] == unserved(seed)


def test_fixed_pattern_allows_different_active_suffixes():
    from ortools.sat.python import cp_model

    _, p = tiny_problem(
        horizon=65, maximum_wait=20, groups=(EanDemandGroup("ab", "A", "B", 0, 2),)
    )
    oracle = PatternTimingOracle(p, workers=1)
    # Both forcing a short prefix and forcing a longer prefix remain feasible.
    # This directly tests conditional route == active, without time fixings.
    movement = oracle.built.movement
    counts = set()
    for maximize in (False, True):
        m = movement.model.clone()
        for (c, v), opts in oracle.options.items():
            m.add(
                m.get_int_var_from_proto_index(
                    movement.selection_by_key[c, v, opts["stop"]].index
                )
                == m.get_int_var_from_proto_index(movement.active_by_cabin[c][v].index)
            )
        active = [
            m.get_int_var_from_proto_index(x.index)
            for seq in movement.active_by_cabin.values()
            for x in seq
        ]
        if maximize:
            m.maximize(sum(active))
        else:
            m.minimize(sum(active))
        solver = cp_model.CpSolver()
        solver.parameters.num_search_workers = 1
        assert solver.solve(m) == cp_model.OPTIMAL
        counts.add(sum(solver.value(x) for x in active))
    assert len(counts) == 2


def test_independent_ean_postcheck_agrees_with_pattern_oracle():
    from ropeway_skip_stop_optimization.benchmarking.pattern_search import (
        independent_assignment,
    )

    scenario, p = tiny_problem(
        horizon=65, groups=(EanDemandGroup("ab", "A", "B", 0, 3),)
    )
    oracle = PatternTimingOracle(p, workers=1)
    t = next(
        t
        for t in DddReferenceTrajectoryGenerator()
        .generate(p.resolved_trajectory_problem.structural_movement_problem)
        .by_cabin_id[0]
        if all(v.decision.value == "stop" for v in t.visits)
    )
    result = oracle.evaluate(oracle.pattern_from(DddReferenceSolution((t,))), budget=5)
    post = independent_assignment(p, scenario, result.incumbent.solution)
    assert (
        post["proven_optimal"]
        and post["unserved_upper_bound"] == unserved(result.incumbent) == 1
    )


def test_screening_gate_counts_distinct_changed_patterns():
    from ropeway_skip_stop_optimization.benchmarking.pattern_search import (
        screening_gate,
    )

    a = dict(distinct_patterns=6, changed_valid_patterns=1)
    assert screening_gate([a, a])["passed"]
    assert not screening_gate([a])["passed"]
    assert not screening_gate([dict(a, changed_valid_patterns=0)] * 2)["passed"]


def test_campaign_freeze_executes_immutable_hashed_sources(tmp_path, monkeypatch):
    import importlib.util
    import hashlib
    import json
    from pathlib import Path

    spec = importlib.util.spec_from_file_location(
        "pattern_cli",
        Path(__file__).resolve().parents[1] / "benchmarks/run_pattern_search.py",
    )
    cli = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(cli)
    root = tmp_path / "repo"
    (root / "src").mkdir(parents=True)
    for name in ("src/model.py", "pyproject.toml", "uv.lock"):
        (root / name).write_text("original")
    monkeypatch.setattr(cli, "ROOT", root)
    monkeypatch.setattr(cli.subprocess, "check_output", lambda *a, **k: "test-head")
    output = tmp_path / "run"
    output.mkdir()
    runtime = cli.freeze(output)
    (root / "src/model.py").write_text("concurrent change")
    assert (runtime / "src/model.py").read_text() == "original"
    manifest = json.loads((output / "source_manifest.json").read_text())
    assert manifest["files"]["src/model.py"] == hashlib.sha256(b"original").hexdigest()


def test_paired_verdict_rejects_trivial_seed_speedup_and_needs_two_seeds():
    from ropeway_skip_stop_optimization.benchmarking.pattern_search_report import (
        paired_verdict,
    )

    rows = [
        dict(
            stage="campaign",
            cabins=k,
            seed=seed,
            method=method,
            domain="same",
            initial_unserved=10,
            final_unserved=10,
            curve=[(0, 10)],
        )
        for k in (38, 39)
        for seed in (0, 1)
        for method in ("vns", "cp_sat")
    ]
    assert paired_verdict(rows)["status"] == "NOT_DEMONSTRATED"
    rows[0].update(final_unserved=8, curve=[(0, 10), (2, 8)])
    assert paired_verdict(rows)["status"] == "NOT_DEMONSTRATED"
    rows[2].update(final_unserved=9, curve=[(0, 10), (2, 9)])
    assert paired_verdict(rows)["status"] == "PROMISING"
    assert paired_verdict(rows[:4])["status"] == "PENDING"
    rows[1]["domain"] = "different"
    with pytest.raises(ValueError):
        paired_verdict(rows)


def test_curve_keeps_incumbent_monotone_and_uses_full_run_clock():
    from ropeway_skip_stop_optimization.benchmarking.pattern_search_report import (
        incumbent_curve,
    )

    r = dict(seed_unserved=10, unserved_upper_bound=6, search_wall_seconds=20)
    events = [
        dict(kind="incumbent", unserved=u, elapsed_seconds=t, run_elapsed_seconds=t + 1)
        for t, u in [(2, 8), (3, 9), (5, 7)]
    ]
    assert incumbent_curve(r, events) == [(0.0, 10), (3, 8), (6, 7), (20, 6)]
