"""Exact native-state and independent physical/capacity regression checks."""

from dataclasses import replace
from itertools import product
from pathlib import Path
import math
import pytest

from ropeway_skip_stop_optimization.benchmarking.ddd_fixed_k_didp import (
    prepare_small,
    prepare_large,
)
from ropeway_skip_stop_optimization.optimization.ddd.didp import prepare_didp_structure
from ropeway_skip_stop_optimization.optimization.ddd.didp.model import build_didp_model
from ropeway_skip_stop_optimization.optimization.ddd.didp.certificate import (
    extract_didp_incumbent,
    replay_didp_checkpoint,
    exact_tick,
)
from ropeway_skip_stop_optimization.optimization.ddd.didp.optimizer import (
    DddDidpConfig,
    DddDidpOptimizer,
)
from ropeway_skip_stop_optimization.optimization.ddd.cp_sat_certificate import (
    validate_ddd_cp_sat_incumbent,
    solution_from_cp_sat_payload,
    read_ddd_cp_sat_checkpoint,
    write_ddd_cp_sat_checkpoint,
)
from ropeway_skip_stop_optimization.optimization.ddd.cp_sat_capacity import (
    DddCpSatCapacityOptimizer,
)
from ropeway_skip_stop_optimization.optimization.ddd.cp_sat_integrated import (
    DddIntegratedCpSatConfig,
)
from ropeway_skip_stop_optimization.optimization.ddd.time_ticks import (
    ddd_seconds_to_tick as tick,
)
from ropeway_skip_stop_optimization.optimization.ean.models import EanDemandGroup


dp = pytest.importorskip("didppy")

def independent_plans(problem):
    """Brute force routes, integer waits and integer assignments; original validator only."""
    movement = problem.resolved_trajectory_problem.fixed_movement_problem
    policy = problem.resolved_trajectory_problem.waiting_policy
    choices = []
    for start in movement.starts:

        def recurse(state, t, routes, times, waits):
            if t > movement.operational_end_tick:
                yield dict(
                    cabin_id=start.cabin_id,
                    route_option_ids=routes,
                    switch_times_tick=times,
                    wait_ticks=waits,
                )
                return
            for route in movement.route_options_by_state_id[state]:
                stop = route.platform_exit_offset_seconds is not None
                maximum = (
                    tick(policy.maximum_wait_seconds(route.station_id)) if stop else 0
                )
                if stop and t + tick(route.platform_exit_offset_seconds) < tick(
                    policy.earliest_wait_time_seconds
                ):
                    maximum = 0
                step = tick(policy.step_seconds) if policy.step_seconds else 1
                for wait in range(0, maximum + 1, step):
                    yield from recurse(
                        route.to_state_id,
                        t + route.duration_tick + wait,
                        routes + [route.id],
                        times + [t],
                        waits + [wait],
                    )

        choices.append(list(recurse(start.state_id, start.time_tick, [], [], [])))
    groups = {g.id: g for g in problem.passenger_build.demand_groups}
    for supports in product(*choices):
        solution = solution_from_cp_sat_payload(
            problem, dict(trajectory_supports=supports)
        )
        try:
            validate_ddd_cp_sat_incumbent(
                problem, solution, {}, provenance="enumeration"
            )
        except ValueError:
            continue
        valid = []
        for ride in problem.passenger_build.ride_candidates:
            try:
                validate_ddd_cp_sat_incumbent(
                    problem, solution, {ride.id: 1}, provenance="enumeration"
                )
            except ValueError:
                continue
            valid.append(ride)
        for counts in product(
            *(
                range(
                    min(
                        groups[r.demand_group_id].count,
                        problem.artifact.config.cabin_capacity,
                    )
                    + 1
                )
                for r in valid
            )
        ):
            try:
                yield validate_ddd_cp_sat_incumbent(
                    problem,
                    solution,
                    {r.id: n for r, n in zip(valid, counts) if n},
                    provenance="enumeration",
                )
            except ValueError:
                pass


