from __future__ import annotations

import json
import math
import os
import tempfile
from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path

from .fixed_k import DddFixedKTrajectoryProblem
from .fixed_k_certificate import (
    DddFixedKPrimalValidator,
    DddValidatedFixedKPlan,
    build_ddd_fixed_k_domain_manifest,
)
from .reference import (
    DddReferenceSolution,
    DddReferenceTrajectory,
    build_ddd_reference_visit,
)
from .time_ticks import (
    ddd_seconds_to_tick,
    ddd_tick_to_seconds,
)

FORMULATION_VERSION = "integrated_cp_sat_v2"


def stable_fingerprint(value: object) -> str:
    return sha256(
        json.dumps(
            value, sort_keys=True, separators=(",", ":"), allow_nan=False
        ).encode()
    ).hexdigest()


def validate_ddd_cp_sat_domain(problem: DddFixedKTrajectoryProblem) -> dict:
    return build_ddd_fixed_k_domain_manifest(problem)


@dataclass(frozen=True)
class DddCpSatIncumbent(DddValidatedFixedKPlan):
    """Backward-compatible CP-SAT view of the shared primal certificate."""


def validate_ddd_cp_sat_incumbent(
    problem: DddFixedKTrajectoryProblem,
    solution: DddReferenceSolution,
    ride_counts: dict[str, int],
    *,
    provenance: str,
    expected_objective_tick: int | None = None,
) -> DddCpSatIncumbent:
    result = DddFixedKPrimalValidator().validate(
        problem,
        solution,
        ride_counts,
        provenance=provenance,
        expected_objective_tick=expected_objective_tick,
    )
    return DddCpSatIncumbent(
        result.solution,
        result.ride_counts,
        result.unserved_counts,
        result.objective_tick,
        result.provenance,
    )


def solution_from_cp_sat_payload(
    problem: DddFixedKTrajectoryProblem, payload: dict
) -> DddReferenceSolution:
    movement = problem.resolved_trajectory_problem.structural_movement_problem
    starts = {s.cabin_id: s for s in movement.starts}
    options = {o.id: o for o in movement.route_options}
    trajectories = []
    for raw in payload["trajectory_supports"]:
        start = starts[raw["cabin_id"]]
        route_ids, ticks = raw["route_option_ids"], raw["switch_times_tick"]
        if (
            not route_ids
            or len(route_ids) != len(ticks)
            or any(type(t) is not int for t in ticks)
        ):
            raise ValueError("invalid CP-SAT checkpoint trajectory dimensions or times")
        waits = raw.get("wait_ticks")
        if waits is None:
            seconds = raw.get("wait_seconds", [0.0] * len(ticks))
            if any(
                not math.isfinite(w)
                or not math.isclose(
                    w,
                    ddd_tick_to_seconds(ddd_seconds_to_tick(w)),
                    rel_tol=0,
                    abs_tol=1e-10,
                )
                for w in seconds
            ):
                raise ValueError("invalid CP-SAT checkpoint wait grid")
            waits = [ddd_seconds_to_tick(w) for w in seconds]
        if len(waits) != len(ticks) or any(type(w) is not int or w < 0 for w in waits):
            raise ValueError("invalid CP-SAT checkpoint waits")
        if "wait_seconds" in raw and (
            len(raw["wait_seconds"]) != len(waits)
            or any(
                not math.isfinite(w) or abs(w - ddd_tick_to_seconds(tick)) > 1e-10
                for w, tick in zip(raw["wait_seconds"], waits, strict=True)
            )
        ):
            raise ValueError("CP-SAT checkpoint wait representations differ")
        visits = tuple(
            build_ddd_reference_visit(
                start=start,
                visit_index=i,
                switch_time_seconds=ddd_tick_to_seconds(t),
                option=options[o],
                operational_end_seconds=movement.operational_end_seconds,
                tolerance_seconds=1e-9,
                wait_seconds=ddd_tick_to_seconds(w),
            )
            for i, (o, t, w) in enumerate(zip(route_ids, ticks, waits, strict=True))
        )
        trajectories.append(DddReferenceTrajectory(start.cabin_id, visits))
    return DddReferenceSolution(tuple(trajectories))


def atomic_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    name = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=path.parent,
            prefix=f".{path.name}.",
            delete=False,
        ) as stream:
            name = stream.name
            json.dump(payload, stream, indent=2, sort_keys=True, allow_nan=False)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(name, path)
    finally:
        if name is not None and os.path.exists(name):
            os.unlink(name)


def write_ddd_cp_sat_checkpoint(
    path: Path,
    *,
    problem: DddFixedKTrajectoryProblem,
    manifest: dict,
    incumbent: DddCpSatIncumbent,
) -> None:
    # Never publish an unvalidated or altered caller-provided assignment.
    incumbent = validate_ddd_cp_sat_incumbent(
        problem,
        incumbent.solution,
        incumbent.ride_counts,
        provenance=incumbent.provenance,
        expected_objective_tick=incumbent.objective_tick,
    )
    atomic_json(
        path,
        {
            "schema": FORMULATION_VERSION,
            "problem_fingerprint": problem.fingerprint,
            "domain_manifest": manifest,
            "domain_fingerprint": stable_fingerprint(manifest),
            "incumbent": incumbent.to_payload(),
        },
    )


def read_ddd_cp_sat_checkpoint(
    path: Path, *, problem: DddFixedKTrajectoryProblem, manifest: dict
) -> DddCpSatIncumbent:
    payload = json.loads(path.read_text())
    if (
        payload.get("schema") not in ("integrated_cp_sat_v1", FORMULATION_VERSION)
        # Old hashes are accepted only for a primal plan with a matching full
        # manifest below. No historical bound or search state is imported.
        or payload.get("problem_fingerprint")
        not in (problem.fingerprint, problem.legacy_fingerprint)
        or payload.get("domain_fingerprint") != stable_fingerprint(manifest)
        or payload.get("domain_fingerprint")
        != stable_fingerprint(payload.get("domain_manifest"))
    ):
        raise ValueError("CP-SAT checkpoint domain fingerprint mismatch")
    raw = payload["incumbent"]
    incumbent = validate_ddd_cp_sat_incumbent(
        problem,
        solution_from_cp_sat_payload(problem, raw),
        raw["ride_counts"],
        provenance=f"checkpoint:{path}",
        expected_objective_tick=raw["objective_tick"],
    )
    if incumbent.unserved_counts != raw["unserved_counts"]:
        raise ValueError("CP-SAT checkpoint demand accounting mismatch")
    return incumbent
