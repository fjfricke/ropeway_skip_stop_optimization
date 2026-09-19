"""Fixed-mixture OIP campaigns: K62 study and K50 fleet sensitivity."""

from __future__ import annotations

import argparse
import json
import hashlib
import os
import time
import shutil
import sys
import threading
from pathlib import Path

BENCHMARKS = Path(__file__).resolve().parent
if str(BENCHMARKS) not in sys.path:
    sys.path.insert(0, str(BENCHMARKS))

from run_oip_nowait_formulation_comparison import (
    CATALOG,
    FRONTEND_ROOT,
    ROOT,
    new_manifest,
    now,
    reference_command,
    save,
    trial_command,
)
from run_oip_type_catalog_campaign import (
    _expose_live_run,
    _mirror_live_run,
    _publish_run,
)

from ropeway_skip_stop_optimization.benchmarking.oip_pattern_waiting import (
    prepare_oip_pattern_waiting_pilot,
)
from ropeway_skip_stop_optimization.optimization.oip.runner import (
    _read_portable_checkpoint,
)
from ropeway_skip_stop_optimization.optimization.oip.incumbent_store import recover_validated_incumbent
from ropeway_skip_stop_optimization.optimization.oip.validation import (
    validate_oip_certificate,
)

from ropeway_skip_stop_optimization.benchmarking.oip_calibration_reuse import (
    verify_cal_o_adoption,
)
from ropeway_skip_stop_optimization.benchmarking.process_supervisor import supervise
from ropeway_skip_stop_optimization.benchmarking.frontend_results import atomic_json
from ropeway_skip_stop_optimization.benchmarking.thesis_contract import (
    HEADWAY_CONTRACT,
    THESIS_CONTRACT_ID,
    solver_versions,
)


def _run_one(command, directory, seconds, args):
    deadline = time.time() + seconds
    command = [*command, "--deadline-unix", str(deadline)]
    return supervise(
        command,
        directory,
        seconds=seconds,
        global_deadline=deadline,
        memory_bytes=int(args.memory_limit_gib * 1024**3),
        env={**os.environ, "PYTHONPATH": str(ROOT / "src")},
        system_memory_pressure_seconds=30,
    )


MIXES = ((62, 0, 0), (46, 8, 8), (30, 16, 16), (16, 23, 23), (0, 31, 31))
K50_MIXES = ((50, 0, 0), (38, 6, 6), (24, 13, 13), (12, 19, 19), (0, 25, 25))


def load_k62_comparison(path, families, loads):
    """Read completed K62 observations for display and frozen-demand checking only."""
    source = json.loads((path / "campaign.json").read_text())
    config = source["configuration"]
    required = dict(demand_window_seconds=1464, horizon_seconds=2364,
                    operation_seconds=2664, ticks_per_second=1000,
                    release_resolution_seconds=15, headway_contract=HEADWAY_CONTRACT)
    if source["status"] != "complete" or source["k_values"] != [62] or any(config.get(k) != v for k, v in required.items()):
        raise ValueError("K50 sensitivity requires a completed K62 campaign with the same physical contract")
    frozen = {}
    hashes = {str((path / "campaign.json").resolve()): hashlib.sha256((path / "campaign.json").read_bytes()).hexdigest()}
    for family in families:
        if source["load_contract"].get(family) != loads[family]:
            raise ValueError("K62 source demand differs from the calibrated experiment load")
        file = path / "frozen_domains" / f"{family}.json"
        frozen[family] = json.loads(file.read_text())
        groups = frozen[family]["demand_groups"]
        digest = hashlib.sha256(json.dumps(groups, separators=(",", ":")).encode()).hexdigest()
        if digest != frozen[family]["demand_fingerprint"] or sum(g[3] for g in groups) != loads[family]:
            raise ValueError("K62 frozen demand is inconsistent")
        hashes[str(file.resolve())] = hashlib.sha256(file.read_bytes()).hexdigest()
    expected_ids = {f"{family}_mix_{'_'.join(map(str, counts))}_k62" for family in families for counts in MIXES}
    selected = [t for t in source["trials"] if t["family"] in families]
    if {t["trial_id"] for t in selected} != expected_ids or len(selected) != len(expected_ids) or any(t["status"] != "complete" for t in selected):
        raise ValueError("K62 comparison is missing completed fixed-mixture cases")
    return {
        "campaign_id": source["campaign_id"], "fleet_count": 62,
        "role": "display_only_previous_fleet", "source_hashes": hashes,
        "trials": [t for t in source["trials"] if t["family"] in families],
    }, frozen



