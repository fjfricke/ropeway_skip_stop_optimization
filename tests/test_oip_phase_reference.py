from dataclasses import replace

import pytest
from test_oip_pattern_waiting import _small_domain

from ropeway_skip_stop_optimization.optimization.oip.phase_reference import (
    phase_rides, regular_geometry, regular_movement, solve_phase_reference,
)
from ropeway_skip_stop_optimization.optimization.oip.runner import _evaluate_fixed_movement_passengers
from ropeway_skip_stop_optimization.optimization.oip.validation import validate_oip_certificate
from ropeway_skip_stop_optimization.optimization.oip.passenger_candidates import (
    oip_passenger_candidate_builder,
)


def test_phase_cells_equal_independent_fixed_ean_at_every_boundary():
    domain = _small_domain(0)
    rides, _, cycle = phase_rides(domain)
    edges = {0, cycle, *(r.first for r in rides), *(r.last + 1 for r in rides)}
    phases = sorted({p for b in edges for p in (b - 1, b) if 0 <= p < cycle})
    best = 0
    for phase in phases:
        stats, certificate = solve_phase_reference(domain, seconds=10, workers=1,
            require_full_service=False, fixed_phase_tick=phase)
        assert stats['native_status'] == 2
        movement, fleet, passengers = certificate
        other = _evaluate_fixed_movement_passengers(domain, movement, fleet,
            time_limit_seconds=10, memory_limit_gib=1)
        assert stats['served'] == other['served_passengers'], (phase, stats, other)
        validate_oip_certificate(domain, movement, fleet, passengers)
        best = max(best, stats['served'])
    free, _ = solve_phase_reference(domain, seconds=10, workers=1, require_full_service=False)
    assert free['served'] == best
    assert free['served_upper_bound'] == best
    impossible, cert = solve_phase_reference(domain, seconds=10, workers=1)
    assert impossible['status'] == 'INFEASIBLE' and cert is None


def test_no_wait_and_timeout_contract():
    with pytest.raises(ValueError, match='No-Wait'):
        regular_geometry(_small_domain(120))
    stats, cert = solve_phase_reference(_small_domain(0), seconds=0)
    assert stats['status'] == 'UNKNOWN' and cert is None


def test_oip_passenger_candidates_are_safe_for_free_initial_placement():
    config = oip_passenger_candidate_builder().optimization_config
    assert not config.enable_candidate_horizon_pruning
    assert not config.enable_single_ring_dominated_ride_pruning


def test_phase_wrap_and_initial_occupancy():
    domain = _small_domain(0, cabin_count=2)
    _, _, boundaries, offsets = regular_geometry(domain)
    for phase in {0, boundaries[-1]-1, *(b for b in boundaries[:-1]),
                  *(boundaries[-1]-o for o in offsets if o)}:
        movement, fleet = regular_movement(domain, phase)
        assert len(fleet.active_cabin_ids) == 2
        assert all(t.visits[-1].exit_switch_time_seconds >= domain.artifact.config.operational_end_seconds
                   or t.visits[-1].exit_switch_time_seconds + next(x.rope_to_next_switch_seconds for x in domain.artifact.timings if x.switch_id == t.visits[-1].switch_id) >= domain.artifact.config.operational_end_seconds
                   for t in movement.trajectories)


def test_certificate_json_preserves_enum_values():
    import importlib.util
    import json
    from pathlib import Path
    spec = importlib.util.spec_from_file_location('calibration_runner', Path(__file__).parents[1] / 'benchmarks/run_oip_phase_calibration.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    domain = _small_domain(0)
    movement, _ = regular_movement(domain, 0)
    saved = module.serializable(movement)
    assert saved['trajectories'][0]['visits'][0]['decision'] == 'stop'
    json.dumps(saved, allow_nan=False)


def test_calibration_continuation_reuses_bracket_and_unknown_probe(tmp_path):
    import importlib.util
    import json
    from pathlib import Path
    spec = importlib.util.spec_from_file_location(
        'calibration_runner_continuation',
        Path(__file__).parents[1] / 'benchmarks/run_oip_phase_calibration.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    folder = tmp_path / 'f3' / 'attempt_1'
    folder.mkdir(parents=True)
    (folder / 'probes.json').write_text(json.dumps([
        {'demand': 4500, 'status': 'FEASIBLE'},
        {'demand': 4562, 'status': 'INFEASIBLE'},
        {'demand': 4531, 'status': 'UNKNOWN'},
    ]))
    (folder / 'certificate.json').write_text(json.dumps({'demand': 4500}))
    lower, upper, retry, history, certificate = module.previous_probe_state(
        tmp_path, 'f3', 'attempt_2')
    assert (lower, upper, retry) == (4500, 4562, 4531)
    assert len(history) == 3
    assert certificate == folder / 'certificate.json'
