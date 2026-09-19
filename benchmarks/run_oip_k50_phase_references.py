#!/usr/bin/env python3
"""Supplement the completed K50 mixture study with three regular phase references."""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from run_oip_fixed_mix_campaign import _run_one
from run_oip_nowait_formulation_comparison import ROOT, FRONTEND_ROOT, now
from run_oip_type_catalog_campaign import _publish_run
from ropeway_skip_stop_optimization.benchmarking.frontend_results import atomic_json
from ropeway_skip_stop_optimization.benchmarking.oip_pattern_waiting import prepare_oip_pattern_waiting_pilot
from ropeway_skip_stop_optimization.benchmarking.thesis_contract import source_digest, solver_versions, HEADWAY_CONTRACT

FAMILIES = ('f2', 'f3', 'f0')
LOADS = dict(zip(FAMILIES, (2266, 5430, 7606)))


def prepare(source: Path) -> dict:
    parent = json.loads((source / 'campaign.json').read_text())
    if parent['status'] != 'complete' or parent['k_values'] != [50] or parent['load_contract'] != LOADS:
        raise ValueError('Expected completed K50 study at unchanged K62 demand')
    hashes = {}
    for path in [source / 'campaign.json', *[source / 'frozen_domains' / f'{f}.json' for f in FAMILIES]]:
        hashes[str(path)] = hashlib.sha256(path.read_bytes()).hexdigest()
    for family in FAMILIES:
        frozen = json.loads((source / 'frozen_domains' / f'{family}.json').read_text())
        domain = prepare_oip_pattern_waiting_pilot(maximum_wait_seconds=0, cabin_count=50,
            demand_total=LOADS[family], demand_family=family).domain
        groups = [[d.arrival_time.isoformat(), d.origin, d.destination, d.count] for d in domain.scenario.demands]
        if (groups != frozen['demand_groups'] or domain.comparison_fingerprint != frozen['comparison_fingerprint']
                or frozen['headway_contract'] != HEADWAY_CONTRACT):
            raise ValueError('Reference preparation differs from frozen K50 contract')
    return {'source_campaign': str(source), 'source_hashes': hashes,
            'source_digest': source_digest(ROOT), 'solver_versions': solver_versions(),
            'fixed_k': 50, 'loads': LOADS, 'seconds_per_reference': 300,
            'completion_reserve_seconds': 10, 'workers': 12, 'seed': 0,
            'memory_limit_gib': 32, 'headway_contract': HEADWAY_CONTRACT}


def command(family: str, directory: Path) -> list[str]:
    return [sys.executable, str(ROOT / 'benchmarks/run_oip_regular_all_stop_reference.py'),
            '--family', family, '--demand-total', str(LOADS[family]), '--fixed-k', '50',
            '--time-limit', '300', '--memory-limit-gib', '32', '--output', str(directory)]


def publish(output: Path, source: Path, frontend: Path, manifest: dict) -> None:
    manifest['updated_at_utc'] = now()
    atomic_json(output / 'campaign.json', manifest)
    # Supplement only the display export. Original campaign and solver results stay frozen.
    parent = json.loads((source / 'campaign.json').read_text())
    parent['supplementary_phase_references'] = {
        'status': manifest['status'], 'reference_runs': manifest['reference_runs'],
        'updated_at_utc': manifest['updated_at_utc']}
    atomic_json(frontend / parent['campaign_id'] / 'snapshot.json', parent)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source-campaign', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--frontend-root', type=Path, default=FRONTEND_ROOT)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument('--build-only', action='store_true')
    mode.add_argument('--run', action='store_true')
    parser.add_argument('--resume', action='store_true')
    args = parser.parse_args()
    if args.resume and args.build_only:
        parser.error('Use --run --resume for execution of a prepared campaign')
    source, output = args.source_campaign.resolve(), args.output.resolve()
    if source == output:
        parser.error('Supplement requires a separate output directory')
    config = prepare(source)
    path = output / 'campaign.json'
    if args.resume:
        manifest = json.loads(path.read_text())
        if manifest['configuration'] != config:
            raise ValueError('Resume requires identical source study, code and configuration')
    else:
        if path.exists():
            raise ValueError('Output already prepared; use --run --resume')
        manifest = {'status': 'prepared', 'configuration': config, 'created_at_utc': now(),
            'reference_runs': {f: {'status': 'planned', 'demand_total': LOADS[f],
                'fixed_k': 50, 'attempts': []} for f in FAMILIES}}
    publish(output, source, args.frontend_root, manifest)
    if args.build_only:
        print('Prepared three K50 common-phase references; no solves started')
        return
    manifest['status'] = 'running'
    args.memory_limit_gib = 32
    for family in FAMILIES:
        trial = manifest['reference_runs'][family]
        if trial['status'] == 'complete':
            continue
        for previous in trial['attempts']:
            if previous['status'] == 'running':
                previous['status'] = 'interrupted'
        n = len(trial['attempts']) + 1
        directory = output / family / f'attempt_{n}'
        directory.mkdir(parents=True, exist_ok=False)
        run_id = f'{source.name}__phase_reference__{family}__a{n}'
        attempt = {'attempt': n, 'status': 'running', 'started_at_utc': now(),
                   'directory': str(directory.relative_to(output))}
        trial['attempts'].append(attempt)
        trial.update(status='running', served=None, served_upper_bound=None)
        trial.pop('run_campaign_id', None)
        publish(output, source, args.frontend_root, manifest)
        guard = _run_one(command(family, directory), directory, 300, args)
        attempt.update(supervisor=guard, finished_at_utc=now())
        result_path = directory / 'result.json'
        search_path = directory / 'phase_search.json'
        if guard.get('exit_code') == 0 and result_path.exists():
            result = json.loads(result_path.read_text())
            meta = json.loads((directory / 'manifest.json').read_text())
            expected = json.loads((source / 'frozen_domains' / f'{family}.json').read_text())
            if (result.get('validation_status') != 'valid' or meta['fixed_k'] != 50
                    or meta['comparison_fingerprint'] != expected['comparison_fingerprint']):
                raise ValueError('Reference certificate contract mismatch')
            trial.update(status='complete', served=result['served_passengers'],
                journey_time_seconds=result['journey_time_seconds'],
                served_upper_bound=result.get('served_upper_bound'),
                proven_optimal=result.get('served_optimal_over_phase', False),
                common_phase_seconds=result['common_phase_seconds'], run_campaign_id=run_id)
            _publish_run(args.frontend_root, directory, run_id)
        elif search_path.exists() and not result_path.exists():
            search = json.loads(search_path.read_text())
            trial.update(status='unknown' if search.get('status') == 'UNKNOWN' else 'interrupted',
                         served_upper_bound=search.get('served_upper_bound'))
        else:
            trial['status'] = 'interrupted'
        attempt['status'] = trial['status']
        publish(output, source, args.frontend_root, manifest)
    manifest['status'] = 'complete' if all(t['status'] == 'complete' for t in manifest['reference_runs'].values()) else 'finished_with_unresolved'
    publish(output, source, args.frontend_root, manifest)


if __name__ == '__main__':
    main()
