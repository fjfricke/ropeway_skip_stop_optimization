"""Crash-safe, independently checked incumbents for supervised OIP solves."""
from __future__ import annotations

import json
import time
from dataclasses import asdict
from pathlib import Path
from threading import Condition, Thread

from .validation import validate_oip_certificate


def atomic_json(path: Path, value) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + '.tmp')
    temporary.write_text(json.dumps(value, default=str, separators=(',', ':')) + '\n')
    temporary.replace(path)


class OipIncumbentStore:
    """Export each native incumbent; check the newest pending one off the callback.

    An interrupted validation never replaces the previous committed certificate.
    The complete checked export is committed in a single atomic JSON replacement.
    """

    def __init__(self, domain, directory: Path, writer):
        self.domain, self.directory, self.writer = domain, directory, writer
        self.condition = Condition()
        self.pending = None
        self.closed = False
        self.best = None
        self.error = None
        self.thread = Thread(target=self._work, name='oip-certificate-writer', daemon=True)
        self.thread.start()

    def submit(self, result):
        if result.movement_plan is None or result.passenger_plan is None:
            return
        # This file is explicitly unverified and never serves as a reported result.
        atomic_json(self.directory / 'candidate.json', {
            'validation_status': 'pending', 'domain_fingerprint': self.domain.fingerprint,
            'result': asdict(result),
        })
        with self.condition:
            if self.closed:
                raise RuntimeError('OIP incumbent store is closed')
            self.pending = result
            self.condition.notify()

    def _work(self):
        while True:
            with self.condition:
                self.condition.wait_for(lambda: self.pending is not None or self.closed)
                if self.pending is None:
                    return
                result, self.pending = self.pending, None
            try:
                metrics = validate_oip_certificate(
                    self.domain, result.movement_plan, result.fleet_plan, result.passenger_plan,
                )
                if metrics.served != result.served_passengers or metrics.unserved != result.unserved_passengers:
                    raise ValueError('Checkpoint service differs from independent validation')
                if abs(metrics.journey_time_seconds - result.journey_time_seconds) > max(1e-6, metrics.served / self.domain.grid.ticks_per_second):
                    raise ValueError('Checkpoint journey time differs from independent validation')
                if self.best is not None and result.objective_value > self.best.objective_value:
                    continue
                staging = self.directory / 'checkpoint_export'
                self.writer(staging, result)
                files = {name: json.loads((staging / name).read_text())
                         for name in ('manifest.json', 'result.json', 'detail.json', 'snapshot.json')}
                atomic_json(self.directory / 'validated_incumbent.json', {
                    'schema_version': 1, 'validation_status': 'valid',
                    'domain_fingerprint': self.domain.fingerprint,
                    'validated_at_unix': time.time(), 'files': files,
                })
                with self.condition:
                    self.best = result
            except Exception as exc:
                self.error = exc
                atomic_json(self.directory / 'checkpoint_error.json', {'error': str(exc)})
                return

    def finish(self, timeout=None):
        with self.condition:
            self.closed = True
            self.condition.notify()
        self.thread.join(timeout=timeout)
        if self.error is not None:
            raise ValueError('OIP incumbent validation failed') from self.error
        return self.best


def recover_validated_incumbent(directory: Path, reason: str, *, expected_domain: str, expected_type_counts: dict | None = None) -> dict | None:
    """Publish a previously checked certificate after its worker has exited.

    This does not infer a plan from live counters, re-run a solver or claim optimality.
    Bounds in the checkpoint refer to this exact solve, not a subsequent attempt.
    """
    path = directory / 'validated_incumbent.json'
    if not path.exists() or (directory / 'checkpoint_error.json').exists():
        return None
    bundle = json.loads(path.read_text())
    if bundle.get('validation_status') != 'valid' or bundle.get('domain_fingerprint') != expected_domain:
        raise ValueError('Checkpoint domain or validation status mismatch')
    files = bundle['files']
    if files['manifest.json'].get('domain_fingerprint') != expected_domain:
        raise ValueError('Checkpoint manifest domain mismatch')
    if expected_type_counts is not None and files['manifest.json'].get('fixed_type_counts') != expected_type_counts:
        raise ValueError('Checkpoint fixed type counts mismatch')
    result = files['result.json']
    if any(result.get(key) is None for key in ('movement_plan', 'fleet_plan', 'passenger_plan', 'served_passengers')):
        raise ValueError('Incomplete validated checkpoint')
    result.update(status='feasible', solver_status='FEASIBLE_CHECKPOINT',
                  termination_reason=reason, recovered_checkpoint=True)
    files['detail.json'].update(status='feasible', termination_reason=reason, recovered_checkpoint=True)
    files['snapshot.json']['status'] = 'complete'
    for name in ('manifest.json', 'detail.json', 'snapshot.json', 'result.json'):
        atomic_json(directory / name, files[name])
    return result
