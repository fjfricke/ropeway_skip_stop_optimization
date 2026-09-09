"""Read-only inventory of saved solver results; never re-certifies historical bounds.

Run from repository root. CSV records are result documents/diagnostic cases, not
necessarily independent runs. Paths and original metric keys preserve provenance.
Large movement/checkpoint artifacts are indexed but not materialized in memory.
"""

from __future__ import annotations
import argparse
import csv
import json
import math
from collections import Counter
from pathlib import Path

UB = (
    "validated_upper_bound",
    "global_upper_bound",
    "best_upper_bound",
    "objective_value_seconds",
    "objective_value",
    "objective",
)
LB = (
    "certified_lower_bound",
    "global_lower_bound",
    "combined_lower_bound",
    "cp_lower_bound",
    "best_bound",
    "solver_best_bound",
)
TIME = (
    "total_wall_seconds",
    "total_seconds",
    "elapsed_seconds",
    "runtime_seconds",
    "solve_seconds",
)


def number(value):
    return (
        value
        if isinstance(value, (int, float))
        and not isinstance(value, bool)
        and math.isfinite(value)
        and abs(value) < 1e90
        else None
    )


def first(data, keys, numeric=False):
    for key in keys:
        value = data.get(key)
        if (
            (number(value) is not None)
            if numeric
            else (value is not None and not isinstance(value, (dict, list)))
        ):
            return value, key
    return None, None


def merged(data):
    out = {}
    for key in ("metadata", "payload", "metrics"):
        if isinstance(data.get(key), dict):
            out.update(merged(data[key]))
    out.update(data)
    return out


def is_result(d):
    return isinstance(d, dict) and (
        any(
            k in d
            for k in (
                "progress_samples",
                "certified_lower_bound",
                "global_lower_bound",
                "validated_upper_bound",
                "solver_status",
                "objective_value_seconds",
                "solver_response_stats",
            )
        )
        or (
            "iterations" in d
            and any(k in d for k in ("status", "scope", "experiment_scope"))
        )
        or (
            "status" in d
            and any(
                k in d
                for k in (
                    *TIME,
                    "model",
                    "objective",
                    "certificate_kind",
                    "certified_reduced_cost_lower_bound",
                )
            )
        )
    )


def series(data):
    points = []
    samples = data.get("progress_samples")
    basis = "solver_runtime"
    if not samples:
        samples = data.get("iterations")
        basis = "sum_iteration_seconds_excludes_unassigned_overhead"
    if not samples:
        samples = data.get("events")
        basis = "optimizer_elapsed_excludes_runner_preparation"
    elapsed = 0
    for item in samples or []:
        if not isinstance(item, dict):
            continue
        if basis.startswith("sum_") and number(item.get("elapsed_seconds")) is not None:
            t = item["elapsed_seconds"]
            basis = "iteration_elapsed"
        elif basis.startswith("sum_"):
            duration = first(item, ("round_seconds", "total_seconds"), True)[0]
            if duration is None:
                continue
            elapsed += duration
            t = elapsed
        else:
            t = first(item, ("runtime_seconds", "elapsed_seconds"), True)[0]
        if t is None:
            continue
        ub = first(
            item,
            ("global_upper_bound", "incumbent_objective", "validated_upper_bound"),
            True,
        )[0]
        lb = first(
            item, ("global_lower_bound", "best_bound", "certified_lower_bound"), True
        )[0]
        for k in ("objective_tick", "cp_objective_tick"):
            if ub is None and number(item.get(k)) is not None:
                ub = item[k] / 1e6
        for k in ("raw_bound_tick", "cp_bound_tick", "bound_tick"):
            if lb is None and number(item.get(k)) is not None:
                lb = math.floor(item[k]) / 1e6
        if ub is not None or lb is not None:
            points.append(
                dict(
                    t=t,
                    ub=ub,
                    lb=lb,
                    event=item.get("kind", item.get("event", item.get("round_index"))),
                )
            )
    return basis, points


def curve_stats(points):
    out = {}
    bestub = bestlb = None
    improvements = 0
    for p in sorted(points, key=lambda p: p["t"]):
        u, lower = p["ub"], p["lb"]
        if u is not None and (bestub is None or u < bestub - 1e-5):
            if bestub is None:
                out.update(first_ub=u, first_ub_time=p["t"])
            else:
                improvements += 1
                out["last_ub_improvement_time"] = p["t"]
            bestub = u
        if lower is not None and (bestlb is None or lower > bestlb + 1e-5):
            if bestlb is None:
                out["first_lb"] = lower
            else:
                out["last_lb_improvement_time"] = p["t"]
            bestlb = lower
    if points:
        out.update(
            curve_end=max(p["t"] for p in points),
            curve_best_ub=bestub,
            curve_best_lb=bestlb,
            ub_improvements=improvements,
        )
        for threshold in (30, 60, 120, 300, 600, 1800, 3600, 7200):
            eligible = [p for p in points if p["t"] <= threshold]
            if eligible and threshold <= out["curve_end"] + 1:
                for key, fn in [("ub", min), ("lb", max)]:
                    vals = [p[key] for p in eligible if p[key] is not None]
                    if vals:
                        out[f"{key}_at_{threshold}s"] = fn(vals)
    return out


