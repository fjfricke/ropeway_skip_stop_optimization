"""Portable, solver-free inventory and frozen thesis result selection."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

CAMPAIGNS = (
    'thesis_journey_geometric_20260919',
    'thesis_journey_all_stop_mip_start_20260920',
    'oip_fixed_mixes_geometric_120_20260918',
    'oip_fixed_mixes_geometric_k50_20260919',
    'oip_exact_phase_short_k62_20260918',
    'oip_k50_phase_references_20260919',
)


def read(path: Path):
    return json.loads(path.read_text())


def sha256(path: Path) -> str:
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def contained(root: Path, relative: str) -> Path:
    path = Path(relative)
    if path.is_absolute() or '..' in path.parts:
        raise ValueError(f'Expected a relative package path: {relative}')
    target = root / path
    if not target.resolve().is_relative_to(root.resolve()):
        raise ValueError(f'Path escapes package: {relative}')
    return target


def resolve_recorded(source: Path, recorded: str) -> Path:
    """Always rebase historical paths, even if the original host path exists."""
    path = Path(recorded)
    if path.is_absolute():
        parts = path.parts
        if source.name in parts:
            return contained(source, str(Path(*parts[parts.index(source.name) + 1:])))
        if source.parent.name == 'results' and 'results' in parts:
            return contained(source.parent, str(Path(*parts[parts.index('results') + 1:])))
        # References to a sibling campaign (supplementary all-stop evaluations).
        for name in CAMPAIGNS:
            if name in parts:
                return contained(source.parent, str(Path(*parts[parts.index(name):])))
        raise ValueError(f'Cannot relocate recorded path: {recorded}')
    return contained(source, recorded)


def selected_journey(results: Path):
    original = read(results / CAMPAIGNS[0] / 'campaign.json')
    replacement = read(results / CAMPAIGNS[1] / 'campaign.json')
    if original['status'] != 'complete' or replacement['status'] != 'complete':
        raise ValueError('Journey campaigns must be complete')
    replacements = {j['id']: j for j in replacement['jobs']}
    if len(replacements) != 22:
        raise ValueError('Expected 22 frozen Journey replacement cases')
    rows = []
    for job in original['jobs']:
        if job['kind'] not in ('relative', 'constant') or job['k'] not in (10, 20, 30):
            continue
        chosen = replacements.get(job['id'], job)
        if chosen['status'] != 'complete' or chosen['demand'] != job['demand']:
            raise ValueError(f'Invalid replacement: {job["id"]}')
        campaign = CAMPAIGNS[int(job['id'] in replacements)]
        path = resolve_recorded(results / campaign, chosen['attempts'][-1]['directory']) / 'result.json'
        rows.append(dict(id=job['id'], campaign=campaign,
                         result_file=str(path.relative_to(results)),
                         replacement=job['id'] in replacements))
    if len(rows) != 64:
        raise ValueError('Expected 64 selected Journey comparisons')
    return rows


def verify_manifest(path: Path):
    manifest = read(path)
    if manifest.get('schema') != 1 or tuple(manifest.get('campaigns', [])) != CAMPAIGNS:
        raise ValueError('Unsupported submission manifest')
    root = path.resolve().parent
    seen = set()
    for item in manifest['files']:
        name = item['path']
        if name in seen:
            raise ValueError(f'Duplicate manifest entry: {name}')
        seen.add(name)
        target = contained(root, name)
        if not target.is_file():
            raise ValueError(f'Missing submission file: {name}')
        if target.stat().st_size != item['bytes'] or sha256(target) != item['sha256']:
            raise ValueError(f'Submission checksum mismatch: {name}')
    # No extra campaign files may silently influence a recursive exporter.
    actual = {str(p.relative_to(root)) for c in CAMPAIGNS for p in (root/c).rglob('*') if p.is_file()}
    if actual - seen:
        raise ValueError(f'Unlisted campaign files: {sorted(actual - seen)[:5]}')
    if 'replay_checks' in manifest:
        if manifest['replay_checks'] != read(root/'replay_checks.json')['records']:
            raise ValueError('Replay checks differ from packaged evidence')
        hashes = {f['path']: f['sha256'] for f in manifest['files']}
        for check in manifest['replay_checks']:
            if hashes.get(check['result_file']) != check['sha256']:
                raise ValueError(f'Replay source differs: {check["id"]}')
    expected = selected_journey(root)
    if manifest['journey_selection'] != expected:
        raise ValueError('Journey selection differs from the frozen campaigns')
    for row in expected + manifest['service_selection']:
        if row['result_file'] not in seen:
            raise ValueError(f'Selected result missing from inventory: {row["result_file"]}')
    return manifest
