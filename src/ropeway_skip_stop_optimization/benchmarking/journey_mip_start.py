"""Solver-free import of a matching All-Stop movement and integer assignment."""
import json
import math
from pathlib import Path

from .ddd_fixed_k_arc_flow import _load_ddd_fixed_k_arc_flow_result_seed
from ..optimization.ddd.fixed_k_certificate import DddFixedKPrimalValidator
from ..optimization.ddd.fixed_k_primal_seed import DddFixedKPrimalSeed
from ..optimization.ddd.reference import DddReferenceSolution


def load_all_stop_start(path: Path, reference_problem, target_problem):
    record = json.loads(path.read_text())
    run = record['run']
    if run['fixed_k_problem_manifest'] != json.loads(json.dumps(reference_problem.certificate_manifest)):
        raise ValueError('All-Stop start physical/demand manifest differs')
    if run['independent_validation_status'] != 'feasible':
        raise ValueError('All-Stop start was not independently validated')
    trajectories, upper = _load_ddd_fixed_k_arc_flow_result_seed(path, problem=reference_problem)
    if upper is None or not math.isfinite(upper):
        raise ValueError('All-Stop start has no finite objective')
    plan = run['validated_passenger_plan']
    if any(plan['unserved_counts_by_demand_group_id'].values()):
        raise ValueError('All-Stop start must fully serve demand')
    candidates = {(q.demand_group_id, q.cabin_id, q.board_visit_index, q.alight_visit_index): q.id
                  for q in target_problem.passenger_build.ride_candidates}
    visits = {(v.cabin_id, v.visit_index): v for t in trajectories for v in t.visits}
    options = {o.id: o for o in target_problem.resolved_trajectory_problem.structural_movement_problem.route_options}
    counts = {}
    for ride in plan['served_rides']:
        n = ride['count']
        if type(n) is not int or n <= 0:
            raise ValueError('MIP start quantities must be positive integers')
        key = tuple(ride[k] for k in ('demand_group_id','cabin_id','board_visit_index','alight_visit_index'))
        qid = candidates[key]
        board, alight = (visits[(ride['cabin_id'], ride[k])] for k in ('board_visit_index','alight_visit_index'))
        times = (board.switch_time_seconds + options[board.route_option_id].platform_exit_offset_seconds + board.wait_seconds,
                 alight.switch_time_seconds + options[alight.route_option_id].platform_entry_offset_seconds)
        if any(not math.isclose(actual, ride[field], rel_tol=0, abs_tol=1e-6)
               for actual, field in zip(times, ('boarding_time_seconds','alighting_time_seconds'))):
            raise ValueError('MIP start passenger times differ from visits')
        counts[qid] = counts.get(qid, 0) + n
    checked = DddFixedKPrimalValidator().validate(
        target_problem, DddReferenceSolution(trajectories), counts, provenance='imported_all_stop')
    if any(checked.unserved_counts.values()) or not math.isclose(checked.objective, upper, rel_tol=0, abs_tol=1e-4):
        raise ValueError('Imported All-Stop service or objective changed')
    seed = DddFixedKPrimalSeed(target_problem.fingerprint, checked.solution, counts, checked.objective, checked.provenance)
    seed.validate(target_problem)
    return seed


def needs_rerun(run):
    """Ignore numerical zero only, not the original 1% stopping tolerance."""
    upper, lower = run.get('validated_upper_bound'), run.get('certified_lower_bound')
    if upper is None or lower is None:
        return True
    if not math.isfinite(upper) or not math.isfinite(lower):
        raise ValueError('Nonfinite stored bounds')
    return upper - lower > max(1e-6, abs(upper) * 1e-10)
