"""Narrow, auditable CAL-O migration; never relax portable-checkpoint identity.

On a regular all-stop fleet every occurrence at a physical checkpoint is a
constant translation of the same cyclic offsets. If the minimum cyclic gap
satisfies every old protection, the old and new phase domains are identical.
Passenger times and releases then coincide for *every* phase and demand level.
"""

from dataclasses import asdict
import hashlib
import json
from pathlib import Path

from .oip_pattern_waiting import prepare_oip_pattern_waiting_pilot
from .thesis_contract import HEADWAY_CONTRACT
from ..models import HeadwayRouteBehavior
from ..optimization.oip.phase_reference import regular_geometry, regular_movement
from ..optimization.oip.runner import decode_oip_certificate
from ..optimization.oip.validation import validate_oip_certificate

OLD_CONTRACT = "oip_regular_phase_short_1ms_v1"
PROOF_SCOPE = "OIP_REGULAR_NO_WAIT_FULL_CYCLE_PHASE_GRID_NESTED_DEMAND"


def file_hash(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def validate_evidence(payload, family):
    if payload.get("contract_id") != OLD_CONTRACT:
        raise ValueError("CAL-O source contract mismatch")
    matches = [e for e in payload.get("evidence", []) if e.get("family") == family]
    if len(matches) != 1:
        raise ValueError("CAL-O family missing or duplicated")
    e = matches[0]
    n = e.get("capacity")
    expected = {
        "contract_id": OLD_CONTRACT,
        "capacity_proven": True,
        "reference_kind": "regular_all_stop_free_common_phase",
        "proof_scope": PROOF_SCOPE,
        "job_id": f"oip_{family}_k62",
        "ticks_per_second": 1000,
        "demand_window_seconds": 1464.0,
        "horizon_seconds": 2364.0,
        "operation_seconds": 2664.0,
        "movement_cycle_ticks": 732010,
    }
    if type(n) is not int or n <= 0 or any(e.get(k) != v for k, v in expected.items()):
        raise ValueError("CAL-O proof contract or K62 mismatch")
    if (
        e.get("proven_feasible_demand") != n
        or e.get("proven_infeasible_demand") != n + 1
        or e.get("load_120") != (6 * n + 4) // 5
    ):
        raise ValueError("CAL-O N/N+1 bracket or 120% load mismatch")
    return e


def all_stop_domain(family, demand, *, legacy):
    p = prepare_oip_pattern_waiting_pilot(
        maximum_wait_seconds=0,
        cabin_count=62,
        demand_family=family,
        demand_total=demand,
        legacy_headways=legacy,
    )
    return p.domain


def verify_cal_o_adoption(source: Path, families):
    """Validate complete source artifacts and return reproducible migration receipts."""
    payload = json.loads(source.read_text())
    receipts = {}
    for family in families:
        e = validate_evidence(payload, family)
        n = e["capacity"]
        files = {str(source.resolve()): file_hash(source)}
        feasible = infeasible = False
        for path in sorted((source.parent / family).glob("attempt_*/probes.json")):
            probes = json.loads(path.read_text())
            relevant = [p for p in probes if p.get("demand") in (n, n + 1)]
            if relevant:
                files[str(path.resolve())] = file_hash(path)
            feasible |= any(
                p.get("demand") == n
                and p.get("status") == "FEASIBLE"
                and p.get("served") == n
                and p.get("unserved") == 0
                for p in relevant
            )
            infeasible |= any(
                p.get("demand") == n + 1
                and p.get("status") == "INFEASIBLE"
                and p.get("native_status") == 3
                for p in relevant
            )
        if not feasible or not infeasible:
            raise ValueError(f"{family}: missing native N/N+1 proof artifacts")
        candidates = [
            (p, json.loads(p.read_text()))
            for p in sorted((source.parent / family).glob("attempt_*/certificate.json"))
        ]
        candidates = [(p, c) for p, c in candidates if c.get("demand") == n]
        if not candidates:
            raise ValueError(f"{family}: missing full-service certificate")
        path, certificate = candidates[-1]
        files[str(path.resolve())] = file_hash(path)
        old, new = (all_stop_domain(family, n, legacy=v) for v in (True, False))
        if certificate.get("domain_fingerprint") != old.fingerprint:
            raise ValueError(f"{family}: historical certificate fingerprint mismatch")
        old_geometry, new_geometry = regular_geometry(old), regular_geometry(new)
        if (
            old_geometry != new_geometry
            or old.scenario.demands != new.scenario.demands
            or old.grid != new.grid
            or old.artifact.config != new.artifact.config
        ):
            raise ValueError(
                f"{family}: movement, demand, grid or time windows changed"
            )
        cycle, offsets = old_geometry[2][-1], old_geometry[3]
        gaps = [b - a for a, b in zip(offsets, (*offsets[1:], offsets[0] + cycle))]
        rules = [
            old.artifact.headway_rule_for_checkpoint(c)
            for c in old.artifact.headway_checkpoints
        ]
        rules += [
            old.artifact.headway_rule_for_full_resource(r)
            for sid in old.artifact.circulation_state_ids
            if (r := old.artifact.initial_boundary_service_resource(sid)) is not None
        ]
        old_required = max(
            old.grid.lower_tick(
                r.required_seconds(
                    HeadwayRouteBehavior.SERVICE, HeadwayRouteBehavior.SERVICE
                )
            )
            for r in rules
        )
        new_required = max(
            new.grid.lower_tick(
                new.artifact.headway_rule_for_checkpoint(c).required_seconds(
                    HeadwayRouteBehavior.SERVICE, HeadwayRouteBehavior.SERVICE
                )
            )
            for c in new.artifact.headway_checkpoints
        )
        if min(gaps) < max(old_required, new_required):
            raise ValueError(
                f"{family}: removed All-Stop requirements are not redundant"
            )
        movement, fleet, passengers = decode_oip_certificate(certificate, old)
        expected_movement, expected_fleet = regular_movement(
            old, certificate["phase_tick"]
        )
        if movement != expected_movement or fleet != expected_fleet:
            raise ValueError(
                f"{family}: source certificate is not the regular phase fleet"
            )
        metrics = validate_oip_certificate(new, movement, fleet, passengers)
        if metrics.served != n or metrics.unserved != 0:
            raise ValueError(f"{family}: source certificate is not full service")
        receipts[family] = {
            "family": family,
            "capacity": n,
            "load_120": (6 * n + 4) // 5,
            "old_contract": OLD_CONTRACT,
            "headway_contract": HEADWAY_CONTRACT,
            "old_domain_fingerprint": old.fingerprint,
            "domain_fingerprint": new.fingerprint,
            "comparison_fingerprint": new.comparison_fingerprint,
            "source_hashes": files,
            "source_evidence": e,
            "minimum_cyclic_gap_ticks": min(gaps),
            "old_maximum_all_stop_headway_ticks": old_required,
            "new_maximum_all_stop_headway_ticks": new_required,
            "cycle_ticks": cycle,
            "phase_domain_ticks": [0, cycle - 1],
            "proof": "identical regular motion and passengers for every phase; all old and new protections satisfied by minimum cyclic gap",
            "validated_served": metrics.served,
            "certificate": {
                "movement_plan": asdict(movement),
                "fleet_plan": asdict(fleet),
                "passenger_plan": asdict(passengers),
            },
        }
    return receipts