def manifest_for(args, loads):
    fleet = getattr(args, "fixed_k", 62)
    mixes = K50_MIXES if fleet == 50 else MIXES
    manifest = new_manifest(args, loads)
    manifest["label"] = "OIP · feste Typmischungen · 120% · No-Wait"
    if fleet == 50:
        manifest["label"] = "OIP · K50-Sensitivität · gleiche Nachfrage · No-Wait"
        manifest["reference_runs"] = {}
        manifest["study_variant"] = "fleet_sensitivity"
        manifest["k_values"] = [50]
        manifest["configuration"]["fixed_k"] = 50
        manifest["configuration"]["comparison_campaign"] = str(args.comparison_campaign.resolve())
    manifest["method"] = "fixed_type_counts_free_positions"
    manifest["headway_contract"] = HEADWAY_CONTRACT
    manifest["contract_id"] = THESIS_CONTRACT_ID
    manifest["configuration"].update(
        headway_contract=HEADWAY_CONTRACT,
        contract_id=THESIS_CONTRACT_ID,
        solver_versions=solver_versions(),
        completion_reserve_seconds=10,
        headway_reduction=True,
        fixed_type_specialization=True,
        demand_window_seconds=1464,
        horizon_seconds=2364,
        operation_seconds=2664,
        ticks_per_second=1000,
        release_resolution_seconds=15,
    )
    manifest["configuration"]["mixtures"] = [list(m) for m in mixes]
    manifest["configuration"]["reference_root"] = (
        str(args.reuse_reference_root.resolve()) if args.reuse_reference_root else None
    )
    manifest["configuration"]["reference_bound_stopping"] = fleet == 62
    trials = []
    for family in args.families:
        types = (
            ("all_stop", "bd", "ce")
            if family == "f2"
            else ("all_stop", "alternating_phase_0", "alternating_phase_1")
        )
        for mix_index, counts in enumerate(mixes):
            trial_id = f"{family}_mix_{'_'.join(map(str, counts))}_k{fleet}"
            trials.append(
                {
                    "trial_id": trial_id,
                    "policy_id": trial_id,
                    "family": family,
                    "load": "gleiche Nachfrage wie K62" if fleet == 50 else "120% phase Nmax",
                    "demand_total": loads[family],
                    "available_fleet_count": fleet,
                    "type_catalog": CATALOG[family],
                    "formulation": "nowait_templates",
                    "objective": "served",
                    "fixed_type_counts": dict(zip(types, counts)),
                    "stop_if_cannot_beat_reference": fleet == 62 and counts != MIXES[0],
                    "status": "planned",
                    "attempts": [],
                    "events": [],
                }
            )
            if fleet == 50:
                trials[-1]["comparison_trial_id"] = f"{family}_mix_{'_'.join(map(str, MIXES[mix_index]))}_k62"
    manifest.update(trials=trials, trial_count=len(trials))
    return manifest


