from copy import deepcopy
from dataclasses import replace
import json

import pytest

from test_optimization_ddd_cp_sat_integrated import tiny_problem
from ropeway_skip_stop_optimization.benchmarking.ddd_fixed_k_arc_flow import (
    _read_compatible_root_cg_lower_bound,
)
from ropeway_skip_stop_optimization.optimization.ddd.cp_sat_certificate import (
    read_ddd_cp_sat_checkpoint,
    stable_fingerprint,
    write_ddd_cp_sat_checkpoint,
)
from ropeway_skip_stop_optimization.optimization.ddd.cp_sat_integrated import (
    DddIntegratedCpSatOptimizer,
)


@pytest.fixture
def problem():
    return tiny_problem()[1]


def certificate(problem):
    return {
        "fixed_k_problem_fingerprint": problem.fingerprint,
        "fixed_k_problem_manifest": problem.certificate_manifest,
        "proof_scope": "FIXED_K_GLOBAL",
        "status": "time_limit_with_certified_interval",
        "certificate_valid": True,
        "certified_lower_bound": 123.0,
    }


def test_current_manifest_roundtrip_imports_bound(problem, tmp_path):
    path = tmp_path / "bound.json"
    path.write_text(json.dumps(certificate(problem)))
    assert _read_compatible_root_cg_lower_bound(path, expected_problem=problem) == 123.0


@pytest.mark.parametrize(
    "change",
    [
        "capacity",
        "route_time",
        "headway",
        "start",
        "release",
        "waiting",
        "candidates",
        "horizon",
    ],
)
def test_fingerprint_covers_full_mathematical_domain(problem, change):
    core = problem.trajectory_problem.movement_core
    trajectory = problem.trajectory_problem
    if change == "capacity":
        changed = replace(
            problem,
            artifact=replace(
                problem.artifact,
                config=replace(problem.artifact.config, cabin_capacity=3),
            ),
        )
    elif change == "route_time":
        route = replace(
            core.route_options[0],
            duration_seconds=core.route_options[0].duration_seconds + 1,
        )
        changed = replace(
            problem,
            trajectory_problem=replace(
                trajectory,
                movement_core=replace(
                    core, route_options=(route, *core.route_options[1:])
                ),
            ),
        )
    elif change == "headway":
        resource = replace(
            core.resources[0], headway_seconds=core.resources[0].headway_seconds + 1
        )
        changed = replace(
            problem,
            trajectory_problem=replace(
                trajectory,
                movement_core=replace(core, resources=(resource, *core.resources[1:])),
            ),
        )
    elif change == "start":
        start = replace(trajectory.start_domain.starts[0], time_seconds=1.0)
        changed = replace(
            problem,
            trajectory_problem=replace(
                trajectory,
                start_domain=replace(trajectory.start_domain, starts=(start,)),
            ),
        )
    elif change == "release":
        group = replace(
            problem.passenger_build.demand_groups[0], release_time_seconds=1.0
        )
        changed = replace(
            problem,
            passenger_build=replace(
                problem.passenger_build,
                demand_groups=(group, *problem.passenger_build.demand_groups[1:]),
            ),
        )
    elif change == "waiting":
        changed = tiny_problem(maximum_wait=1.0)[1]
    elif change == "horizon":
        changed = replace(
            problem,
            trajectory_problem=replace(
                trajectory, movement_core=replace(core, operational_end_seconds=131.0)
            ),
        )
    else:
        changed = replace(
            problem,
            passenger_build=replace(
                problem.passenger_build,
                ride_candidates=problem.passenger_build.ride_candidates[:-1],
            ),
        )
    assert changed.fingerprint != problem.fingerprint
    assert stable_fingerprint(changed.certificate_manifest) == changed.fingerprint


@pytest.mark.parametrize(
    ("key", "value"),
    [
        ("certificate_valid", False),
        ("certificate_valid", None),
        ("proof_scope", "FIXED_MOVEMENT"),
        ("proof_scope", None),
        ("status", "internal_certificate_error"),
        ("status", "internal_validation_error"),
        ("fixed_k_problem_manifest", None),
        ("fixed_k_problem_fingerprint", "foreign"),
        ("certified_lower_bound", float("nan")),
        ("certified_lower_bound", float("inf")),
        ("certified_lower_bound", True),
        ("certified_lower_bound", "123"),
    ],
)
def test_import_rejects_invalid_or_incomplete_certificate(
    problem, tmp_path, key, value
):
    payload = certificate(problem)
    payload[key] = value
    path = tmp_path / "bound.json"
    path.write_text(json.dumps(payload))
    with pytest.raises(ValueError):
        _read_compatible_root_cg_lower_bound(path, expected_problem=problem)


def test_import_rejects_rehashed_foreign_capacity(problem, tmp_path):
    payload = deepcopy(certificate(problem))
    payload["fixed_k_problem_manifest"]["cabin_capacity"] = 3
    payload["fixed_k_problem_fingerprint"] = stable_fingerprint(
        payload["fixed_k_problem_manifest"]
    )
    path = tmp_path / "bound.json"
    path.write_text(json.dumps(payload))
    with pytest.raises(ValueError, match="fingerprint"):
        _read_compatible_root_cg_lower_bound(path, expected_problem=problem)


def test_legacy_primal_is_revalidated_and_progress_streamed(problem, tmp_path):
    events = []
    result = DddIntegratedCpSatOptimizer().solve(problem, event_callback=events.append)
    assert events == list(result.events)
    assert events[-1]["kind"] == "final"
    assert result.callback_extraction_seconds >= 0
    assert result.callback_validation_seconds >= 0
    path = tmp_path / "seed.json"
    write_ddd_cp_sat_checkpoint(
        path,
        problem=problem,
        manifest=result.domain_manifest,
        incumbent=result.incumbent,
    )
    payload = json.loads(path.read_text())
    payload["problem_fingerprint"] = problem.legacy_fingerprint
    # Bound-like metadata in an old seed must never become a proof.
    payload["certified_lower_bound"] = 1e9
    path.write_text(json.dumps(payload))
    checked = read_ddd_cp_sat_checkpoint(
        path, problem=problem, manifest=result.domain_manifest
    )
    assert checked.objective_tick == result.incumbent.objective_tick
    payload.pop("domain_manifest")
    path.write_text(json.dumps(payload))
    with pytest.raises(ValueError, match="fingerprint"):
        read_ddd_cp_sat_checkpoint(
            path, problem=problem, manifest=result.domain_manifest
        )


def test_seed_evaluation_uses_problem_demand_instead_of_example_defaults():
    from ropeway_skip_stop_optimization.benchmarking.ddd_scaling import (
        build_initial_ddd_network_problem,
    )
    from ropeway_skip_stop_optimization.optimization.ddd.fixed_k_primal_seed import (
        DddFixedKPrimalSeedFactory,
    )

    scenario, problem = tiny_problem()
    result = DddIntegratedCpSatOptimizer().solve(problem)
    seed = DddFixedKPrimalSeedFactory(
        scenario=scenario,
        problem=problem,
        network_problem=build_initial_ddd_network_problem(
            problem.resolved_trajectory_problem.structural_movement_problem
        ),
        passenger_time_limit_seconds=10,
        threads=1,
    ).build(
        result.incumbent.solution.trajectories, provenance="custom_demand_regression"
    )
    assert seed.objective_value == pytest.approx(result.incumbent.objective)
    assert set(seed.ride_counts_by_candidate_id) <= {
        q.id for q in problem.passenger_build.ride_candidates
    }
