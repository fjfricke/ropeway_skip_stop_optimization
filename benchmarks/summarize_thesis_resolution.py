"""Conservative release-resolution decisions from matching 15/5-second runs."""
import argparse
import hashlib
import json
from pathlib import Path
from ropeway_skip_stop_optimization.optimization.ddd.cp_sat_certificate import atomic_json


def relative_interval_difference(coarse, fine):
    if None in (*coarse, *fine) or min(*coarse, *fine) <= 0:
        return None
    return max(abs(a - b) / b for a in coarse for b in fine)


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--results-root', type=Path, action='append', required=True)
    p.add_argument('--output', type=Path, required=True)
    args = p.parse_args()
    cases = []
    for root in args.results_root:
        for path in sorted(root.rglob('result.json')):
            cp = path.parent / 'case_spec.json'
            if not cp.exists():
                continue
            result, spec = json.loads(path.read_text()), json.loads(cp.read_text())
            ap = path.parent / 'arguments.json'
            arguments = json.loads(ap.read_text()) if ap.exists() else {}
            if spec.get('geometry') == 'g500' and spec.get('demand_profile') == 'p0':
                cases.append((path, spec, result, arguments))
    evidence = {}
    for topology in ('t5r', 't6r'):
        for family in ('f0', 'f2', 'f3', 'f4'):
            for objective in ('unserved', 'journey_time'):
                if objective == 'journey_time' and topology != 't5r':
                    continue
                key = f"{'capacity' if objective == 'unserved' else 'journey'}_{topology}_{family}_g500_p0"
                relevant = [c for c in cases if c[1]['topology'] == topology and c[1]['demand_family'] == family and c[1]['objective'] == objective]
                comparisons = []
                if objective == 'unserved':
                    intervals, sources = {}, []
                    for resolution in (15, 5):
                        rows = [(p, r['run']) for p, s, r, a in relevant if s.get('release_resolution_seconds') == resolution and r.get('method') == 'all_stop_phase']
                        lower = max((r.get('proven_feasible_demand') or 0 for _, r in rows), default=0)
                        upper = min((r['proven_infeasible_demand'] - 1 for _, r in rows if r.get('proven_infeasible_demand') is not None), default=None)
                        intervals[resolution] = (lower, upper)
                        sources += [str(p) for p, _ in rows]
                    difference = relative_interval_difference(intervals[15], intervals[5])
                    comparisons.append(dict(mode='capacity', coarse=intervals[15], fine=intervals[5], maximumRelativeDifference=difference, sources=sources))
                else:
                    for mode in ('all_stop', 'skip_stop'):
                        pairs = []
                        rows = [(p, s, r, a) for p, s, r, a in relevant if r.get('method') == 'labelled_arc_flow'
                                and r.get('run', {}).get('operating_mode') == mode and r['run'].get('independent_validation_status') == 'feasible']
                        for p15, s15, r15, a15 in rows:
                            if s15.get('release_resolution_seconds') != 15 or a15.get('cabins') != 10:
                                continue
                            for p5, s5, r5, a5 in rows:
                                if s5 != {**s15, 'release_resolution_seconds': 5} or a5.get('cabins') != 10:
                                    continue
                                coarse = (r15['run'].get('certified_lower_bound'), r15['run'].get('validated_upper_bound'))
                                fine = (r5['run'].get('certified_lower_bound'), r5['run'].get('validated_upper_bound'))
                                diff = relative_interval_difference(coarse, fine)
                                pairs.append(dict(mode=mode, demand=s15['demand_total'], k=10, coarse=coarse, fine=fine,
                                                  maximumRelativeDifference=diff, sources=[str(p15), str(p5)]))
                        # All paired loads must pass, not merely the most favourable one.
                        comparisons.extend(pairs or [dict(mode=mode, maximumRelativeDifference=None, sources=[])])
                diffs = [c['maximumRelativeDifference'] for c in comparisons]
                status = 'passed' if diffs and all(d is not None and d <= .01 for d in diffs) else 'unresolved'
                if any(c.get('coarse') and c.get('fine') and None not in (*c['coarse'], *c['fine'])
                       and (c['coarse'][0] > 1.01 * c['fine'][1] or c['coarse'][1] < .99 * c['fine'][0]) for c in comparisons):
                    status = 'failed'
                evidence[key] = dict(status=status, testedResolutionSeconds=[15, 5], comparisons=comparisons,
                                     scope='K10 low-demand calibration only' if objective == 'journey_time' else 'regular saturated All-Stop capacity')
    hashes = {p: hashlib.sha256(Path(p).read_bytes()).hexdigest() for item in evidence.values() for c in item['comparisons'] for p in c['sources']}
    evidence['_source_sha256'] = hashes
    atomic_json(args.output, evidence)
    print(json.dumps({k: v['status'] for k, v in evidence.items() if not k.startswith('_')}, indent=2))


if __name__ == '__main__':
    main()