def mixture_command(trial, reference, output, args):
    command = trial_command(trial, reference, output, args)
    # A regular All-Stop plan is a comparison only, not a valid mixed-type seed.
    index = command.index("--start-checkpoint")
    del command[index : index + 2]
    command[command.index("--fixed-k") + 1] = str(trial["available_fleet_count"])
    if reference is None:
        index = command.index("--all-stop-reference")
        del command[index:index + 2]
    command += [
        "--fixed-type-counts",
        json.dumps(trial["fixed_type_counts"], sort_keys=True),
    ]
    if trial["stop_if_cannot_beat_reference"]:
        command.append("--stop-if-cannot-beat-reference")
    return command


def checked_reference(path, family, demand):
    domain = prepare_oip_pattern_waiting_pilot(
        maximum_wait_seconds=0,
        cabin_count=62,
        demand_total=demand,
        demand_family=family,
    ).domain
    certificate = _read_portable_checkpoint(path, domain)
    return validate_oip_certificate(domain, *certificate)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--fixed-k", type=int, choices=(50, 62), default=62)
    parser.add_argument("--comparison-campaign", type=Path,
                        help="Completed K62 campaign; display only, never a K50 hint or bound")
    parser.add_argument(
        "--calibration",
        type=Path,
        default=ROOT / "results/oip_exact_phase_short_k62_20260918/references.json",
    )
    parser.add_argument("--frontend-root", type=Path, default=FRONTEND_ROOT)
    parser.add_argument("--reuse-reference-root", type=Path)
    parser.add_argument(
        "--families", nargs="+", choices=("f2", "f3", "f0"), default=["f2", "f3", "f0"]
    )
    parser.add_argument("--trial-time-limit-seconds", type=float, default=300)
    parser.add_argument("--reference-time-limit-seconds", type=float, default=300)
    parser.add_argument("--workers", type=int, default=12)
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument("--memory-limit-gib", type=float, default=32)
    parser.add_argument("--build-only", action="store_true")
    parser.add_argument("--resume", action="store_true")
    parser.add_argument("--accept-persistence-fix", action="store_true",
                        help="Explicitly record a code-only checkpoint fix on resume; all other configuration must match")
    parser.add_argument("--skip-interrupted", action="store_true",
                        help="Continue only unstarted trials; do not repeat interrupted attempts")
    args = parser.parse_args()
    if (
        len(set(args.families)) != len(args.families)
        or min(
            args.trial_time_limit_seconds,
            args.reference_time_limit_seconds,
            args.workers,
            args.memory_limit_gib,
        )
        <= 0
        or args.memory_limit_gib > 32
        or args.workers > 12
        or max(args.trial_time_limit_seconds, args.reference_time_limit_seconds) > 300
    ):
        parser.error("invalid families or resource budgets")
    if args.accept_persistence_fix and not args.resume:
        parser.error("--accept-persistence-fix requires --resume")
    if args.build_only and args.resume:
        parser.error("build-only and resume are exclusive")
    if args.fixed_k == 50:
        if args.reuse_reference_root is not None:
            parser.error("K50 sensitivity does not import K62 reference certificates")
        args.comparison_campaign = args.comparison_campaign or ROOT / "results/oip_fixed_mixes_geometric_120_20260918"
    elif args.comparison_campaign is not None:
        parser.error("--comparison-campaign is only supported for K50 sensitivity")
    args.formulations = ["nowait_templates"]
    # Do not silently replace an unresolved capacity with its lower bound.
    adoption = verify_cal_o_adoption(args.calibration.resolve(), args.families)
    loads = {family: receipt["load_120"] for family, receipt in adoption.items()}
    output, frontend = args.output.resolve(), args.frontend_root.resolve()
    expected = manifest_for(args, loads)
    comparison_frozen = None
    if args.fixed_k == 50:
        comparison, comparison_frozen = load_k62_comparison(args.comparison_campaign.resolve(), args.families, loads)
        expected["comparison_campaign"] = comparison
        expected["configuration"]["comparison_source_hashes"] = comparison["source_hashes"]
    expected["calibration_adoption"] = {
        family: {k: v for k, v in receipt.items() if k != "certificate"}
        for family, receipt in adoption.items()
    }
    expected["configuration"]["calibration_source_hashes"] = {
        family: receipt["source_hashes"] for family, receipt in adoption.items()
    }
    frozen_domains = {}
    for family, demand in loads.items():
        domain = prepare_oip_pattern_waiting_pilot(
            maximum_wait_seconds=0,
            demand_family=family,
            demand_total=demand,
            cabin_count=args.fixed_k,
        ).domain
        groups = [
            (d.arrival_time.isoformat(), d.origin, d.destination, d.count)
            for d in domain.scenario.demands
        ]
        frozen_domains[family] = {
            "domain_fingerprint": domain.fingerprint,
            "comparison_fingerprint": domain.comparison_fingerprint,
            "demand_fingerprint": hashlib.sha256(
                json.dumps(groups, separators=(",", ":")).encode()
            ).hexdigest(),
            "demand_total": demand,
            "demand_groups": groups,
            "headway_contract": HEADWAY_CONTRACT,
            "scenario_metadata": domain.scenario.experiment_metadata,
        }
        if comparison_frozen is not None and groups != [tuple(g) for g in comparison_frozen[family]["demand_groups"]]:
            raise ValueError("Changing K changed demand releases or OD assignment")
        if family in expected["reference_runs"]:
            expected["reference_runs"][family]["comparison_fingerprint"] = domain.comparison_fingerprint
        for trial in expected["trials"]:
            if trial["family"] == family:
                trial.update(
                    {
                        k: frozen_domains[family][k]
                        for k in (
                            "domain_fingerprint",
                            "comparison_fingerprint",
                            "demand_fingerprint",
                        )
                    }
                )
    expected["configuration"]["domain_fingerprints"] = {
        f: d["domain_fingerprint"] for f, d in frozen_domains.items()
    }
    path = output / "campaign.json"
    if args.resume:
        manifest = json.loads(path.read_text())
        previous_configuration = manifest["configuration"]
        if args.accept_persistence_fix:
            previous_configuration = dict(previous_configuration)
            previous_configuration["source_digest"] = expected["configuration"]["source_digest"]
        if (
            previous_configuration != expected["configuration"]
            or manifest["load_contract"] != loads
        ):
            raise ValueError(
                "Resume requires the same code, configuration, and calibrated loads"
            )
        if args.accept_persistence_fix and manifest["configuration"]["source_digest"] != expected["configuration"]["source_digest"]:
            manifest.setdefault("code_revisions", []).append({
                "at_utc": now(), "reason": "incumbent persistence and deadline finalization fix",
                "previous_source_digest": manifest["configuration"]["source_digest"],
                "source_digest": expected["configuration"]["source_digest"],
                "completed_and_interrupted_trials": [t["trial_id"] for t in manifest["trials"] if t["status"] != "planned"],
            })
            manifest["configuration"] = expected["configuration"]
    else:
        if path.exists():
            raise ValueError("Campaign already exists; use --resume")
        manifest = expected
    output.mkdir(parents=True, exist_ok=True)
    for family, domain_payload in frozen_domains.items():
        atomic_json(output / "frozen_domains" / f"{family}.json", domain_payload)
    for family, receipt in adoption.items():
        atomic_json(output / "calibration_adoption" / f"{family}.json", receipt)
    save(output, frontend, manifest)
    if args.build_only:
        print(
            f"Prepared {len(manifest['trials'])} fixed-mixture trials and {len(manifest['reference_runs'])} reference evaluations; no solves"
        )
        return
    manifest["status"] = "running"
    save(output, frontend, manifest)
    references = {}
    for family in manifest["reference_runs"]:
        directory = output / "references" / family
        if not (directory / "result.json").exists():
            source = (
                args.reuse_reference_root / family
                if args.reuse_reference_root
                else None
            )
            if source is not None and (source / "result.json").exists():
                checked_reference(source, family, loads[family])
                shutil.copytree(source, directory, dirs_exist_ok=True)
            else:
                directory.mkdir(parents=True, exist_ok=True)
                guard = _run_one(
                    reference_command(family, loads[family], directory, args),
                    directory,
                    args.reference_time_limit_seconds,
                    args,
                )
                if guard.get("exit_code") != 0:
                    manifest["status"] = "blocked_missing_all_stop_reference"
                    save(output, frontend, manifest)
                    return
        metrics = checked_reference(directory, family, loads[family])
        references[family] = directory
        manifest["reference_runs"][family].update(
            status="complete", served=metrics.served, unserved=metrics.unserved
        )
        _publish_run(frontend, directory, f"{output.name}__reference__{family}")
        save(output, frontend, manifest)
    for trial in manifest["trials"]:
        if trial["status"] == "complete" or (args.skip_interrupted and trial["status"] == "interrupted"):
            continue
        # Old interrupted attempts are retained; never overwrite solver files.
        for old in trial["attempts"]:
            if old["status"] == "running":
                old["status"] = "interrupted"
        number = len(trial["attempts"]) + 1
        directory = output / "trials" / trial["trial_id"] / f"attempt_{number}"
        directory.mkdir(parents=True, exist_ok=False)
        run_id = f"{output.name}__{trial['trial_id']}__a{number}"
        command = mixture_command(trial, references.get(trial["family"]), directory, args)
        attempt = {
            "attempt": number,
            "status": "running",
            "command": command,
            "directory": str(directory.relative_to(output)),
            "run_campaign_id": run_id,
            "started_at_utc": now(),
        }
        trial["attempts"].append(attempt)
        trial.update(status="running", run_campaign_id=run_id)
        _expose_live_run(frontend, directory, run_id)
        stop = threading.Event()
        mirror = threading.Thread(
            target=_mirror_live_run,
            args=(directory, frontend / run_id, stop),
            daemon=True,
        )
        mirror.start()
        save(output, frontend, manifest)
        try:
            guard = _run_one(command, directory, args.trial_time_limit_seconds, args)
        finally:
            stop.set()
            mirror.join(timeout=5)
        attempt.update(finished_at_utc=now(), supervisor=guard)
        result_file = directory / "result.json"
        recovered = None
        if guard.get("exit_code") != 0 or not result_file.exists():
            recovered = recover_validated_incumbent(
                directory, guard.get("supervisor_reason") or "PROCESS_INTERRUPTED",
                expected_domain=trial["domain_fingerprint"],
                expected_type_counts=trial["fixed_type_counts"],
            )
        if (guard.get("exit_code") == 0 or recovered is not None) and result_file.exists():
            result = json.loads(result_file.read_text())
            trial.update(
                status="complete",
                solver_status=result.get("solver_status"),
                served=result.get("served_passengers"),
                unserved=result.get("unserved_passengers"),
                journey_time_seconds=result.get("journey_time_seconds"),
                relative_gap=result.get("gap"),
                best_bound=result.get("best_bound"),
                type_counts=result.get("type_counts"),
                termination_reason=result.get("termination_reason"),
                reference_served_cutoff=result.get("reference_served_cutoff"),
                reduction_stats=result.get("reduction_stats"),
                build_seconds=result.get("build_seconds"),
                solve_seconds=result.get("runtime_seconds"),
            )
            attempt["status"] = "complete"
            attempt["recovered_checkpoint"] = recovered is not None
        else:
            attempt["status"] = "interrupted"
            trial["status"] = "interrupted"
            trial["termination_reason"] = guard.get("supervisor_reason") or "PROCESS_INTERRUPTED"
        _publish_run(frontend, directory, run_id)
        save(output, frontend, manifest)
    manifest["status"] = (
        "complete"
        if all(t["status"] == "complete" for t in manifest["trials"])
        else "partial"
    )
    manifest["finished_at_utc"] = now()
    save(output, frontend, manifest)


if __name__ == "__main__":
    main()