@pytest.mark.parametrize(
    "k,waiting,step", [(1, 0, 1), (1, 2, 1), (1, 2, 0.5), (2, 0, 1)]
)
def test_all_enumerated_plans_replay_and_optimum_matches_cp(k, waiting, step):
    _, problem = prepare_small(
        k,
        waiting=waiting,
        step=step,
        horizon=80,
        capacity=1,
        groups=(EanDemandGroup("ab", "A", "B", 0, 2),),
    )
    built = build_didp_model(prepare_didp_structure(problem))
    best = math.inf
    count = 0
    for incumbent in independent_plans(problem):
        replay_didp_checkpoint(problem, built, incumbent)
        best = min(best, sum(incumbent.unserved_counts.values()))
        count += 1
    assert count > 0
    native = dp.CABS(
        built.model, time_limit=10, keep_all_layers=True, quiet=True
    ).search()
    assert native.is_optimal
    checked = extract_didp_incumbent(problem, built, native.transitions, native.cost)
    cp = DddCpSatCapacityOptimizer(
        DddIntegratedCpSatConfig(total_time_limit_seconds=10, num_workers=1)
    ).solve(problem)
    assert cp["proven_optimal"]
    assert sum(checked.unserved_counts.values()) == best == cp["unserved_upper_bound"]


@pytest.mark.parametrize("steps", [0, 1, 2, 3, 4, 5, 9])
def test_binary_wait_range_preserves_every_value(steps):
    _, problem = prepare_small(1, waiting=max(1, steps), step=1, groups=())
    built = build_didp_model(prepare_didp_structure(problem))
    op = next(o for o in built.prepared.operations if o.visit == 0 and o.maximum_steps)
    state = built.transitions[f"route/{op.index}"].apply(
        built.model.target_state, built.model
    )
    state[built.variables["hi"]] = steps
    stack = [state]
    leaves = []
    while stack:
        current = stack.pop()
        lo, hi = current[built.variables["lo"]], current[built.variables["hi"]]
        if lo == hi:
            leaves.append(lo)
        else:
            for half in ("low", "high"):
                tr = built.transitions[f"split/{op.index}/{half}"]
                assert tr.is_applicable(current, built.model)
                stack.append(tr.apply(current, built.model))
    assert sorted(leaves) == list(range(steps + 1))


def test_delayed_reservation_and_exact_horizon_boundary():
    _, problem = prepare_small(2, groups=())
    b = build_didp_model(prepare_didp_structure(problem))
    r = next(i for i, n in enumerate(b.prepared.calendar_sizes) if n >= 2)
    v = b.variables
    state = b.model.target_state
    state[v["phase"]] = 5
    state[v["pending_resource"]] = r
    state[v[f"count/{r}"]] = 1
    state[v[f"entry/{r}/0"]] = 100.0
    state[v[f"end/{r}/0"]] = 110.0
    # A later-planned movement enters BEFORE an existing future reservation.
    state[v["pending_entry"]] = 80.0
    state[v["pending_end"]] = 100.0
    insert = b.transitions[f"insert/{r}"]
    assert insert.is_applicable(state, b.model)
    after = insert.apply(state, b.model)
    assert after[v[f"entry/{r}/0"]] == 80 and after[v[f"entry/{r}/1"]] == 100
    state[v["pending_end"]] = 101.0
    assert not insert.is_applicable(state, b.model)


def test_unfulfilled_obligation_cannot_terminate_or_skip():
    _, problem = prepare_small(1)
    b = build_didp_model(prepare_didp_structure(problem))
    v = b.variables
    state = b.model.target_state
    state[v["due/0/0"]] = 1
    for op in b.prepared.operations:
        if op.visit == 0 and op.route.platform_exit_offset_seconds is None:
            assert not b.transitions[f"route/{op.index}"].is_applicable(state, b.model)
    state[v["time/0"]] = float(b.prepared.operation_end + 1)
    assert not b.model.is_base(state)
    state[v["due/0/0"]] = 0
    assert b.model.is_base(state)


def test_ticks_above_i32_remain_exact_and_bad_ticks_rejected():
    assert exact_tick(float(2**31 + 7)) == 2**31 + 7
    _, problem = prepare_small(1, horizon=2300, groups=())
    b = build_didp_model(prepare_didp_structure(problem))
    assert b.prepared.operation_end > 2**31
    for value in (0.5, float("inf"), float(2**53)):
        with pytest.raises(ValueError):
            exact_tick(value)
    with pytest.raises(ValueError, match="Float64"):
        huge = replace(
            problem.passenger_build,
            demand_groups=(EanDemandGroup("far", "A", "B", 2**53, 1),),
        )
        prepare_didp_structure(replace(problem, passenger_build=huge))