def write_csv(path, rows):
    fields = list(dict.fromkeys(k for r in rows for k in r))
    with path.open("w") as f:
        w = csv.DictWriter(f, fieldnames=fields, lineterminator="\n")
        w.writeheader()
        w.writerows(rows)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path("benchmarks/output"))
    parser.add_argument(
        "--output", type=Path, default=Path("benchmarks/output/solver_history_audit")
    )
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    inventory = []
    records = []
    curves = []

    def add(path, d, section="root", inherited=None):
        base = merged(d)
        context = dict(inherited or {})
        context.update(d.get("config", {}) if isinstance(d.get("config"), dict) else {})
        context.update(base)
        if is_result(base):
            family = path.relative_to(args.root).parts[0]
            record = dict(
                source=str(path),
                section=section,
                family=family,
                record_kind="artifact_snapshot"
                if "artifacts" in path.parts
                else ("diagnostic_case" if section != "root" else "result_document"),
            )
            mapping = {
                "scenario": ("example_id", "case_id", "scenario_id", "instance_id"),
                "k": (
                    "exact_active_cabin_count",
                    "cabin_count",
                    "available_fleet_count",
                ),
                "method": (
                    "method",
                    "formulation",
                    "experiment_scope",
                    "scope",
                    "schema",
                    "variant_id",
                    "id",
                ),
                "objective_kind": ("passenger_objective", "objective"),
                "status": ("status", "solver_status", "termination_reason"),
                "fingerprint": (
                    "domain_fingerprint",
                    "problem_fingerprint",
                    "fixed_k_problem_fingerprint",
                    "fingerprint",
                    "instance_fingerprint",
                ),
                "start_policy": ("start_policy", "fixed_start_policy"),
                "operating_mode": ("operating_mode", "policy_id"),
                "horizon": ("horizon_seconds", "operational_end_seconds"),
                "warmup": ("warmup_seconds",),
                "validation": (
                    "independent_validation_status",
                    "validation_status",
                    "certificate_valid",
                ),
                "time_limit": (
                    "total_time_limit_seconds",
                    "time_limit_seconds",
                    "time_limit_seconds_per_case",
                ),
                "variables": ("model_variable_count", "variable_count"),
                "rows": (
                    "linear_constraint_count",
                    "model_constraint_count",
                    "constraint_count",
                ),
                "movement_variables": ("movement_variable_count",),
                "passenger_variables": ("passenger_variable_count",),
                "build_seconds": ("model_build_seconds", "model_setup_runtime_seconds"),
                "network_seconds": ("network_build_seconds",),
                "prepare_seconds": (
                    "prepare_seconds",
                    "setup_seconds",
                    "preparation_seconds",
                ),
                "solve_seconds": ("solve_seconds", "runtime_seconds"),
                "served": ("served_passenger_count", "served_count"),
                "unserved": ("unserved_passenger_count", "unserved_count"),
                "relative_gap": ("relative_gap", "mip_gap"),
                "termination": ("termination_reason", "detail"),
                "timestamp": ("timestamp", "generated_at_utc", "created_at"),
                "git_commit": ("git_commit",),
                "root_lp_certified": ("root_lp_certified",),
            }
            for name, keys in mapping.items():
                record[name] = first(context, keys)[0]
            for name, keys in [("ub", UB), ("lb", LB), ("time", TIME)]:
                record[name], record[name + "_field"] = first(base, keys, True)
            for nested in ("solver_policy", "solver", "model_stats"):
                v = context.get(nested)
                if isinstance(v, dict):
                    for key in (
                        "time_limit_seconds",
                        "total_time_limit_seconds",
                        "threads",
                        "num_workers",
                        "variables",
                        "constraints",
                    ):
                        if key in v:
                            record[nested + "_" + key] = v[key]
            waiting = context.get("waiting_policy")
            record["waiting"] = (
                json.dumps(waiting, sort_keys=True)
                if isinstance(waiting, (dict, list))
                else waiting
            )
            record["maximum_wait_seconds"] = context.get("maximum_wait_seconds")
            record["diagnostic_headway_feasible"] = base.get(
                "diagnostic_headway_feasible"
            )
            record["diagnostic_headway_violation_count"] = base.get(
                "diagnostic_headway_violation_count"
            )
            if isinstance(base.get("movement_plan"), dict):
                plan = base["movement_plan"]
                record["scenario"] = record["scenario"] or plan.get("scenario_id")
                record["exported_trajectory_count"] = len(plan.get("trajectories", []))
                record["horizon"] = record["horizon"] or plan.get("horizon_seconds")
            is_oip = (
                "optimized_initial_placement" in str(record.get("scenario") or path)
                or record.get("operating_mode") == "optimized_initial_placement"
            )
            record["objective_semantics"] = (
                "lexicographic_unserved_then_served_time_then_fleet"
                if is_oip
                else (
                    "reservoir_lexicographic_see_phase_fields"
                    if family == "ddd_reservoir_arc_flow_gates"
                    else "reported_objective_verify_domain"
                )
            )
            for key in (
                "primary_lower_bound",
                "primary_upper_bound",
                "secondary_lower_bound",
                "secondary_upper_bound",
                "primary_optimal",
                "secondary_optimal",
                "primary_seconds",
                "secondary_seconds",
            ):
                if key in base:
                    record[key] = base[key]
            basis, points = series(base)
            record["curve_basis"] = basis if points else None
            record["curve_samples"] = len(points)
            record["curve_units"] = (
                "multiobjective_phase_not_identified"
                if is_oip
                else "reported_objective_units"
            )
            if not is_oip:
                record.update(curve_stats(points))
            records.append(record)
            curves.extend(
                dict(source=str(path), section=section, basis=basis, **point)
                for point in points
            )
        # Explicit summary containers only: never mistake solver iterations for runs.
        for key in ("result", "root", "reference_lp"):
            if isinstance(d.get(key), dict):
                add(path, d[key], f"{section}.{key}", context)
        for key in ("cases", "variants", "runs", "results", "probes"):
            v = d.get(key)
            entries = (
                v.items()
                if isinstance(v, dict)
                else enumerate(v)
                if isinstance(v, list)
                else ()
            )
            for label, child in entries:
                if isinstance(child, dict):
                    add(path, child, f"{section}.{key}.{label}", context)

    for path in sorted(args.root.rglob("*.json")):
        if args.output in path.parents:
            continue
        size = path.stat().st_size
        r = dict(source=str(path), bytes=size)
        if size > 30_000_000:
            r["classification"] = "large_support_artifact_not_loaded"
        else:
            try:
                data = json.loads(path.read_text())
                before = len(records)
                if isinstance(data, dict):
                    add(path, data)
                r["classification"] = (
                    "result_or_diagnostic"
                    if len(records) > before
                    else "support_or_manifest"
                )
                r["records"] = len(records) - before
            except (OSError, ValueError) as error:
                r.update(classification="read_error", error=str(error))
        inventory.append(r)
    # Campaign traces use a separate clock/schema. Preserve certified global
    # values separately from provisional solver reports; do not merge them.
    campaign_points = []
    jsonl_inventory = []
    for path in sorted(args.root.rglob("*.jsonl")):
        if args.output in path.parents:
            continue
        lines = errors = 0
        before = len(campaign_points)
        with path.open() as stream:
            for line in stream:
                if not line.strip():
                    continue
                lines += 1
                try:
                    item = json.loads(line)
                except ValueError:
                    errors += 1
                    continue
                if not isinstance(item, dict) or "policy_id" not in item:
                    continue
                t = number(item.get("elapsed_seconds"))
                if t is None:
                    continue
                campaign_points.append(
                    dict(
                        source=str(path),
                        method=item.get("policy_id"),
                        k=item.get("available_fleet_count"),
                        fingerprint=item.get("trial_fingerprint"),
                        t=t,
                        stage=item.get("stage"),
                        event=item.get("kind"),
                        certified_global_lb=number(
                            item.get("global_certified_lower_bound")
                        ),
                        validated_global_ub=number(
                            item.get("global_validated_upper_bound")
                        ),
                        provisional_local_lb=number(item.get("local_solver_bound")),
                        provisional_local_ub=number(item.get("local_solver_incumbent")),
                    )
                )
        jsonl_inventory.append(
            dict(
                source=str(path),
                lines=lines,
                read_errors=errors,
                campaign_points=len(campaign_points) - before,
            )
        )
    write_csv(args.output / "campaign_trajectories.csv", campaign_points)
    write_csv(args.output / "jsonl_inventory.csv", jsonl_inventory)
    write_csv(args.output / "run_inventory.csv", records)
    write_csv(args.output / "bound_trajectories.csv", curves)
    write_csv(args.output / "file_inventory.csv", inventory)
    summary = dict(
        json_files=len(inventory),
        records=len(records),
        curve_records=sum(r["curve_samples"] > 0 for r in records),
        curve_points=len(curves),
        classifications=dict(Counter(r["classification"] for r in inventory)),
        families=dict(Counter(r["family"] for r in records)),
        record_kinds=dict(Counter(r["record_kind"] for r in records)),
    )
    summary.update(
        jsonl_files=len(jsonl_inventory),
        jsonl_lines=sum(r["lines"] for r in jsonl_inventory),
        jsonl_read_errors=sum(r["read_errors"] for r in jsonl_inventory),
        campaign_points=len(campaign_points),
    )
    (args.output / "coverage.json").write_text(json.dumps(summary, indent=2))
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
