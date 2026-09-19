"""Fresh reference dependencies for the two agreed fixed-start Journey series."""

from .thesis_contract import (
    CONSTANT_JOURNEY_K, CONSTANT_REFERENCE_K, RELATIVE_JOURNEY_K, JOURNEY_REFERENCE_K,
    THESIS_CONTRACT_ID, ThesisWindows,
)

FAMILIES = ("f0", "f2", "f3", "f4")
PROOF_SCOPE = "FIXED_K_BALANCED_START_ALL_STOP_AND_NESTED_DEMAND"


def journey_jobs() -> list[dict]:
    jobs = []
    for k in JOURNEY_REFERENCE_K:
        for family in FAMILIES:
            jobs.append(dict(
                id=f"reference_{family}_k{k}", kind="reference", family=family,
                k=k, demand=20_000, mode="all_stop", status="planned", attempts=[],
            ))
    for series, grid, percentages in (
        ("relative", RELATIVE_JOURNEY_K, (25, 75)),
        ("constant", CONSTANT_JOURNEY_K, (50,)),
    ):
        for k in grid:
            for percent in percentages:
                for family in FAMILIES:
                    for mode in ("all_stop", "skip_stop"):
                        ref_k = k if series == "relative" else CONSTANT_REFERENCE_K
                        jobs.append(dict(
                            id=f"{series}_{percent}_{family}_k{k}_{mode}",
                            kind=series, family=family, k=k, mode=mode,
                            reference_id=f"reference_{family}_k{ref_k}",
                            reference_k=ref_k, percent=percent, demand=None,
                            status="pending_reference", attempts=[],
                        ))
    return jobs


def exact_reference_capacity(result: dict, *, k: int) -> int:
    """Require N/N+1 evidence from the new physical/time contract."""
    run = result.get("run", {})
    n = run.get("proven_feasible_demand")
    if (
        run.get("proof_scope") != PROOF_SCOPE
        or run.get("cabins") != k
        or run.get("capacity_proven") is not True
        or type(n) is not int or n < 1
        or run.get("proven_infeasible_demand") != n + 1
    ):
        raise ValueError("matching exact All-Stop reference is still missing")
    probes = run.get("probes", [])
    for demand, outcome in ((n, "feasible"), (n + 1, "infeasible")):
        if not any(
            p.get("demand") == demand and p.get("outcome") == outcome
            and p.get("case", {}).get("thesis_contract_id") == THESIS_CONTRACT_ID
            and p.get("case", {}).get("continuation_tick") == 300_000_000
            and p.get("case", {}).get("problem_fingerprint")
            for p in probes
        ):
            raise ValueError("reference evidence uses another physical/time contract")
    return n


def study_definition(cycle_seconds: float = 732.0) -> dict:
    return {
        "schema": "thesis_study_v2", "contract_id": THESIS_CONTRACT_ID,
        "status": "preparation", "topology": "T5R", "geometry": "G500",
        "windows": ThesisWindows(cycle_seconds).manifest(),
        "journey": {
            "relative_k": list(RELATIVE_JOURNEY_K),
            "relative_load_percent": [25, 75],
            "constant_k": list(CONSTANT_JOURNEY_K),
            "constant_reference_k": CONSTANT_REFERENCE_K,
            "constant_load_percent": 50,
            "families": list(FAMILIES), "start_policy": "fixed_balanced",
            "objective": "journey_time_full_service", "waiting_seconds": 0,
            "time_limit_seconds": 1800, "relative_gap": 0.01,
            "reference_jobs": len(JOURNEY_REFERENCE_K) * len(FAMILIES), "comparison_jobs": 104,
        },
        "oip": {
            "families": ["f0", "f2", "f3"],
            "start_policy": "optimized_initial_placement", "waiting_seconds": 0,
            "demand_status": "new_calibration_required", "demand_totals": None,
            "reference_kind": "regular_all_stop_free_common_phase",
            "reference_proof_scope": "regular_all_stop_only_not_free_oip_optimum",
            "objective": "lexicographic_unserved_then_journey_time",
        },
        "notes": [
            "No new thesis runs have been launched.",
            "Old results retain their original contracts in the archive.",
            "An All-Stop witness is not an optimal OIP capacity certificate.",
        ],
    }


def constant_demand_gate(family: str, by_id: dict) -> dict:
    """Use proven nested capacities; no extra solves or start-plan transfer.

    A full-service witness at N also serves every prefix up to N. All three
    capacities must be certified under this contract before the series starts.
    """
    from pathlib import Path
    import hashlib
    import json

    capacities, evidence = {}, {}
    for k in CONSTANT_JOURNEY_K:
        reference = by_id[f"reference_{family}_k{k}"]
        if reference["status"] != "complete" or not reference["attempts"]:
            return dict(status="pending_reference", reason=f"All-Stop reference K{k} missing")
        path = Path(reference["attempts"][-1]["directory"]) / "result.json"
        try:
            raw = path.read_bytes()
            capacities[k] = exact_reference_capacity(json.loads(raw), k=k)
        except (OSError, ValueError) as error:
            return dict(status="pending_reference", reason=f"K{k}: {error}")
        evidence[str(k)] = dict(capacity=capacities[k], result_sha256=hashlib.sha256(raw).hexdigest())
    demand = capacities[CONSTANT_REFERENCE_K] // 2
    failed = [k for k in CONSTANT_JOURNEY_K if capacities[k] < demand]
    if demand < 1 or failed:
        return dict(status="blocked_constant_demand", demand=demand, evidence=evidence,
                    reason=f"Half K{CONSTANT_REFERENCE_K} demand is zero or exceeds All-Stop capacity at {failed}")
    return dict(status="passed", demand=demand, evidence=evidence,
                reason="Nested full-service demand is within the certified capacity at K20, K25 and K30")
