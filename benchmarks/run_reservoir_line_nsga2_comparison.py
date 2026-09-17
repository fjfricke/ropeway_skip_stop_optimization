"""Frozen NSGA-II comparison with matched existing GA runs and trajectory traces.

Waits for an existing campaign before launching solver children. Waiting is
separate from the bounded new campaign, and never runs a competing solver.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import sys
import time

from ropeway_skip_stop_optimization.benchmarking.native_solvers import supervise
from ropeway_skip_stop_optimization.optimization.ddd.cp_sat_certificate import atomic_json

ROOT = Path(__file__).resolve().parents[1]


def summarize_run(directory):
    result_path = directory / 'result.json'
    if not result_path.exists():
        return {'run': directory.name, 'status': 'incomplete'}
    result = json.loads(result_path.read_text())
    events = result['events']
    cuts = {}
    for second in (30, 60, 120, 180, 300):
        before = [e for e in events if e['elapsed_seconds'] <= second]
        populations = [e for e in before if e['kind'] == 'population']
        frontiers = [e for e in before if e['kind'] == 'fleet_frontier']
        mixed = [e for e in frontiers if any(p != 'all_stop' for p in e['pattern_ids'])]
        potential = [e for e in before if e['kind'] == 'potential_frontier']
        members = populations[-1]['members'] if populations else []
        cuts[str(second)] = {
            'best_valid_served_including_reference': max((e['served'] for e in frontiers), default=None),
            'best_native_per_k_served': max((e['served'] for e in frontiers if e['origin'] != 'reference'), default=None),
            'best_valid_mixed_served': max((e['served'] for e in mixed), default=None),
            'largest_valid_mixed_k': max((e['fleet_size'] for e in mixed), default=None),
            'best_relaxed_assigned': max((e['potential']['assigned'] for e in potential), default=None),
            'population_valid': sum(m['served'] is not None for m in members),
            'population_valid_mixed': sum(m['served'] is not None and any(p != 'all_stop' for p in m['pattern_ids']) for m in members),
            'population_conflicting': sum(m['conflicts'] > 0 for m in members),
            'population_k': sorted(set(m['fleet_size'] for m in members)),
            'population': members,
        }
    improvements = [e for e in events if e['kind'] == 'incumbent' and e['origin'] != 'reference']
    return {
        'run': directory.name, 'status': 'complete', 'cuts': cuts,
        'served': result['best']['passengers']['served'] if result.get('best') else None,
        'evaluations': result['evaluations'], 'feasible': result['feasible_evaluations'],
        'last_incumbent_improvement_seconds': max((e['elapsed_seconds'] for e in improvements), default=None),
        'last_per_k_improvement_seconds': max((e['elapsed_seconds'] for e in events if e['kind'] == 'fleet_frontier' and e['origin'] != 'reference'), default=None),
        'evaluation_totals': result.get('evaluation_totals'),
        'selection': result.get('selection'), 'wall_seconds': result['total_wall_seconds'],
    }


def summarize(out, baseline):
    rows = [summarize_run(d) for d in sorted(out.glob('s[012]_*')) if d.is_dir()]
    old = [summarize_run(d) for d in sorted(baseline.glob('s[012]_*')) if d.is_dir()]
    atomic_json(out / 'summary.json', {'nsga2': rows, 'ga_baseline': old})
    lines = ['# NSGA-II und GA: Entwicklung der Reservoir-Linienpläne', '',
        'Gleiche R2-Domäne, No-Wait, K≤50, relevant-Katalog, 32 Individuen, acht Nachkommen und mixed_global. '
        'NSGA-II verwendet native Pareto-Auswahl mit unzugeordneter Nachfrage, Konfliktanzahl und Überlappungsdauer als Suchzielen. '
        'Nur die Konflikte zwischen Kabinen werden für die Potenzialbewertung ignoriert. '
        'Die Spalte „bedient“ enthält ausschließlich unabhängig gültige Fahrpläne.', '',
        'Die GA-Basis stammt aus dem zuvor eingefrorenen Vergleich. Sie bewertet kollidierende Vorschläge ohne Passagier-IP. '
        'Das ist ein Vergleich der vollständigen Verfahren einschließlich Bewertungsaufwand, keine isolierte Selektionsablation.', '',
        '| Engine | Run | Bedient | Bewertungen | Gültig | Letzte Incumbent-Verbesserung (s) | Letzte Verbesserung je K (s) |',
        '|---|---|---:|---:|---:|---:|---:|']
    for engine, data in [('GA', old), ('NSGA-II', rows)]:
        for r in data:
            lines.append(f"| {engine} | {r['run']} | {r.get('served')} | {r.get('evaluations')} | {r.get('feasible')} | {r.get('last_incumbent_improvement_seconds')} | {r.get('last_per_k_improvement_seconds')} |")
    lines += ['', '## Verlauf statt alleiniger Endwert', '',
        'summary.json enthält Schnitte bei 30/60/120/180/300 Sekunden: gültige Bedienung, beste gültige Musterkombination, '
        'größtes gültiges gemischtes K, separat das relaxierte Potenzial und vollständige überlebende Populationen. '
        'events.jsonl enthält Musterfolgen, Dispatchzeiten, Konflikte und Populationsentwicklung. '
        'best.json wird bei jeder gültigen Verbesserung sofort gesichert. Potenzialwerte sind keine Fahrplanerfolge und keine globalen Bounds.', '',
        'Zeitgleiche Änderungen von Musterfamilien lassen sich aus den Populationsschnitten prüfen. '
        'Der letzte Fortschritt je K kann stattfinden, obwohl der globale Incumbent bereits plateauiert. '
        'Eine kleinere Konfliktzahl allein beweist keine Nähe zu einem ausführbaren Fahrplan.', '',
        '## Ausführungsstatus', '',
        f"Abgeschlossene NSGA-II-Läufe: {sum(r['status']=='complete' for r in rows)}/6. "
        "Ausstehende Läufe sind keine negativen Ergebnisse.",
    ]
    (out / 'report.md').write_text('\n'.join(lines) + '\n')


def main():
    p = argparse.ArgumentParser()
    p.add_argument('--baseline-campaign', type=Path, required=True)
    p.add_argument('--output', type=Path, required=True)
    p.add_argument('--seconds', type=float, default=300)
    p.add_argument('--wait-timeout', type=float, default=3600)
    a = p.parse_args()
    if a.seconds <= 3 or a.wait_timeout < 0:
        p.error('seconds must exceed 3 and wait-timeout must be nonnegative')
    baseline = a.baseline_campaign.resolve()
    out = a.output.resolve()
    out.mkdir(parents=True, exist_ok=False)
    frozen = out / 'sources'
    (frozen / 'benchmarks').mkdir(parents=True)
    shutil.copytree(ROOT / 'src', frozen / 'src', ignore=shutil.ignore_patterns('__pycache__', '*.pyc'))
    runner = frozen / 'benchmarks/run_reservoir_line_evolution.py'
    shutil.copy2(ROOT / 'benchmarks/run_reservoir_line_evolution.py', runner)
    shutil.copy2(__file__, frozen / 'benchmarks' / Path(__file__).name)
    for name in ('reference.json', 'all_stop.json'):
        shutil.copy2(baseline / name, out / name)
    for name in ('pyproject.toml', 'uv.lock'):
        shutil.copy2(ROOT / name, frozen / name)
    manifest = {'queued_unix': time.time(), 'baseline': str(baseline), 'state': 'waiting_for_baseline', 'runs': [],
        'source_hashes': {str(f.relative_to(frozen)): hashlib.sha256(f.read_bytes()).hexdigest()
                         for f in frozen.rglob('*') if f.is_file()},
        'single_run_wall_limit_seconds': a.seconds, 'process_tree_memory_limit_gib': 32}
    atomic_json(out / 'campaign.json', manifest)
    while True:
        previous = json.loads((baseline / 'campaign.json').read_text())
        if previous.get('finished_unix') is not None:
            break
        if time.time() - manifest['queued_unix'] > a.wait_timeout:
            manifest['state'] = 'WAIT_TIMEOUT'; atomic_json(out / 'campaign.json', manifest); return
        time.sleep(1)
    # Deadline starts after the existing solver campaign ends. Waiting does not
    # consume a search budget and is explicitly logged above.
    started = time.time(); deadline = started + 6 * a.seconds + 60
    manifest.update(started_unix=started, deadline_unix=deadline, state='running')
    atomic_json(out / 'campaign.json', manifest)
    env = dict(os.environ); env['PYTHONPATH'] = str(frozen / 'src')
    for seed in (0, 1, 2):
        for seeded in ((True, False) if seed % 2 == 0 else (False, True)):
            if time.time() + a.seconds > deadline:
                manifest['state'] = 'GLOBAL_DEADLINE'; break
            name = f's{seed}_' + ('seeded' if seeded else 'unseeded')
            d = out / name; d.mkdir()
            command = [sys.executable, str(runner), '--_worker', '--reference-checkpoint', str(out / 'reference.json'),
                '--output', str(d), '--engine', 'nsga2', '--operator-profile', 'mixed_global',
                '--dispatch-window-end', '300', '--time-limit', str(a.seconds), '--workers', '12',
                '--memory-limit-gib', '32', '--seed', str(seed), '--passenger-time-limit', '2',
                '--population-size', '32', '--offspring-size', '8']
            command += ['--initial-checkpoint', str(out / 'all_stop.json')] if seeded else ['--no-reference-initialization']
            entry = {'name': name, 'command': command, 'status': 'running'}; manifest['runs'].append(entry)
            atomic_json(out / 'campaign.json', manifest)
            entry['supervisor'] = supervise(command, d, seconds=a.seconds, memory_bytes=32 * 1024**3,
                global_deadline=deadline, system_memory_pressure_seconds=30, env=env)
            entry['status'] = 'complete' if (d / 'result.json').exists() else 'incomplete'
            atomic_json(out / 'campaign.json', manifest); summarize(out, baseline)
    manifest['finished_unix'] = time.time()
    manifest['state'] = 'finished'
    manifest['complete'] = len(manifest['runs']) == 6 and all(r['status'] == 'complete' for r in manifest['runs'])
    atomic_json(out / 'campaign.json', manifest); summarize(out, baseline)


if __name__ == '__main__':
    main()
