"""Inventory the six raw campaigns; no raw solver evidence is modified."""
import argparse
import json
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))
from ropeway_skip_stop_optimization.submission import CAMPAIGNS, read, resolve_recorded, selected_journey, sha256


def freeze_replay_checks(root, audit_path):
    paths={}
    for c in CAMPAIGNS:
     state=json.loads((root/c/'campaign.json').read_text())
     for row in state.get('jobs',state.get('trials',[])):
      rid=row.get('id',row.get('trial_id'))
      for n,a in enumerate(row.get('attempts',[])):
       if 'directory' not in a: continue
       paths[a.get('run_campaign_id') or f'{c}__{rid}__a{n+1}']=resolve_recorded(root/c,a['directory'])/'result.json'
     for f,r in state.get('reference_runs',{}).items():
      if r.get('attempts'):
       for a in r['attempts']:
        paths[r['run_campaign_id']]=resolve_recorded(root/c,a['directory'])/'result.json'
      else: paths[f'{c}__reference__{f}']=root/c/'references'/f/'result.json'
    records=[]
    for r in json.loads(audit_path.read_text()):
     p=paths[r['id']]
     records.append({k:v for k,v in r.items() if k!='source_stamp'}|dict(result_file=str(p.relative_to(root)),sha256=sha256(p)))
    checks=dict(checker_contract='Finite resource entry through operation horizon; full clearance; continuous spacing on visible horizon',
     checker_source_sha256={str(p.relative_to(ROOT)):sha256(p) for p in (ROOT/'frontend/src/safety').glob('*.ts') if not p.name.endswith('.test.ts')},
     records=records)
    (root/'replay_checks.json').write_text(json.dumps(checks,indent=2)+'\n')

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--results-root', type=Path, default=ROOT / 'results')
    parser.add_argument('--replay-audit', type=Path, help='Freeze a freshly generated frontend replay-audit.json')
    args = parser.parse_args()
    root = args.results_root.resolve()
    if args.replay_audit:
        freeze_replay_checks(root, args.replay_audit)
    services = []
    checks = read(root/'oip_service_contract_checks.json')
    checked = {r['trial_id']: r for r in checks['records']}
    for campaign in CAMPAIGNS[2:4]:
        for trial in read(root/campaign/'campaign.json')['trials']:
            path = resolve_recorded(root/campaign, trial['attempts'][-1]['directory'])/'result.json'
            validation = checked.get(trial['trial_id'])
            if validation and (not validation['valid'] or sha256(path) != validation['sha256']):
                raise ValueError(f'Service contract check invalid: {trial["trial_id"]}')
            services.append(dict(id=trial['trial_id'], campaign=campaign,
                result_file=str(path.relative_to(root)), served=trial['served'],
                has_incumbent=trial['served'] is not None,
                passenger_contract='same_cabin_later_destination_stop_allowed',
                additional_contract_check=validation))
    files = []
    paths = [root/'README.md', root/'oip_service_contract_checks.json', root/'replay_checks.json']
    for campaign in CAMPAIGNS:
        paths.extend(p for p in (root/campaign).rglob('*') if p.is_file())
    for path in sorted(paths):
        if path.is_symlink():
            raise ValueError(f'Symlinks are not submission evidence: {path}')
        files.append(dict(path=str(path.relative_to(root)), bytes=path.stat().st_size, sha256=sha256(path)))
    # Audit historical file references in campaign metadata. Recorded commands and
    # source-code/runtime paths are provenance, not data dependencies.
    inventory = {r['path'] for r in files}
    refs = set()
    def walk(value):
        if isinstance(value, dict):
            for k, v in value.items(): walk(k); walk(v)
        elif isinstance(value, list):
            for v in value: walk(v)
        elif isinstance(value, str) and value.startswith('/') and '/results/' in value and '\n' not in value:
            rel = value.split('/results/', 1)[1]
            candidate = root/rel
            if candidate.is_file():
                if rel not in inventory: raise ValueError(f'External result dependency: {rel}')
                refs.add(rel)
    historical = {}
    for campaign in CAMPAIGNS:
        state = read(root/campaign/'campaign.json')
        walk(state)
        historical[campaign] = {k: state[k] for k in ('identity','configuration','code_revisions','continuation_source_digests') if k in state}
    code = subprocess.check_output(['git','rev-parse','HEAD'], cwd=ROOT, text=True).strip()
    manifest = dict(schema=1, code_commit=code, campaigns=list(CAMPAIGNS),
        journey_selection=selected_journey(root), service_selection=services,
        historical_provenance=historical, checked_data_references=sorted(refs),
        replay_checks=read(root/'replay_checks.json')['records'], files=files)
    (root/'submission_manifest.json').write_text(json.dumps(manifest, indent=2)+'\n')
    # Feed this list to zip from the repository root; no recursive results/ glob.
    entries = ['results/submission_manifest.json', 'results/submission_files.txt'] + ['results/'+r['path'] for r in files]
    (root/'submission_files.txt').write_text('\n'.join(entries)+'\n')
    print(f"Inventoried {len(files)} files ({sum(r['bytes'] for r in files)/1024**3:.2f} GiB).", flush=True)

if __name__ == '__main__': main()
