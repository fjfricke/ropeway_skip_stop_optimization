"""Report already validated diagnostic trials; no optimization is performed."""

import argparse
import csv
import hashlib
import json
import re
from pathlib import Path


def read(path):
    return json.loads(path.read_text())


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("campaign", type=Path)
    parser.add_argument("--plot", action="store_true")
    a = parser.parse_args()
    root = a.campaign
    manifest = read(root / "campaign.json")
    entries = list(manifest["runs"])
    if (root / "followup.json").exists():
        entries += read(root / "followup.json")["runs"]
    reference = manifest["reference_tick"] / 1e6
    time_limit = manifest.get("time_limit_per_trial", 120)
    rows, trace = [], []
    for entry in entries:
        if "folder" not in entry:
            continue
        folder = root / entry["folder"]
        if not (folder / "result.json").exists():
            continue
        result = read(folder / "result.json")
        if "solver_status" not in result:
            continue
        profile, seed = entry["profile"], entry["seed"]
        native = [e for e in result["events"] if e["kind"] == "incumbent"]
        bounds = [e for e in result["events"] if e["kind"] == "bound"]
        best, first, last, count = reference, None, None, 0
        for event in native:
            value = event["objective_raw"] / 1e6
            if value < best:
                first = event["elapsed_seconds"] if first is None else first
                last = event["elapsed_seconds"]
                count += 1
                best = value
        bound_best, last_bound, material_bound = 0, None, None
        last_material_value = 0
        for event in bounds:
            value = max(0, event["bound_raw"] / 1e6)
            if value > bound_best:
                bound_best = value
                last_bound = event["elapsed_seconds"]
                if value - last_material_value >= reference * 0.001:
                    material_bound = event["elapsed_seconds"]
                    last_material_value = value
        log = (folder / "solver.log").read_text()
        presolved = (
            log.split("Presolved optimization model", 1)[-1]
            if "Presolved optimization model" in log
            else ""
        )

        def number(pattern, presolved=presolved):
            match = re.search(pattern, presolved, re.MULTILINE)
            return int(match[1].replace("'", "")) if match else None

        search = re.search(r"Starting search at ([0-9.]+)s", log)
        ub = result["validated_upper_bound"]
        lb = result["cp_lower_bound"]
        row = {
            "profile": profile,
            "seed": seed,
            "status": result["solver_status"],
            "scope": result["proof_scope"],
            "upper_seconds": ub,
            "lower_seconds_in_scope": lb,
            "gap_in_scope": None if lb is None else (ub - lb) / ub,
            "proven_optimal_in_scope": result["proven_optimal"],
            "improvement_seconds": reference - ub,
            "native_improvement_events": count,
            "first_native_solution_seconds": native[0]["elapsed_seconds"]
            if native
            else None,
            "first_native_improvement_seconds": first,
            "last_native_improvement_seconds": last,
            "last_bound_increase_seconds": last_bound,
            "last_material_bound_increase_seconds": material_bound,
            "build_seconds": result["model_build_seconds"],
            "hint_seconds": result["hint_seconds"],
            "solve_seconds": result["solve_seconds"],
            "total_worker_seconds": result["total_wall_seconds"],
            "presolve_and_search_setup_seconds_from_log": float(search[1])
            if search
            else None,
            "initial_variables": result["model_stats"]["variables"],
            "presolved_variables": number(r"^#Variables: ([0-9']+)"),
            "presolved_time_products": number(r"^#kIntProd: ([0-9']+)"),
            "presolved_no_overlap": number(r"^#kNoOverlap: ([0-9']+)"),
            "peak_rss_gib": entry["monitor"]["peak_process_tree_rss_bytes"] / 1024**3,
            "source_folder": "sources_followup"
            if profile.endswith("_assignment")
            else "sources",
        }
        rows.append(row)
        for kind, events in [
            ("native_ub", native),
            ("native_lb", bounds),
            ("final", [result["events"][-1]]),
        ]:
            for event in events:
                trace.append(
                    {
                        "profile": profile,
                        "seed": seed,
                        "scope": row["scope"],
                        "kind": kind,
                        "elapsed_seconds": event["elapsed_seconds"],
                        "value_seconds": event.get("objective_raw", 0) / 1e6
                        if kind != "native_lb"
                        else event["bound_raw"] / 1e6,
                    }
                )
    for name, records in [("comparison.csv", rows), ("progress.csv", trace)]:
        if records:
            with (root / name).open("w") as stream:
                writer = csv.DictWriter(stream, fieldnames=list(records[0]))
                writer.writeheader()
                writer.writerows(records)
    report = {
        "reference_seconds": reference,
        "rows": rows,
        "report_source_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        "note": "Restricted lower bounds cannot be used as full-domain bounds. Native intermediate objectives are solver reports; exported checkpoints and final plans are independently validated.",
    }
    (root / "analysis.json").write_text(json.dumps(report, indent=2) + "\n")
    lines = [
        "# Reservoir-Diagnose: Messwerte",
        "",
        "Alle Kosten in Passagiersekunden. **LB und Gap gelten ausschließlich für die jeweilige Einschränkung.**",
        "",
        "| Profil | Seed | UB | LB im Teilproblem | Gap | Optimal im Teilproblem | Presolved Variablen | Restprodukte |",
        "|---|---:|---:|---:|---:|---|---:|---:|",
    ]
    for row in rows:
        lb = row["lower_seconds_in_scope"]
        gap = row["gap_in_scope"]
        lines.append(
            f"| {row['profile']} | {row['seed']} | {row['upper_seconds']:.6f} | {'—' if lb is None else format(lb, '.6f')} | {'—' if gap is None else format(gap, '.2%')} | {row['proven_optimal_in_scope']} | {row['presolved_variables']} | {row['presolved_time_products'] or 0} |"
        )
    lines += [
        "",
        "Native Ereigniszeiten, Aufbau, Presolve, Suche, letzter Fortschritt und Speicher stehen in `comparison.csv`; sämtliche Rohereignisse in `progress.csv` und den Laufunterordnern. Fehlende Logzähler bleiben nicht verfügbar.",
        "",
        f"Hauptläufe: {time_limit} s Prozessbudget, etwaiger Zusatz mit fester Zuordnung: 90 s. Jeweils 5 s Reserve für Aufbauumgebung/Abschluss, zwölf Worker, Seeds 0/1, identischer Referenzplan. Kein Standardwechsel.",
    ]
    if a.plot:
        import matplotlib

        matplotlib.use("Agg")
        import matplotlib.pyplot as plt

        profiles = list(dict.fromkeys(row["profile"] for row in rows))
        fig, axes = plt.subplots(
            1, 2, figsize=(13, 5), sharey=True, layout="constrained"
        )
        colors = {p: plt.get_cmap("tab10")(i) for i, p in enumerate(profiles)}
        for seed, ax in enumerate(axes):
            for profile in profiles:
                values = [
                    x
                    for x in trace
                    if x["seed"] == seed
                    and x["profile"] == profile
                    and x["kind"] == "native_lb"
                ]
                finals = [
                    x for x in rows if x["seed"] == seed and x["profile"] == profile
                ]
                if not finals:
                    continue
                end = finals[0]
                points = [(0, 0)] + [
                    (x["elapsed_seconds"], max(0, x["value_seconds"])) for x in values
                ]
                points.append(
                    (end["total_worker_seconds"], end["lower_seconds_in_scope"] or 0)
                )
                ax.step(
                    [x for x, _ in points],
                    [v / 1000 for _, v in points],
                    where="post",
                    label=profile,
                    color=colors[profile],
                    linewidth=1.6,
                )
            ax.axhline(
                reference / 1000,
                color="black",
                linestyle="--",
                linewidth=1,
                label="Referenz-UB",
            )
            ax.set(
                title=f"Seed {seed}",
                xlabel="Sekunden ab Solver-Wrapperstart",
                xlim=(0, time_limit),
                ylim=(-5, 385),
            )
            ax.grid(alpha=0.2)
        axes[0].set_ylabel(
            "Untere Schranke im jeweiligen Teilproblem\n(Tausend Passagiersekunden)"
        )
        axes[1].legend(loc="lower right", fontsize=8)
        fig.suptitle(
            "Diagnose: Diese Schranken gelten NICHT gemeinsam für das volle Reservoir"
        )
        fig.savefig(root / "bound_progress.png", dpi=170)
        fig.savefig(root / "bound_progress.svg")
        plt.close(fig)
        lines += [
            "",
            "![Schranken der verschiedenen eingeschränkten Modelle](bound_progress.png)",
        ]
    (root / "report.md").write_text("\n".join(lines) + "\n")
    print(
        json.dumps(
            {
                "completed_results": len(rows),
                "best_upper": min((r["upper_seconds"] for r in rows), default=None),
            }
        )
    )


if __name__ == "__main__":
    main()
