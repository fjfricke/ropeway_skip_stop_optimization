"""Dashboard-only replay of physical conflicts; never invoke a timing solver."""
import argparse
import json
import time
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
from ropeway_skip_stop_optimization.optimization.ddd.cp_sat_certificate import atomic_json


def point(elapsed, values, **extra):
    return dict(elapsed_seconds=elapsed, mean=sum(values)/len(values) if values else None,
                minimum=min(values) if values else None, maximum=max(values) if values else None,
                complete=len(values), population=extra.pop('population', len(values)),
                construction_failed=extra.pop('construction_failed', 0), **extra)


def population_point(event):
    members = event['members']
    counts = [m['conflicts'] for m in members if m.get('decoder_status') in
              ('NO_WAIT_VALID', 'WAITING_CANDIDATE')]
    return point(event['elapsed_seconds'], counts, population=len(members),
                 construction_failed=sum(m.get('decoder_status') == 'CONSTRUCTION_FAILED' for m in members))


class Replay:
    def __init__(self, source):
        from ropeway_skip_stop_optimization.optimization.ddd.reservoir_hybrid.domain import load_reference
        from ropeway_skip_stop_optimization.optimization.ddd.reservoir_boundary import apply_boundary_arguments
        from ropeway_skip_stop_optimization.optimization.ddd.reservoir_lines import (
            ReservoirLineConfig, ReservoirLineVariant, ReservoirLinePreparation,
            ReservoirLineFormulation, ReservoirLineMode, ReservoirLineCatalogProfile, prepare_line_problem)
        from ropeway_skip_stop_optimization.optimization.ddd.reservoir_lines.evolution import GenomeFactory
        args = SimpleNamespace(**json.loads(Path(source).with_name('arguments.json').read_text()))
        domain, _ = load_reference(Path(args.reference_checkpoint))
        p = apply_boundary_arguments(domain.problem, args)
        if args.earliest_wait_seconds is not None:
            p = replace(p, waiting_policy=replace(p.waiting_policy, earliest_wait_time_seconds=args.earliest_wait_seconds))
        self.problem = p
        self.prepared = prepare_line_problem(p, ReservoirLineConfig(
            dispatch_window_end_seconds=args.dispatch_window_end,
            passenger_service_start_seconds=args.dispatch_window_end,
            maximum_cabins=args.max_cabins or p.available_fleet_count,
            variant=ReservoirLineVariant.INTERVALS, preparation=ReservoirLinePreparation.ENCODING_SPECIFIC,
            formulation=ReservoirLineFormulation.SHARED_ROUNDS, mode=ReservoirLineMode.EXACT_SERVICE,
            catalog_profile=ReservoirLineCatalogProfile.RELEVANT))
        recorded = json.loads(Path(source).with_name('prepared.json').read_text())
        assert p.fingerprint == recorded['problem_fingerprint'], 'Replay domain mismatch'
        self.factory = GenomeFactory(p, self.prepared)

    def conflicts(self, event):
        from ropeway_skip_stop_optimization.optimization.ddd.reservoir_lines.evolution import decode_no_wait
        genome = self.factory.from_dispatches(event['pattern_ids'], event['repair']['dispatch_ticks'])
        value = decode_no_wait(self.problem, self.prepared, genome)
        if value.reason is not None:
            raise ValueError(value.reason)
        return len(value.conflicts)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--source', action='append', required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--manifest', type=Path, required=True)
    args = parser.parse_args()
    sources = dict(s.split('=', 1) for s in args.source)
    offsets = dict.fromkeys(sources, 0)
    data = {metric: {key: [] for key in sources} for metric in ('runs', 'infeasible', 'missing')}
    replays, errors = {}, {}
    done_passes = 0
    while True:
        caught_up = True
        for key, source in sources.items():
            path = Path(source)
            if not path.exists():
                continue
            slice_end = time.monotonic() + .4
            with path.open() as stream:
                stream.seek(offsets[key])
                while True:
                    before = stream.tell()
                    line = stream.readline()
                    if not line or not line.endswith('\n'):
                        offsets[key] = before
                        break
                    event = json.loads(line)
                    if event['kind'] == 'population':
                        data['runs'][key].append(population_point(event))
                        failed = [m['structural_violation'] for m in event['members']
                                  if m.get('decoder_status') == 'CONSTRUCTION_FAILED']
                        data['missing'][key].append(point(event['elapsed_seconds'], failed))
                    if event['kind'] == 'unrepaired_candidate':
                        data['infeasible'][key].append(point(event['elapsed_seconds'], [event['conflicts']],
                                                           repair_status='NOT_ATTEMPTED'))
                    if event['kind'] == 'waiting_repair' and event['served'] is None:
                        try:
                            if key not in replays:
                                replays[key] = Replay(source)
                            count = replays[key].conflicts(event)
                            data['infeasible'][key].append(point(event['elapsed_seconds'], [count],
                                                               repair_status=event['repair']['status']))
                        except (ValueError, AssertionError) as error:
                            errors[key] = str(error)
                    offsets[key] = stream.tell()
                    if time.monotonic() >= slice_end:
                        caught_up = False
                        break
        atomic_json(args.output, {**data, 'updated_unix': time.time(), 'errors': errors,
                                  'scope': 'infeasible_before_repair_and_population_after_repair',
                                  'replay_caught_up': caught_up})
        manifest = json.loads(args.manifest.read_text())
        done_passes = done_passes+1 if manifest.get('status') in ('complete', 'failed') and caught_up else 0
        if done_passes >= 2:
            break
        time.sleep(3 if caught_up else .5)


if __name__ == '__main__':
    main()
