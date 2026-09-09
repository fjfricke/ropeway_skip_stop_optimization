"""Derive comparable end metrics and anytime traces from the saved follow-up jobs."""

from __future__ import annotations

import csv
import json
import math
from pathlib import Path

BASE = (
    Path(__file__).resolve().parents[1] / "benchmarks/output/solver_followup_20260909"
)


def read(path):
    return json.loads(path.read_text()) if path.exists() else {}


def finite(value):
    return type(value) in (int, float) and math.isfinite(value) and abs(value) < 1e90


def write_csv(path, rows):
    keys = list(dict.fromkeys(k for row in rows for k in row))
    with path.open("w", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=keys, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def main():
    rows = []
    points = []
    for source in sorted(BASE.rglob("result.json")):
        if "frozen" in source.parts:
            continue
        result = read(source)
        folder = source.parent
        config = read(folder / "config.json")
        metrics = read(folder / "metrics.json")
        post = read(folder / "post_ip/validation.json")
        name = str(folder.relative_to(BASE))
        is_cp = "cp_lower_bound" in result
        ub = result.get("validated_upper_bound")
        lb = (
            result.get("cp_lower_bound")
            if is_cp
            else result.get("certified_lower_bound")
        )
        post_ub = post.get("objective", metrics.get("post_ip_objective"))
        selected = (
            min(v for v in (ub, post_ub) if finite(v))
            if any(finite(v) for v in (ub, post_ub))
            else None
        )
        if finite(lb) and selected is not None and lb > selected + 1e-4:
            raise ValueError(f"{name}: bound contradicts validated incumbent")
        stats = result.get("model_stats", {})
        row = dict(
            run=name,
            method="cp_sat_product" if is_cp else result.get("formulation"),
            k=result.get("exact_active_cabin_count"),
            mode=result.get("operating_mode"),
            waiting=config.get("maximum_wait_seconds", 0),
            seed=result.get("random_seed", config.get("solver", {}).get("seed")),
            status=result.get("solver_status", result.get("status")),
            result_status=result.get("status"),
            proof_scope=result.get("proof_scope"),
            raw_ub=ub,
            post_ip_ub=post_ub,
            selected_ub=selected,
            lb=lb,
            gap=None
            if not finite(lb) or selected is None or selected == 0
            else max(0.0, selected - lb) / selected,
            served=post.get(
                "served", metrics.get("served", result.get("served_count"))
            ),
            unserved=post.get(
                "unserved", metrics.get("unserved", result.get("unserved_count"))
            ),
            run_seconds=metrics.get(
                "end_to_end_seconds",
                result.get("total_wall_seconds", result.get("total_seconds")),
            ),
            build_seconds=result.get(
                "build_seconds", result.get("model_build_seconds")
            ),
            solve_seconds=result.get("solve_seconds"),
            prepare_seconds=result.get("prepare_seconds"),
            setup_seconds=result.get("setup_seconds"),
            network_seconds=result.get("network_build_seconds"),
            seed_seconds=result.get("seed_seconds"),
            validation_seconds=result.get(
                "validation_seconds", result.get("independent_validation_seconds")
            ),
            time_to_first_incumbent_seconds=result.get(
                "time_to_first_incumbent_seconds"
            ),
            node_count=result.get("node_count"),
            post_ip_seconds=post.get("total_seconds", metrics.get("post_ip_seconds")),
            callback_extraction_seconds=result.get("callback_extraction_seconds"),
            callback_validation_seconds=result.get("callback_validation_seconds"),
            progress_delivery_seconds=result.get("progress_delivery_seconds"),
            variables=stats.get("variables"),
            constraints=stats.get("constraints", result.get("linear_constraint_count")),
            movement_variables=result.get("movement_variable_count"),
            passenger_variables=result.get("passenger_variable_count"),
            peak_rss_mb=metrics.get("peak_rss_mb", result.get("peak_rss_mb")),
            problem_fingerprint=result.get("problem_fingerprint"),
            comparison_fingerprint=config.get("comparison_fingerprint"),
            source=str(source),
        )
        initial = (
            read(Path(config["resume_checkpoint"]))
            if config.get("resume_checkpoint")
            else {}
        )
        best_ub = initial.get("incumbent", {}).get(
            "objective", config.get("seed_upper_bound")
        )
        best_lb = 0.0
        last_change = None
        history = []
        events = folder / "events.jsonl"
        if events.exists():
            for line in events.read_text().splitlines():
                event = json.loads(line)
                t = event.get("runner_elapsed_seconds", event.get("elapsed_seconds"))
                if not finite(t):
                    continue
                if is_cp:
                    upper = event.get("objective_tick", event.get("cp_objective_tick"))
                    upper = upper / 1e6 if finite(upper) else None
                    lower = event.get("cp_bound_tick", event.get("raw_bound_tick"))
                    lower = (
                        math.floor(math.nextafter(lower, -math.inf)) / 1e6
                        if finite(lower)
                        else None
                    )
                else:
                    upper = event.get("solver_incumbent")
                    lower = event.get("certified_lower_bound")
                if finite(upper) and (best_ub is None or upper < best_ub - 1e-5):
                    best_ub = upper
                    last_change = t
                if finite(lower):
                    best_lb = max(best_lb, lower)
                history.append(
                    dict(
                        run=name,
                        runner_seconds=t,
                        ub=best_ub,
                        lb=best_lb,
                        kind=event.get("kind", event.get("phase")),
                        validation="solver_report_between_checkpoints",
                    )
                )
        if history:
            row["last_ub_improvement_seconds"] = last_change
            for threshold in (60, 120, 300, 600, 900, 1200, 1500, 1800):
                before = [p for p in history if p["runner_seconds"] <= threshold]
                if before and threshold <= row["run_seconds"] + 1:
                    row[f"ub_at_{threshold}s"] = before[-1]["ub"]
                    row[f"lb_at_{threshold}s"] = before[-1]["lb"]
            points.extend(history)
        rows.append(row)
    portfolios = []
    fingerprints = {
        r["problem_fingerprint"]
        for r in rows
        if r["method"] == "cp_sat_product" and r["proof_scope"] == "FIXED_K_GLOBAL"
    }
    for fingerprint in sorted(fingerprints):
        members = [
            r
            for r in rows
            if r["problem_fingerprint"] == fingerprint
            and r["method"] == "cp_sat_product"
            and r["proof_scope"] == "FIXED_K_GLOBAL"
        ]
        full_domains = {read(Path(r["source"]))["domain_fingerprint"] for r in members}
        if len(full_domains) != 1:
            raise ValueError(
                "Matching problem fingerprints with different CP manifests"
            )
        upper = min(
            (r for r in members if finite(r["selected_ub"])),
            key=lambda r: r["selected_ub"],
            default=None,
        )
        lower = max(
            (r for r in members if finite(r["lb"])), key=lambda r: r["lb"], default=None
        )
        if upper and lower:
            portfolios.append(
                dict(
                    problem_fingerprint=fingerprint,
                    runs=[r["run"] for r in members],
                    ub=upper["selected_ub"],
                    ub_source=upper["run"],
                    lb=lower["lb"],
                    lb_source=lower["run"],
                    gap=(upper["selected_ub"] - lower["lb"]) / upper["selected_ub"],
                )
            )
    (BASE / "portfolios.json").write_text(
        json.dumps(portfolios, indent=2, allow_nan=False) + "\n"
    )
    write_csv(BASE / "results.csv", rows)
    write_csv(BASE / "progress.csv", points)
    (BASE / "summary.json").write_text(
        json.dumps(rows, indent=2, allow_nan=False) + "\n"
    )
    print(
        json.dumps(
            [
                {
                    k: r[k]
                    for k in (
                        "run",
                        "status",
                        "raw_ub",
                        "selected_ub",
                        "lb",
                        "served",
                        "run_seconds",
                    )
                }
                for r in rows
            ],
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
