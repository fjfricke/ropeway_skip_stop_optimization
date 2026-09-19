"""Native incumbent persistence survives interrupted validation and hard deadlines."""
import json
import os
import signal
import subprocess
import sys
import time
from dataclasses import asdict, replace
from pathlib import Path
from threading import Event

import pytest

from test_oip_pattern_waiting import _small_domain
from ropeway_skip_stop_optimization.optimization.oip.cp_sat import OipCpSatConfig, solve_oip_cp_sat
from ropeway_skip_stop_optimization.optimization.oip.incumbent_store import OipIncumbentStore, recover_validated_incumbent
from ropeway_skip_stop_optimization.optimization.oip.runner import OipRunConfig, _write_run, decode_oip_certificate, run_oip


@pytest.fixture(scope='module')
def solution():
    domain = _small_domain(0)
    result = solve_oip_cp_sat(domain, OipCpSatConfig(time_limit_seconds=5, objective='served'))
    assert result.passenger_plan is not None
    return domain, result


def make_store(tmp_path, domain):
    config = OipRunConfig(objective='served', output_directory=tmp_path)
    return OipIncumbentStore(domain, tmp_path, lambda directory, result: _write_run(directory, domain, config, result))


def test_native_callback_exports_complete_certificates(solution):
    domain, _ = solution
    seen = []
    result = solve_oip_cp_sat(domain, OipCpSatConfig(time_limit_seconds=5, objective='served', incumbent_callback=seen.append))
    assert seen and seen[-1].served_passengers == result.served_passengers
    for candidate in seen:
        decode_oip_certificate({
            'movement_plan': asdict(candidate.movement_plan),
            'fleet_plan': asdict(candidate.fleet_plan),
            'passenger_plan': asdict(candidate.passenger_plan),
        }, domain)


def test_recover_checked_certificate_after_deadline(tmp_path, solution):
    domain, result = solution
    store = make_store(tmp_path, domain)
    store.submit(result)
    assert store.finish(10) is result
    # A newer unverified candidate must never replace the committed incumbent.
    (tmp_path / 'candidate.json').write_text('{partial interrupted write')
    recovered = recover_validated_incumbent(tmp_path, 'WALL_DEADLINE', expected_domain=domain.fingerprint)
    assert recovered['solver_status'] == 'FEASIBLE_CHECKPOINT'
    assert recovered['served_passengers'] == result.served_passengers
    assert recovered['status'] != 'optimal'
    decode_oip_certificate(recovered, domain)
    assert json.loads((tmp_path / 'snapshot.json').read_text())['status'] == 'complete'
    with pytest.raises(ValueError, match='domain'):
        recover_validated_incumbent(tmp_path, 'WALL_DEADLINE', expected_domain='wrong')


def test_recovery_rejects_another_mixture(tmp_path, solution):
    domain, result = solution
    store = make_store(tmp_path, domain)
    store.submit(result)
    store.finish(10)
    with pytest.raises(ValueError, match='type counts'):
        recover_validated_incumbent(tmp_path, 'WALL_DEADLINE', expected_domain=domain.fingerprint,
                                    expected_type_counts={'all_stop': 62})


def test_validation_failure_never_publishes_false_incumbent(tmp_path, solution):
    domain, result = solution
    store = make_store(tmp_path, domain)
    store.submit(replace(result, served_passengers=result.served_passengers + 1))
    with pytest.raises(ValueError, match='validation failed'):
        store.finish(10)
    assert not (tmp_path / 'validated_incumbent.json').exists()
    assert recover_validated_incumbent(tmp_path, 'WALL_DEADLINE', expected_domain=domain.fingerprint) is None


def test_incomplete_validation_retains_previous_atomic_commit(tmp_path, solution, monkeypatch):
    domain, result = solution
    import ropeway_skip_stop_optimization.optimization.oip.incumbent_store as module
    store = make_store(tmp_path, domain)
    store.submit(result)
    deadline = time.monotonic() + 10
    while store.best is None and time.monotonic() < deadline:
        time.sleep(.01)
    assert store.best is result
    committed = (tmp_path / 'validated_incumbent.json').read_bytes()
    entered, release = Event(), Event()
    original = module.validate_oip_certificate
    def delayed(*args):
        entered.set()
        release.wait(5)
        return original(*args)
    monkeypatch.setattr(module, 'validate_oip_certificate', delayed)
    store.submit(replace(result, runtime_seconds=999))
    assert entered.wait(2)
    assert store.finish(.01) is result
    assert (tmp_path / 'validated_incumbent.json').read_bytes() == committed
    release.set()
    store.thread.join(5)


def test_runner_saves_checked_incumbents_and_normal_optimum(tmp_path, solution):
    domain, _ = solution
    result = run_oip(domain, OipRunConfig(objective='served', output_directory=tmp_path, time_limit_seconds=5))
    assert result.status == 'optimal'
    assert (tmp_path / 'validated_incumbent.json').exists()
    assert json.loads((tmp_path / 'result.json').read_text())['served_passengers'] == result.served_passengers


def test_real_process_kill_preserves_committed_certificate(tmp_path, solution):
    domain, _ = solution
    script = '''
import time
from pathlib import Path
from test_oip_pattern_waiting import _small_domain
from ropeway_skip_stop_optimization.optimization.oip.runner import OipRunConfig, run_oip
run_oip(_small_domain(0), OipRunConfig(objective='served', time_limit_seconds=5, output_directory=Path(__import__('sys').argv[1])))
time.sleep(60)
'''
    root = Path(__file__).parents[1]
    process = subprocess.Popen([sys.executable, '-c', script, str(tmp_path)],
                               env={**os.environ, 'PYTHONPATH': os.pathsep.join([str(root/'src'), str(root/'tests')])},
                               start_new_session=True)
    try:
        deadline = time.monotonic() + 15
        while not (tmp_path/'validated_incumbent.json').exists() and time.monotonic() < deadline:
            time.sleep(.02)
        assert (tmp_path/'validated_incumbent.json').exists()
        os.killpg(process.pid, signal.SIGKILL)
        process.wait(timeout=3)
        recovered = recover_validated_incumbent(tmp_path, 'WALL_DEADLINE', expected_domain=domain.fingerprint)
        assert recovered is not None
        decode_oip_certificate(recovered, domain)
    finally:
        if process.poll() is None:
            os.killpg(process.pid, signal.SIGKILL)
            process.wait()


def test_absolute_deadline_requests_stop_independently_of_solution_callbacks(monkeypatch, solution):
    from ortools.sat.python import cp_model
    domain, _ = solution
    stopped = Event()
    original_solve, original_stop = cp_model.CpSolver.solve, cp_model.CpSolver.stop_search
    def observe_stop(self):
        stopped.set()
        return original_stop(self)
    def delayed_native_return(self, *args, **kwargs):
        status = original_solve(self, *args, **kwargs)
        assert stopped.wait(2), 'Absolute deadline never requested a cooperative stop'
        return status
    monkeypatch.setattr(cp_model.CpSolver, 'solve', delayed_native_return)
    monkeypatch.setattr(cp_model.CpSolver, 'stop_search', observe_stop)
    solve_oip_cp_sat(domain, OipCpSatConfig(time_limit_seconds=5, search_deadline_unix=time.time()+.2))
    assert stopped.is_set()