@pytest.mark.parametrize(
    "k,path,expected",
    [
        (38, "pattern_search_20260910/seeds/k38_waiting_n3074/incumbent.json", 315),
        (39, "pattern_search_followup_20260910/run/incumbent.json", 1402),
    ],
)
def test_historical_replay(k, path, expected):
    source = Path("benchmarks/output") / path
    if not source.exists():
        pytest.skip("Historical local checkpoint not present")
    _, problem = prepare_large(k)
    p = prepare_didp_structure(problem)
    try:
        checked = read_ddd_cp_sat_checkpoint(
            source, problem=problem, manifest=p.manifest
        )
    except ValueError as exc:
        # Local historical artifacts may predate the current physical contract.
        # Their rejection is the required behavior; they are archive evidence,
        # not current replay fixtures.
        assert "domain fingerprint mismatch" in str(exc)
        return
    b = build_didp_model(p)
    transitions, replayed = replay_didp_checkpoint(problem, b, checked)
    assert transitions
    assert sum(replayed.unserved_counts.values()) == expected


def test_supervised_timeout_does_not_claim_infeasible():
    _, problem = prepare_small(1)
    result = DddDidpOptimizer(DddDidpConfig(time_limit_seconds=0.001)).solve(problem)
    assert result["solver_status"] == "TIME_LIMIT"
    assert not result["proven_optimal"]
    assert result["native_unserved"] is None


def test_bypass_overtaking_is_representable():
    _, problem = prepare_small(2, groups=(), horizon=80)
    b = build_didp_model(prepare_didp_structure(problem))
    overtakes = 0
    for checked in independent_plans(problem):
        a, c = checked.solution.trajectories
        if any(
            x.next_switch_time_seconds > y.next_switch_time_seconds
            for x, y in zip(a.visits, c.visits)
        ):
            replay_didp_checkpoint(problem, b, checked)
            overtakes += 1
    assert overtakes > 0


def test_releases_during_wait_and_positive_wait_warmup():
    _, base = prepare_small(1, waiting=2, step=1, horizon=80, capacity=1, groups=())
    first = next(
        o
        for o in base.resolved_trajectory_problem.fixed_movement_problem.route_options_by_state_id[
            "A_entry_cw"
        ]
        if o.platform_exit_offset_seconds is not None
    )
    release = first.platform_exit_offset_seconds + 1
    from ropeway_skip_stop_optimization.optimization.ean.builders.passenger_builder import (
        EanPassengerCandidateBuildResult,
        build_ean_ride_candidates,
    )

    group = (EanDemandGroup("wait_release", "A", "B", release, 1),)
    problem = replace(
        base,
        passenger_build=EanPassengerCandidateBuildResult(
            group, build_ean_ride_candidates(group, base.artifact)
        ),
    )
    b = build_didp_model(prepare_didp_structure(problem))
    native = dp.CABS(b.model, time_limit=10, keep_all_layers=True, quiet=True).search()
    assert native.is_optimal and native.cost == 1
    checked = extract_didp_incumbent(problem, b, native.transitions, native.cost)
    assert checked.solution.trajectories[0].visits[0].wait_seconds >= 1
    # The current artifact adapter fixes this phase to zero. Exercise the
    # native gate directly; an inconsistent public domain is correctly rejected.
    b = build_didp_model(
        replace(prepare_didp_structure(problem), earliest_wait=tick(release))
    )
    op = next(o for o in b.prepared.operations if o.visit == 0 and o.maximum_steps)
    state = b.transitions[f"route/{op.index}"].apply(b.model.target_state, b.model)
    assert state[b.variables["hi"]] == 0


def test_arrival_at_horizon_and_one_tick_after():
    _, base = prepare_small(1, groups=())
    routes = base.resolved_trajectory_problem.fixed_movement_problem.route_options_by_state_id
    first = next(
        o for o in routes["A_entry_cw"] if o.platform_exit_offset_seconds is not None
    )
    second = next(
        o
        for o in routes[first.to_state_id]
        if o.platform_entry_offset_seconds is not None
    )
    arrival = first.duration_tick + tick(second.platform_entry_offset_seconds)
    # Retain the canonical candidate from the wider fixture: the existing EAN
    # candidate generator uses seconds and can prune the rounded exact boundary.
    _, wide = prepare_small(
        1, capacity=1, groups=(EanDemandGroup("ab", "A", "B", 0, 1),)
    )
    for delta, expected in [(0, 1), (-1, 0)]:
        _, problem = prepare_small(
            1,
            horizon=(arrival + delta) / 1e6,
            capacity=1,
            groups=(EanDemandGroup("ab", "A", "B", 0, 1),),
        )
        problem = replace(problem, passenger_build=wide.passenger_build)
        b = build_didp_model(prepare_didp_structure(problem))
        r = dp.CABS(b.model, time_limit=5, quiet=True, keep_all_layers=True).search()
        assert r.is_optimal and r.cost == expected
        checked = extract_didp_incumbent(problem, b, r.transitions, r.cost)
        assert (
            checked.solution.trajectories[0].visits[-1].next_switch_time_seconds
            > problem.artifact.config.horizon_seconds
        )


