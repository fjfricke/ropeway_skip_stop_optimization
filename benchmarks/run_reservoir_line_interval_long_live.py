"""Two sequential 30-minute R2 interval-decoder runs with live snapshots."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import subprocess
import sys
import time

from ropeway_skip_stop_optimization.optimization.ddd.cp_sat_certificate import atomic_json

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--reference', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--live-dir', type=Path, required=True)
    args = parser.parse_args()
    out = args.output.resolve(); out.mkdir(parents=True, exist_ok=False)
    live = args.live_dir.resolve(); live.mkdir(parents=True, exist_ok=True)
    manifest = {
        'schema': 'reservoir_line_evolution_live_manifest_v1',
        'label': 'R2 · 30-minute interval search', 'status': 'running',
        'started_unix': time.time(),
        'runs': [
            {'id':'intervals', 'label':'Interval decoder · No-Wait',
             'status':'queued', 'snapshot':'/generated/evolution-live/intervals.json'},
            {'id':'intervals_waiting', 'label':'Interval decoder · Waiting fallback',
             'status':'queued', 'snapshot':'/generated/evolution-live/intervals_waiting.json'},
        ],
    }
    atomic_json(live/'manifest.json', manifest)
    atomic_json(out/'campaign.json', manifest)
    with (out/'campaign.log').open('w') as log:
        for index, (name, repair) in enumerate((('intervals',0),('intervals_waiting',5))):
            manifest['runs'][index]['status'] = 'running'
            atomic_json(live/'manifest.json', manifest); atomic_json(out/'campaign.json', manifest)
            command = [sys.executable, str(ROOT/'benchmarks/run_reservoir_line_evolution.py'),
                '--reference-checkpoint', str(args.reference.resolve()), '--output', str(out/name),
                '--engine','ga','--operator-profile','mixed_global','--dispatch-window-end','300',
                '--time-limit','1800','--workers','12','--memory-limit-gib','32','--seed','0',
                '--passenger-time-limit','2','--no-reference-initialization',
                '--dispatch-decoder','intervals','--waiting-repair-seconds',str(repair),
                '--earliest-wait-seconds','0','--live-snapshot',str(live/f'{name}.json'),
                '--live-label',manifest['runs'][index]['label']]
            manifest['runs'][index]['command'] = command
            atomic_json(out/'campaign.json', manifest)
            result = subprocess.run(command, stdout=log, stderr=subprocess.STDOUT)
            manifest['runs'][index]['status'] = 'complete' if result.returncode == 0 else 'failed'
            manifest['runs'][index]['exit_code'] = result.returncode
            atomic_json(live/'manifest.json', manifest); atomic_json(out/'campaign.json', manifest)
            if result.returncode:
                break
    manifest['status'] = ('complete' if all(r['status']=='complete' for r in manifest['runs'])
                          else 'failed')
    manifest['finished_unix'] = time.time()
    atomic_json(live/'manifest.json', manifest); atomic_json(out/'campaign.json', manifest)


if __name__ == '__main__':
    main()
