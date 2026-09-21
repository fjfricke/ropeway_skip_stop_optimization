"""Replace one reference-cutoff observation with an uncapped-reference attempt.

The ordinary wall/memory limits remain. Original attempt artifacts are retained.
"""
import argparse
import copy
import fcntl
import json
from pathlib import Path
import sys
import threading
from types import SimpleNamespace

from run_oip_fixed_mix_campaign import (
    ROOT, FRONTEND_ROOT, _run_one, _expose_live_run, _mirror_live_run,
    _publish_run, save, now, recover_validated_incumbent, atomic_json,
)
from ropeway_skip_stop_optimization.benchmarking.thesis_contract import source_digest, solver_versions


def replacement_command(command, directory, *, repeat_unknown=False):
    command = list(command)
    if '--stop-if-cannot-beat-reference' not in command and not repeat_unknown:
        raise ValueError('Source attempt did not use a reference cutoff')
    if '--stop-if-cannot-beat-reference' in command:
        command.remove('--stop-if-cannot-beat-reference')
    command[command.index('--output') + 1] = str(directory)
    command[0] = sys.executable
    return command


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--campaign', type=Path, required=True)
    parser.add_argument('--trial', required=True)
    parser.add_argument('--repeat-unknown', action='store_true',
                        help='Repeat one completed UNKNOWN observation without a reference cutoff')
    args = parser.parse_args()
    output = args.campaign.resolve()
    with (output / '.replacement.lock').open('w') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        manifest = json.loads((output / 'campaign.json').read_text())
        if manifest['status'] == 'running':
            raise ValueError('Campaign is already running')
        trial = next(t for t in manifest['trials'] if t['trial_id'] == args.trial)
        if args.repeat_unknown:
            if trial.get('solver_status') != 'UNKNOWN' or trial.get('status') != 'complete' or trial.get('served') is not None:
                raise ValueError('Only a completed UNKNOWN without an incumbent may be repeated')
        elif trial.get('termination_reason') != 'cannot_beat_reference':
            raise ValueError('Only a reference-aborted observation may be replaced by this command')
        previous = copy.deepcopy(trial)
        number = len(trial['attempts']) + 1
        directory = output / 'trials' / args.trial / f'attempt_{number}'
        command = replacement_command(trial['attempts'][-1]['command'], directory, repeat_unknown=args.repeat_unknown)
        seconds = float(command[command.index('--time-limit') + 1])
        memory = float(command[command.index('--memory-limit-gib') + 1])
        if seconds > 300 or memory > 32:
            raise ValueError('Replacement must retain the five-minute / 32 GiB study limits')
        directory.mkdir(parents=True, exist_ok=False)
        atomic_json(directory / 'previous_observation.json', previous)
        atomic_json(directory / 'campaign_before_replacement.json', manifest)
        run_id = f'{output.name}__{args.trial}__a{number}'
        attempt = dict(attempt=number, status='running', command=command,
                       directory=str(directory.relative_to(output)), run_campaign_id=run_id,
                       started_at_utc=now(), source_digest=source_digest(ROOT), solver_versions=solver_versions(),
                       reason=('User-requested repetition of UNKNOWN; same wall budget, no reference cutoff' if args.repeat_unknown
                               else 'User-requested repetition without reference cutoff; same wall budget'),
                       replaces_run_campaign_id=trial['run_campaign_id'], stop_if_cannot_beat_reference=False)
        trial['attempts'].append(attempt)
        for key in ('served','unserved','journey_time_seconds','relative_gap','best_bound','type_counts',
                    'solver_status','build_seconds','solve_seconds','termination_reason','reference_served_cutoff'):
            trial[key] = None
        trial.update(status='running', run_campaign_id=run_id, stop_if_cannot_beat_reference=False)
        manifest.update(status='running')
        manifest.pop('finished_at_utc', None)
        manifest.setdefault('replacements', []).append({k:attempt[k] for k in
            ('reason','started_at_utc','run_campaign_id','replaces_run_campaign_id','source_digest','solver_versions')})
        _expose_live_run(FRONTEND_ROOT, directory, run_id)
        save(output, FRONTEND_ROOT, manifest)
        stop = threading.Event()
        mirror = threading.Thread(target=_mirror_live_run, args=(directory, FRONTEND_ROOT / run_id, stop), daemon=True)
        mirror.start()
        try:
            guard = _run_one(command, directory, seconds, SimpleNamespace(memory_limit_gib=memory))
        finally:
            stop.set()
            mirror.join(timeout=5)
        attempt.update(finished_at_utc=now(), supervisor=guard)
        result_file = directory / 'result.json'
        recovered = None
        if guard.get('exit_code') != 0 or not result_file.exists():
            recovered = recover_validated_incumbent(directory, guard.get('supervisor_reason') or 'PROCESS_INTERRUPTED',
                expected_domain=trial['domain_fingerprint'], expected_type_counts=trial['fixed_type_counts'])
        if (guard.get('exit_code') == 0 or recovered is not None) and result_file.exists():
            result = json.loads(result_file.read_text())
            for target, key in dict(solver_status='solver_status', served='served_passengers', unserved='unserved_passengers',
                journey_time_seconds='journey_time_seconds', relative_gap='gap', best_bound='best_bound', type_counts='type_counts',
                termination_reason='termination_reason', reference_served_cutoff='reference_served_cutoff',
                reduction_stats='reduction_stats', build_seconds='build_seconds', solve_seconds='runtime_seconds').items():
                trial[target] = result.get(key)
            trial['status'] = attempt['status'] = 'complete'
            attempt['recovered_checkpoint'] = recovered is not None
        else:
            trial['status'] = attempt['status'] = 'interrupted'
            trial['termination_reason'] = guard.get('supervisor_reason') or 'PROCESS_INTERRUPTED'
        _publish_run(FRONTEND_ROOT, directory, run_id)
        manifest.update(status='complete' if all(t['status']=='complete' for t in manifest['trials']) else 'partial', finished_at_utc=now())
        save(output, FRONTEND_ROOT, manifest)
        print(json.dumps({k:trial.get(k) for k in ('trial_id','solver_status','served','best_bound','termination_reason')}), flush=True)


if __name__ == '__main__':
    main()
