"""Revalidate an unchanged legacy timetable under the shared rope-headway port."""

import argparse
from dataclasses import asdict, replace
from pathlib import Path

from ropeway_skip_stop_optimization.benchmarking.ddd_reservoir_arc_flow import (
    DddReservoirArcFlowRunConfig,
    prepare_ddd_reservoir_arc_flow_run,
)
from ropeway_skip_stop_optimization.optimization.ddd.cp_sat_certificate import (
    atomic_json,
)
from ropeway_skip_stop_optimization.optimization.ddd.reservoir_boundary import (
    ReservoirBoundaryPolicy,
    geometry_fingerprint,
    validate_port_separation,
)
from ropeway_skip_stop_optimization.optimization.ddd.reservoir_cp_sat_certificate import (
    validate_reservoir_cp_plan,
    write_reservoir_cp_checkpoint,
)
from ropeway_skip_stop_optimization.optimization.ddd.reservoir_hybrid.domain import (
    load_reference,
)


def migrate(checkpoint, example_id, output):
    domain, plan = load_reference(checkpoint)
    p = domain.problem
    old = validate_reservoir_cp_plan(p, plan)
    # Rebuild the named physical example. Geometry equality is mandatory;
    # matching a scenario label alone is not sufficient evidence.
    maxima = {v for _, v in p.waiting_policy.maximum_wait_seconds_by_station_id}
    if len(maxima) > 1:
        raise ValueError("example evidence adapter requires a uniform waiting maximum")
    physical = prepare_ddd_reservoir_arc_flow_run(
        DddReservoirArcFlowRunConfig(
            example_id=example_id,
            entry_state_id=p.entry_state_id,
            available_fleet_count=p.available_fleet_count,
            waiting_max_seconds=next(iter(maxima), 0),
            waiting_step_seconds=p.waiting_policy.step_seconds or 0.000001,
        )
    )
    if geometry_fingerprint(physical.problem.movement_core) != geometry_fingerprint(
        p.movement_core
    ):
        raise ValueError(
            "example geometry differs from checkpoint; cannot derive port evidence"
        )
    boundary = ReservoirBoundaryPolicy.from_headway_policy(
        p.movement_core, p.entry_state_id, physical.headway_policy
    )
    q = replace(p, boundary_policy=boundary)
    output.mkdir(parents=True, exist_ok=False)
    atomic_json(output / "port_headway_evidence.json", asdict(boundary))
    report = {
        "source": str(checkpoint.resolve()),
        "source_fingerprint": p.fingerprint,
        "target_fingerprint": q.fingerprint,
        "old_metrics": asdict(old),
        "port": validate_port_separation(replace(q, boundary_policy=None), plan),
        "required_port_gap_tick": boundary.headway_tick,
        "imported_native_bounds": False,
    }
    try:
        checked = validate_reservoir_cp_plan(q, plan)
        write_reservoir_cp_checkpoint(output / "validated.json", q, plan)
        # Verify serialization as well as the in-memory certificate.
        reloaded, replay = load_reference(output / "validated.json")
        assert reloaded.fingerprint == q.fingerprint and replay == plan
        report.update(status="validated_unchanged", new_metrics=asdict(checked))
    except ValueError as error:
        report.update(status="rejected", reason=str(error))
    atomic_json(output / "migration.json", report)
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__, allow_abbrev=False)
    parser.add_argument("--checkpoint", required=True, type=Path)
    parser.add_argument("--example", required=True)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    report = migrate(args.checkpoint, args.example, args.output)
    print(report["status"])
    return 0 if report["status"] == "validated_unchanged" else 2


if __name__ == "__main__":
    raise SystemExit(main())