def test_full_cabin_alight_before_board_and_rest_bound_on_all_small_states():
    _, problem = prepare_small(
        1,
        horizon=130,
        capacity=1,
        groups=(
            EanDemandGroup("ab", "A", "B", 0, 1),
            EanDemandGroup("bc", "B", "C", 0, 1),
        ),
    )
    b = build_didp_model(prepare_didp_structure(problem))
    memo = {}
    all_transitions = list(b.transitions.values())
    forced = [tr for name, tr in b.transitions.items() if name.startswith("expire/")]

    def dfs(state):
        key = tuple(state[var] for var in b.variables.values())
        if key in memo:
            return memo[key]
        if b.model.is_base(state):
            return 0
        options = [tr for tr in forced if tr.is_applicable(state, b.model)]
        options = (
            options[:1]
            if options
            else [
                tr
                for tr in all_transitions
                if not tr.name.startswith("expire/")
                and tr.is_applicable(state, b.model)
            ]
        )
        best = None
        for tr in options:
            rest = dfs(tr.apply(state, b.model))
            if rest is not None:
                candidate = tr.eval_cost(0, state, b.model) + rest
                best = candidate if best is None else max(best, candidate)
        if best is not None:
            assert b.model.eval_dual_bound(state) >= best
        memo[key] = best
        return best

    assert dfs(b.model.target_state) == 2
    assert len(memo) > 50


def test_entry_at_operating_end_keeps_protection_after_end():
    _, problem = prepare_small(1, groups=())
    b = build_didp_model(prepare_didp_structure(problem))
    v = b.variables
    op = next(o for o in b.prepared.operations if o.route.resource_usages)
    usage = op.route.resource_usages[0]
    state = b.model.target_state
    state[v["phase"]] = 3
    state[v["operation"]] = op.index
    state[v["cursor"]] = 0
    state[v[f"time/{op.cabin}"]] = float(
        b.prepared.operation_end - usage.follower_enter_offset_tick
    )
    inside = b.transitions[f"reserve/{op.index}/0/inside"]
    outside = b.transitions[f"reserve/{op.index}/0/outside"]
    assert inside.is_applicable(state, b.model) and not outside.is_applicable(
        state, b.model
    )
    state = inside.apply(state, b.model)
    assert state[v["pending_end"]] > b.prepared.operation_end
    state[v["phase"]] = 3
    state[v[f"time/{op.cabin}"]] += 1
    assert outside.is_applicable(state, b.model) and not inside.is_applicable(
        state, b.model
    )


def test_memory_limit_is_not_an_infeasibility_proof():
    _, problem = prepare_small(1)
    result = DddDidpOptimizer(
        DddDidpConfig(time_limit_seconds=5, memory_limit_gib=0.001)
    ).solve(problem)
    assert result["solver_status"] == "MEMORY_LIMIT"
    assert not result["proven_optimal"]


def test_reference_is_external_fallback_and_build_only_replays(tmp_path):
    _, problem = prepare_small(1)
    b = build_didp_model(prepare_didp_structure(problem))
    r = dp.CABS(b.model, time_limit=5, quiet=True, keep_all_layers=True).search()
    x = extract_didp_incumbent(problem, b, r.transitions, r.cost)
    path = tmp_path / "reference.json"
    write_ddd_cp_sat_checkpoint(
        path, problem=problem, manifest=b.prepared.manifest, incumbent=x
    )
    result = DddDidpOptimizer(
        DddDidpConfig(time_limit_seconds=5, reference_checkpoint=path, build_only=True)
    ).solve(problem)
    assert result["solver_status"] == "BUILD_ONLY"
    assert result["native_unserved"] is None and not result["native_warmstart"]
    assert result["best_validated_unserved"] == sum(x.unserved_counts.values())
    assert any(e["kind"] == "reference_replayed" for e in result["events"])
