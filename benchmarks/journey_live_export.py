"""Publish Journey campaign state and existing thesis detail/replay views."""
from datetime import UTC, datetime
import math
from pathlib import Path
import time

try:
    from benchmarks.export_thesis_frontend import export, _read, _slug
    from benchmarks.thesis_detail_export import read_events
except ImportError:
    from export_thesis_frontend import export, _read, _slug
    from thesis_detail_export import read_events
from ropeway_skip_stop_optimization.benchmarking.thesis_contract import THESIS_CONTRACT_ID
from ropeway_skip_stop_optimization.optimization.ddd.cp_sat_certificate import atomic_json


def finite(value):
    return isinstance(value, (int, float)) and math.isfinite(value) and abs(value) < 1e50


def publish(output: Path, state: dict, frontend: Path) -> None:
    atlas = export((output,), frontend / "thesis", preserve_existing=True)
    summaries = {r['id']: r for r in atlas['runs']}
    rows = []
    for job in state['jobs']:
        directory = Path(job['attempts'][-1]['directory']) if job['attempts'] else None
        summary = summaries.get(_slug(directory), {}) if directory else {}
        # Capacity probes carry large passenger witnesses but no Journey bounds.
        events = read_events(directory / 'events.jsonl') if directory and job['kind'] != 'reference' else []
        native = bound = None
        for event in events:
            if finite(event.get('solver_incumbent')): native = event['solver_incumbent']
            if finite(event.get('certified_lower_bound')): bound = event['certified_lower_bound']
        if finite(summary.get('globalLowerBound')): bound = summary['globalLowerBound']
        validated = summary.get('journeyTime') if summary.get('validated') else None
        upper = validated if finite(validated) else native
        gap = max(0, upper - bound) / abs(upper) if finite(upper) and finite(bound) and upper != 0 else None
        result = _read(directory / 'result.json') if directory else None
        run = (result or {}).get('run', {})
        rows.append(dict(id=job['id'], family=job['family'], k=job['k'], kind=job['kind'],
                         mode=job['mode'], percent=job.get('percent'), demand=job.get('demand'),
                         status=job['status'], reason=job.get('reason'),
                         native_incumbent=native, validated_objective=validated, lower_bound=bound, gap=gap,
                         capacity=run.get('proven_feasible_demand'), capacity_proven=run.get('capacity_proven', False),
                         detail_url=f"/thesis?run={_slug(directory)}" if summary else None))
    campaign_id = state['campaign_id']
    snapshot = dict(schema_version=1, campaign_id=campaign_id,
        label="Journey Time · fixed starts · geometric headways", campaign_kind="journey_comparison",
        contract_id=THESIS_CONTRACT_ID, study_membership="current_thesis", status=state['status'],
        objective="journey_time_full_service", sequence=time.time_ns() // 1000,
        updated_at_utc=datetime.now(UTC).isoformat(),
        completed_trial_count=sum(j['status']=='complete' for j in state['jobs']),
        trial_count=sum(j["status"] != "deferred" for j in state["jobs"]), trials=[], events=[], journey_jobs=rows,
        constant_gates=state.get('constant_gates', {}), live_error=None)
    atomic_json(frontend / 'optimization' / campaign_id / 'snapshot.json', snapshot)
    index_path = frontend / 'optimization/index.json'
    index = _read(index_path) or dict(schema_version=1, campaigns=[])
    summary = {k:v for k,v in snapshot.items() if k not in {'journey_jobs','trials','events','constant_gates'}}
    index['campaigns'] = [c for c in index['campaigns'] if c['campaign_id'] != campaign_id] + [summary]
    atomic_json(index_path, index)


def main():
    """Refresh display independently without restarting a running solver."""
    import argparse
    import json
    import os
    import traceback

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--campaign-dir", type=Path, required=True)
    parser.add_argument("--frontend-root", type=Path, required=True)
    parser.add_argument("--watch-pid", type=int)
    args = parser.parse_args()
    while True:
        alive = True
        if args.watch_pid is not None:
            try:
                os.kill(args.watch_pid, 0)
            except ProcessLookupError:
                alive = False
        state = json.loads((args.campaign_dir / "campaign.json").read_text())
        try:
            publish(args.campaign_dir, state, args.frontend_root)
        except Exception:
            traceback.print_exc()
            if args.watch_pid is None or not alive:
                raise
        if args.watch_pid is None or not alive or state["status"] in {"complete", "partial", "interrupted", "failed"}:
            break
        time.sleep(5)


if __name__ == "__main__":
    main()
