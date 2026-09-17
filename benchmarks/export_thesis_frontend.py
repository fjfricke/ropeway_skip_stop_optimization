"""Build a portable, read-only frontend package for the G500 thesis runs."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import tempfile
import time
from datetime import UTC, datetime
from pathlib import Path

try:
    from .thesis_detail_export import write_detail
except ImportError:
    from thesis_detail_export import write_detail

from ropeway_skip_stop_optimization.benchmarking.thesis_cases import (
    thesis_g500_experiment_groups,
)
from ropeway_skip_stop_optimization.benchmarking.thesis_contract import (
    THESIS_CONTRACT_ID,
)

COPIED_ARTIFACTS = (
    "arguments.json",
    "case_spec.json",
    "prepared_case.json",
    "best_case.json",
    "result.json",
    "events.jsonl",
    "scenario.json",
    "best.json",
    "source_identity.json",
    "supervisor.json",
    "failure.json",
    "evolution_prepared.json",
)


def _read(path: Path) -> dict | None:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return value if isinstance(value, dict) else None


def _portable(value):
    if isinstance(value, dict):
        return {_portable(k): _portable(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_portable(item) for item in value]
    if isinstance(value, str):
        return re.sub(r"/(?:Users|private|var|opt)/[^\s\"']+", "[local-path]", value)
    return value


def _copy_portable(source: Path, target: Path):
    try:
        if source.suffix == ".jsonl":
            values = []
            for line in source.read_text().splitlines():
                try:
                    values.append(json.dumps(_portable(json.loads(line))))
                except ValueError:
                    continue
            content = "\n".join(values) + "\n"
        else:
            content = json.dumps(_portable(json.loads(source.read_text())))
        temporary = target.with_suffix(target.suffix + ".tmp")
        temporary.write_text(content)
        temporary.replace(target)
    except (OSError, ValueError):
        pass  # Keep the previous complete snapshot during an atomic writer update.


def _live_directories(root):
    found = {}
    state = _read(root / "study.json") or {}
    for attempt in state.get("attempts", []):
        directory = root / Path(attempt["result"]).parent
        found[directory] = "running" if state.get("status") == "running" and attempt["status"] == "running" else "failed" if attempt["status"] == "interrupted" else "unknown"
    state = _read(root / "preflight.json") or {}
    if not state:
        state = _read(root / "checks.json") or {}
    for job in state.get("jobs", []):
        if job["status"] in {"running", "failed", "skipped"}:
            found[root / job["id"]] = ("running" if state.get("status") == "running" else "unknown") if job["status"] == "running" else "failed"
    return found


def _first(mapping: dict, *paths: tuple[str, ...]):
    for path in paths:
        value = mapping
        for key in path:
            if not isinstance(value, dict) or key not in value:
                break
            value = value[key]
        else:
            if value is not None:
                return value
    return None


def _slug(path: Path) -> str:
    digest = hashlib.sha256(str(path.resolve()).encode()).hexdigest()[:10]
    stem = "-".join(part for part in path.parts[-3:] if part not in (".", ".."))
    safe = "".join(char.lower() if char.isalnum() else "-" for char in stem)
    return f"{safe.strip('-')[:70]}-{digest}"


def _status(result: dict) -> str:
    raw = str(
        _first(
            result,
            ("status",),
            ("run", "status"),
            ("run", "construction", "status"),
            ("best", "status"),
        )
        or "unknown"
    ).lower()
    if raw in {"optimal", "integer_optimal", "complete", "completed", "finished", "success"}:
        return "complete"
    run = result.get("run")
    if isinstance(run, dict) and str(run.get("schema", "")).endswith("capacity_search_v1"):
        return "complete"
    if isinstance(run, dict) and run.get("independent_validation_status") == "feasible":
        return "complete"
    if _first(result, ("run", "best"), ("best",)) is not None:
        return "complete"
    if raw in {"running", "queued", "planned", "failed"}:
        return raw
    return "unknown"


def _group_id(case: dict) -> str | None:
    required = ("topology", "geometry", "demand_family", "demand_profile", "objective")
    if any(key not in case for key in required) or case["geometry"] != "g500":
        return None
    prefix = "capacity" if case["objective"] == "unserved" else "journey"
    return "_".join(
        (prefix, case["topology"], case["demand_family"], case["geometry"], case["demand_profile"])
    )


def _run_summary(
    run_dir: Path,
    result: dict,
    case: dict,
    arguments: dict,
    *,
    contract_id: str | None = None,
) -> dict | None:
    group_id = _group_id(case)
    if group_id is None:
        return None
    method = arguments.get("method") or result.get("method") or "unknown"
    if method == "labelled_arc_flow":
        frontend_method = "labelled_arc_flow"
    elif method in {"evolution", "reservoir_line_evolution"} or "evolution" in result.get("schema", ""):
        frontend_method = "evolution"
    elif method == "all_stop_phase":
        frontend_method = "all_stop_phase"
    else:
        return None
    run_id = _slug(run_dir)
    monitoring = _read(run_dir / "supervisor.json") or {}
    stopped = monitoring.get("supervisor_reason") or monitoring.get("exit_code")
    metrics = _first(
        result,
        ("run", "best", "passengers"),
        ("best", "passengers", "metrics"),
        ("best", "metrics"),
        ("run", "metrics"),
        ("run", "construction", "physical_plan_metrics"),
        ("run", "construction", "reference_metrics"),
    ) or {}
    validated_arc = (
        frontend_method == "labelled_arc_flow"
        and _first(result, ("run", "independent_validation_status")) == "feasible"
    )
    served = _first(
        metrics,
        ("served",),
        ("served_passengers",),
    )
    if served is None:
        served = _first(result, ("run", "best", "passengers", "served"), ("best", "passengers", "served"))
    unserved = _first(
        metrics,
        ("unserved",),
        ("unserved_passengers",),
    )
    if unserved is None:
        unserved = _first(result, ("run", "best", "passengers", "unserved"), ("best", "passengers", "unserved"))
    validated = validated_arc or (
        frontend_method == "evolution"
        and _first(result, ("run", "best", "movement", "feasible")) is True
        and _first(result, ("run", "best", "passengers", "plan")) is not None
    )
    if validated_arc and case.get("objective") == "journey_time":
        served = case.get("demand_total")
        unserved = 0
    journey_time = _first(
        metrics,
        ("journey_time_passenger_seconds",),
        ("journey_time",),
    )
    if journey_time is None:
        journey_tick = _first(metrics, ("journey_time_tick",))
        if journey_tick is not None:
            journey_time = float(journey_tick) / 1_000_000
    if journey_time is None and validated_arc:
        journey_time = _first(result, ("run", "independent_validation_objective"), ("run", "validated_upper_bound"))
    if frontend_method != "all_stop_phase" and not validated:
        served, unserved, journey_time = None, None, None
    operating_mode = (
        "all_stop"
        if frontend_method == "all_stop_phase"
        else arguments.get("operating_mode") or _first(result, ("run", "operating_mode"))
    )
    summary = {
        "id": run_id,
        "groupId": group_id,
        "status": "failed" if stopped else _status(result),
        "stopReason": monitoring.get("supervisor_reason") or ("process_failed" if monitoring.get("exit_code") else None),
        "method": frontend_method,
        "validated": validated,
        "primalSeedKind": _first(result, ("run", "seed_kind")),
        "primalSeedObjective": _first(result, ("run", "primal_seed_objective_value")),
        "operatingMode": operating_mode,
        "k": arguments.get("fixed_k", arguments.get("cabins")),
        "demand": case.get("demand_total"),
        "releaseResolutionSeconds": case.get("release_resolution_seconds"),
        "caseFingerprint": result.get("case_fingerprint"),
        "seed": arguments.get("seed"),
        "elapsedSeconds": _first(
            result,
            ("runner_total_wall_seconds",),
            ("total_wall_seconds",),
            ("run", "total_wall_seconds"),
        ),
        "cumulativeSeconds": result.get("cumulative_wall_seconds"),
        "supervisedWallSeconds": monitoring.get("civil_wall_seconds"),
        "peakRssBytes": monitoring.get("peak_process_tree_rss_bytes"),
        "served": served,
        "unserved": unserved,
        "journeyTime": journey_time,
        "globalLowerBound": _first(
            result,
            ("global_certified_lower_bound",),
            ("run", "certified_lower_bound",),
        ),
        "boundScope": _first(result, ("proof_scope",), ("run", "proof_scope")),
        "parentRunId": result.get("parent_run_id"),
        "snapshot": f"/generated/thesis/runs/{run_id}/result.json",
        "replay": (
            f"/generated/thesis/runs/{run_id}/best.json"
            if (run_dir / "best.json").is_file()
            else None
        ),
        "contractId": contract_id,
        "studyMembership": (
            "current_thesis" if contract_id == THESIS_CONTRACT_ID else "archive"
        ),
    }
    if frontend_method == "all_stop_phase":
        summary["reference"] = _reference(result, case)
    return summary


def _reference(result: dict, case: dict) -> dict | None:
    capacity = result.get("capacity")
    feasible = result.get("proven_feasible_demand")
    infeasible = result.get("proven_infeasible_demand")
    if capacity is None and feasible is None and infeasible is None:
        nested = result.get("run")
        return _reference(nested, case) if isinstance(nested, dict) else None
    return {
        "provenFeasibleDemand": feasible,
        "provenInfeasibleDemand": infeasible,
        "capacity": capacity,
        "capacityProven": bool(result.get("capacity_proven")),
        "fleet": _first(result, ("config", "cabins"), ("cabins",)),
        "proofScope": result.get("proof_scope"),
        "releaseResolutionSeconds": case.get("release_resolution_seconds"),
    }


_HASH_CACHE = {}


def _file_hash(path):
    stat = path.stat()
    key = (str(path.resolve()), stat.st_mtime_ns, stat.st_size)
    if key not in _HASH_CACHE:
        _HASH_CACHE[key] = hashlib.sha256(path.read_bytes()).hexdigest()
    return _HASH_CACHE[key]


def _export_one(run_dir, output, live_status):
    target = output / "runs" / _slug(run_dir)
    sources = [run_dir / name for name in COPIED_ARTIFACTS]
    sources += sorted((run_dir / "incumbents").glob("*.json"))
    stamp = [[str(path.relative_to(run_dir)), path.stat().st_mtime_ns, path.stat().st_size]
             for path in sources if path.is_file()]
    stamp.append(["export_version", Path(__file__).stat().st_mtime_ns,
                  Path(write_detail.__code__.co_filename).stat().st_mtime_ns, live_status])
    cached = _read(target / "export_cache.json")
    if cached and cached.get("stamp") == stamp and (target / "detail.json").exists():
        return dict(cached["summary"])
    result = _read(run_dir / "result.json")
    case = _read(run_dir / "case_spec.json")
    prepared = _read(run_dir / "prepared_case.json") or {}
    arguments = _read(run_dir / "arguments.json") or {}
    placeholder = result is None
    if result is None and live_status:
        result = {"schema": "thesis_unfinished_snapshot_v1", "method": arguments.get("method"),
                  "status": live_status, "native_result_available": False, "run": {}}
    if result is None or case is None:
        return None
    contract_id = prepared.get("thesis_contract_id") or case.get("thesis_contract_id")
    summary = _run_summary(
        run_dir, result, case, arguments, contract_id=contract_id
    )
    if summary is None:
        return None
    if placeholder and summary["method"] == "evolution":
        checkpoint = _read(run_dir / "best.json") or {}
        metrics = checkpoint.get("metrics") or {}
        if checkpoint.get("schema") == "single_use_reservoir_cp_checkpoint_v1" and checkpoint.get("plan") and checkpoint.get("domain_manifest") and metrics.get("served") is not None:
            # This artifact is written only after the existing independent validator.
            summary.update(validated=True, served=metrics["served"], unserved=metrics.get("unserved"),
                           journeyTime=metrics.get("journey_time_tick", 0) / 1e6,
                           validationSource="saved_independently_checked_checkpoint")
    target.mkdir(parents=True, exist_ok=True)
    for source in sources:
        if source.is_file():
            destination = target / source.relative_to(run_dir)
            destination.parent.mkdir(parents=True, exist_ok=True)
            _copy_portable(source, destination)
    if placeholder:
        snapshot = target / "result.json.tmp"
        snapshot.write_text(json.dumps(result)); snapshot.replace(target / "result.json")
    write_detail(run_dir, target, result, summary)
    cache = target / "export_cache.json.tmp"
    cache.write_text(json.dumps({"stamp": stamp, "summary": summary}))
    cache.replace(target / "export_cache.json")
    return summary


def export(results_roots: tuple[Path, ...], output: Path, study_manifest: Path | None = None) -> dict:
    groups = []
    for item in thesis_g500_experiment_groups():
        if item.objective.value != "journey_time" or item.topology.value != "t5r":
            continue
        groups.append(
            {
                "id": item.group_id,
                "topology": item.topology.value,
                "geometry": item.geometry.value,
                "demandFamily": item.demand_family.value,
                "demandProfile": item.demand_profile.value,
                "objective": item.objective.value,
                "method": "evolution" if item.objective.value == "unserved" else "labelled_arc_flow",
                "runIds": [],
            }
        )
    by_group = {group["id"]: group for group in groups}
    output.mkdir(parents=True, exist_ok=True)
    runs = []
    archived_runs = []
    running = False
    seen = set()
    for root in results_roots:
        if not root.exists():
            continue
        live = _live_directories(root)
        study = _read(root / "study.json") or {}
        attempts = {root / Path(a["result"]).parent: a for a in study.get("attempts", [])}
        successful = {a["key"]: root / Path(a["result"]).parent for a in study.get("attempts", []) if a["status"] == "complete"}
        cumulative = 0.0
        cumulative_by_dir = {}
        for a in study.get("attempts", []):
            cumulative += a.get("wallSeconds", 0)
            cumulative_by_dir[root / Path(a["result"]).parent] = cumulative
        for run_dir in sorted({path.parent for path in root.rglob("result.json")} | set(live)):
            if run_dir.resolve() in seen:
                continue
            seen.add(run_dir.resolve())
            summary = _export_one(run_dir, output, live.get(run_dir))
            if summary is None:
                continue
            attempt = attempts.get(run_dir)
            if attempt:
                parent = successful.get(attempt.get("parent"))
                summary.update(parentRunId=_slug(parent) if parent else None,
                               cumulativeSeconds=cumulative_by_dir[run_dir],
                               transferKind=attempt.get("transfer"), provenance="main_study")
            else:
                summary["provenance"] = "calibration"
            if (
                summary.get("studyMembership") != "current_thesis"
                or summary.get("contractId") != THESIS_CONTRACT_ID
                or summary["groupId"] not in by_group
            ):
                archived_runs.append(summary)
                continue
            runs.append(summary)
            by_group[summary["groupId"]]["runIds"].append(summary["id"])
            running = running or summary["status"] == "running"
            reference = summary.get("reference")
            if reference is not None and summary["method"] == "all_stop_phase":
                previous = by_group[summary["groupId"]].get("reference")
                # Default display is 15 s; individual runs retain their own reference.
                if previous is None or (reference.get("releaseResolutionSeconds") == 15 and
                        (previous.get("releaseResolutionSeconds") != 15 or
                         (bool(reference.get("capacityProven")), reference.get("provenFeasibleDemand") or 0) >
                         (bool(previous.get("capacityProven")), previous.get("provenFeasibleDemand") or 0))):
                    by_group[summary["groupId"]]["reference"] = reference

    payload = {
        "schema": "thesis_frontend_index_v1",
        "generatedAt": datetime.now(UTC).isoformat(),
        "campaignStatus": "running" if running else "partial" if runs else "planned",
        "contractId": THESIS_CONTRACT_ID,
        "groups": groups,
        "runs": runs,
        "sources": [
            {
                "label": "Cable C1 press kit",
                "url": "https://www.iledefrance-mobilites.fr/le-reseau/projets/cablec1/mediatheque/kit-presse-c1",
                "use": "Published 500-1800 m interstation range motivates the synthetic G500 scale.",
            },
            {
                "label": "Haimerl et al. (2022)",
                "url": "https://informs-sim.org/wsc22papers/138.pdf",
                "use": "Reference scale for rope speed, platform speed and cabin capacity.",
            },
        ],
    }
    if study_manifest is not None:
        study = _read(study_manifest)
        if study and study.get("schema") == "thesis_study_v1":
            payload["launchReadiness"] = {"status": study["status"], "groups": [
                {"id": group["id"], "blockers": group["blockers"], "demandBasis": group.get("demandBasis")}
                for group in study["groups"]]}
            _copy_portable(study_manifest, output / "study_manifest.json")
    with tempfile.NamedTemporaryFile("w", dir=output, delete=False, encoding="utf-8") as stream:
        json.dump(payload, stream, indent=2, sort_keys=True)
        stream.write("\n")
        temporary = Path(stream.name)
    temporary.replace(output / "index.json")
    archive_payload = {
        "schema": "thesis_archive_index_v1",
        "generatedAt": payload["generatedAt"],
        "runs": sorted(archived_runs, key=lambda item: item["id"]),
    }
    with tempfile.NamedTemporaryFile(
        "w", dir=output, delete=False, encoding="utf-8"
    ) as stream:
        json.dump(archive_payload, stream, indent=2, sort_keys=True)
        stream.write("\n")
        archive_temporary = Path(stream.name)
    archive_temporary.replace(output / "archive-index.json")
    # Include archived generated artifacts too; an existing public directory may
    # retain older read-only runs that are no longer in the active index.
    files = [path for path in output.rglob("*") if path.is_file()
             and path.suffix in {".json", ".jsonl"}
             and path.name not in {"package_manifest.json", "export_cache.json"}]
    package = {"schema": "thesis_portable_package_v1", "files": [
        {"path": str(path.relative_to(output)), "bytes": path.stat().st_size,
         "sha256": _file_hash(path)} for path in sorted(set(files)) if path.name != "export_cache.json"
    ]}
    temporary = output / "package_manifest.json.tmp"
    temporary.write_text(json.dumps(package, indent=2)); temporary.replace(output / "package_manifest.json")
    return payload


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, allow_abbrev=False)
    parser.add_argument("--results-root", type=Path, action="append", default=[])
    parser.add_argument("--study-manifest", type=Path)
    parser.add_argument("--watch-seconds", type=float, default=0,
                        help="Refresh this read-only export while local runs execute")
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("frontend/public/generated/thesis"),
    )
    args = parser.parse_args()
    deadline = time.time() + args.watch_seconds
    while True:
        payload = export(tuple(args.results_root), args.output, args.study_manifest)
        print(json.dumps({"groups": len(payload["groups"]), "runs": len(payload["runs"]), "output": str(args.output)}), flush=True)
        if time.time() >= deadline:
            break
        time.sleep(min(5, max(0, deadline - time.time())))


if __name__ == "__main__":
    main()
