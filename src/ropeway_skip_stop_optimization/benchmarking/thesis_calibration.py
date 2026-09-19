"""Frozen job definitions and evidence export for thesis calibrations."""

from __future__ import annotations

from dataclasses import asdict, dataclass
import hashlib
import json
from pathlib import Path

from .thesis_contract import JOURNEY_REFERENCE_K
from .thesis_reruns import FAMILIES


OIP_FAMILIES = ("f0", "f2", "f3")
OIP_REFERENCE_KIND = "regular_all_stop_free_common_phase"
JOURNEY_REFERENCE_KIND = "fixed_balanced_all_stop"


@dataclass(frozen=True, slots=True)
class CalibrationJob:
    id: str
    group: str
    family: str
    cabins: int
    reference_kind: str
    status: str = "planned"

    def payload(self) -> dict:
        return {**asdict(self), "attempts": []}


def calibration_jobs(*, oip_cabins: int) -> list[dict]:
    if oip_cabins <= 0:
        raise ValueError("OIP reference fleet must be positive")
    jobs = [
        CalibrationJob(
            id=f"journey_{family}_k{k}",
            group="journey",
            family=family,
            cabins=k,
            reference_kind=JOURNEY_REFERENCE_KIND,
        ).payload()
        for k in JOURNEY_REFERENCE_K
        for family in FAMILIES
    ]
    jobs.extend(
        CalibrationJob(
            id=f"oip_{family}_k{oip_cabins}",
            group="oip",
            family=family,
            cabins=oip_cabins,
            reference_kind=OIP_REFERENCE_KIND,
        ).payload()
        for family in OIP_FAMILIES
    )
    return jobs


def result_evidence(job: dict, result_path: Path) -> dict:
    result = json.loads(result_path.read_text(encoding="utf-8"))
    run = result.get("run", {})
    evidence = {
        "job_id": job["id"],
        "group": job["group"],
        "family": job["family"],
        "cabins": job["cabins"],
        "reference_kind": job["reference_kind"],
        "capacity_proven": run.get("capacity_proven") is True,
        "proven_feasible_demand": run.get("proven_feasible_demand"),
        "proven_infeasible_demand": run.get("proven_infeasible_demand"),
        "proof_scope": run.get("proof_scope"),
        "result_path": str(result_path.resolve()),
        "result_sha256": hashlib.sha256(result_path.read_bytes()).hexdigest(),
    }
    return evidence
