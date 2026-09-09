"""Explicit checkpoint boundary; legacy CP checkpoints keep their own schema."""

from __future__ import annotations

import json
from pathlib import Path

from ..ean.horizon_contract import FINITE_EVENT_ENTRY_CONTRACT
from .cp_sat_certificate import (
    atomic_json,
    read_ddd_cp_sat_checkpoint,
    solution_from_cp_sat_payload,
    stable_fingerprint,
    validate_ddd_cp_sat_incumbent,
    write_ddd_cp_sat_checkpoint,
)
from .fixed_k_certificate import (
    DddFixedKPrimalValidator,
    build_ddd_fixed_k_domain_manifest,
)


class DddReservationCheckpointAdapter:
    schema = "reservation_insertion_v1"

    def read(self, path: Path, *, problem):
        manifest = build_ddd_fixed_k_domain_manifest(problem)
        raw = json.loads(path.read_text())
        if raw.get("schema") != self.schema:
            prior = read_ddd_cp_sat_checkpoint(path, problem=problem, manifest=manifest)
            return DddFixedKPrimalValidator().validate(
                problem,
                prior.solution,
                prior.ride_counts,
                provenance=prior.provenance,
                expected_objective_tick=prior.objective_tick,
            )
        if (
            raw.get("domain_fingerprint") != stable_fingerprint(manifest)
            or raw.get("domain_fingerprint")
            != stable_fingerprint(raw.get("domain_manifest"))
            or raw.get("horizon_contract") != FINITE_EVENT_ENTRY_CONTRACT
        ):
            raise ValueError("reservation checkpoint domain mismatch")
        plan = raw["incumbent"]
        validated = DddFixedKPrimalValidator().validate(
            problem,
            solution_from_cp_sat_payload(problem, plan),
            plan["ride_counts"],
            provenance=f"checkpoint:{path}",
            expected_objective_tick=plan["objective_tick"],
        )
        if validated.unserved_counts != plan["unserved_counts"]:
            raise ValueError("reservation checkpoint demand mismatch")
        return validated

    def write(self, path: Path, *, problem, plan):
        plan = DddFixedKPrimalValidator().validate(
            problem,
            plan.solution,
            plan.ride_counts,
            provenance=plan.provenance,
            expected_objective_tick=plan.objective_tick,
        )
        manifest = build_ddd_fixed_k_domain_manifest(problem)
        atomic_json(
            path,
            {
                "schema": self.schema,
                "domain_manifest": manifest,
                "domain_fingerprint": stable_fingerprint(manifest),
                "incumbent": plan.to_payload(),
                "horizon_contract": FINITE_EVENT_ENTRY_CONTRACT,
                "proof_scope": "heuristic_finite_horizon",
            },
        )

    def export_cp_seed(self, path: Path, *, problem, plan):
        incumbent = validate_ddd_cp_sat_incumbent(
            problem,
            plan.solution,
            plan.ride_counts,
            provenance=plan.provenance,
            expected_objective_tick=plan.objective_tick,
        )
        write_ddd_cp_sat_checkpoint(
            path,
            problem=problem,
            manifest=build_ddd_fixed_k_domain_manifest(problem),
            incumbent=incumbent,
        )
