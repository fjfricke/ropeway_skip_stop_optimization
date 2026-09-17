"""Materialize the twelve study recipes and their evidence-based launch gates."""
import argparse
from dataclasses import asdict
import hashlib
import json
import math
from pathlib import Path

from ropeway_skip_stop_optimization.benchmarking.thesis_cases import thesis_g500_experiment_groups, ExperimentCaseSpec, prepare_experiment_case
from ropeway_skip_stop_optimization.benchmarking.thesis_study import confirmed_service, journey_confirmed, validate_study
from ropeway_skip_stop_optimization.optimization.ddd.cp_sat_certificate import atomic_json


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--results-root", type=Path, action="append", required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--resolution-evidence", type=Path, required=True)
    parser.add_argument("--group", action="append", default=[], help="Freeze only these explicit group IDs")
    parser.add_argument("--reference-mode", choices=("exact", "witness"), default="exact",
                        help="Witness mode labels the initial load as a proven lower reference, never exact capacity")
    args = parser.parse_args()
    available = {group.group_id for group in thesis_g500_experiment_groups()}
    if set(args.group) - available:
        parser.error("unknown group ID")
    evidence = json.loads(args.resolution_evidence.read_text())
    results = []
    for root in args.results_root:
        for path in sorted(root.rglob("result.json")):
            spec_path = path.parent / "case_spec.json"
            if not spec_path.exists():
                continue
            result, spec = json.loads(path.read_text()), json.loads(spec_path.read_text())
            arguments = json.loads((path.parent / "arguments.json").read_text())
            if spec.get("geometry") == "g500" and spec.get("demand_profile") == "p0" and spec.get("release_resolution_seconds") == 15:
                results.append((path, spec, result, arguments))
    groups = []
    for group in thesis_g500_experiment_groups():
        key = group.group_id
        if args.group and key not in args.group:
            continue
        physical = prepare_experiment_case(ExperimentCaseSpec(group.topology, group.geometry, group.demand_family, group.demand_profile, group.objective, 1, release_resolution_seconds=15))
        k_as = physical.all_stop_reference_cabins
        capacity = group.objective.value == "unserved"
        expected_k = k_as if capacity else 10
        expected_scope = "REGULAR_NO_WAIT_ALL_STOP_COMMON_PHASE_AND_NESTED_DEMAND" if capacity else "FIXED_K_BALANCED_START_ALL_STOP_AND_NESTED_DEMAND"
        candidates = [(path, result, arguments) for path, spec, result, arguments in results
                      if (spec["topology"], spec["demand_family"], spec["objective"]) == (group.topology.value, group.demand_family.value, group.objective.value)]
        references = [(path, result, arguments) for path, result, arguments in candidates if result.get("method") == "all_stop_phase"
                      and arguments.get("cabins") == expected_k and result.get("run", {}).get("proof_scope") == expected_scope]
        references.sort(key=lambda item: (bool(item[1]["run"].get("capacity_proven")), item[1]["run"].get("proven_feasible_demand") or 0), reverse=True)
        reference = references[0] if references else None
        native = reference[1]["run"] if reference else {}
        lower = native.get("proven_feasible_demand") or 0
        full_reference = bool(native.get("capacity_proven"))
        pilot = any((confirmed_service(result) is not None and confirmed_service(result)[0] > 0) if group.objective.value == "unserved" else
                    journey_confirmed(result) and result.get("run", {}).get("operating_mode") == "skip_stop"
                    for _, result, arguments in candidates if result.get("method") != "all_stop_phase" and arguments.get("cabins") == expected_k)
        blockers = []
        if not full_reference and (args.reference_mode == "exact" or lower <= 0):
            blockers.append("exact_all_stop_reference_pending" if args.reference_mode == "exact" else "validated_all_stop_witness_pending")
        if not pilot:
            blockers.append("validated_optimization_pilot_pending")
        if evidence.get(key, {}).get("status") != "passed":
            blockers.append("release_resolution_evidence_pending")
        groups.append({"id": key, "topology": group.topology.value, "family": group.demand_family.value,
                       "objective": group.objective.value, "resolution_seconds": 15,
                       "k_values": sorted({min(k, physical.physical_dispatch_bound) for k in [k_as, k_as + 1, math.ceil(1.1 * k_as)]}) if capacity else [10, 15, 23],
                       "seeds": [0, 1, 2] if capacity else [0], "stage_seconds": 300 if capacity else 1800,
                       "mip_gap": None if capacity else 0.01,
                       "demand": max(1, lower if capacity else lower // 2),
                       "demandIsPlaceholder": lower == 0, "demandBasis": "exact_reference_capacity" if full_reference else "validated_reference_lower_bound", "max_demand_levels": 5,
                       "reference": None if reference is None else {"result": str(reference[0]),
                          "sha256": hashlib.sha256(reference[0].read_bytes()).hexdigest(),
                          "lower": lower, "upperExclusive": native.get("proven_infeasible_demand"),
                          "exact": full_reference, "scope": native.get("proof_scope")},
                       "blockers": blockers})
    manifest = {"schema": "thesis_study_v1", "status": "ready" if not any(group["blockers"] for group in groups) else "gated",
                "workers": 12, "memory_gib": 32, "geometry": "g500", "operation": "no_wait",
                "catalog": "od_endpoints_v1", "journey_stop_rule": "two_successive_points_without_a_validated_full_service_solution",
                "capacity_stop_rule": "full_service_stops_K_scan; geometric_N_then_at_most_three_midpoints_after_unresolved_load",
                "source_resolution_evidence": str(args.resolution_evidence),
                "source_resolution_sha256": hashlib.sha256(args.resolution_evidence.read_bytes()).hexdigest(), "groups": groups}
    manifest["maximum_stage_budget_seconds"] = sum(
        group["stage_seconds"] * len(group["seeds"]) * len(group["k_values"]) *
        (group["max_demand_levels"] + 3 if group["objective"] == "unserved" else 2) for group in groups)
    validate_study(manifest, require_ready=False)
    atomic_json(args.output, manifest)
    print(json.dumps({"ready": [group["id"] for group in groups if not group["blockers"]],
                      "blocked": {group["id"]: group["blockers"] for group in groups if group["blockers"]}}, indent=2))


if __name__ == "__main__":
    main()
